"""★ 2026-09-23 修复回归测试：同题多证据合并后的 overall 必须与 `_judge_overall` 同口径。

现场（教科版五上 U7 第4大题「听录音作答」）：
    该大题每题只有 2 维可查（选项 + 作答；题干由音频呈现、App 不显示文字）。
    单条证据时 `_record_module_evidence` 第 3830 行 `_judge_overall(dims)` 已判"通过"，
    但只要该题被上报过两次（`_merge_evidence_record` 介入），就退回"未判定"。
    实测结果区显示「通过 14 / 不通过 1 / 未审 5」——那 5 题本该是通过。

根因：判定口径分叉。`_judge_overall` 是 2026-09-20 抽出的唯一口径
    （任一 False → 不通过；≥2 维明确通过 或 ≥3 维已核验 → 通过；只剩 1 维 → 未判定），
但 `_merge_evidence_record` 里还留着一份**旧口径** `len(_ck) >= 3 → True，否则 None`。
"只剩 2 维"的题在合并路径被压成 None。

本测试锁定：
  1) 2 个 True → 合并后仍判"通过"（不再被旧口径压成 None）
  2) 1 个 True → 未判定（信息太薄，不冒充通过）
  3) 任一 False → 不通过（不通过优先级最高）
  4) 穷举 6 维三态组合：合并结果与 `_judge_overall` 完全一致（口径不可能再分叉）
  5) 回归不变量：不通过数 / 通过数 / 未判定数 三态互斥且合起来 = 总题数

运行：python scripts/tests/test_fix_20260923e_merge_judge_consistency.py
"""
import itertools
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import web_server as W  # noqa: E402

PASS = 0
FAIL = []


def chk(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {extra}")


DIMS = ("ai_stem", "ai_content", "ai_image", "ai_answer", "ai_audio", "ai_post_error")


def mk_rec(dims):
    """造一条最小可合并记录：dims 里给 True/False/None。"""
    r = {k: dims.get(k) for k in DIMS}
    r.update({
        "stem": "", "options": "", "screenshot": "", "question_type": "",
        "score_info": "", "human_label": None, "human_note": "", "note": "",
        "script": None, "layer": "basic_only",
        "conclusions": {d: {"status": "na", "detail": ""} for d in
                        ("stem", "content", "image", "answerable", "audio", "flow")},
    })
    for k in ("stem", "content", "image", "answer", "audio", "post_error"):
        r[k + "_reason"] = ""
        r[k + "_suggestion"] = ""
    return r


def merged_overall(prev_dims, new_dims):
    prev, new = mk_rec(prev_dims), mk_rec(new_dims)
    return W._merge_evidence_record(prev, new)["overall_passed"]


print("== 1) 现场复现：2 维可查（选项+作答）→ 必须「通过」 ==")
# U7 第4大题第1小题真实形态：ao_stem=None, content=True, answer=True
q4 = {"ai_stem": None, "ai_content": True, "ai_answer": True}
chk("单条时 _judge_overall → True", W._judge_overall(
    {"stem": None, "content": True, "image": None, "answer": True,
     "audio": None, "post_error": None}) is True)
chk("合并后仍为 True（旧口径会给出 None）",
    merged_overall(q4, {"ai_stem": None, "ai_content": True, "ai_answer": True}) is True)
chk("合并后不是 None（旧口径症状）",
    merged_overall(q4, {"ai_content": True}) is not None)

print("== 2) 只有 1 维可查 → 未判定（不冒充通过） ==")
chk("1 个 True → None", merged_overall({"ai_answer": True}, {"ai_answer": True}) is None)

print("== 3) 任一 False → 不通过（优先级最高） ==")
chk("1 True + 1 False → False",
    merged_overall({"ai_stem": None, "ai_answer": False}, {"ai_content": True}) is False)
chk("prev False + new True → False（不通过优先）",
    merged_overall({"ai_answer": False}, {"ai_answer": True}) is False)

print("== 4) 穷举 6 维三态：合并结果 ≡ _judge_overall（口径分叉不可能再出现） ==")
_vals = (True, False, None)
_bad = []
_n = 0
for combo in itertools.product(_vals, repeat=6):
    _n += 1
    rec = mk_rec(dict(zip(DIMS, combo)))
    # 合并一条"完全空"的证据：合并不变量 = 维度取"不通过>通过>未检"，逐维等于原值
    got = W._merge_evidence_record(mk_rec({}), rec)["overall_passed"]
    want = W._judge_overall({k: rec[k] for k in DIMS})
    if got != want:
        _bad.append((combo, got, want))
chk(f"穷举 {_n} 种组合全部一致", not _bad, f"不一致样例(前3): {_bad[:3]}")

print("== 5) 三态互斥且自洽（通过 + 不通过 + 未判定 = 总数） ==")
_cnt = {True: 0, False: 0, None: 0}
for combo in itertools.product(_vals, repeat=6):
    rec = mk_rec(dict(zip(DIMS, combo)))
    _cnt[W._merge_evidence_record(mk_rec({}), rec)["overall_passed"]] += 1
chk("三态计数相加 = 组合总数",
    sum(_cnt.values()) == 3 ** 6, f"{_cnt}")
chk("存在「通过」桶（新口径生效，不是全 None）", _cnt[True] > 0, f"{_cnt}")
chk("存在「不通过」桶", _cnt[False] > 0, f"{_cnt}")
chk("存在「未判定」桶（信息太薄的仍保守留白）", _cnt[None] > 0, f"{_cnt}")

print()
print(f"PASS {PASS} / FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
