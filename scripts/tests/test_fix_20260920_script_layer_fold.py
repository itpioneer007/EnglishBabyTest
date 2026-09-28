# -*- coding: utf-8 -*-
"""
2026-09-20 修复回归：脚本层结论折算进六维 + 统一综合判定口径。

修的两个真问题（用户实测反馈）：
  ① "脚本问题日志里明明打出来了，结果 / 报告里一条都看不到。"
     → `_run_llm_script_review` 合并处只写 `_basic["script"]`，六维布尔 /
       `overall_passed` 没动；报告按 `overall_passed is False` 取错题 → 0 条。
  ② "口语训练 20 题，通过 0 / 未审 20。"
     → 旧综合判定要求"可查维度 ≥3 才判通过"，而口语训练每题天生只有
       题干+作答两维可查 → 通过结论全部被压成"未审"。

同时守住一条底线：**脚本层判过 ≠ App 界面通过**，不能让脚本层的 True 顶替
基础层缺失的维度，否则会造出"假通过"（实测大4 听音题有 5 道未核验）。

用法： python scripts/tests/test_fix_20260920_script_layer_fold.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import web_server as W  # noqa: E402

_OK, _BAD = [], []


def chk(name, cond, extra=""):
    (_OK if cond else _BAD).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  → {extra}" if extra and not cond else ""))


def _rec(**dims):
    """构造一条基础层记录（六维 + 空 reasons/conclusions）。"""
    r = {
        "ai_stem": None, "ai_content": None, "ai_image": None,
        "ai_answer": None, "ai_audio": None, "ai_post_error": None,
        "stem_reason": "", "content_reason": "", "image_reason": "",
        "answer_reason": "", "audio_reason": "", "post_error_reason": "",
        "stem_suggestion": "", "content_suggestion": "", "image_suggestion": "",
        "answer_suggestion": "", "audio_suggestion": "", "post_error_suggestion": "",
        "overall_passed": None,
        "conclusions": {k: {"status": "na", "detail": ""} for k in
                        ("stem", "content", "image", "answerable",
                         "answer_knowledge", "audio", "flow", "report")},
    }
    for k, v in dims.items():
        r[f"ai_{k}"] = v
    return r


print("=== A. _judge_overall 统一口径 ===")
chk("全未检 → None(未判定)", W._judge_overall(
    {"stem": None, "answer": None}) is None)
chk("只有 1 维可查且通过 → None（信息太薄，不冒充通过）",
    W._judge_overall({"stem": True, "answer": None}) is None)
chk("2 维明确通过 → True（口语训练主路径，旧口径下永远是 None）",
    W._judge_overall({"stem": True, "answer": True, "content": None}) is True)
chk("3 维已核验且无异常 → True", W._judge_overall(
    {"stem": True, "answer": True, "audio": True}) is True)
chk("任一维不通过 → False（优先级最高）", W._judge_overall(
    {"stem": True, "answer": True, "content": False}) is False)
chk("空 dict → None", W._judge_overall({}) is None)

print("\n=== B. 脚本层 False 必须折算进六维与综合判定 ===")
b = _rec(answer=True)
b["answer_reason"] = "作答元素: 麦克风/录音控件可见且可点击"
scr = {
    "stem": None, "content": None, "image": None,
    "answer": False, "audio": None, "post_error": None,
    "answer_reason": "[不通过 | 置信度:92] | 关键词「bring their raincoats」与参考答案不一致：答案里是「take their raincoats」",
    "suggestions": {"答案": "统一参考答案与关键词的用词"},
    "overall_passed": False,
}
W._fold_script_layer(b, scr)
chk("ai_answer 被置 False", b["ai_answer"] is False)
chk("overall_passed 变成 False（旧代码这里仍是 None）", b["overall_passed"] is False)
chk("原因带「脚本层不通过」标签", b["answer_reason"].startswith("❌ 脚本层不通过："))
chk("原因保留了界面层原话（分层可见）", "界面层：" in b["answer_reason"])
chk("LLM 的『建议修改』被带出", "统一参考答案与关键词" in b["answer_suggestion"])
chk("LLM 前缀噪音 [不通过 | 置信度:92] | 被清掉",
    "[不通过" not in b["answer_reason"] and "置信度" not in b["answer_reason"])
chk("conclusions.answerable → fail", b["conclusions"]["answerable"]["status"] == "fail")
chk("conclusions.flow → fail", b["conclusions"]["flow"]["status"] == "fail")
chk("脚本层逐维结论留档 _script_dims", b["_script_dims"].get("answer") is False)

print("\n=== C. 脚本层 True 不得顶替基础层缺失的维度（防假通过）===")
b2 = _rec(answer=True)          # 基础层只核了作答，题目内容没比对（听音题）
scr2 = {"stem": True, "content": True, "answer": None, "image": None,
        "audio": None, "post_error": None, "overall_passed": True}
W._fold_script_layer(b2, scr2)
chk("ai_stem 保持 None（不被脚本层 True 顶成通过）", b2["ai_stem"] is None)
chk("综合判定仍为 None（1 维不够，宁可未判定也不假通过）",
    b2["overall_passed"] is None)
chk("脚本层结论仍可查（留档）", b2["_script_dims"].get("stem") is True)

print("\n=== D. 脚本层判过 + 基础层两维通过 → 通过（修复『未审 20 题』）===")
b3 = _rec(stem=True, answer=True)
W._fold_script_layer(b3, {"stem": True, "content": True, "answer": True,
                          "image": None, "audio": None, "post_error": None})
chk("overall_passed → True", b3["overall_passed"] is True)
chk("conclusions.stem → pass", b3["conclusions"]["stem"]["status"] == "pass")
chk("conclusions.flow → pass", b3["conclusions"]["flow"]["status"] == "pass")

print("\n=== E. 幂等：重复折算不得把原因拼两遍 ===")
_before = b["answer_reason"]
W._fold_script_layer(b, scr)
W._fold_script_layer(b, scr)
chk("原因文案不变", b["answer_reason"] == _before)
chk("overall 不变", b["overall_passed"] is False)

print("\n=== F. 缺 script / 空 script 时安全跳过 ===")
b4 = _rec(stem=True, answer=True)
W._fold_script_layer(b4, None)
W._fold_script_layer(b4, {})
chk("None / {} 不改变判定", b4["overall_passed"] is None and b4["ai_stem"] is True)

print("\n=== G. 报告端：script_issues 随 metadata 下发 ===")
try:
    import inspect
    _src = inspect.getsource(W._live_regen_error_report)
    chk("_live_regen_error_report 传了 script_issues",
        '"script_issues"' in _src)
except Exception as e:  # pragma: no cover
    chk("_live_regen_error_report 传了 script_issues", False, str(e))
from src.report_exporter import ReportExporter  # noqa: E402
chk("报告端有脚本自检渲染入口",
    hasattr(ReportExporter, "_render_script_section")
    and hasattr(ReportExporter, "_split_script_issues"))

print("\n=== H. 报告端：脚本问题按 (单元,大题,小题) 归位 ===")
_qs = [{"progress": "大4-Q3", "_unit": "4"}, {"progress": "大4-Q2", "_unit": "4"}]
_e = ReportExporter(save_dir=str(ROOT / "outputs" / "_tmptest"))
_per, _mod = _e._split_script_issues(
    {"口语训练": [
        {"type": "答案与关键词不一致", "location": "U4 第4大题 第3小题", "severity": "高"},
        {"type": "字段名不统一", "location": "全文", "severity": "中"},
        {"type": "知识点为占位符", "location": "U7 第4大题", "severity": "中"},
    ]}, {"unit": "4"}, _qs)
chk("带小题号且本单元的 → 归位", len(_per.get(id(_qs[0]), [])) == 1)
chk("『全文』→ 留在模块级", any(i["type"] == "字段名不统一" for i in _mod))
chk("其他单元 U7（不在本次实跑）→ 留在模块级",
    any(i["type"] == "知识点为占位符" for i in _mod))
chk("模块级按严重度排序（高在前）",
    [i["severity"] for i in _mod] == ["中", "中"] or _mod[0]["severity"] != "低")
import shutil  # noqa: E402
shutil.rmtree(ROOT / "outputs" / "_tmptest", ignore_errors=True)

print("\n" + "=" * 60)
print(f"结果: {len(_OK)} 通过, {len(_BAD)} 失败")
for b_ in _BAD:
    print("  - " + b_)
print("全部通过 ✅" if not _BAD else "存在失败 ❌")
sys.exit(1 if _BAD else 0)
