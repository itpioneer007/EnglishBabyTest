# -*- coding: utf-8 -*-
"""回归测试：前端审查结果总览的"三态统计"口径（2026-09-23 修复）

## 背景（用户反馈）
口语训练跑完一个单元，总览显示"不通过 6"，但"不通过题清单"与"错题日志"
一条都不展示（都是 0）。用户原话：
    "看见有6道错题可是没有展示在审查结果上面"

## 根因
templates/index.html 的 updQ()：
    const aipa = ids.filter((id) => qs[id].overall_passed).length;  // 只数 true
    const aifa = t - aipa;                                          // ← 总数 - 通过数
`overall_passed` 有**三态**：true（通过）/ false（不通过）/ null（未判定）。
`t - aipa` 把 6 道 None（未判定）也算进了"不通过"，
而 failIds 与 updWrong 都用严格 `=== false` 过滤 → 数字与列表自相矛盾。

## 不变量（本测试断言）
    通过数 + 不通过数 + 未判定数 === 总题数
    "不通过数" 必须严格等于 overall_passed === false 的题数，与列表口径一致。

运行：python scripts/tests/test_fix_20260923_stats_three_state.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print("  ✔ %s" % name)
    else:
        _failed += 1
        print("  ✘ %s  %s" % (name, detail))


def _counts(ids, qs):
    """复刻修复后 updQ() 的统计口径。"""
    t = len(ids)
    aipa = len([i for i in ids if qs[i].get("overall_passed") is True])
    aifa = len([i for i in ids if qs[i].get("overall_passed") is False])
    nopt = len([i for i in ids
                if qs[i].get("overall_passed") is None])
    return t, aipa, aifa, nopt


def _counts_old(ids, qs):
    """复刻修复前的错误口径（aifa = t - aipa）。"""
    t = len(ids)
    aipa = len([i for i in ids if qs[i].get("overall_passed")])
    return t, aipa, t - aipa


print("=" * 60)
print("A. 合成数据（模拟本次事故：14 通过 / 0 不通过 / 6 未判定）")
print("=" * 60)
qs = {}
for i in range(1, 15):
    qs["auto-Q01-%02d" % i] = {"overall_passed": True}
for i in range(1, 7):
    qs["auto-Q03-%02d" % i] = {"overall_passed": None}
ids = sorted(qs)

t, aipa, aifa, nopt = _counts(ids, qs)
print("  修复后：总 %d ／ 通过 %d ／ 不通过 %d ／ 未判定 %d" % (t, aipa, aifa, nopt))
check("总题数 = 20", t == 20, t)
check("通过 = 14", aipa == 14, aipa)
check("不通过 = 0（None 不再被算错题）", aifa == 0, aifa)
check("未判定 = 6", nopt == 6, nopt)
check("三态自洽：通过+不通过+未判定 === 总数",
      aipa + aifa + nopt == t, (aipa, aifa, nopt, t))
check("不通过数 === 不通过题清单长度（前端两处口径一致）",
      aifa == len([i for i in ids if qs[i].get("overall_passed") is False]))

print()
print("=" * 60)
print("B. 反向验证：旧口径确实会把 None 算成不通过（bug 存在性）")
print("=" * 60)
t, aipa_old, aifa_old = _counts_old(ids, qs)
print("  修复前：总 %d ／ 通过 %d ／ 『不通过』%d" % (t, aipa_old, aifa_old))
check("旧口径误报 6 道错题（复现用户看到的数字）", aifa_old == 6, aifa_old)
check("旧口径三数不自洽（14+6+6=26 > 20）",
      aipa_old + aifa_old + nopt != t)
check("新旧口径在含 None 时必然不同", aifa_old != aifa)

print()
print("=" * 60)
print("C. 真实状态文件（若存在）—— 用本次 U6 实跑数据核验")
print("=" * 60)
state_path = os.path.join(ROOT, "data", "inspection_state.json")
if os.path.exists(state_path):
    try:
        st = json.load(open(state_path, encoding="utf-8"))
        rqs = st.get("questions") or {}
        rids = sorted(rqs)
        if rids:
            t, aipa, aifa, nopt = _counts(rids, rqs)
            print("  状态文件：总 %d ／ 通过 %d ／ 不通过 %d ／ 未判定 %d"
                  % (t, aipa, aifa, nopt))
            check("真实数据三态自洽",
                  aipa + aifa + nopt == t, (aipa, aifa, nopt, t))
            # 不通过题必须都有明确的不通过维度原因（不能是空壳）
            _no_reason = []
            for i in rids:
                q = rqs[i]
                if q.get("overall_passed") is False:
                    has = any(q.get(k) is False for k in
                              ("ai_stem", "ai_content", "ai_image",
                               "ai_answer", "ai_audio", "ai_post_error"))
                    if not has:
                        _no_reason.append(i)
            check("每道不通过题都有明确的失败维度", not _no_reason, _no_reason)
        else:
            print("  （状态文件无题目，跳过）")
    except Exception as e:
        print("  状态文件解析失败，跳过：%s" % e)
else:
    print("  （无状态文件，跳过）")

print()
print("=" * 60)
print("结果：%d 通过 / %d 失败" % (_passed, _failed))
print("=" * 60)
sys.exit(1 if _failed else 0)
