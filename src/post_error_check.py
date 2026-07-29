"""
src/post_error_check.py — 答错后检查（需求文档第5项）
负责人：A 同学

职责：
  检测"部分模块需要答错才会出现的内容"是否正确：
  1. 正确答案是否显示
  2. 知识点是否正确
  3. 听力题：听力材料文字是否正确并与音频相符

调用方：B 的巡检循环（每模块首题答错 → 截图结果页 → 调用本模块）
"""

from dataclasses import dataclass, field

@dataclass
class CheckResult:
    passed: bool = False
    score: float = 0.0
    details: list = field(default_factory=list)
    error: str = ""

class PostErrorChecker:
    """答错后检查器"""

    def __init__(self):
        from src.reviewer_common import LLMClient
        self.llm = LLMClient.from_config()

    def check(self, shot_path: str, script_q, ui_texts: list = None) -> CheckResult:
        """
        检查答错后的结果页
        Returns: CheckResult — passed=True 表示结果页显示正确
        """
        result = CheckResult()
        # ===== A 在这里实现 =====
        result.passed = True
        result.score = 1.0
        result.details.append("[TODO: A实现] 答错后检查: 答案/知识点/听力文字")
        return result
