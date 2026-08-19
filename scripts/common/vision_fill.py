"""vision_fill.py — 图片题识别补全（视觉模型）

用途：脚本生成时，图片题的选项是图片（App 截图），XML 无文字可提取，
     脚本里只有 "A. / B." 占位 → 审查时无法核对答案对应图片是否合理。

方案：遍历答题时对图片题截图（screenshots/script_imgs/），
     生成脚本时用视觉模型识别截图 → 输出选项图片内容描述 + 确认答案。

依赖：
  - LLMClient.ask(prompt, image_path=...)（reviewer_common，已支持视觉模型）
  - 配置：llm_config.json 的 vision_model（如 qwen3.7-plus）

用法：
  from common.vision_fill import recognize_image_question
  result = recognize_image_question(img_path, question_hint="听音选择图片")
  # result = {"options": ["A. 图片：苹果", "B. 图片：香蕉", ...],
  #           "answer": "A", "description": "图片内容描述...", "ok": True}
"""
import os
import sys
import json

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_llm():
    """懒加载 LLMClient（带缓存）"""
    if not hasattr(_get_llm, "_client"):
        sys.path.insert(0, _PROJECT_ROOT)
        from src.reviewer_common import LLMClient
        _get_llm._client = LLMClient.from_config()
    return _get_llm._client


def recognize_image_question(img_path: str, question_hint: str = "",
                             known_options: list = None,
                             answer_hint: str = "") -> dict:
    """用视觉模型识别一道图片题的截图，补全选项内容 + 确认答案。

    Args:
        img_path: 截图路径（图片题的答题页截图，含题目图片+选项图片）
        question_hint: 题型提示（如 "听音选择图片" / "看图选词"）
        known_options: 已知选项文字列表（如 ["A. ", "B. ", "C. "]，可空）
        answer_hint: 答案提示（遍历时用户点击的选项字母，可空）

    Returns:
        {"options": [完整选项列表], "answer": "A/B/C", "description": "图片内容",
         "ok": bool, "error": str}
    """
    if not img_path or not os.path.exists(img_path):
        return {"ok": False, "error": f"截图不存在: {img_path}"}
    try:
        llm = _get_llm()
    except Exception as e:
        return {"ok": False, "error": f"LLM 初始化失败: {e}"}

    opts_hint = ""
    if known_options:
        opts_hint = "\n".join(f"- {o}" for o in known_options)
    else:
        opts_hint = "（选项为图片，无法从界面文字获取，请识别截图中的选项区域）"
    ans_hint = f"\n遍历时点击的答案是: {answer_hint}（用于辅助确认）" if answer_hint else ""

    prompt = f"""请识别这张小学英语听力/看图题的手机截图，并完成以下任务：

【题型】{question_hint or "图片选择题"}

【任务】
1. 识别题目要求（题干，如"听录音，选择与录音内容相符的图片"）
2. 识别页面中的题目图片内容（如：一只猫 / 一个苹果）
3. 识别选项区域：图片题通常有 A/B/C 三个选项（每个选项是一张图），
   请描述每个选项图片的内容
4. 若提供了"遍历时点击的答案"，请结合该信息确认正确答案

【已知选项】
{opts_hint}
{ans_hint}

【输出格式】(严格JSON)
{{
  "stem": "题目要求文字（若可见）",
  "description": "题目图片内容描述（如：画面是一只小猫）",
  "options": ["A. 图片：苹果", "B. 图片：香蕉", "C. 图片：葡萄"],
  "answer": "A 或 B 或 C（正确答案）"
}}

只输出JSON，不要其他内容。若某选项图片无法识别，用"A. （图片无法识别）"标注。"""
    try:
        resp = llm.ask(prompt, image_path=img_path)
    except Exception as e:
        return {"ok": False, "error": f"视觉识别调用失败: {e}"}

    # 解析 JSON
    try:
        data = json.loads(resp)
    except Exception:
        import re
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        if not m:
            return {"ok": False, "error": f"视觉识别返回无法解析: {resp[:150]}"}
        try:
            data = json.loads(m.group())
        except Exception:
            return {"ok": False, "error": f"视觉识别返回无法解析: {resp[:150]}"}

    options = data.get("options") or []
    answer = str(data.get("answer", "") or "").strip().upper()
    return {
        "options": options,
        "answer": answer,
        "stem": data.get("stem", ""),
        "description": data.get("description", ""),
        "ok": True,
    }


def batch_recognize(img_paths: list, question_hint: str = "",
                    known_options: list = None) -> list:
    """批量识别（供 finish_unit 一次处理多题）"""
    results = []
    for p in img_paths:
        results.append(recognize_image_question(p, question_hint, known_options))
    return results
