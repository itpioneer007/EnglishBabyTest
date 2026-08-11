"""
report_check.py — A3: 模块完成报告检查
=========================================

职责:
  全部题目答完后，检查完成报告页:
    1. 得分是否正确（与预期一致）
    2. 知识点/知识内容是否正确
    3. 报告页布局是否正常

触发条件:
  - 仅模块最后一题答完后触发
  - B 同学截图报告页后调用

接口约定 (B 同学调用):
  checker = ReportChecker()
  result = checker.check(report_shot, completed_questions, expected_score=None)
  # result 是 CheckResult 对象: passed, score, details, error

数据字段 (写入 _review_item, 仅最后一题有值):
  ai_report: true/false/null
  report_reason: str
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reviewer_common import LLMClient
from src.feedback_loop import FeedbackStore, ThreeStageTrainer


# ============================================================
# CheckResult (与 review_agent 保持一致)
# ============================================================

@dataclass
class CheckResult:
    """单次检查结果"""
    passed: bool = False
    score: float = 0.0
    details: list = field(default_factory=list)
    error: str = ""

    def to_dict(self):
        return {
            "passed": self.passed,
            "score": self.score,
            "details": self.details[:5],
            "error": self.error[:80],
        }


# ============================================================
# ReportChecker — 模块完成报告检查器
# ============================================================

class ReportChecker:
    """
    A3 实现: 模块完成报告页检查

    检查模块全部答完后的完成报告页:
      - 总分是否合理
      - 知识点总结是否正确
      - 错题回顾是否显示
      - 报告页UI布局

    用法:
        checker = ReportChecker()

        # B 同学在所有题答完后调用
        completed = [
            {"qid": "Q01", "answer": "B", "user_choice": "B", "passed": True},
            {"qid": "Q02", "answer": "A", "user_choice": "C", "passed": False},
            ...
        ]
        result = checker.check("screenshots/report_u6.png", completed)
    """

    def __init__(self, llm: LLMClient = None):
        self.llm = llm or LLMClient.from_config()
        self.feedback = FeedbackStore()
        self.trainer = ThreeStageTrainer(llm=self.llm, store=self.feedback)

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------

    def check(self, report_shot: str, completed_questions: list,
              expected_score: int = None) -> CheckResult:
        """
        检查模块完成报告页

        Args:
            report_shot: 报告页截图路径
            completed_questions: 已完成的题目列表
                [{"qid": "...", "answer": "B", "passed": True/False, ...}, ...]
            expected_score: 预期得分（不传则根据 completed_questions 计算）

        Returns:
            CheckResult
        """
        result = CheckResult()

        if not report_shot or not Path(report_shot).exists():
            result.error = "报告截图不存在"
            result.details.append("[错误] 模块完成报告页截图缺失")
            return result

        # 统计
        total = len(completed_questions)
        correct_count = sum(1 for q in completed_questions if q.get("passed", False))
        if expected_score is None:
            expected_score = correct_count

        # 收集错题
        wrong_questions = [
            q for q in completed_questions if not q.get("passed", False)
        ]

        try:
            prompt = self._build_prompt(
                total=total,
                correct_count=correct_count,
                expected_score=expected_score,
                wrong_questions=wrong_questions,
            )

            answer = self.llm.ask(prompt, image_path=report_shot)

            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.5
            result.details.append(answer[:200])

            # 保存反馈
            self._save_feedback(
                ai_judgment="通过" if passed else "不通过",
                ai_reason=answer[:120],
            )

        except Exception as e:
            result.error = str(e)
            result.details.append(f"[异常] {e}")

        return result

    # ----------------------------------------------------------
    # Prompt 构建
    # ----------------------------------------------------------

    def _build_prompt(self, total: int, correct_count: int,
                      expected_score: int, wrong_questions: list) -> str:
        """构建报告页检查 prompt"""

        fewshot = self.feedback.build_fewshot_prompt(
            max_samples=2, dim_filter="report"
        )
        rules = self.feedback.build_rules()

        # 错题摘要
        wrong_summary = ""
        if wrong_questions:
            wrong_summary = "\n".join(
                f"  - {q.get('qid', '?')}: 正确答案 {q.get('answer', '?')}"
                for q in wrong_questions[:5]
            )
        else:
            wrong_summary = "  (全部正确，无错题)"

        prompt = f"""【你的身份】你是一位小学英语教育APP的题目审查专家。

【任务: 检查模块完成报告页】
学生已完成本模块全部 {total} 道题，这是完成后的报告页截图。

【已知信息】
- 总题数: {total}
- 答对数: {correct_count}
- 预期得分: {expected_score}/{total}
- 预期错题:
{wrong_summary}

请判断:
A. 报告页显示的得分是否约为 {expected_score}/{total}？如有明显偏差请指出。
B. 报告页是否包含知识点总结/知识内容？内容是否合理？
C. 错题是否在报告中有体现？（如错题回顾列表）
D. 报告页整体布局是否正常？有无截断/重叠/模糊？
E. 如果全部正确，报告页是否显示了"满分"/"全对"等鼓励信息？

回答格式: [通过/不通过] | 理由 | 修改建议
"""
        if fewshot:
            prompt = fewshot + "\n\n" + prompt
        if rules:
            prompt += f"\n\n【审查规则】\n{rules}"

        return prompt

    # ----------------------------------------------------------
    # 反馈记录
    # ----------------------------------------------------------

    def _save_feedback(self, ai_judgment: str, ai_reason: str):
        try:
            from src.feedback_loop import FeedbackSample
            sample = FeedbackSample(
                question_id="module_report",
                check_dimension="report",
                ai_judgment=ai_judgment,
                ai_reason=ai_reason,
            )
            self.feedback.add(sample)
        except Exception:
            pass


# ============================================================
# 便捷函数
# ============================================================

_report_checker = None

def get_checker() -> ReportChecker:
    """获取全局 ReportChecker 实例"""
    global _report_checker
    if _report_checker is None:
        _report_checker = ReportChecker()
    return _report_checker


def check_report(report_shot: str, completed_questions: list,
                 expected_score: int = None) -> dict:
    """
    便捷函数: 检查模块完成报告页

    Args:
        report_shot: 报告页截图
        completed_questions: 已完成题目列表
        expected_score: 预期得分

    Returns:
        {"passed": bool, "score": float, "details": [str], "error": str}
    """
    checker = get_checker()
    result = checker.check(report_shot, completed_questions, expected_score)
    return result.to_dict()


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    # 模拟已完成的题目
    mock_completed = [
        {"qid": "U6-Q01", "answer": "B", "user_choice": "B", "passed": True},
        {"qid": "U6-Q02", "answer": "A", "user_choice": "C", "passed": False},
        {"qid": "U6-Q03", "answer": "C", "user_choice": "C", "passed": True},
        {"qid": "U6-Q04", "answer": "B", "user_choice": "B", "passed": True},
    ]

    print("=" * 50)
    print("A3 模块报告检查 - 独立测试")
    print("=" * 50)

    checker = ReportChecker()

    test_shot = "screenshots/test_report.png"
    if Path(test_shot).exists():
        result = checker.check(test_shot, mock_completed)
        print(f"通过: {result.passed}")
        print(f"分数: {result.score}")
        print(f"详情: {result.details}")
    else:
        print(f"⚠ 测试截图不存在: {test_shot}")
        print("请放置一张模块完成报告页截图到 screenshots/test_report.png")
        print()
        print("检查器已就绪，B 同学可通过以下方式调用:")
        print("  from src.report_check import check_report")
        print("  result = check_report('截图.png', completed_questions)")
