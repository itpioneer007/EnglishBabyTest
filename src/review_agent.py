"""
review_agent.py — 英语宝审查智能体 (v2: 知识库 + 反馈循环)
=====================================================================

功能:
  - 四维检查: (1)题干 (2)内容 (3)配图 (4)作答
  - 知识库查证: 验证题目是否在教材范围内
  - 反馈循环: 记录AI判断, 对比人工标注, 持续优化
  - 双模型架构: deepseek-v4-pro(文本) + qwen3.7-plus(视觉)

用法:
    # 命令行模式(快速审查)
    python review_agent.py --docx "脚本.docx" --unit 6 --stage "基础巩固"

    # 编程模式
    agent = ReviewAgent(script_docx="脚本.docx", knowledge_docx="教材.docx")
    results = agent.review_by_questions(q06_shot="screenshots/q006.png", ...)
    agent.export_report("审查报告.md")

三阶段训练:
    agent.trainer.run_phase2_comparison(ai_results, human_labels)
    agent.trainer.export_report()
"""

import sys, json, time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reviewer_common import LLMClient
from src.parse_yingyubao_docx import parse, YingYuBaoQuestion
from src.feedback_loop import FeedbackStore, FeedbackSample, ThreeStageTrainer
from src.knowledge_base import KnowledgeBase


# ============================================================
# 配置
# ============================================================

@dataclass
class ReviewConfig:
    """审查配置"""
    docx_path: str = ""               # 公司提供的脚本 DOCX
    knowledge_docx: str = ""          # 教材知识库来源(可选, 同名DOCX)
    unit: int = 0                     # 0=全部
    stage: str = ""                   # 空=全部, "基础巩固"/"综合进阶"/"难点突破"
    screenshot_dir: str = "screenshots"
    output_dir: str = "outputs"
    verbose: bool = True              # 打印详细信息

# ============================================================
# 审查结果数据模型
# ============================================================

@dataclass
class CheckResult:
    """单次检查结果"""
    passed: bool = False
    score: float = 0.0                # 0~1
    details: list = field(default_factory=list)
    error: str = ""
    
    def to_dict(self):
        return {"passed": self.passed, "score": self.score, 
                "details": self.details[:5], "error": self.error[:80]}

@dataclass
class QuestionReview:
    """一题的完整审查结果"""
    idx: int = 0
    question_type: str = ""
    script_answer: str = ""
    
    # 四维检查结果
    stem_check: CheckResult = field(default_factory=CheckResult)
    content_check: CheckResult = field(default_factory=CheckResult)
    image_check: CheckResult = field(default_factory=CheckResult)
    answer_check: CheckResult = field(default_factory=CheckResult)
    
    # 知识库查证
    knowledge_check: dict = field(default_factory=dict)
    
    # 综合判定
    overall_passed: bool = False
    overall_score: float = 0.0
    
    screenshot: str = ""
    timestamp: str = ""

    def to_dict(self):
        return {
            "idx": self.idx,
            "type": self.question_type,
            "script_answer": self.script_answer,
            "stem": self.stem_check.to_dict(),
            "content": self.content_check.to_dict(),
            "image": self.image_check.to_dict(),
            "answer": self.answer_check.to_dict(),
            "knowledge": self.knowledge_check,
            "overall_passed": self.overall_passed,
            "overall_score": round(self.overall_score, 2),
            "screenshot": self.screenshot,
        }


# ============================================================
# 审查智能体 (核心)
# ============================================================

class ReviewAgent:
    """
    英语宝审查智能体

    四维检查 + 知识库查证 + 反馈循环
    """

    def __init__(self, config: ReviewConfig = None):
        self.cfg = config or ReviewConfig()
        
        # LLM (双模型)
        self.llm = LLMClient.from_config()
        
        # 脚本数据
        self.script_questions: list[YingYuBaoQuestion] = []
        self._load_script()

        # 知识库
        self.kb = KnowledgeBase()
        if self.cfg.knowledge_docx:
            self.kb.add_bulk_from_docx(self.cfg.knowledge_docx)

        # 反馈循环
        self.feedback = FeedbackStore()
        self.trainer = ThreeStageTrainer(llm=self.llm, store=self.feedback)

        # 结果
        self.results: list[QuestionReview] = []

    # ============================================================
    # 脚本加载
    # ============================================================

    def _load_script(self):
        if self.cfg.docx_path and Path(self.cfg.docx_path).exists():
            self.script_questions = parse(self.cfg.docx_path)
            # 过滤
            if self.cfg.unit:
                self.script_questions = [
                    q for q in self.script_questions if q.unit == self.cfg.unit
                ]
            if self.cfg.stage:
                self.script_questions = [
                    q for q in self.script_questions if q.stage == self.cfg.stage
                ]
            print(f"📋 加载脚本: {len(self.script_questions)} 题")
        else:
            print("⚠ 未加载脚本文件 (仅做基本检查)")

    # ============================================================
    # 审查入口
    # ============================================================

    def review(self, screenshots: dict[int, str] = None) -> list[QuestionReview]:
        """
        执行完整审查
        
        Args:
            screenshots: {global_idx: "screenshot_path", ...}
                         如果不传, 自动从 screenshot_dir 扫描
            
        Returns:
            list[QuestionReview]
        """
        if screenshots is None:
            screenshots = self._scan_screenshots()

        self.results = []
        for q in self.script_questions:
            shot = screenshots.get(q.global_idx, "")
            r = self._review_one(q, shot)
            self.results.append(r)

            if self.cfg.verbose:
                icon = "✅" if r.overall_passed else "❌"
                print(f"  Q{r.idx:02d} {icon} score={r.overall_score:.2f}")

        return self.results

    def _scan_screenshots(self) -> dict:
        """扫描截图文件夹"""
        folder = Path(self.cfg.screenshot_dir)
        mapping = {}
        if folder.exists():
            for f in sorted(folder.glob("*.png")):
                num = f.stem.replace("q", "").replace("Q", "")
                try:
                    mapping[int(num)] = str(f)
                except ValueError:
                    pass
        return mapping

    # ============================================================
    # 单题审查
    # ============================================================

    def _review_one(self, q: YingYuBaoQuestion, screenshot: str) -> QuestionReview:
        """审查一道题 (四维 + 知识库)"""
        r = QuestionReview(
            idx=q.global_idx,
            question_type=q.type_2,
            script_answer=q.answer,
            screenshot=screenshot,
            timestamp=datetime.now().isoformat(),
        )

        if not screenshot or not Path(screenshot).exists():
            r.stem_check.error = "无截图"
            r.content_check.error = "无截图"
            r.image_check.error = "无截图"
            r.answer_check.error = "无截图"
            r.overall_passed = False
            return r

        # ---- (1) 题干检查 ----
        r.stem_check = self._check_stem(q, screenshot)

        # ---- (2) 内容检查 + 知识库 ----
        r.content_check = self._check_content(q, screenshot)
        r.knowledge_check = self._verify_knowledge(q)

        # ---- (3) 配图检查 ----
        r.image_check = self._check_image(q, screenshot)

        # ---- (4) 作答检查 ----
        r.answer_check = self._check_answer(q, screenshot)

        # ---- 综合评分 ----
        scores = [
            r.stem_check.score,
            r.content_check.score,
            r.image_check.score,
            r.answer_check.score,
        ]
        r.overall_score = sum(scores) / len(scores) if scores else 0.0
        r.overall_passed = r.overall_score >= 0.7

        return r

    # ============================================================
    # 四维检查实现
    # ============================================================

    def _check_stem(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(1) 题干检查: OCR提取文字 vs 脚本 """
        result = CheckResult()
        try:
            # 用视觉模型看题干是否完整清晰
            prompt = self.trainer.build_enhanced_prompt(
                f"你是英语题题干质检专家。\n题目: {q.stem}\n题型: {q.type_2}\n\n"
                f"请看截图,判断:\n1. 题目文字是否完整清晰?\n2. 有无错别字?\n"
                f"3. 是否与脚本'题目: {q.stem}'一致?\n"
                f"用1行回答,末尾格式: [通过/不通过] + 理由",
                dim_filter="stem"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.3
            result.details.append(answer[:120])
        except Exception as e:
            result.error = str(e)
        return result

    def _check_content(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(2) 内容检查: 选项文字 vs 脚本 + 知识库查证"""
        result = CheckResult()
        try:
            kb_verify = self._verify_knowledge(q)
            kb_info = ""
            if kb_verify:
                matched = kb_verify.get("matched", [])
                unknown = kb_verify.get("unknown", [])
                if matched:
                    kb_info = f"(知识库: {len(matched)}个词匹配教材)"
                if unknown:
                    kb_info += f" ⚠ {len(unknown)}个词不在教材范围={unknown[:3]}"

            prompt = self.trainer.build_enhanced_prompt(
                f"你是英语题内容质检专家。\n题型: {q.type_2}\n答案: {q.answer}\n"
                f"录音: {q.recording}\n{kb_info}\n\n"
                f"请看截图,判断:\n1. 选项文字是否与录音匹配?\n2. 答案是否正确?\n"
                f"3. 知识点是否在教材范围内?\n"
                f"用1行回答,末尾格式: [通过/不通过] + 理由",
                dim_filter="content"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.3
            result.details.append(answer[:120])
        except Exception as e:
            result.error = str(e)
        return result

    def _check_image(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(3) 配图检查: 图片内容是否匹配录音/答案"""
        result = CheckResult()
        if "图片" not in q.type_2:
            result.passed = True
            result.score = 1.0
            result.details.append("⏭ 非配图题")
            return result

        try:
            prompt = self.trainer.build_enhanced_prompt(
                f"你是英语听力题配图质检专家。\n"
                f"录音: {q.recording}\n答案: {q.answer}\n题型: {q.type_2}\n\n"
                f"截图中有配图,请判断:\n"
                f"1. 图片是否清晰完整(无截断/模糊)?\n"
                f"2. 图片内容是否与录音匹配?\n"
                f"3. 图片有无逻辑问题?\n"
                f"用1行回答,末尾格式: [通过/不通过] + 理由",
                dim_filter="image"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.3
            result.details.append(answer[:120])
        except Exception as e:
            result.error = str(e)
        return result

    def _check_answer(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(4) 作答检查: 题目可否作答, 答案能否完整输入"""
        result = CheckResult()
        try:
            # 检查UI可点击元素 (通过截图识别)
            prompt = self.trainer.build_enhanced_prompt(
                f"你是英语题作答可行性质检专家。\n题型: {q.type_2}\n\n"
                f"请看截图,判断:\n"
                f"1. 这道题的选项/输入框是否可见?\n"
                f"2. 能否正常作答(点击/输入)?\n"
                f"3. 如果能填写答案, 答案'{q.answer}'能否完整输入?\n"
                f"用1行回答,末尾格式: [通过/不通过] + 理由",
                dim_filter="answer"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.3
            result.details.append(answer[:120])
        except Exception as e:
            result.error = str(e)
        return result

    # ============================================================
    # 知识库查证
    # ============================================================

    def _verify_knowledge(self, q: YingYuBaoQuestion) -> dict:
        """验证题目是否在教材知识范围内"""
        # 从问题中提取词汇
        vocab = []
        for opt in q.options:
            import re
            clean = re.sub(r'^[A-C][\.\、\s]+', '', opt).strip()
            if clean:
                vocab.extend(re.findall(r'[a-zA-Z]+', clean.lower()))

        result = self.kb.verify_question(
            unit=q.unit,
            vocab_used=vocab,
            version="湘鲁版",
            grade=self._name_to_grade(q.keywords) or "五上",
        )
        return result

    def _name_to_grade(self, keywords: list) -> str:
        """从关键词中提取年级"""
        for kw in keywords:
            if "三上" in kw: return "三上"
            if "三下" in kw: return "三下"
            if "四上" in kw: return "四上"
            if "四下" in kw: return "四下"
            if "五上" in kw: return "五上"
            if "五下" in kw: return "五下"
            if "六上" in kw: return "六上"
            if "六下" in kw: return "六下"
        return "五上"

    # ============================================================
    # 报告生成
    # ============================================================

    def export_report(self, path: str = None) -> str:
        """导出审查报告 (Markdown)"""
        if not path:
            self.cfg.output_dir and Path(self.cfg.output_dir).mkdir(exist_ok=True)
            path = f"{self.cfg.output_dir or 'outputs'}/review_report.md"

        total = len(self.results)
        passed = sum(1 for r in self.results if r.overall_passed)
        avg_score = sum(r.overall_score for r in self.results) / total if total else 0

        lines = [
            "# 英语宝审查报告\n",
            f"生成时间: {datetime.now().isoformat()}",
            f"脚本: {self.cfg.docx_path}",
            f"单元: {self.cfg.unit or '全部'} | 阶段: {self.cfg.stage or '全部'}",
            f"审查题数: {total}",
            f"通过: {passed}/{total} ({passed/total*100:.0f}%)",
            f"综合得分: {avg_score:.2f}\n",
        ]

        # 按题型统计
        type_stats = {}
        for r in self.results:
            tp = r.question_type or "未知"
            if tp not in type_stats:
                type_stats[tp] = {"total": 0, "passed": 0}
            type_stats[tp]["total"] += 1
            if r.overall_passed:
                type_stats[tp]["passed"] += 1

        lines.append("## 题型统计\n")
        lines.append("| 题型 | 总数 | 通过 | 通过率 |")
        lines.append("|------|------|------|--------|")
        for tp, s in sorted(type_stats.items()):
            rate = f"{s['passed']/s['total']*100:.0f}%" if s['total'] else "-"
            lines.append(f"| {tp} | {s['total']} | {s['passed']} | {rate} |")

        # 逐题详情
        lines.extend(["\n## 逐题详情\n", "| # | 题型 | 题干 | 内容 | 配图 | 作答 | 总评 |"])
        lines.append("|---|------|------|------|------|------|------|")
        for r in self.results:
            def icon(p):
                return "✅" if p else "❌"
            lines.append(
                f"| Q{r.idx:02d} | {r.question_type[:10]} | "
                f"{icon(r.stem_check.passed)} | "
                f"{icon(r.content_check.passed)} | "
                f"{icon(r.image_check.passed)} | "
                f"{icon(r.answer_check.passed)} | "
                f"{'✅' if r.overall_passed else '❌'} ({r.overall_score:.2f}) |"
            )

        # 问题题目
        failed = [r for r in self.results if not r.overall_passed]
        if failed:
            lines.append(f"\n## 问题题目 ({len(failed)} 题)\n")
            for r in failed:
                lines.append(f"### Q{r.idx:02d} ({r.question_type})\n")
                if r.stem_check.details:
                    lines.append(f"- 题干: {r.stem_check.details[0]}")
                if r.content_check.details:
                    lines.append(f"- 内容: {r.content_check.details[0]}")
                if r.image_check.details:
                    lines.append(f"- 配图: {r.image_check.details[0]}")
                if r.answer_check.details:
                    lines.append(f"- 作答: {r.answer_check.details[0]}")
                lines.append("")

        # 反馈统计
        feedback_stats = self.feedback.get_stats()
        if feedback_stats.get("total", 0) > 0:
            lines.append("\n## 反馈数据\n")
            lines.append(f"- 总样本: {feedback_stats['total']}")
            lines.append(f"- 准确率: {feedback_stats['accuracy']}")
            bad_patterns = self.feedback.get_bad_patterns()
            if bad_patterns:
                lines.append("- 高频错误模式:")
                for p in bad_patterns:
                    lines.append(f"  - {p}")

        report = "\n".join(lines)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(report, encoding="utf-8")
        print(f"📄 报告已保存: {path}")
        return report

    def export_json(self, path: str = None) -> str:
        """导出 JSON 格式结果"""
        if not path:
            self.cfg.output_dir and Path(self.cfg.output_dir).mkdir(exist_ok=True)
            path = f"{self.cfg.output_dir or 'outputs'}/review_results.json"

        data = {
            "config": {
                "docx": self.cfg.docx_path,
                "unit": self.cfg.unit,
                "stage": self.cfg.stage,
            },
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.overall_passed),
                "avg_score": round(
                    sum(r.overall_score for r in self.results) / len(self.results), 2
                ) if self.results else 0,
            },
            "results": [r.to_dict() for r in self.results],
            "feedback_stats": self.feedback.get_stats(),
            "timestamp": datetime.now().isoformat(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"📄 JSON 已保存: {path}")
        return path


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="英语宝审查智能体")
    p.add_argument("--docx", required=True, help="脚本 DOCX 文件")
    p.add_argument("--knowledge", help="知识库来源 DOCX (可选)")
    p.add_argument("--unit", type=int, default=0, help="指定单元")
    p.add_argument("--stage", default="", help="指定阶段")
    p.add_argument("--screenshots", default="screenshots", help="截图目录")
    p.add_argument("--feedback", action="store_true", help="运行后进入反馈模式")
    p.add_argument("--report", action="store_true", help="生成报告")
    p.add_argument("--train", action="store_true", help="生成训练报告")
    args = p.parse_args()

    cfg = ReviewConfig(
        docx_path=args.docx,
        knowledge_docx=args.knowledge or args.docx,
        unit=args.unit,
        stage=args.stage,
        screenshot_dir=args.screenshots,
    )

    agent = ReviewAgent(cfg)
    results = agent.review()

    if args.report:
        agent.export_report()
        agent.export_json()

    if args.feedback:
        print("\n反馈统计:")
        print(json.dumps(agent.feedback.get_stats(), ensure_ascii=False, indent=2))
        print("\n错误模式:")
        for p in agent.feedback.get_bad_patterns():
            print(f"  {p}")

    if args.train:
        print(agent.trainer.export_report())
