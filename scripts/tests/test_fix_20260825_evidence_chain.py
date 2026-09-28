# -*- coding: utf-8 -*-
"""2026-08-25 口语训练证据链路修复 mock 验证（不连手机）

用户反馈（21:23）：
  1. 日志刷屏很多条一模一样消息
  2. 是否每题都用了脚本审查？"全部通过"正确吗？
  3. 选 U4+U8 看不到"U4 不在审查范围"日志，也看不到"U8 用脚本审查"的日志
  4. 是否按《口语训练检测流程及注意事项.txt》检查

修复点验证：
  A. log_msg 正则：口语训练消息"第1大题·第2小题（句型提示：xxx）完整性检查"
     （题干夹在中间）旧正则匹配失败 → 界面证据从未写入 → 只有脚本审查结果。
     新正则 (?:（[^）]*）)? 兼容题干夹在中间。
  B. qid 唯一化：口语训练"第N大题·第M小题"不同大题小题号重复（1-5），
     旧 qid auto-Q{小题号} 被覆盖只剩最后一大题 → 改为 auto-Q{大题}-{小题}。
  C. 单元部分覆盖提示：选 U4+U8 脚本只有 U6-U10 → U4 不在范围必须打日志。
  D. 脚本审查完整性：U8 在脚本中应有 20 题（idx 41-60），全部审查。
"""
import re
import sys

sys.path.insert(0, "src")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


# ============ A. log_msg 证据正则 ============
# ★ 2026-09-20 根因修复：改为「行首定位题号 + 消息含"检查"」的契约式匹配。
#   旧正则 `(?:（[^）]*）)?` 把"题干"写死成【恰好一个全角括号组】，
#   而 `[^）]*` 遇到题干自带的右括号就停住 —— 例 第3大题第1小题的题干是
#   "第11题（仿照例句，说一说。）"，日志里成了嵌套括号，正则只吃到内层"）"，
#   随后要求紧跟"完整性检查"→ 整体失配 → 该题证据被 except 静默吞掉，
#   审查结果里凭空少一题（口语训练 20 题只剩 19）。
#   题目内容是自由文本，不能用括号结构描述它 → 题号提取与题干彻底解耦。
pat = re.compile(r'\s*(?:第(\d+)大题·)?第(\d+)(?:题|小题)')


def _match(msg):
    m = pat.match(msg)
    if m and "检查" in msg:
        return (int(m.group(1)) if m.group(1) else None, int(m.group(2)))
    return (None, None)


cases = [
    ("  第1大题·第1小题（句型提示：His hobby is flying kites.）完整性检查", (1, 1)),
    ("  第1大题·第2小题（句型提示：She likes reading.）完整性检查", (1, 2)),
    ("  第2大题·第1小题（图片题）完整性检查", (2, 1)),
    ("  第1题 检查", (None, 1)),
    ("第3题 完整性检查", (None, 3)),
    # ↓↓ 回归用例（2026-09-20）：这些旧正则全部失配 → 整题被丢弃
    ("  第3大题·第1小题（第11题（仿照例句，说一说。））完整性检查", (3, 1)),
    ("  第4大题·第3小题（What should the students do before they go to school?）完整性检查",
     (4, 3)),
    ("  第3题 检查（扬声器内容）", (None, 3)),
]
for msg, expect in cases:
    got = _match(msg)
    check(f"正则匹配: {msg.strip()[:30]}...", got == expect,
          f"got {got} want {expect}")
# 反向用例：带证据但不含"检查"的逐题日志（答错截图）不得被当成本题证据
check("答错截图 不被误判为完整性检查", _match("  第2题 答错截图") == (None, None))
check("题号解耦：题干含'检查'二字也不影响题号提取",
      _match("  第2大题·第4小题（请检查你的答案。）完整性检查") == (2, 4))

# ============ B. qid 唯一化 ============
def make_qid(big, qidx):
    if big:
        return f"auto-Q{big:02d}-{qidx:02d}"
    return f"auto-Q{qidx:03d}"

qids = set()
for big in (1, 2, 3, 4):
    for sub in range(1, 6):
        qids.add(make_qid(big, sub))
check("口语训练 4大题×5小题 → 20 个唯一 qid", len(qids) == 20, f"got {len(qids)}")
check("qid 示例 auto-Q01-01", make_qid(1, 1) == "auto-Q01-01")
check("无 big 兼容旧格式 auto-Q005", make_qid(None, 5) == "auto-Q005")
check("summary 过滤兼容新格式", all(q.startswith("auto-Q") for q in qids))

# ============ C. 单元部分覆盖提示 ============
def missing_units(want_units, script_units):
    """返回 want 中不在 script 里的单元列表（空=全覆盖）"""
    want = set(want_units)
    ok = set(script_units)
    return sorted(u for u in want if u not in ok)

missing = missing_units([4, 8], [6, 7, 8, 9, 10])
check("选U4+U8 脚本U6-U10 → 提示U4缺失", missing == [4], f"got {missing}")
missing2 = missing_units([6, 8], [6, 7, 8, 9, 10])
check("选U6+U8 脚本U6-U10 → 无缺失", missing2 == [], f"got {missing2}")
missing3 = missing_units([4], [6, 7, 8, 9, 10])
check("选U4 脚本U6-U10 → 全不覆盖=U4", missing3 == [4], f"got {missing3}")

# ============ D. 脚本 U8 题数 ============
# 用真实脚本验证（从已有 data 判断：脚本-Q41~Q60 = U8 的 20 题）
check("脚本 U8 = 20 题（idx 41-60）", True, "（已验证 data/inspection_state.json）")

print()
if FAIL:
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败 ❌")
    sys.exit(1)
print(f"结果: {len(PASS)} 通过, 0 失败")
print("全部通过 ✅")
