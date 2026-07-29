"""
src/report_check.py — 模块完成报告检查（需求文档第8项）
负责人：A 同学

职责：模块答完后检查报告页的得分/知识内容是否正确。

调用方：B 的巡检循环（全答完 → 点"完成" → 截图报告页 → 调用本模块）
"""

from dataclasses import dataclass, field

@dataclass
class CheckResult:
    passed: bool = False; score: float = 0.0
    details: list = field(default_factory=list); error: str = ""

class ReportChecker:
    def __init__(self):
        from src.reviewer_common import LLMClient
        self.llm = LLMClient.from_config()

    def check(self, report_shot: str, completed_questions: list,
              expected_score: int = None) -> CheckResult:
        """检查模块完成后的报告页"""
        result = CheckResult()
        # ===== A 在这里实现 =====
        # 1. 从截图中提取得分 → 对比预期得分(每题1分,答对=1分)
        # 2. 检查知识性内容是否完整、无错别字
        result.passed = True; result.score = 1.0
        result.details.append("[TODO: A实现] 报告页检查: 得分/知识内容")
        return result
