"""
tests/test_consistency_checker.py — Mock 数据驱动的一致性验证测试
=================================================================

不调用真实 LLM/手机，用预定义的 5 道题 × 3 轮模拟审查结果，
验证 ConsistencyChecker 的逻辑是否正确。
"""

import sys
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from src.consistency_checker import ConsistencyChecker, ConsistencyReport, DimensionVariance


# ============================================================
# Mock: 构造真实的 CheckResult / QuestionReview 对象
# ============================================================

from src.review_agent import CheckResult, QuestionReview
from src.parse_yingyubao_docx import YingYuBaoQuestion


def make_check(passed: bool, score: float, confidence: int, method: str = "llm",
               details: list = None) -> CheckResult:
    """快捷构造一个 CheckResult"""
    c = CheckResult()
    c.passed = passed
    c.score = score
    c.confidence = confidence
    c.method = method
    c.details = details or []
    return c


def make_review(stem: dict, content: dict, image: dict, answer: dict,
                idx: int = 0, qtype: str = "选择") -> QuestionReview:
    """快捷构造一个四维审查结果"""
    r = QuestionReview(idx=idx, question_type=qtype)
    r.stem_check = make_check(**stem)
    r.content_check = make_check(**content)
    r.image_check = make_check(**image)
    r.answer_check = make_check(**answer)
    return r


# ============================================================
# Mock Agent: 不调 LLM，返回预定义的审查结果
# ============================================================

class MockAgent:
    """Mock 审查智能体，返回预定义的 3 轮审查结果"""

    def __init__(self, scenarios: dict):
        """
        scenarios: {qid: [review_run1, review_run2, review_run3]}
        """
        self.scenarios = scenarios
        self._call_count = {}

    def _create_empty_review(self) -> QuestionReview:
        return QuestionReview()

    def _review_batch(self, q, shot, r, ui_texts=None):
        """不调 LLM，直接用预定义结果覆盖"""
        idx = getattr(q, 'global_idx', getattr(q, 'idx', 0))
        key = f"Q{idx}"
        # 递增调用次数
        self._call_count[key] = self._call_count.get(key, 0) + 1
        run_idx = self._call_count[key] - 1  # 0-based

        if key not in self.scenarios:
            # 兜底：全部通过
            preset = make_review(
                stem=dict(passed=True, score=1.0, confidence=95),
                content=dict(passed=True, score=1.0, confidence=90),
                image=dict(passed=True, score=1.0, confidence=85),
                answer=dict(passed=True, score=1.0, confidence=80),
            )
            self._copy_review(preset, r)
            return

        runs = self.scenarios[key]
        preset = runs[min(run_idx, len(runs) - 1)]
        self._copy_review(preset, r)

    def _copy_review(self, src: QuestionReview, dst: QuestionReview):
        """复制审查结果"""
        for attr in ["stem_check", "content_check", "image_check", "answer_check"]:
            src_check = getattr(src, attr)
            dst_check = getattr(dst, attr)
            dst_check.passed = src_check.passed
            dst_check.score = src_check.score
            dst_check.confidence = src_check.confidence
            dst_check.method = src_check.method
            dst_check.details = list(src_check.details)
            dst_check.error = src_check.error


# ============================================================
# 构造 5 道 Mock 题目，每题预设 3 轮审查结果
# ============================================================

def build_scenarios():
    """
    5 道题，模拟不同一致性场景：

    Q1 — "完全稳定通过"：所有维度 3 次都通过，高置信度
    Q2 — "完全稳定不通过"：所有维度 3 次都不通过
    Q3 — "不稳定（置信度边界）"：题干维度 3 次分别 通过/不通过/不通过
    Q4 — "存在不确定"：作答维度 1 次不确定 = 需人工复核
    Q5 — "基本一致"：3 次中 2 次通过 1 次不通过 → agreement_rate=67%
    """

    sc = {}

    # ========== Q1: 完全稳定通过 ==========
    sc["Q1"] = [
        make_review(
            stem=dict(passed=True, score=1.0, confidence=95, details=["通过"]),
            content=dict(passed=True, score=1.0, confidence=92, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=88, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=90, details=["通过"]),
            idx=1, qtype="选择"
        ),
        make_review(
            stem=dict(passed=True, score=1.0, confidence=94, details=["通过"]),
            content=dict(passed=True, score=1.0, confidence=91, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=87, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=89, details=["通过"]),
            idx=1, qtype="选择"
        ),
        make_review(
            stem=dict(passed=True, score=1.0, confidence=96, details=["通过"]),
            content=dict(passed=True, score=1.0, confidence=93, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=86, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=91, details=["通过"]),
            idx=1, qtype="选择"
        ),
    ]

    # ========== Q2: 完全稳定不通过 ==========
    sc["Q2"] = [
        make_review(
            stem=dict(passed=False, score=0.5, confidence=88, details=["不通过 | 题干文字与脚本不一致"]),
            content=dict(passed=False, score=0.5, confidence=85, details=["不通过 | 选项B显示不完整"]),
            image=dict(passed=True, score=1.0, confidence=80, details=["通过"]),
            answer=dict(passed=False, score=0.5, confidence=82, details=["不通过 | 录音内容与答案不匹配"]),
            idx=2, qtype="听力"
        ),
        make_review(
            stem=dict(passed=False, score=0.5, confidence=87, details=["不通过 | 题干文字与脚本不一致"]),
            content=dict(passed=False, score=0.5, confidence=86, details=["不通过 | 选项B显示不完整"]),
            image=dict(passed=True, score=1.0, confidence=79, details=["通过"]),
            answer=dict(passed=False, score=0.5, confidence=83, details=["不通过 | 录音内容与答案不匹配"]),
            idx=2, qtype="听力"
        ),
        make_review(
            stem=dict(passed=False, score=0.5, confidence=89, details=["不通过 | 题干文字与脚本不一致"]),
            content=dict(passed=False, score=0.5, confidence=84, details=["不通过 | 选项B显示不完整"]),
            image=dict(passed=True, score=1.0, confidence=81, details=["通过"]),
            answer=dict(passed=False, score=0.5, confidence=84, details=["不通过 | 录音内容与答案不匹配"]),
            idx=2, qtype="听力"
        ),
    ]

    # ========== Q3: 不稳定（题干维度摇摆）==========
    sc["Q3"] = [
        make_review(
            stem=dict(passed=True, score=1.0, confidence=72, details=["通过 | 置信度:72 | 题干基本清晰"]),
            content=dict(passed=True, score=1.0, confidence=80, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=75, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=78, details=["通过"]),
            idx=3, qtype="匹配"
        ),
        make_review(
            stem=dict(passed=False, score=0.5, confidence=68, details=["不通过 | 置信度:68 | 题干疑似截断"]),
            content=dict(passed=True, score=1.0, confidence=82, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=74, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=76, details=["通过"]),
            idx=3, qtype="匹配"
        ),
        make_review(
            stem=dict(passed=False, score=0.5, confidence=65, details=["不通过 | 置信度:65 | 题干文字模糊"]),
            content=dict(passed=True, score=1.0, confidence=79, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=73, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=77, details=["通过"]),
            idx=3, qtype="匹配"
        ),
    ]

    # ========== Q4: 存在不确定（作答维度缺图片）==========
    sc["Q4"] = [
        make_review(
            stem=dict(passed=True, score=1.0, confidence=85, details=["通过"]),
            content=dict(passed=True, score=1.0, confidence=80, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=82, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=78, details=["通过"]),
            idx=4, qtype="口语"
        ),
        make_review(
            stem=dict(passed=True, score=1.0, confidence=86, details=["通过"]),
            content=dict(passed=True, score=1.0, confidence=81, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=83, details=["通过"]),
            answer=dict(passed=False, score=0.3, confidence=0, method="uncertain",
                        details=["⚠ 需人工复核 | 无法解析: '配图缺失无法判断作答正确性'"]),
            idx=4, qtype="口语"
        ),
        make_review(
            stem=dict(passed=True, score=1.0, confidence=84, details=["通过"]),
            content=dict(passed=True, score=1.0, confidence=82, details=["通过"]),
            image=dict(passed=True, score=1.0, confidence=81, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=79, details=["通过"]),
            idx=4, qtype="口语"
        ),
    ]

    # ========== Q5: 基本一致（2/3 通过）= mostly ==========
    sc["Q5"] = [
        make_review(
            stem=dict(passed=True, score=1.0, confidence=75, details=["通过 | 置信度:75"]),
            content=dict(passed=True, score=1.0, confidence=73, details=["通过 | 置信度:73"]),
            image=dict(passed=True, score=1.0, confidence=70, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=72, details=["通过"]),
            idx=5, qtype="排序"
        ),
        make_review(
            stem=dict(passed=True, score=1.0, confidence=76, details=["通过 | 置信度:76"]),
            content=dict(passed=False, score=0.5, confidence=65, details=["不通过 | 置信度:65 | 内容疑似有知识错误"]),
            image=dict(passed=True, score=1.0, confidence=71, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=70, details=["通过"]),
            idx=5, qtype="排序"
        ),
        make_review(
            stem=dict(passed=True, score=1.0, confidence=74, details=["通过 | 置信度:74"]),
            content=dict(passed=True, score=1.0, confidence=74, details=["通过 | 置信度:74"]),
            image=dict(passed=True, score=1.0, confidence=69, details=["通过"]),
            answer=dict(passed=True, score=1.0, confidence=73, details=["通过"]),
            idx=5, qtype="排序"
        ),
    ]

    return sc


# ============================================================
# 主测试
# ============================================================

def main():
    print("=" * 70)
    print("  英语宝审查一致性验证 — Mock 数据测试")
    print("=" * 70)

    scenarios = build_scenarios()
    mock_agent = MockAgent(scenarios)

    # 构造 question 对象和 dummy 截图
    import tempfile, os
    tmpdir = tempfile.mkdtemp(prefix="mock_shots_")
    questions = {}
    shots = {}
    for qid in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        idx = int(qid[1])
        q = YingYuBaoQuestion(global_idx=idx, stem=f"Mock题目{qid}", type_2="选择")
        questions[qid] = q
        # 创建 dummy 截图文件，让一致性检查不跳过
        shot_path = os.path.join(tmpdir, f"{qid}.png")
        Path(shot_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        shots[qid] = shot_path

    # 运行一致性检查
    checker = ConsistencyChecker(mock_agent)
    reports = checker.check_batch(questions, shots, runs=3)

    # ==================== 详细输出 ====================
    print(f"\n{'题目':<6} {'整体稳定性':<12} {'需人工复核':<10} {'维度':<6} {'状态':<10} {'一致率':<8} {'平均置信度':<10} {'各轮判定'}")
    print("-" * 100)

    for report in reports:
        overall = "✅ 稳定" if report.overall_stable else "⚠️ 不稳定"
        needs = "是" if report.any_needs_review else "否"

        for i, (dim_name, dv) in enumerate(report.dimensions.items()):
            qid_col = report.question_id if i == 0 else ""
            overall_col = overall if i == 0 else ""
            needs_col = needs if i == 0 else ""

            status_icon = {"stable": "✅", "mostly": "🟡", "unstable": "🔴"}
            icon = status_icon.get(dv.status, "?")

            verdicts_str = " | ".join(dv.verdicts)
            rate_str = f"{dv.agreement_rate:.0%}"
            conf_str = f"{dv.avg_confidence:.0f}%"

            print(f"{qid_col:<6} {overall_col:<12} {needs_col:<10} "
                  f"{dim_name:<6} {icon} {dv.status:<7} "
                  f"{rate_str:<8} {conf_str:>8}   {verdicts_str}")

        print("-" * 100)

    # ==================== 汇总统计 ====================
    summary = checker.summary()
    print(f"\n{'='*70}")
    print(f"  汇总统计")
    print(f"{'='*70}")
    print(f"  总题目数:       {summary['total_questions']}")
    print(f"  稳定题目:       {summary['stable_questions']}")
    print(f"  不稳定题目:     {summary['unstable_questions']}")
    print(f"  需人工复核:     {summary['needs_human_review']}")
    print(f"  整体稳定率:     {summary['overall_stability']:.0%}")
    print(f"\n  各维度平均一致率:")
    for dim, rate in summary["dim_avg_agreement"].items():
        print(f"    {dim}: {rate:.0%}")
    if summary["dim_unstable_count"]:
        print(f"\n  不稳定维度分布:")
        for dim, count in summary["dim_unstable_count"].items():
            print(f"    {dim}: {count} 题")

    # ==================== 断言验证 ====================
    print(f"\n{'='*70}")
    print(f"  断言验证")
    print(f"{'='*70}")

    errors = []

    # 断言 1: Q1 应该完全稳定
    r1 = reports[0]
    if not r1.overall_stable:
        errors.append("FAIL: Q1 应该是完全稳定通过，但标记为不稳定")
    else:
        print("  ✅ Q1 完全稳定通过 ✓")

    # 断言 2: Q2 应该完全稳定（虽然不通过）
    r2 = reports[1]
    if not r2.overall_stable:
        errors.append("FAIL: Q2 应该是完全稳定不通过，但标记为不稳定")
    else:
        print("  ✅ Q2 完全稳定不通过 ✓")

    # 断言 3: Q3 题干维度应为 mostly (1/3通过, 2/3不通过 → 一致率 67%)
    r3 = reports[2]
    stem3 = r3.dimensions["题干"]
    if stem3.status != "mostly":
        errors.append(f"FAIL: Q3题干 status 应为 'mostly'（1通过/2不通过=67%），实际为 '{stem3.status}'")
    if stem3.pass_count != 1 or stem3.fail_count != 2:
        errors.append(f"FAIL: Q3题干 pass/fail 应为 1/2，实际为 {stem3.pass_count}/{stem3.fail_count}")
    else:
        print("  ✅ Q3 题干维度 1/3通过 2/3不通过 = mostly ✓")

    # 断言 4: Q4 应有 uncertain + needs_review
    r4 = reports[3]
    if not r4.any_needs_review:
        errors.append("FAIL: Q4 作答维度存在不确定，应标记 needs_review")
    ans4 = r4.dimensions["作答"]
    if ans4.uncertain_count != 1:
        errors.append(f"FAIL: Q4作答 uncertain_count 应为 1，实际为 {ans4.uncertain_count}")
    else:
        print("  ✅ Q4 作答维度标记 1 次 uncertain + needs_review ✓")

    # 断言 5: Q5 内容维度应为 mostly (2/3)
    r5 = reports[4]
    content5 = r5.dimensions["内容"]
    if content5.status != "mostly":
        errors.append(f"FAIL: Q5内容 status 应为 'mostly'，实际为 '{content5.status}'")
    if content5.pass_count != 2 or content5.fail_count != 1:
        errors.append(f"FAIL: Q5内容 pass/fail 应为 2/1，实际为 {content5.pass_count}/{content5.fail_count}")
    else:
        print("  ✅ Q5 内容维度 2/3 通过 = mostly ✓")

    if errors:
        print(f"\n  ❌ {len(errors)} 个断言失败:")
        for e in errors:
            print(f"     {e}")
        return 1
    else:
        print(f"\n  🎉 所有断言通过！一致性检查模块工作正常。")
        return 0


if __name__ == "__main__":
    exit(main())
