# -*- coding: utf-8 -*-
"""
C1 / C2  溯源数据引擎 + 截图红框标注
====================================
这个文件你（C同学）负责，做两件事：
  1) generate()    —— 读一道题的审查数据，算出"哪几个维度没过、为什么、怎么改、错在哪"
  2) draw_mark()   —— 用 Pillow 在截图上画红框 + 文字（这就是 C2 红框标注）

你不需要懂 Pillow 内部怎么画，只要会调用 draw_mark() 就行（真正画图交给库）。
"""

import os
from PIL import Image, ImageDraw, ImageFont

# 维度对照表：数据里的字段 → 中文维度名 + 对应原因字段 + 程度(high/medium/low，仅存数据，界面不展示)
# 顺序就是报告里出现的顺序。null 表示该项没检查（当通过处理，不报错）。
DIMENSIONS = [
    ("ai_stem",       "stem_reason",       "题干",   "medium"),
    ("ai_content",    "content_reason",    "内容",   "high"),
    ("ai_image",      "image_reason",      "图片",   "high"),
    ("ai_answer",     "answer_reason",     "答案",   "high"),
    ("ai_audio",      "audio_reason",      "音频",   "low"),
    ("ai_post_error", "post_error_reason", "答错检查", "low"),
    ("ai_report",     "report_reason",     "报告",   "low"),
]


class TraceEngine:
    """溯源数据引擎：把一道题的审查结果，转成"错题证据"。"""

    def __init__(self, screenshots_dir: str = "screenshots"):
        # screenshots_dir：APP 原始截图放在哪个文件夹（默认 ./screenshots）
        self.screenshots_dir = screenshots_dir

    # ---------------------------------------------------------------
    # C1：生成溯源数据
    # ---------------------------------------------------------------
    def generate(self, qid: str, question_data: dict) -> dict:
        """
        输入：qid（题号字符串）和这道题的审查数据（来自 inspection_state.json）
        输出：一份"溯源数据"字典，结构见分工文档 5.2：
              {
                "qid": ...,
                "checks": [ {dimension, passed, reason, suggestion, severity, error_region}, ... ],
                "script_context": {stem, recording, answer, options}
              }
        """
        checks = []

        for ai_field, reason_field, dim_name, severity in DIMENSIONS:
            passed = question_data.get(ai_field)
            # null = 该项未检查，跳过；True = 通过，跳过；只有 False 才记一条错误
            if passed is not False:
                continue

            # 这一项没过 → 记一条错误
            reason = (question_data.get(reason_field) or "").strip()
            if not reason:
                reason = "（未提供具体原因，请人工确认）"

            checks.append({
                "dimension": dim_name,
                "passed": False,
                "reason": reason,
                "suggestion": f"请检查并修正「{dim_name}」维度：{reason}",
                "severity": severity,
                "error_region": self._compute_region(question_data, len(checks)),
            })

        # 题干/录音/答案等上下文，供报告展示用
        script_context = {
            "stem": question_data.get("stem", ""),
            "recording": question_data.get("recording", ""),
            "answer": question_data.get("script_answer", ""),
            "options": question_data.get("options", []),
        }

        return {
            "qid": qid,
            "checks": checks,
            "script_context": script_context,
        }

    # ---------------------------------------------------------------
    # 计算红框坐标
    # ---------------------------------------------------------------
    def _compute_region(self, question_data: dict, index: int) -> dict:
        """
        计算红框坐标 error_region。
        理想情况：数据里直接带 error_box（A/B 提供的真实坐标），优先用它。
        演示情况：没有坐标 → 用默认区域（TODO：接真实布局坐标）。
        """
        # 如果数据里带了坐标，直接用（真实项目建议让 A/B 把坐标写进这里）
        if "error_box" in question_data and question_data["error_box"]:
            return question_data["error_box"]

        # 否则给一个占位区域：从上往下排，每多一个错误往下挪一点
        # TODO(C同学): 把这里换成 A/B trace_engine 实际输出的坐标
        y = 60 + index * 120
        return {"x": 40, "y": y, "w": 420, "h": 90}

    # ---------------------------------------------------------------
    # C2：画红框标注
    # ---------------------------------------------------------------
    def draw_mark(self, screenshot_name: str, checks: list, out_path: str) -> str:
        """
        C2 红框标注：打开截图，在每个 error_region 上画红框 + 文字，保存为 marked.png
        返回保存后的文件路径。
        """
        img_path = os.path.join(self.screenshots_dir, screenshot_name)
        if not os.path.exists(img_path):
            raise FileNotFoundError(
                f"找不到截图：{img_path}（请确认 screenshots/ 下有 {screenshot_name}）"
            )

        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 尽量用系统字体，没有就退化成默认字体
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except Exception:
            font = ImageFont.load_default()

        for i, chk in enumerate(checks):
            r = chk.get("error_region") or {"x": 40, "y": 60 + i * 120, "w": 420, "h": 90}
            x, y, w, h = r["x"], r["y"], r["w"], r["h"]
            # 画红色方框（width=4 是线宽）
            draw.rectangle([x, y, x + w, y + h], outline="red", width=4)
            # 在框上方写"维度 + 原因"
            label = f"[{chk['dimension']}] {chk['reason']}"
            draw.text((x, max(0, y - 24)), label, fill="red", font=font)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path)
        return out_path
