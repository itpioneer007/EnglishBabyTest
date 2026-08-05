with open('engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_start = "# ==================== ⑨ 填空题处理（新题型） ===================="
old_end = "    return False\n\n\n# ==================== ⑧ 入口（批量调度） ===================="

start_idx = content.find(old_start)
end_idx = content.find("# ==================== ⑧ 入口（批量调度） ====================")
if start_idx == -1 or end_idx == -1:
    print('NOT FOUND')
else:
    new_func = '''# ==================== ⑨ 填空题处理（新题型） ====================

# 键盘字母固定坐标（基于 1080×2400 屏幕截图实测）
# 键盘布局（4行）：
#   qwertyuiop (y=875)
#   asdfghjkl  (y=990)
#   小写/ zxcvbnm /删除 (y=1110)
#   123 / \\' / 空格 / - / 英文 (y=1215)
_KEYBOARD_LETTERS = {
    'q': (60, 875), 'w': (170, 875), 'e': (280, 875), 'r': (390, 875),
    't': (500, 875), 'y': (610, 875), 'u': (720, 875), 'i': (830, 875),
    'o': (940, 875), 'p': (1020, 875),
    'a': (115, 990), 's': (225, 990), 'd': (335, 990), 'f': (445, 990),
    'g': (555, 990), 'h': (665, 990), 'j': (775, 990), 'k': (885, 990),
    'l': (995, 990),
    'z': (150, 1110), 'x': (265, 1110), 'c': (380, 1110), 'v': (495, 1110),
    'b': (610, 1110), 'n': (725, 1110), 'm': (840, 1110),
    ' ': (450, 1215),
}


def _handle_fill_blank(d, config):
    """处理填空题（用户约定）：
    1. 找所有 EditText 输入框，先填当前可见的
    2. 每个方框：点方框 → 弹键盘 → 点 2-3 个字母 → back 收起键盘
    3. 全部当前可见填完 → 下滑一次找新方框 → 重复
    4. 全部填完 → 点检查
    """
    import re as _re
    print(f"    填空题，处理中...")

    def _find_inputs():
        xml = d.dump_hierarchy()
        inputs = []
        for m in _re.finditer(
            r'class="android\\.widget\\.EditText"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            cx, cy = (x1+x2)//2, (y1+y2)//2
            inputs.append((cx, cy, y1))
        inputs.sort(key=lambda t: t[2])
        return inputs

    import random
    words = ['a', 'b', 'cat', 'dog', 'sun', 'ok', 'hi', 'go']
    filled = set()  # 已填的方框 y1 集合

    for round_i in range(8):
        inputs = _find_inputs()
        new_inputs = [i for i in inputs if i[2] not in filled]
        if not new_inputs:
            if round_i < 4:
                # 下滑找新方框
                d.swipe(540, 1800, 540, 800, 0.4)
                time.sleep(1.5)
                continue
            else:
                break

        # 填一个方框（避免 back 后布局变化丢失目标）
        cx, cy, y1 = new_inputs[0]
        d.click(cx, cy)
        time.sleep(1.5)
        word = random.choice(words)
        for ch in word:
            if ch == ' ':
                d.click(*_KEYBOARD_LETTERS[' '])
            elif ch.lower() in _KEYBOARD_LETTERS:
                d.click(*_KEYBOARD_LETTERS[ch.lower()])
            time.sleep(0.4)
        time.sleep(0.6)
        # back 收起键盘（不是点\\"英文\\"按钮，那是切换中英文）
        d.press("back")
        time.sleep(1.5)
        filled.add(y1)
        print(f"    填 (y={y1}) 字={word}")

    time.sleep(1.5)
    if d(text="检查").exists(timeout=2):
        d(text="检查").click()
        print(f"    填空完成，点击检查")
        time.sleep(1.5)
        return True
    return False


'''
    new_content = content[:start_idx] + new_func + '\n\n' + content[end_idx:]
    with open('engine.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('OK, 函数数:', new_content.count('def _handle_fill_blank'))
