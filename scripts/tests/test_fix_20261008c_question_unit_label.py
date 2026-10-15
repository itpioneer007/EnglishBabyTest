# -*- coding: utf-8 -*-
r"""★ 2026-10-08c 回归测试：题卡「所属单元」不再被写成运行范围串。

━━━ 背景（第 4 次跑出来的真实缺陷）━━━
用户勾了「口语训练 · 湘少版(2024审定) · 四年级下册 · U1、U3」，跑完 25 题：
    通过=5  不通过=0  未判定=20   （状态里三数自洽）
但生成的 report_live.html 里「未判定（20 道）」清单的**每一条**都渲染成
    U1,3 · 第1大题 · 第2小题
    U1,3 · 第1大题 · 第3小题
    ...（20 条，且 U1 与 U3 的同名小题两两重复、彼此无法区分）

"1,3" 是**本轮运行范围**，不是单元号。审查员拿到这份报告根本定位不到题
（用户明确要求：报告位置必须可直接定位，不许含糊标签）。

━━━ 根因 ━━━
web_server._record_module_evidence 写题卡时取
    "_unit": _inspection_state.get("unit", "")
而 state["unit"] 是本轮范围（调度器塞进去的 "1,3"）。
同一个函数在 100 行之前**已经**算好了逐题单元：
    _scope_unit = str(logger.get_current_unit() or "")      # 模块上报的"正在作答单元"
但没被用到 _unit 上。
证据（data/inspection_state.json 的 _qid_owner，记录当时落盘的 scope key）：
    auto-Q01-0X → "口语训练||1|1"   ← U1 的大题1
    auto-Q02-0X → "口语训练||1|2"   → U1 的大题2
    auto-Q003~007 → "口语训练||3|1" → U3 的大题1
    auto-Q008~012 → "口语训练||3|2" → U3 的大题2
⇒ 记录当时的单元号**是对的**，只是没写进 `_unit`。

━━━ 修法（两层，纵深防御）━━━
① web_server._resolve_question_unit(scope_unit, state_unit)：
   优先模块上报的当前单元；模块没上报且 state_unit 是**单个纯数字**才回退；
   其余（"1,3" / "5-6" / "全部" / ""）一律返回 "" —— 绝不把范围串当单元号。
② src/report_exporter._render_undet_section：
   meta["unit"] 与记录里的 `_unit` 都必须通过 `^\d+$` 才渲染成 U<x>，
   否则留空退回 progress（"大1-Q2"）。与 _render_position 的 .isdigit() 同口径。

━━━ 本测试锁定 ━━━
  T1 _resolve_question_unit：上报优先 / 纯数字回退 / 范围串一律留空（含反向）
  T2 未判定清单：U1、U3 的同名小题**分别**渲染成 U1… 与 U3…
  T3 【关键反向】清单里绝不出现 "U1,3"
  T4 【反向】记录里残留范围串 "_unit"="1,3" 时也不印成单元号
  T5 【反向】meta["unit"]="1,3" 不参与兜底；meta["unit"]="5" 仍是兜底
  T6 位置仍完整（大题/小题号不因加固而丢失）
  T7 【反向】_render_position 卡片标题不出现 "U1,3"

运行：python scripts/tests/test_fix_20261008c_question_unit_label.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import web_server as ws                          # noqa: E402
from src.report_exporter import ReportExporter   # noqa: E402

PASS = 0
FAIL = 0


def chk(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [XX] {name}   {detail}")


def mkq(qid, unit, big, sub, stem="", note="", dims=None):
    return {
        "qid": qid,
        "progress": f"大{big}-Q{sub}",
        "big": big,
        "idx": sub,
        "_unit": unit,
        "stem": stem,
        "note": note,
        "module": "口语训练",
        "stem_reason": "", "content_reason": "", "image_reason": "",
        "answer_reason": "", "audio_reason": "", "post_error_reason": "",
        "_score": {"dims": dims or [{"name": "作答", "passed": True}]},
    }


print("\n" + "=" * 74)
print("T1 _resolve_question_unit：上报优先 / 纯数字回退 / 范围串留空")
print("=" * 74)
RU = ws._resolve_question_unit
chk("模块上报 U3 优先于范围串 ('3','1,3') → '3'", RU("3", "1,3") == "3", RU("3", "1,3"))
chk("模块上报 U1 优先 ('1','') → '1'", RU("1", "") == "1")
chk("模块上报 int 3 → '3'", RU(3, "1,3") == "3", repr(RU(3, "1,3")))
chk("模块没上报 + state='5'（纯数字）→ '5'", RU("", "5") == "5")
chk("模块没上报 + state=5（int）→ '5'", RU(None, 5) == "5", repr(RU(None, 5)))
chk("【反向】模块没上报 + state='1,3'（范围串）→ ''", RU("", "1,3") == "", repr(RU("", "1,3")))
chk("【反向】'5-6' → ''", RU("", "5-6") == "")
chk("【反向】'全部' → ''", RU("", "全部") == "")
chk("【反向】'' → ''", RU("", "") == "")
chk("【反向】None/None → ''", RU(None, None) == "")
chk("【反向】'1,3' 绝不会被原样返回",
    RU("", "1,3") != "1,3" and RU(None, "1,3") != "1,3")
chk("【反向】' 3 ' 带空白也认（strip）", RU(" 3 ", "1,3") == "3", repr(RU(" 3 ", "1,3")))
chk("【反向】' 1,3 ' 带空白仍留空", RU("", " 1,3 ") == "", repr(RU("", " 1,3 ")))

print("\n" + "=" * 74)
print("T2/T3 未判定清单：U1 与 U3 的同名小题必须可区分，且不出现 'U1,3'")
print("=" * 74)
exp = ReportExporter()
# 真实场景：U1 与 U3 都各有「第1大题·第2小题」
undet = [
    mkq("auto-Q01-02", "1", 1, 2, ""),
    mkq("auto-Q005", "3", 1, 2, ""),
]
html = exp._render_undet_section({"_undet_list": undet, "unit": "1,3"})
chk("出现 U1 · 第1大题 · 第2小题", "U1 · 第1大题 · 第2小题" in html)
chk("出现 U3 · 第1大题 · 第2小题", "U3 · 第1大题 · 第2小题" in html)
chk("【关键反向】绝不出现 'U1,3'", "U1,3" not in html, html[:200])
chk("【关键反向】绝不出现 'U1,3' 中的逗号形态 'U1，3'", "U1，3" not in html)
chk("标题计数正确（2 道）", "未判定（2 道）" in html)
chk("两条位置互不相同（不是同一个标签重复）",
    html.count("U1 · 第1大题 · 第2小题") == 1
    and html.count("U3 · 第1大题 · 第2小题") == 1)

print("\n" + "=" * 74)
print("T4/T5 纵深防御：残留范围串 / meta 兜底")
print("=" * 74)
html = exp._render_undet_section(
    {"_undet_list": [mkq("auto-Q01-02", "1,3", 1, 2)], "unit": "1,3"})
chk("【反向】记录 _unit='1,3' 残留 → 不印成 U1,3", "U1,3" not in html, html[:200])
chk("  且位置仍完整（第1大题 · 第2小题，只是不带 U 前缀）",
    "第1大题 · 第2小题" in html, html[-260:])

html = exp._render_undet_section(
    {"_undet_list": [mkq("auto-Q01-02", "", 1, 2)], "unit": "1,3"})
chk("【反向】_unit 空 + meta='1,3' → 不印成 U1,3", "U1,3" not in html)
chk("  且位置仍完整（第1大题 · 第2小题）", "第1大题 · 第2小题" in html, html[-260:])
chk("  【反向】此时不得凭空补一个 U 前缀", "· U" not in html, html[-260:])

html = exp._render_undet_section(
    {"_undet_list": [mkq("auto-Q01-02", "", 1, 2)], "unit": "5"})
chk("meta='5'（纯数字）仍是合法兜底 → U5", "U5 · 第1大题 · 第2小题" in html, html[:300])

print("\n" + "=" * 74)
print("T6 位置信息完整（大题/小题号未因加固而丢失）")
print("=" * 74)
html = exp._render_undet_section(
    {"_undet_list": [mkq("auto-Q03-04", "3", 3, 4)], "unit": "1,3"})
chk("U3 · 第3大题 · 第4小题 完整", "U3 · 第3大题 · 第4小题" in html)
chk("仍带维度说明『仅 1 维可查（作答）』", "仅 1 维可查（作答）" in html)

print("\n" + "=" * 74)
print("T7 【反向】题卡标题（_loc_label）不出现 'U1,3'")
print("=" * 74)
q = mkq("auto-Q01-02", "1,3", 1, 2)
_pos = exp._loc_label(q, {"unit": "1,3"})
chk(f"_loc_label 结果不含 U1,3（实际: {_pos!r}）", "U1,3" not in _pos)
chk("  位置仍完整（第1大题·第2小题）", "第1大题·第2小题" in _pos, _pos)
q2 = mkq("auto-Q01-02", "3", 1, 2)
chk("_unit='3' → 标题含 U3", "U3" in exp._loc_label(q2, {"unit": "1,3"}),
    exp._loc_label(q2, {"unit": "1,3"}))

print("\n" + "=" * 74)
print("T8 真机状态文件交叉校验（存在时）")
print("=" * 74)
_state = os.path.join(ROOT, "data", "inspection_state.json")
if os.path.exists(_state):
    import json
    with open(_state, encoding="utf-8") as fh:
        st = json.load(fh)
    owner = st.get("_qid_owner") or {}
    units_in_owner = set()
    for k in owner.values():
        parts = str(k).split("|")
        if len(parts) >= 3 and parts[2]:
            units_in_owner.add(parts[2])
    print(f"  _qid_owner 里出现的单元: {sorted(units_in_owner)}")
    chk("_qid_owner 记录了逐题单元（≥1 个）", len(units_in_owner) >= 1)
    if "1,3" in units_in_owner:
        chk("【反向】_qid_owner 里绝不能出现范围串当单元", False, f"{units_in_owner}")
    qs = st.get("questions") or {}
    bad = [k for k, v in qs.items() if not str(v.get("_unit") or "").isdigit() and v.get("_unit")]
    print(f"  当前题卡里 _unit 为非纯数字的条数: {len(bad)} {bad[:5]}")
    chk("（说明）若 >0 表示本轮状态是修复前写入的，需回填或用修复后重跑",
        True)
else:
    print("  [--] 无 data/inspection_state.json，跳过")

print("\n" + "=" * 74)
print(f"结果: {PASS} 通过 / {FAIL} 失败")
print("=" * 74)
sys.exit(1 if FAIL else 0)
