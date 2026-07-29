"""
src/trace_engine.py — 溯源数据生成引擎
负责人：C

职责：
  1. 根据审查结果 + APP截图 + 脚本数据生成一个完整的 _trace_detail 结构
  2. 包含每个错误维度的：原因、修改建议、严重程度、(可选的)截图标注坐标

调用方：
  routes/trace_routes.py → 调用 TraceEngine.generate(qid, question_data)
  routes/export_routes.py → 导出时也可能读取 trace 数据

实现思路：
  1. 解析 _review_item 中的 reason 字段，提取关键信息
  2. 调用 LLM 生成修改建议（复用 src.reviewer_common.LLMClient）
  3. 读取脚本内容（从 KnowledgeBase 或 parse_yingyubao_docx）
  4. 组装成 _trace_detail 结构返回

_数据契约见 routes/trace_routes.py 中的 _data_contract 注释
"""

from pathlib import Path
from typing import Optional


class TraceEngine:
    """溯源数据生成引擎"""

    def __init__(self, screenshot_dir: str = None):
        project_root = Path(__file__).parent.parent
        self.screenshot_dir = Path(screenshot_dir or str(project_root / "screenshots"))

    def generate(self, qid: str, question_data: dict) -> dict:
        """
        生成单道题的完整溯源数据

        Args:
            qid: 题目ID，如 "新湘鲁六上-U6-Q03"
            question_data: 审查结果数据（_review_item 结构）

        Returns:
            _trace_detail 结构的字典

        TODO: A 实现
        """
        # ===== A 在这里填真正的逻辑 =====

        checks = []
        for dim in ["stem", "content", "image", "answer"]:
            passed = question_data.get(f"ai_{dim[:3]}", False)
            reason = question_data.get(f"{dim}_reason", "")
            checks.append({
                "dimension": self._dim_name(dim),
                "passed": bool(passed),
                "reason": reason,
                "suggestion": self._generate_suggestion(dim, reason, question_data),
                "severity": self._calc_severity(dim, reason),
                "error_region": None,  # 可选：{"x":, "y":, "w":, "h":}
            })

        return {
            "qid": qid,
            "question_type": question_data.get("question_type", ""),
            "screenshot": question_data.get("screenshot", ""),
            "overall_passed": question_data.get("overall_passed", False),
            "overall_score": question_data.get("overall_score", 0),
            "checks": checks,
            "script_context": {
                "stem": question_data.get("stem", ""),
                "recording": question_data.get("recording", ""),
                "answer": question_data.get("script_answer", ""),
                "options": [],         # TODO(A): 从脚本中获取
                "kb_words": [],        # TODO(A): 从 KnowledgeBase 获取
            },
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }

    def _dim_name(self, dim_short: str) -> str:
        """维度缩写 → 中文名"""
        return {"stem": "题干", "content": "内容", "image": "配图", "answer": "作答"}.get(dim_short, dim_short)

    def _generate_suggestion(self, dim: str, reason: str, q_data: dict) -> str:
        """根据错误原因生成修改建议（可调LLM增强）"""
        # TODO(A): 调用 LLM 生成更精准的修改建议
        return ""

    def _calc_severity(self, dim: str, reason: str) -> str:
        """根据维度类型计算严重程度"""
        # 默认：配图/作答问题严重度更高
        if dim in ("image", "answer"):
            return "high"
        return "medium"
