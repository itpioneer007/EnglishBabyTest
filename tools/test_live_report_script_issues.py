# -*- coding: utf-8 -*-
"""
实时错题报告 · 三档判定 + 脚本自检归位 端到端验证（零 LLM / 不碰真机）。

背景（用户反馈）：
  1. 跑完口语训练 U4 后，报告把 20 题**全**列成"不通过"（或全列成"未审"），
     理由是"未在六维中标记，详见原始理由" —— 旧口径 `not overall_passed` 把
     None（未判定）当成了 False。
  2. `check_script_completeness` 命中的 3 处脚本问题（含高严重度的
     "参考答案 take ↔ 关键词 bring"）报告里**一条都看不到** —— 因为它只写进
     `_inspection_state["_script_issues"]` 和前端日志。

本测试用磁盘上真实的 `data/inspection_state.json` 走一遍报告生成，
写入**临时目录**（绝不覆盖 outputs/reports 下已产出的报告）。

用法： python tools/test_live_report_script_issues.py
"""
from __future__ import annotations

import json
import re
import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.report_exporter import ReportExporter  # noqa: E402

_OK, _BAD = [], []


def chk(name: str, cond: bool, extra: str = ""):
    (_OK if cond else _BAD).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  → {extra}" if extra and not cond else ""))


STATE = ROOT / "data" / "inspection_state.json"
if not STATE.exists():
    print(f"!! 找不到 {STATE}（先在真机上跑一次口语训练再回来）")
    sys.exit(2)

state = json.loads(STATE.read_text(encoding="utf-8"))
qs_all = list((state.get("questions") or {}).values())
print(f"状态文件：{STATE.name} · {len(qs_all)} 题 · unit={state.get('unit')!r}")

# 期望的判定分布（脚本层折算后）
_exp_fail = sum(1 for q in qs_all if q.get("overall_passed") is False)
_exp_pass = sum(1 for q in qs_all if q.get("overall_passed") is True)
_exp_und = sum(1 for q in qs_all if q.get("overall_passed") is None)
print(f"状态里的判定分布：通过 {_exp_pass} / 不通过 {_exp_fail} / 未判定 {_exp_und}")

meta = {
    "version": state.get("version", "未知版本"),
    "unit": state.get("unit", "全部"),
    "stage": state.get("stage", "全部"),
    "date": "2026-09-20 00:00",
    "total": len(qs_all),
    "script_issues": state.get("_script_issues") or {},
}

tmp = Path(tempfile.mkdtemp(prefix="live_report_test_"))
try:
    exp = ReportExporter(save_dir=str(tmp))
    out = Path(exp.export_html_live(qs_all, meta))
    doc = out.read_text(encoding="utf-8")
    print(f"\n生成：{out.name}（{len(doc)} 字符）\n")

    def _num(cls):
        m = re.search(rf'<div class="stat {cls}"><div class="num">(\d+)</div>', doc)
        return int(m.group(1)) if m else -1

    # ── 1. 三档计数 ───────────────────────────────────────────
    print("【1】判定口径：未判定不得混进不通过，通过也不能被吞")
    n_fail, n_und = _num("s-fail"), _num("s-undet")
    n_scc = _num("s-sc")
    n_total = _num("s-total")
    n_sc = sum(len(v) for v in (state.get("_script_issues") or {}).values()
               if isinstance(v, list))
    print(f"      报告：不通过={n_fail} 未判定={n_und} 脚本自检={n_scc} 已审查={n_total}")
    print(f"      状态：不通过={_exp_fail} 未判定={_exp_und} 脚本问题={n_sc}")
    chk("报告『不通过』== 状态里 overall_passed is False 的题数",
        n_fail == _exp_fail, f"{n_fail} vs {_exp_fail}")
    chk("报告『未判定』== 状态里 overall_passed is None 的题数",
        n_und == _exp_und, f"{n_und} vs {_exp_und}")
    chk("脚本自检计数 == _script_issues 总条数", n_scc == n_sc, f"{n_scc} vs {n_sc}")
    chk("已审查 == 全部题数", n_total == len(qs_all), f"{n_total} vs {len(qs_all)}")
    chk("不再出现“未在六维中标记”占位", "未在六维中标记" not in doc)
    chk("未判定 + 不通过 + 通过 == 全部（没有题被静默吞掉）",
        n_fail + n_und + _exp_pass == len(qs_all))
    # 通过率 = 通过 / 全部
    m_rate = re.search(r'<div class="stat s-pass"><div class="num">(\d+)%</div>', doc)
    rate = int(m_rate.group(1)) if m_rate else -1
    chk("通过率按『通过/全部』计（未判定不算通过）",
        rate == round(_exp_pass / len(qs_all) * 100), f"{rate}% vs 期望 {round(_exp_pass/len(qs_all)*100)}%")

    # ── 2. 不通过题必须在报告里，且带上原因/怎么改 ──────────────
    print("\n【2】不通过题卡片")
    cards = re.findall(r'<details class="card([^"]*)">(.*?)</details>', doc, re.S)
    print(f"      报告共 {len(cards)} 张卡片")
    chk("卡片数 == 不通过 + 仅脚本自检命中的题数",
        len(cards) >= n_fail, f"{len(cards)} vs {n_fail}")
    chk("每张卡片都有『怎么改』", all("怎么改" in b for _, b in cards))
    chk("每张卡片都有『脚本问题』或六维结论块",
        all(("脚本问题" in b) or ('class="chk"' in b) for _, b in cards))

    # ── 3. 高严重度“答案↔关键词不一致”必须现身（2026-09-20 晚语义更新）──
    # ★ 2026-09-20 晚用户规则："只论我在跑的单元"。
    #   本次实跑 U6，take↔bring 是 U4 的问题 → 应当**彻底不出现**在本次报告里
    #   （既不挂到 U6 题卡，也不留在模块级区块）。
    print("\n【3】take ↔ bring：本次跑 U6 → 不得出现（归位行为另用合成数据验证）")
    chk("U4 的问题不出现在 U6 运行报告里", "take their raincoats" not in doc)
    chk("不挂到 U6 题卡（位置不匹配不硬归位）",
        not any("bring their raincoats" in b for _, b in cards))

    #   3b 归位行为用合成数据单独验证：运行单元=4 时应挂到题卡
    _q4 = {"module": "口语训练", "stage": "", "progress": "大4-Q3",
           "big": 4, "module_qno": 3, "_unit": "4",
           "overall_passed": False, "question_type": "口语题",
           "stem_reason": "❌ 参考答案与关键词不一致"}
    _meta4 = {"version": "教科版(2024审定)", "unit": "4", "stage": "全部",
              "date": "2026-09-20 00:00", "total": 1,
              "script_issues": {"口语训练": [{
                  "severity": "高", "type": "答案与关键词不一致",
                  "location": "U4 第4大题 第3小题",
                  "detail": "关键词「bring their raincoats」与参考答案不一致："
                            "答案里是「take their raincoats」",
                  "quote": "关键词 bring their raincoats ↔ 参考答案 take their raincoats",
                  "suggestion": "把关键词改成 take their raincoats"
                                "（学生按关键词作答会被判错）"}]}}
    out4 = Path(ReportExporter(save_dir=str(tmp)).export_html_live([_q4], _meta4))
    doc4 = out4.read_text(encoding="utf-8")
    hit4 = [b for _, b in re.findall(r'<details class="card([^"]*)">(.*?)</details>',
                                     doc4, re.S) if "take their raincoats" in b]
    chk("运行单元=4 时归位到题卡（合成数据）", len(hit4) == 1, f"命中 {len(hit4)} 张")
    if hit4:
        chk("写清了『学生按关键词作答会被判错』这一后果", "判错" in hit4[0])
        chk("给出了具体改法", "take their raincoats" in hit4[0])

    # ── 4. 模块级区块（全文 / 其他单元） ──────────────────────
    print("\n【4】无法归位的问题进模块级「脚本自检」区块")
    chk("存在脚本自检区块", 'class="sc-sec"' in doc)
    chk("区块标题带条数", re.search(r'脚本自检（\d+ 处）', doc) is not None)
    chk("“全文”类问题在区块里", "字段名不统一" in doc)
    # ★ 2026-09-23 修正测试自身的过期假设：旧断言写死"U7 的知识点占位符问题不该出现"，
    #   那是"本次跑 U6"时留下的。state 可能是任意单元 → 必须按 state["unit"] 动态判断：
    #     实跑含 U7 → 该问题**必须**出现（否则是漏报，这反过来才是 bug）；
    #     实跑不含 U7 → 才不许出现（"只报在跑单元"）。
    _run_units = str(state.get("unit", "") or "")
    _has_u7 = "7" in re.split(r"[-,\s]+", _run_units.strip())
    if _has_u7:
        chk("本次实跑含 U7 → U7 的知识点占位符问题必须出现（不漏报）",
            "占位符" in doc, "报告里没有 U7 的知识点占位符问题")
    else:
        chk("非本次实跑单元（U7）的问题不再出现", "占位符" not in doc,
            "出现了 U7 的知识点占位符问题")
    chk("区块说明写明只保留本次实跑单元", "实跑单元" in doc)

    # ── 5. 文案 ─────────────────────────────────────────────
    print("\n【5】文案")
    chk("副标题写清三档", "道不通过" in doc and "道未判定" in doc)
    chk("去掉了 emoji（用户要求 UI 无 emoji）", "🎉" not in doc)
    chk("未判定题不会被说成“全部通过”", not (_exp_fail == 0 and "全部通过" in doc and n_und))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 60)
print(f"PASS {len(_OK)} / FAIL {len(_BAD)}")
for b in _BAD:
    print("  - " + b)
sys.exit(1 if _BAD else 0)
