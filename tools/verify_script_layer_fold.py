# -*- coding: utf-8 -*-
"""
验证「脚本层结论折算进六维」是否符合预期，并可选把它应用到现有状态文件。

背景（用户反馈的原话）：
  "脚本问题日志里明明打出来了，结果 / 报告里一条都看不到。"
根因：`_run_llm_script_review` 的合并处只做了 `_basic["script"] = _state["script"]`，
      六维布尔、原因文案、`overall_passed` 全都没动 → 脚本层判"不通过"的题
      （实测 U4 第3大题：LLM 指出脚本题干为空、缺例句）在结果区显示"未审"，
      实时错题报告按 `overall_passed is False` 取错题 → 一条错题都没有。

本脚本对状态文件里**已有 script 子字典**的记录跑一遍 `_fold_script_layer`，
对比折算前后的综合判定分布，并按需写回。

用法：
  python tools/verify_script_layer_fold.py            # 只看，不写
  python tools/verify_script_layer_fold.py --apply    # 写回状态文件（先自动备份）
"""
from __future__ import annotations

import collections
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_server as W  # noqa: E402

STATE = ROOT / "data" / "inspection_state.json"
APPLY = "--apply" in sys.argv

state = json.loads(STATE.read_text(encoding="utf-8"))
qs = state.get("questions") or {}
print(f"状态文件 {STATE.name} · {len(qs)} 题 · unit={state.get('unit')!r}\n")


def dist(records):
    c = collections.Counter()
    for v in records.values():
        c[v.get("overall_passed")] += 1
    return dict(c)


print("折算前 overall_passed 分布:", dist(qs))

# 只处理"有脚本层结论"的记录（口语训练这类 merge 进 auto-* 的题）
_targets = [k for k, v in qs.items() if isinstance(v.get("script"), dict) and v["script"]]
print(f"其中带脚本层结论的记录: {len(_targets)} 题")

# 打印前几题的脚本层逐维判定，便于人工核对折算是否合理
print("\n脚本层逐维判定（前 6 题）：")
for k in _targets[:6]:
    scr = qs[k]["script"]
    dims = {d: scr.get(d) for d in W._SCRIPT_DIM_KEYS}
    print(f"  {k:14s} script={dims} script_overall={scr.get('overall_passed')}")

# ── 在副本上折算，先看结果 ─────────────────────────────────
snapshot = {k: json.loads(json.dumps(v)) for k, v in qs.items()}
for k in _targets:
    W._fold_script_layer(snapshot[k], snapshot[k]["script"])

print("\n折算后 overall_passed 分布:", dist(snapshot))
print("\n变化明细：")
_flip = 0
for k in _targets:
    b, a = qs[k].get("overall_passed"), snapshot[k].get("overall_passed")
    if b != a:
        _flip += 1
        _bad = [d for d in W._SCRIPT_DIM_KEYS if snapshot[k].get(f"ai_{d}") is False]
        print(f"  {k:14s} {b!s:5s} → {a!s:5s}   不通过维度={_bad}")
print(f"共 {_flip} 题判定发生变化")

# 幂等性：再折算一次不应再变（否则重跑模块会把原因文案拼两遍）
_before = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
for k in _targets:
    W._fold_script_layer(snapshot[k], snapshot[k]["script"])
_after = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
print("幂等复检:", "OK（二次折算无变化）" if _before == _after else "异常！二次折算又改了内容")

if not APPLY:
    print("\n（仅查看模式；加 --apply 写回状态文件）")
    sys.exit(0)

bak = STATE.with_suffix(".json.bak_before_fold")
shutil.copy2(STATE, bak)
state["questions"] = snapshot
W._inspection_state = state
W._save_inspection_state_merge()
print(f"\n已写回 {STATE.name}（备份：{bak.name}）")
print("新分布:", dist(json.loads(STATE.read_text(encoding='utf-8'))["questions"]))
