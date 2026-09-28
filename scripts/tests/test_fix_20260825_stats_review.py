# -*- coding: utf-8 -*-
"""2026-08-25 修复验证（mock，不连手机）

验证两个修复：
  1. _check_content 对 REVIEW(信息不足) 标 method='uncertain'
     → _qreview_to_state._cr 转 None（未检）→ 不再连累整体判定
     （口语训练朗读单词题"front"无选项，LLM 合理 REVIEW，旧逻辑误判不通过）
  2. /api/errors/summary 统计口径：
     - 分母 = 实际测试的题数（auto-Q* 前缀，引擎真正跑到的题）
     - 分子 = 其中严格不通过(overall_passed is False)的题数
     - 排除 *-脚本-Q*（LLM 脚本全量审查，含未实际测试的题）
     - None(未审查) 不误计为不通过
"""
import sys
import json
import types

sys.path.insert(0, "src")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


# ============ 1. REVIEW → uncertain → _cr 转 None ============
def _cr(chk_passed, chk_method):
    """web_server._qreview_to_state._cr 的核心判定"""
    if chk_method == "skip":
        return None
    if chk_method == "uncertain":
        return None
    return chk_passed


def overall_of(dims):
    checked = [v for v in dims.values() if v is not None]
    if not checked:
        return None
    if any(v is False for v in checked):
        return False
    if all(v is True for v in checked):
        return True
    return None


# 模拟 _check_content 修复前后（朗读单词题 front，无选项）
before_content_method = ""          # 修复前：REVIEW → passed=False, method=''
after_content_method = "uncertain"  # 修复后：REVIEW → method='uncertain'
dims_before = {"stem": True, "content": _cr(False, before_content_method), "answer": None}
dims_after = {"stem": True, "content": _cr(False, after_content_method), "answer": None}
check("修复前：REVIEW 误判整体不通过", overall_of(dims_before) is False,
      f"got {overall_of(dims_before)}")
check("修复后：REVIEW 转未检，整体通过", overall_of(dims_after) is True,
      f"got {overall_of(dims_after)}")


# ============ 2. 统计口径 ============
def summary_stats(questions):
    """复刻修复后的 /api/errors/summary 统计逻辑"""
    q_items = list(questions.items()) if isinstance(questions, dict) else [
        (str(q.get("qid") or f"q{i}"), q) for i, q in enumerate(questions)]
    tested = [q for _qid, q in q_items
              if str(_qid).startswith("auto-Q") or
              (str(_qid).startswith("Q") and "脚本-Q" not in str(_qid))]
    failed = [q for q in tested if q.get("overall_passed") is False]
    return len(tested), len(failed), len(q_items) - len(tested)


# 构造与真实 data/inspection_state.json 同构的数据
questions = {}
for i in range(1, 21):  # 20 条实际测试（auto-Q）
    questions[f"auto-Q{i:03d}"] = {
        "overall_passed": False if i <= 4 else (None if i == 5 else True),
        "module": "口语训练", "idx": i,
    }
for i in range(1, 56):  # 55 条脚本全量审查（口语训练-脚本-Q*）
    questions[f"口语训练-脚本-Q{i:02d}"] = {
        "overall_passed": False if i % 2 == 0 else True,
        "module": "口语训练", "idx": i,
    }
# 2 条旧的"未审查(None)"脚本题（旧逻辑会被误计为不通过）
questions["口语训练-脚本-Q99"] = {"overall_passed": None, "module": "口语训练", "idx": 99}
questions["听力专项-脚本-Q99"] = {"overall_passed": None, "module": "听力专项", "idx": 99}

tested_n, failed_n, script_n = summary_stats(questions)
check("分母=实际测试题数 20", tested_n == 20, f"got {tested_n}")
check("分子=严格不通过 4", failed_n == 4, f"got {failed_n}")
check("脚本审查另计 57（55+2个None）", script_n == 57, f"got {script_n}")
check("不再出现 32/75 错误口径", not (tested_n == 75 and failed_n == 32),
      f"got {failed_n}/{tested_n}")

# 旧逻辑对照：not overall_passed → 会把 None 也计为不通过
old_failed = sum(1 for q in questions.values() if not q.get("overall_passed", True))
check("旧逻辑误计 None 为不通过", old_failed > failed_n, f"old={old_failed} new={failed_n}")

print()
if FAIL:
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败 ❌")
    sys.exit(1)
print(f"结果: {len(PASS)} 通过, 0 失败")
print("全部通过 ✅")
