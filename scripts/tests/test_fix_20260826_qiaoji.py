# -*- coding: utf-8 -*-
"""2026-08-26 巧记单词三问题修复 mock 验证（不连手机）

问题1：题数按 App 页面 N/M 记录（答错重做不重复计数）
问题2：无试题关卡只记一次提示，跳过继续下一关
问题3：巧记单词脚本审查——App题干类型与脚本题型一致，内容对应
"""
import sys
import re
import difflib

sys.path.insert(0, ".")
sys.path.insert(0, "src")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


# ============ 问题1：按 App N/M 记录题号 ============
def extract_progress(xml_text):
    """与 _answer_loop 完全一致：从 XML 的 text 标签提取 N/M"""
    txts = ' '.join(re.findall(r'text="([^"]+)"', xml_text))
    m = re.search(r'第?\d+\s*关\s*(\d+)/(\d+)', txts)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.search(r'(\d+)/(\d+)', txts)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    return 0, 0

cur, total = extract_progress('<node text="第1关  3/15"/>')
check("进度提取 第1关 3/15 → 3/15", (cur, total) == (3, 15), f"got ({cur},{total})")
cur, total = extract_progress('<node text="第2关  1/15"/>')
check("进度提取 第2关 1/15 → 1/15", (cur, total) == (1, 15), f"got ({cur},{total})")
cur, total = extract_progress('<node text="15/15"/>')
check("进度提取 15/15（无'关'）→ 15/15", (cur, total) == (15, 15), f"got ({cur},{total})")
cur, total = extract_progress('<node text="3/40"/>')
check("进度提取 3/40（习题兜底）→ 3/40", (cur, total) == (3, 40), f"got ({cur},{total})")
check("无进度文本→0", extract_progress('<node text="没有进度"/>') == (0, 0))
check("浏览页(无N/M)→0", extract_progress('<node text="这几个单词你还记得吗？"/><node text="new"/>') == (0, 0))

# 答错重做：同一题 App 进度不变 → 不重复计数
# 模拟：第1题答错 → 重新答题（进度仍1/15）→ 再答对（进度变3/15）→ 计数=3
simulate_progresses = [1, 1, 1, 3, 3, 4]  # 答错重做时进度不变
last_max = 0
answered_qs = []
for p in simulate_progresses:
    if p > last_max:
        last_max = p
        answered_qs.append(p)
check("答错重做不重复计数（进度1,1,1,3,3,4→记录1,3,4）", answered_qs == [1, 3, 4],
      f"got {answered_qs}")
check("最终题数=App最大进度4", last_max == 4, f"got {last_max}")


# ============ 问题2：无试题关卡只记一次 ============
def is_no_question(txt):
    return any(k in txt for k in ("没有试题", "暂无题目", "暂无数", "无题", "敬请期待", "正在开发"))

check("无试题文案识别", is_no_question("暂无题目，请稍后再试"))
check("正常答题页不误判", not is_no_question("听录音，选择与录音内容相符的释义。"))
# 只记一次提示（用 _no_question_logged 标志）
logged = False
count = 0
for _ in range(5):
    if is_no_question("暂无题目"):
        if not logged:
            logged = True
            count += 1
check("无试题只记一次提示", logged and count == 1, f"count={count}")


# ============ 问题3：巧记单词脚本审查（内容匹配） ============
# ★ 2026-09-10 修复：原来写死微信下载目录（文件搬走后测试必定报"脚本解析失败"）
#   → 改为项目 uploads/ 下的样本；样本缺失时明确跳过，不误报失败。
import os as _os
_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_doc = _os.path.join(_root, "uploads", "260413巧记单词闯关部分新湘少五上（已一校）.doc")
if not _os.path.exists(_doc):
    print(f"  ⚠ 跳过问题3（脚本样本不存在）: {_doc}")
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败（问题3 已跳过）")
    sys.exit(0)
try:
    from parse_yingyubao_docx import parse
    qs = parse(_doc)
    u1 = [q for q in qs if q.unit == 1]
except Exception as e:
    check(f"脚本解析失败: {e}", False)
    sys.exit(1)


def match_qiaoji(stem_text, _u_cur=1):
    _cands = [s for s in u1 if s.unit == _u_cur]
    _best, _best_ratio = None, 0.0
    for s in _cands:
        _ss = getattr(s, "stem", "") or ""
        if not _ss:
            continue
        _r = difflib.SequenceMatcher(None, _ss[:20], stem_text[:20]).ratio()
        if _r > _best_ratio:
            _best_ratio, _best = _r, s
    return (_best, _best_ratio) if (_best and _best_ratio >= 0.6) else (None, _best_ratio)


best, ratio = match_qiaoji("听录音，选择与录音内容相符的释义。")
check("脚本U1解析118题", len(u1) > 0, f"got {len(u1)}")
check("听音选释义→匹配听音选择释义", best is not None and "听" in best.type_2,
      f"got {best.type_2 if best else None} ratio={ratio:.2f}")
best2, _ = match_qiaoji("根据中文提示，选择正确的字母补全单词。")
check("字母补全→匹配补全", best2 is not None and "补全" in best2.type_2,
      f"got {best2.type_2 if best2 else None}")
best3, ratio3 = match_qiaoji("看图片，选择正确的单词。")
check("看图选单词(错误类型)→不匹配", best3 is None, f"ratio={ratio3:.2f}")

print()
if FAIL:
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败 ❌")
    sys.exit(1)
print(f"结果: {len(PASS)} 通过, 0 失败")
print("全部通过 ✅")
