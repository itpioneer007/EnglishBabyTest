# -*- coding: utf-8 -*-
"""
C1 / C2  溯源数据引擎 + 截图红框标注
====================================
这个文件你（C同学）负责，做两件事：
  1) generate()    —— 读一道题的审查数据，算出"哪几个维度没过、为什么、怎么改、错在哪"
  2) draw_mark()   —— 用 Pillow 在截图上画红框 + 文字（这就是 C2 红框标注）

你不需要懂 Pillow 内部怎么画，只要会调用 draw_mark() 就行（真正画图交给库）。

★ 2026-09-17 修复（用户实测：红框画到手机状态栏上）
  旧实现 _compute_region() 在拿不到真实坐标时会返回一个**占位框**
  (x=40, y=60+index*120, w=420, h=90)。1080×2400 的截图里这个位置正好是
  顶部通知栏/状态栏 —— 于是"题干与脚本不符"的红框框住了信号和电量图标，
  与问题描述完全无关，检查人员看到只会更困惑。
  现在：
    - 有真实坐标（question_data["_boxes"]，来自 uiautomator 的 node bounds）→ 精确框选；
    - 没有真实坐标 → **不画框**，改为在图片顶部画一条结论横幅，宁可没有框也不误导；
    - 额外提供 crop_evidence()，把出错区域裁成特写图给错题卡展示。
"""

import os
from PIL import Image, ImageDraw, ImageFont

# 维度对照表：(数据字段, 原因字段, 建议字段, 中文维度名, 程度, 坐标键)
# 顺序就是报告里出现的顺序。None 表示该项没检查（当通过处理，不报错）。
DIMENSIONS = [
    ("ai_stem",       "stem_reason",       "stem_suggestion",       "题干",     "medium", "stem"),
    ("ai_content",    "content_reason",    "content_suggestion",    "内容",     "high",   "content"),
    ("ai_image",      "image_reason",      "image_suggestion",      "图片",     "high",   "image"),
    ("ai_answer",     "answer_reason",     "answer_suggestion",     "答案",     "high",   "answer"),
    ("ai_audio",      "audio_reason",      "audio_suggestion",      "音频",     "low",    "audio"),
    ("ai_post_error", "post_error_reason", "post_error_suggestion", "答错检查",  "low",    "post_error"),
    ("ai_report",     "report_reason",     "report_suggestion",     "报告",     "low",    "report"),
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
        boxes = question_data.get("_boxes") or {}
        # ★ 真实修改建议（LLM 给的，如"把关键词改为 take their raincoats"）；
        #   旧实现把 reason 原样拼进"请检查并修正「题干」维度：{reason}"，
        #   导致卡片上"原因"和"建议"文字一模一样（用户实测反馈"不够直白/太长"）。
        sugg_map = question_data.get("_suggestions") or {}
        # ★ 脚本层结论（layer=basic+script 时挂在 question_data["script"]）。
        #   基础层看的是"App 界面"，脚本层看的是"脚本内容"，两者互补：
        #   只读基础层会漏掉"关键词与答案不一致"这类纯脚本内容缺陷（用户实测需求）。
        sc = question_data.get("script") if isinstance(question_data.get("script"), dict) else {}
        sc_sugg = (sc.get("suggestions") or {}) if isinstance(sc, dict) else {}

        for ai_field, reason_field, sugg_field, dim_name, severity, box_key in DIMENSIONS:
            dim_key = ai_field[3:]                      # ai_stem → stem
            b_pass = question_data.get(ai_field)        # 基础层判定
            s_pass = sc.get(dim_key) if sc else None    # 脚本层判定
            b_reason = (question_data.get(reason_field) or "").strip()
            s_reason = ((sc.get(dim_key + "_reason") or "") if sc else "").strip()

            # 合并规则：任一层判 False → 记错（错题卡不放过任何一层的问题）；
            # 两层都 False → 以基础层线索为主，并把脚本层结论一并附上（信息不丢）。
            if b_pass is not False and s_pass is not False:
                continue                                # 未检或通过 → 不记错
            if b_pass is False and s_pass is False:
                layer = "基础层+脚本层"
                reason = b_reason or s_reason
                if b_reason and s_reason and s_reason not in b_reason:
                    reason = f"{b_reason}；脚本层：{s_reason}"
            elif b_pass is False:
                layer, reason = "基础层", b_reason
            else:
                layer, reason = "脚本层", s_reason

            if not reason:
                reason = "（未提供具体原因，请人工确认）"

            suggestion = (question_data.get(sugg_field) or "").strip() \
                or (sugg_map.get(dim_name) or "").strip() \
                or ((sc.get(dim_key + "_suggestion") or "").strip() if sc else "") \
                or (sc_sugg.get(dim_name) or "").strip()
            if not suggestion or suggestion == reason:
                # 没拿到独立建议 → 给一句可执行的兜底，绝不与原因重复
                suggestion = _fallback_suggestion(dim_name, reason)

            checks.append({
                "dimension": dim_name,
                "layer": layer,                         # 基础层 / 脚本层
                "passed": False,
                "reason": reason,
                "suggestion": suggestion,
                "severity": severity,
                "error_region": self._compute_region(boxes, box_key),
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
    def _compute_region(self, boxes: dict, box_key: str):
        """返回真实红框坐标；**拿不到就返回 None（不画框）**。

        boxes 形如 {"stem": {"x":..,"y":..,"w":..,"h":..}}，由 web_server 从
        uiautomator 的 node bounds 写入（见 _record_module_evidence）。
        """
        b = (boxes or {}).get(box_key)
        if not b:
            return None
        try:
            x, y, w, h = int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"])
        except (KeyError, TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return {"x": x, "y": y, "w": w, "h": h}

    # ---------------------------------------------------------------
    # C2：画红框标注
    # ---------------------------------------------------------------
    def draw_mark(self, screenshot_name: str, checks: list, out_path: str) -> str:
        """C2 红框标注：在**有真实坐标**的维度上画红框 + 文字，保存后返回路径。

        ★ 没有任何维度带真实坐标时，不再画"假框"（旧版会框到状态栏），
          改为在顶部画一条结论横幅，保证图片本身不会误导人。
        """
        img_path = os.path.join(self.screenshots_dir, screenshot_name)
        if not os.path.exists(img_path):
            raise FileNotFoundError(
                f"找不到截图：{img_path}（请确认 screenshots/ 下有 {screenshot_name}）"
            )

        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = _load_font(22)
        small = _load_font(18)

        drawn = 0
        for i, chk in enumerate(checks):
            r = chk.get("error_region")
            if not r:
                continue
            x, y, w, h = r["x"], r["y"], r["w"], r["h"]
            # 越界钳制（不同机型分辨率不一致，避免框跑到画布外）
            x = max(0, min(x, img.width - 2))
            y = max(0, min(y, img.height - 2))
            w = max(4, min(w, img.width - x))
            h = max(4, min(h, img.height - y))
            for off in range(5):                      # 5px 线宽
                draw.rectangle([x - off, y - off, x + w, y + h], outline=(220, 38, 38))
            label = f"[{chk['dimension']}] {str(chk.get('reason') or '')[:40]}"
            ty = y - 30 if y >= 30 else y + h + 6
            draw.rectangle([x, ty, x + min(len(label) * 15 + 12, img.width - x), ty + 26],
                           fill=(255, 255, 255))
            draw.text((x + 6, ty + 3), label, fill=(190, 20, 20), font=font)
            drawn += 1

        if not drawn:
            # 没有任何可用坐标 → 顶部结论横幅（明确告知"未定位到具体区域"）
            lines = [f"[{c['dimension']}] {str(c.get('reason') or '')[:34]}" for c in checks][:3]
            band_h = 30 + 26 * max(1, len(lines))
            draw.rectangle([0, 0, img.width, band_h], fill=(255, 244, 244))
            draw.rectangle([0, band_h - 4, img.width, band_h], fill=(220, 38, 38))
            draw.text((12, 8), "本图未定位到具体出错区域（未采集到控件坐标）", fill=(150, 20, 20), font=font)
            for i, ln in enumerate(lines):
                draw.text((12, 34 + i * 26), ln, fill=(120, 30, 30), font=small)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path)
        return out_path

    # ---------------------------------------------------------------
    # C2b：出错区域特写（错题卡展示用）
    # ---------------------------------------------------------------
    def crop_evidence(self, screenshot_name: str, checks: list, out_path: str,
                      pad_x: int = 40, pad_top: int = 110, pad_bottom: int = 60) -> str:
        """把出错区域裁成特写图：检查人员一眼就能看到"错的是哪一行"。

        无任何真实坐标 → 返回 ""（调用方回退到整图，不硬裁）。
        """
        boxes = [c["error_region"] for c in checks if c.get("error_region")]
        if not boxes:
            return ""
        img_path = os.path.join(self.screenshots_dir, screenshot_name)
        if not os.path.exists(img_path):
            return ""
        img = Image.open(img_path).convert("RGB")
        x1 = min(b["x"] for b in boxes)
        y1 = min(b["y"] for b in boxes)
        x2 = max(b["x"] + b["w"] for b in boxes)
        y2 = max(b["y"] + b["h"] for b in boxes)
        left = max(0, x1 - pad_x)
        top = max(0, y1 - pad_top)
        right = min(img.width, x2 + pad_x)
        bottom = min(img.height, y2 + pad_bottom)
        if right - left < 60 or bottom - top < 60:
            return ""
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.crop((left, top, right, bottom)).save(out_path)
        return out_path


# ---------------------------------------------------------------
# 工具
# ---------------------------------------------------------------
_FALLBACK_SUGGEST = {
    "题干": "把 App 上的题干改成与脚本一致（或反过来更新脚本），保持两边逐字一致",
    "内容": "核对 App 显示的选项/内容与脚本是否一致，把不一致的一方改正",
    "图片": "把 App 配图换成与脚本、题干都匹配的那张图",
    "答案": "统一参考答案与关键词的用词，确保学生按关键词作答不会被判错",
    "音频": "核对音频内容与脚本录音原文是否一致，不一致请重录或改脚本",
    "答错检查": "核对答错后的解析/反馈内容是否正确、是否与本题相关",
}


def _fallback_suggestion(dim_name: str, reason: str) -> str:
    return _FALLBACK_SUGGEST.get(dim_name, "请对照脚本核对该项内容并修正")


def _load_font(size: int):
    """优先中文字体（微软雅黑），否则退化为默认字体。"""
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()
