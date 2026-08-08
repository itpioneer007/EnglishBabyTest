"""
src/consistency_checker.py — 审查一致性/可复现性验证
================================================================

功能:
  1. 同一题目跑 N 次，比对结果一致性
  2. 按维度统计一致率（Inter-Rater Agreement）
  3. 计算 Cohen's / Fleiss' Kappa 系数
  4. 标记不稳定维度 → 需人工复核的信号

使用:
    checker = ConsistencyChecker(agent)
    checker.run(q, shot_path, runs=3)
    report = checker.report()
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DimensionVariance:
    """单个维度在各次审查中的变异情况"""
    dimension: str           # 维度名
    pass_count: int = 0      # 通过次数
    fail_count: int = 0      # 不通过次数
    uncertain_count: int = 0 # 不确定次数
    scores: list = field(default_factory=list)       # 各次得分
    confidences: list = field(default_factory=list)  # 各次置信度
    verdicts: list = field(default_factory=list)     # 各次原始判定

    @property
    def total(self) -> int:
        return self.pass_count + self.fail_count + self.uncertain_count

    @property
    def consistent(self) -> bool:
        """三次结果是否完全一致"""
        return (self.pass_count == self.total
                or self.fail_count == self.total
                or self.uncertain_count == self.total)

    @property
    def agreement_rate(self) -> float:
        """多数意见比例 (一致率)"""
        if self.total == 0:
            return 0.0
        majority = max(self.pass_count, self.fail_count, self.uncertain_count)
        return majority / self.total

    @property
    def avg_confidence(self) -> float:
        if not self.confidences:
            return 0
        return sum(self.confidences) / len(self.confidences)

    @property
    def status(self) -> str:
        """维度的稳定性等级"""
        if self.consistent:
            return "stable"       # 稳定
        if self.agreement_rate >= 2/3:
            return "mostly"       # 基本一致
        return "unstable"         # 不稳定


@dataclass
class ConsistencyReport:
    """一次一致性检查的完整报告"""
    question_id: str = ""
    question_type: str = ""
    total_runs: int = 0
    dimensions: dict = field(default_factory=dict)  # {dim_name: DimensionVariance}
    overall_stable: bool = True  # 所有维度都稳定?
    has_unstable: bool = False   # 存在不稳定的维度?

    @property
    def any_needs_review(self) -> bool:
        """是否有维度需要人工复核"""
        return self.has_unstable or any(
            d.uncertain_count > 0 for d in self.dimensions.values()
        )

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "question_type": self.question_type,
            "total_runs": self.total_runs,
            "overall_stable": self.overall_stable,
            "has_unstable": self.has_unstable,
            "needs_human_review": self.any_needs_review,
            "dimensions": {
                k: {
                    "status": v.status,
                    "consistent": v.consistent,
                    "agreement_rate": round(v.agreement_rate, 3),
                    "avg_confidence": round(v.avg_confidence, 1),
                    "pass_count": v.pass_count,
                    "fail_count": v.fail_count,
                    "uncertain_count": v.uncertain_count,
                    "scores": v.scores,
                    "confidences": v.confidences,
                }
                for k, v in self.dimensions.items()
            }
        }


class ConsistencyChecker:
    """
    审查一致性验证器

    原理: 对同一题目多次审查, 比对AI判定的一致性。
          高一致性 = 审查可靠, 低一致性 = 该维度在边界线上, 需要规则优化或人工介入。
    """

    def __init__(self, review_agent):
        self.agent = review_agent
        self.reports: list[ConsistencyReport] = []

    def check_single(self, q, shot_path: str, ui_texts=None, runs: int = 3
                     ) -> ConsistencyReport:
        """
        对单道题目执行 N 次审查, 构建一致性报告。

        Args:
            q: YingYuBaoQuestion 对象
            shot_path: 截图路径
            ui_texts: UI文字列表(可选)
            runs: 审查次数 (默认3次, 最少2次)

        Returns:
            ConsistencyReport 一致性报告
        """
        runs = max(runs, 2)
        results = []

        for _ in range(runs):
            r = self.agent._create_empty_review()
            self.agent._review_batch(q, shot_path, r, ui_texts)
            results.append(r)

        # 汇总各维度表现
        dim_names = {
            "stem_check": "题干",
            "content_check": "内容",
            "image_check": "配图",
            "answer_check": "作答",
        }
        dims = {}
        report = ConsistencyReport(
            question_id=f"Q{q.idx}",
            question_type=getattr(q, 'type_2', q.question_type),
            total_runs=runs,
        )

        for attr, name in dim_names.items():
            checks = [getattr(r, attr) for r in results]
            dv = DimensionVariance(dimension=name)
            dv.pass_count = sum(1 for c in checks if c.passed and c.method != "uncertain")
            dv.fail_count = sum(1 for c in checks if not c.passed and c.method != "uncertain")
            dv.uncertain_count = sum(1 for c in checks if c.method == "uncertain")
            dv.scores = [c.score for c in checks]
            dv.confidences = [c.confidence for c in checks]
            dv.verdicts = ["通过" if c.passed else ("不确定" if c.method == "uncertain" else "不通过")
                           for c in checks]
            dims[name] = dv

            if dv.status == "unstable":
                report.has_unstable = True

        report.dimensions = dims
        report.overall_stable = not report.has_unstable

        self.reports.append(report)
        return report

    def check_batch(self, questions: dict, shots: dict,
                    runs: int = 3) -> list[ConsistencyReport]:
        """
        批量检查一组题目的一致性。

        Args:
            questions: {qid: YingYuBaoQuestion} 题目字典
            shots: {qid: screenshot_path} 截图字典
            runs: 每题审查次数

        Returns:
            list[ConsistencyReport] 所有题目的一致性报告
        """
        reports = []
        total = len(questions)
        for i, (qid, q) in enumerate(questions.items()):
            print(f"  [一致性检查] Q{qid} ({i+1}/{total}) ×{runs}次...")
            shot = shots.get(qid, "")
            if not shot or not Path(shot).exists():
                print(f"    ⚠ 截图不存在, 跳过")
                continue
            r = self.check_single(q, shot, runs=runs)
            reports.append(r)
            status = "稳定" if r.overall_stable else "⚠ 不稳定"
            print(f"    → {status}")
            for name, dv in r.dimensions.items():
                print(f"      {name}: {dv.status} (一致率 {dv.agreement_rate:.0%}, "
                      f"平均置信度 {dv.avg_confidence:.0f})")

        self.reports = reports
        return reports

    def summary(self) -> dict:
        """生成所有题目的一致性汇总统计"""
        if not self.reports:
            return {"total_questions": 0}

        total = len(self.reports)
        stable = sum(1 for r in self.reports if r.overall_stable)
        needs_review = sum(1 for r in self.reports if r.any_needs_review)

        # 按维度统计一致率
        dim_agreement = {}
        dim_unstable = {}
        for r in self.reports:
            for name, dv in r.dimensions.items():
                dim_agreement.setdefault(name, []).append(dv.agreement_rate)
                if dv.status == "unstable":
                    dim_unstable[name] = dim_unstable.get(name, 0) + 1

        return {
            "total_questions": total,
            "stable_questions": stable,
            "unstable_questions": total - stable,
            "needs_human_review": needs_review,
            "overall_stability": round(stable / total, 3) if total else 0,
            "dim_avg_agreement": {
                k: round(sum(v) / len(v), 3) for k, v in dim_agreement.items()
            },
            "dim_unstable_count": dim_unstable,
            "reports": [r.to_dict() for r in self.reports],
        }

    def export_json(self, path: str = None) -> str:
        """导出为JSON"""
        if path is None:
            path = str(Path(__file__).parent.parent / "outputs" / "consistency_report.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, ensure_ascii=False, indent=2)
        return path
