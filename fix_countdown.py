# -*- coding: utf-8 -*-
import io

p = 'scripts/engine.py'
with io.open(p, encoding='utf-8') as f:
    c = f.read()

# 1) 初始化 _idle（空转计数，防倒计时/死循环）
old1 = "    q = 0\n    _xml = \"\"  # 当前 UI 缓存\n    _need_dump = True  # 需要在下一轮重新 dump"
new1 = "    q = 0\n    _idle = 0  # 连续空转计数（无选项且无题型匹配），防倒计时被误计/死循环\n    _xml = \"\"  # 当前 UI 缓存\n    _need_dump = True  # 需要在下一轮重新 dump"
assert old1 in c, "init anchor not found"
c = c.replace(old1, new1, 1)

# 2) 新题兜底分支：先找选项，找到才 q+1；无选项不计数（★ 修复倒计时 3、2、1 被算成 3 道题）
old2 = """        # 新题
        q += 1
        print(f"    📸 第{q}题")
        step_log(f"📸 第{q}题", "step")
        time.sleep(0.3); _xml = _dump()

        opt = _find_opt()
        if opt:
            _click_text(opt)
            print(f"      → 选 {opt}")
            step_log(f"  第{q}题: 选 {opt} → 检查", "info")
            time.sleep(0.5); _xml = _dump()
            if _has("检查"):
                _click_text("检查")
                print(f"      → 检查")
                time.sleep(0.5); _need_dump = True
            continue

        # 兜底：无选项 → 下轮重试
        time.sleep(0.3); _need_dump = True
"""
new2 = """        # 新题：★ 先找选项，找到才计题（倒计时3、2、1/页面加载中无选项 → 不计题！）
        opt = _find_opt()
        if not opt:
            # 无选项 → 倒计时/加载中/异常页：不计数，空转保护防死循环
            _idle += 1
            if _idle >= 15:
                step_log(f"⚠ 连续 {_idle} 轮无有效题目（可能停在非答题页/倒计时异常），退出答题循环", "warning")
                return q
            time.sleep(0.3); _need_dump = True
            continue
        _idle = 0
        q += 1
        print(f"    📸 第{q}题")
        step_log(f"📸 第{q}题", "step")
        time.sleep(0.3); _xml = _dump()

        _click_text(opt)
        print(f"      → 选 {opt}")
        step_log(f"  第{q}题: 选 {opt} → 检查", "info")
        time.sleep(0.5); _xml = _dump()
        if _has("检查"):
            _click_text("检查")
            print(f"      → 检查")
            time.sleep(0.5); _need_dump = True
        continue
"""
assert old2 in c, "new-question anchor not found"
c = c.replace(old2, new2, 1)

# 3) 各真实处理分支 continue 前重置 _idle（页面在推进，非空转）
anchors = [
    # 关弹窗
    ('            print("      → 关弹窗")',
     '            print("      → 关弹窗")\n            _idle = 0'),
    # 下一题（答错）
    ('            print(f"      → 下一题（答错）")',
     '            print(f"      → 下一题（答错）")\n            _idle = 0'),
    # 排序题处理
    ('            time.sleep(0.4); _need_dump = True; continue\n        elif qtype == "match_questions":',
     '            _idle = 0\n            time.sleep(0.4); _need_dump = True; continue\n        elif qtype == "match_questions":'),
    # 匹配题处理
    ('        elif qtype == "match_questions":\n            _handle_match_question(d, config)\n            time.sleep(0.4); _need_dump = True; continue',
     '        elif qtype == "match_questions":\n            _handle_match_question(d, config)\n            _idle = 0\n            time.sleep(0.4); _need_dump = True; continue'),
]
for old, new in anchors:
    if old in c:
        c = c.replace(old, new, 1)
    else:
        print("  WARN 未找到锚点: %r" % old[:50])

with io.open(p, 'w', encoding='utf-8') as f:
    f.write(c)
print("patch done")
