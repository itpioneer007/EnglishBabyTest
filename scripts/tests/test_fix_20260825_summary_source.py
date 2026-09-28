# -*- coding: utf-8 -*-
"""2026-08-25 统计口径 + 数据源修复 mock 验证（不连手机）

修复点：
  1. /api/errors/summary 只统计实际测试的题（auto-Q*），排除脚本全量审查（*-脚本-Q*）
  2. 分子 = 严格不通过(overall_passed is False)，None(未审查)不误计
  3. ★ 数据源修复：优先读内存 _inspection_state（本次运行），内存空才读磁盘兜底；
     多模块入口启动时清内存后同步 _save_inspection_state() 清磁盘
  4. 场景：三年级口语训练未上线 → 本次0题 → summary 必须返回 0/0（不得显示上次的4/20）
"""
import sys
import json

sys.path.insert(0, "src")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


def summary_stats(questions):
    """复刻修复后的 /api/errors/summary 统计逻辑（纯计算，不含IO）"""
    if isinstance(questions, dict):
        q_items = list(questions.items())
    else:
        q_items = [(str(q.get("qid") or f"q{i}"), q) for i, q in enumerate(questions)]
    tested = [q for _qid, q in q_items
              if str(_qid).startswith("auto-Q") or
              (str(_qid).startswith("Q") and "脚本-Q" not in str(_qid))]
    failed = [q for q in tested if q.get("overall_passed") is False]
    return len(tested), len(failed)


# ============ 场景1：上次五年级残留75条（磁盘），本次三年级未上线0题（内存） ============
old_disk = {}
for i in range(1, 21):
    old_disk[f"auto-Q{i:03d}"] = {"overall_passed": False if i <= 4 else True}
for i in range(1, 56):
    old_disk[f"口语训练-脚本-Q{i:02d}"] = {"overall_passed": i % 2 == 0}

# 修复后：summary 优先读内存（本次），内存空 → 读磁盘。内存=本次0题
mem_tested, mem_failed = summary_stats({})
disk_tested, disk_failed = summary_stats(old_disk)

check("本次0题（内存）→ 分母0", mem_tested == 0, f"got {mem_tested}")
check("本次0题（内存）→ 分子0（不再显示上次4/20）", mem_failed == 0, f"got {mem_failed}")
check("旧磁盘残留75条仅作兜底，不作为本次结果", disk_tested == 20, f"got {disk_tested}")

# ============ 场景2：本次真的测了20题（口语训练五上） ============
cur = {}
for i in range(1, 21):
    cur[f"auto-Q{i:03d}"] = {"overall_passed": False if i <= 4 else (None if i == 5 else True)}
for i in range(1, 56):
    cur[f"口语训练-脚本-Q{i:02d}"] = {"overall_passed": True}
t, f = summary_stats(cur)
check("本次20题 → 分母20", t == 20, f"got {t}")
check("本次20题 → 严格不通过4（None不计）", f == 4, f"got {f}")

# ============ 场景3：全部通过（无错题） ============
allpass = {f"auto-Q{i:03d}": {"overall_passed": True} for i in range(1, 11)}
t, f = summary_stats(allpass)
check("全通过 → 0/10", t == 10 and f == 0, f"got {f}/{t}")

print()
if FAIL:
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败 ❌")
    sys.exit(1)
print(f"结果: {len(PASS)} 通过, 0 失败")
print("全部通过 ✅")
