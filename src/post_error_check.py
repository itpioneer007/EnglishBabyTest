"""
post_error_check.py — A1: 答错后结果页检查
=============================================

职责:
  每模块首题故意选错 → 截图结果页 → 检查:
    1. 正确答案是否正确显示
    2. 知识点/解析是否与脚本一致
    3. 听力文字（如有）是否完整

接口约定 (B 同学调用):
  checker = PostErrorChecker()
  result = checker.check(shot_path, script_q, ui_texts=None)
  # result 是 CheckResult 对象: passed, score, details, error

数据字段 (写入 _review_item):
  ai_post_error: true/false/null
  post_error_reason: str
"""

import sys
import re
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
    """单次检查结果 — 与 review_agent.CheckResult 保持一致"""
    passed: bool = False
    score: float = 0.0                # 0~1, 默认: 1.0(通过)/0.5(不通过)/1.0(跳过)
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
# PostErrorChecker — 答错后检查器
# ============================================================

class PostErrorChecker:
    """
    A1 实现: 答错后结果页检查

    触发条件:
      - 每模块第一题故意选错答案
      - B 同学在巡检循环中截图结果页后调用

    检查维度:
      1. 正确答案显示 — APP是否显示了正确答案
      2. 知识点/解析 — 知识点标注是否与脚本一致
      3. 听力文字 — 听力内容是否完整显示（听力题）
      4. 整体布局 — 结果页UI是否正常（无截断/错位）

    用法:
        checker = PostErrorChecker()

        # B 同学在巡检中调用
        script_q = {"answer": "B", "recording": "This student is helpful.", ...}
        result = checker.check("screenshots/post_error_q01.png", script_q)

        # 返回:
        # CheckResult(passed=True, score=1.0, details=["..."])
        # 或
        # CheckResult(passed=False, score=0.3, details=["[不通过] 正确答案未显示..."])
    """

    def __init__(self, llm: LLMClient = None):
        """
        Args:
            llm: LLM 客户端（可选，不传则自动从配置创建）
        """
        self.llm = llm or LLMClient.from_config()
        self.feedback = FeedbackStore()
        self.trainer = ThreeStageTrainer(llm=self.llm, store=self.feedback)

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------

    def check(self, shot_path: str, script_q, ui_texts: list = None) -> CheckResult:
        """
        检查答错后的结果页截图

        Args:
            shot_path: 结果页截图路径
            script_q: 脚本题目数据 (YingYuBaoQuestion 或 dict)
                      必须有: answer, recording, stem, type_2, options
            ui_texts: OCR 提取的 UI 文字列表（可选，增强检查精度）

        Returns:
            CheckResult: passed=True 表示结果页正确显示了答案和解析
        """
        result = CheckResult()

        # 检查截图是否存在
        if not shot_path or not Path(shot_path).exists():
            result.error = "截图不存在"
            result.details.append("[错误] 答错后结果页截图缺失")
            return result

        # 提取脚本数据（兼容 YingYuBaoQuestion 和 dict）
        script_answer = getattr(script_q, "answer", "") or script_q.get("answer", "")
        script_recording = getattr(script_q, "recording", "") or script_q.get("recording", "")
        script_type = getattr(script_q, "type_2", "") or script_q.get("type_2", "")
        script_stem = getattr(script_q, "stem", "") or script_q.get("stem", "")
        script_kp = getattr(script_q, "knowledge_points", []) or script_q.get("knowledge_points", [])

        is_audio_question = any(kw in script_type for kw in ["听音", "听力", "听"])

        try:
            # 构建审查 prompt
            prompt = self._build_prompt(
                script_answer=script_answer,
                script_recording=script_recording,
                script_type=script_type,
                script_stem=script_stem,
                script_kp=script_kp,
                is_audio=is_audio_question,
                ui_texts=ui_texts,
            )

            # 调用 LLM（视觉模型）
            answer = self.llm.ask(prompt, image_path=shot_path)

            # 解析结果
            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.5
            result.details.append(answer[:200])

            # 保存反馈样本（用于后续优化）
            self._save_feedback(
                question_id=script_q.get("qid", "") if isinstance(script_q, dict) else "",
                script_type=script_type,
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

    def _build_prompt(self, script_answer: str, script_recording: str,
                      script_type: str, script_stem: str, script_kp: list,
                      is_audio: bool, ui_texts: list = None) -> str:
        """构建答错后检查的 LLM prompt"""

        # few-shot 示例
        fewshot = self.feedback.build_fewshot_prompt(
            max_samples=2, dim_filter="post_error"
        )
        # 规则
        rules = self.feedback.build_rules()

        # OCR 文本（如果有）
        ocr_info = ""
        if ui_texts:
            ocr_info = f"\n【OCR 识别到的屏幕文字】\n" + "\n".join(
                f"  - {t}" for t in ui_texts[:20]
            )

        prompt = f"""【你的身份】你是一位小学英语教育APP的题目审查专家。

【任务: 检查答错后的结果页】
这是学生故意选错答案后显示的结果页截图。请仔细检查:

1. **正确答案是否显示**: 脚本正确答案是 "{script_answer}"，截图中是否显示了正确答案？
2. **题型**: {script_type}
3. **题干**: {script_stem[:80]}
4. **脚本录音原文**: {script_recording}
{ocr_info}

请判断:
A. 结果页是否显示了正确答案？正确答案是否为 "{script_answer}"？
B. 结果页是否显示了知识点/解析？如有，是否合理？
C. {"（听力题）听力文字是否完整显示？" if is_audio else "（非听力题，不检查听力文字）"}
D. 结果页整体布局是否正常？有无截断/重叠/模糊？

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

    def _save_feedback(self, question_id: str, script_type: str,
                       ai_judgment: str, ai_reason: str):
        """保存本次检查结果到反馈库"""
        try:
            from src.feedback_loop import FeedbackSample
            sample = FeedbackSample(
                question_id=question_id,
                check_dimension="post_error",
                question_type=script_type,
                ai_judgment=ai_judgment,
                ai_reason=ai_reason,
            )
            self.feedback.add(sample)
        except Exception:
            pass  # 反馈保存失败不影响主流程


# ============================================================
# 便捷函数（供 B 同学直接调用）
# ============================================================

_checker_instance = None

def get_checker() -> PostErrorChecker:
    """获取全局 PostErrorChecker 实例（延迟初始化）"""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = PostErrorChecker()
    return _checker_instance


def check_post_error(shot_path: str, script_q,
                     ui_texts: list = None) -> dict:
    """
    便捷函数: 检查答错后结果页

    Args:
        shot_path: 结果页截图
        script_q: 脚本题目 (dict 或 YingYuBaoQuestion)
        ui_texts: OCR 文字

    Returns:
        {"passed": bool, "score": float, "details": [str], "error": str}
    """
    checker = get_checker()
    result = checker.check(shot_path, script_q, ui_texts)
    return result.to_dict()


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    # 构造模拟题目
    mock_q = {
        "qid": "新湘鲁六上-U6-Q01",
        "answer": "B",
        "recording": "This student is helpful.",
        "stem": "英语课上，老师在播放一段录音...",
        "type_2": "听音选择词汇",
        "options": ["A. help", "B. helpful", "C. happy"],
        "knowledge_points": ["helpful 有帮助的"],
    }

    print("=" * 50)
    print("A1 答错后检查 - 独立测试")
    print("=" * 50)

    checker = PostErrorChecker()

    # 如果有测试截图
    test_shot = "screenshots/test_post_error.png"
    if Path(test_shot).exists():
        result = checker.check(test_shot, mock_q)
        print(f"通过: {result.passed}")
        print(f"分数: {result.score}")
        print(f"详情: {result.details}")
    else:
        print(f"⚠ 测试截图不存在: {test_shot}")
        print("请放置一张答错后结果页截图到 screenshots/test_post_error.png")
        print()
        print("检查器已就绪，B 同学可通过以下方式调用:")
        print("  from src.post_error_check import check_post_error")
        print("  result = check_post_error('截图.png', script_q)")
