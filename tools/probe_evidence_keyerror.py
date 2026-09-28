# -*- coding: utf-8 -*-
"""口语训练「小题内容 / 大题说明」判定的定点探针（不连设备）。

复现并回归验证三件事：
  1. `_record_module_evidence` 对"只剩小题题干"的后续小题不再抛 KeyError（曾 `_sugg.pop("stem")`）
  2. 带「大题说明已省略」标记的后续小题 → **不再刷** "⚠ App 未取到大题说明文字…需连手机确认"
     的假告警，且小题内容一致时题干维度能判「通过」（以前永远是"未检"）
  3. 小题内容比对是**逐字一致**：`nose nate` vs 脚本 `nose note` 必须判不通过
     （旧版 0.85 相似度会把它判成"一致"→ 脚本内容写错查不出来）
  4. 没有标记时（App 真没渲染大题说明）→ 保留人工确认提示（不能被新逻辑顺手抹掉）
"""
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("ANDROID_SERIAL", "127.0.0.1:16384")

import web_server as W  # noqa: E402

W._save_inspection_state = lambda: None          # 别影响正在跑的检测
W._save_inspection_state_merge = lambda: None
# ⚠ 探针用的是**合成数据**，绝不能让它刷新实时错题报告
#   （否则 outputs/reports/latest/report_live.html 会被 4 条假记录覆盖，
#    真实运行的报告就丢了 —— 实测踩过一次）
W._live_regen_error_report = lambda: ""

_DOCX = "260727口语训练新教科五上U4-7（已二校）.docx"
W._GLOBAL_DOCX_MAP = {"口语训练": _DOCX}

W._inspection_state.clear()
W._inspection_state.update({
    "questions": {}, "version": "教科版（2024审定）", "grade": "五年级上册",
    "unit": 4, "stage": "全部", "_qid_owner": {}, "_qid_map": {}, "_seen_qids": {},
    "_modules_total": {}, "_script_issues": {},
})

from common.logger import set_current_module          # noqa: E402
set_current_module("口语训练", "")

# 从真实脚本取"大题说明"与"小题题面"，避免探针自己编数据
from src.review_agent import ReviewAgent, ReviewConfig              # noqa: E402
_agent = ReviewAgent(ReviewConfig(docx_path=str(ROOT / "uploads" / _DOCX),
                                  unit=0, screenshot_dir="", verbose=False))
_SQ = _agent.script_questions


def _q(unit, big, sub):
    for s in _SQ:
        if s.unit == unit and s.big == big and s.stage_idx == sub:
            return s
    return None


def caption_of(big):
    q = _q(4, big, 1)
    return ((getattr(q, "caption", "") or "").strip() if q else "")


def sub_of(big, sub):
    q = _q(4, big, sub)
    return ((getattr(q, "stem", "") or "").strip() if q else "")


MARK = {"field": "大题说明已省略", "type": "info", "actual": "1",
        "diff": "同大题第2小题起不再重复上报大题说明（避免重复证据卡）"}

CAP1 = caption_of(1)
S2 = sub_of(1, 2)
S3 = sub_of(1, 3)
S4 = sub_of(1, 4)
print(f"脚本 U4 第1大题说明: {CAP1[:40]}…")
print(f"脚本小题内容: 2={S2!r}  3={S3!r}  4={S4!r}")

CASES = [
    # (说明, big, sub, evidence, 期望 ai_stem, 是否必须出现"未取到大题说明")
    ("第1小题·有大题说明 → 比 大题说明↔caption", 1, 1, [
        {"field": "题型", "diff": "[口语跟读]", "type": "info"},
        {"field": "小题题干", "actual": S2 and sub_of(1, 1), "src": "dom", "type": "info"},
        {"field": "题干", "actual": CAP1, "diff": "题干与脚本一致", "type": "text_ok"},
        {"field": "音频", "actual": "小喇叭可点", "diff": "无需检查小喇叭", "type": "text_ok"},
        {"field": "作答", "actual": "麦克风可点", "diff": "作答元素存在", "type": "text_ok"},
    ], True, False),

    ("第2小题·有标记 + 小题内容一致", 1, 2, [
        {"field": "小题题干", "actual": S2, "src": "dom", "type": "info"}, MARK,
    ], True, False),

    ("第3小题·有标记 + 小题内容**改写一个字母**（必须判不通过）", 1, 3, [
        {"field": "小题题干", "actual": S3.replace("note", "nate"), "src": "dom", "type": "info"},
        MARK,
    ], False, False),

    ("第4小题·**无**标记（App 真没渲染大题说明）→ 应保留人工确认", 1, 4, [
        {"field": "小题题干", "actual": S4, "src": "dom", "type": "info"},
    ], None, True),
]

FAIL = []
for name, big, sub, ev, want_dim, want_warn in CASES:
    print("=" * 70)
    print(f"### {name}  (big={big}, sub={sub})")
    try:
        W._record_module_evidence(sub, f"第{big}大题·{sub}小题（x）完整性检查", ev, big=big)
        qs = W._inspection_state["questions"]
        key = f"auto-Q{big:02d}-{sub:02d}"
        rec = qs.get(key) or {}
        rs = rec.get("stem_reason") or ""
        got = rec.get("ai_stem")
        has_warn = "App 未取到大题说明文字" in rs
        print(f"  入库={key in qs}  ai_stem={got} (期望 {want_dim})  含假告警={has_warn} (期望 {want_warn})")
        print(f"  reason={rs[:200]}")
        if key not in qs:
            FAIL.append((name, "未入库"))
        if got != want_dim:
            FAIL.append((name, f"ai_stem={got} 期望 {want_dim}"))
        if has_warn != want_warn:
            FAIL.append((name, f"人工确认提示={has_warn} 期望 {want_warn}"))
    except Exception:
        print("  ❌ 抛异常：")
        traceback.print_exc()
        FAIL.append((name, "抛异常"))

print("=" * 70)
if FAIL:
    print("RESULT ❌")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("RESULT ✅ 判定与告警行为全部符合预期")
