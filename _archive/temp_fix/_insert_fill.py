with open('engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

fill_func = r'''
# ==================== ⑨ 填空题处理（新题型） ====================

# 键盘字母固定坐标（基于 1080×2400 屏幕截图）
_KEYBOARD_LETTERS = {
    'q': (60, 770), 'w': (170, 770), 'e': (280, 770), 'r': (390, 770),
    't': (500, 770), 'y': (610, 770), 'u': (720, 770), 'i': (830, 770),
    'o': (940, 770), 'p': (1030, 770),
    'a': (95, 900), 's': (205, 900), 'd': (315, 900), 'f': (425, 900),
    'g': (535, 900), 'h': (645, 900), 'j': (755, 900), 'k': (865, 900),
    'l': (975, 900),
    'z': (130, 1030), 'x': (240, 1030), 'c': (350, 1030), 'v': (460, 1030),
    'b': (570, 1030), 'n': (680, 1030), 'm': (790, 1030),
    ' ': (540, 1140),
    'OK': (960, 1140),  # 右下角"确定"按钮
}


def _handle_fill_blank(d, config):
    """处理填空题：
    1. 找所有 EditText 输入框（需要下滑看到）
    2. 依次：点方框 → 弹键盘 → 随机输入 2-3 个字母 → 点确定 → 下一个方框
    3. 全部填完 → 点检查
    """
    import re as _re
    print(f"    填空题，处理中...")

    def _find_inputs():
        inputs = []
        for m in _re.finditer(
            r'class="android\.widget\.EditText"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            d.dump_hierarchy()
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            cx, cy = (x1+x2)//2, (y1+y2)//2
            inputs.append((cx, cy, y1))
        return inputs

    import random
    words = ['a', 'b', 'cat', 'dog', 'sun', 'ok', 'hi', 'go']
    for attempt in range(8):
        d.swipe(540, 1200, 540, 800, 0.4)
        time.sleep(0.4)
        inputs = _find_inputs()
        if len(inputs) >= 3:
            break
    inputs.sort(key=lambda t: t[2])
    print(f"    找到 {len(inputs)} 个输入框")
    if not inputs:
        return False

    for i, (cx, cy, y1) in enumerate(inputs, 1):
        d.click(cx, cy)
        time.sleep(0.6)
        word = random.choice(words)
        for ch in word:
            if ch in _KEYBOARD_LETTERS:
                px, py = _KEYBOARD_LETTERS[ch]
                d.click(px, py)
                time.sleep(0.3)
        time.sleep(0.35)
        d.click(960, 1140)  # 点右下角"确定"
        time.sleep(0.5)
        if i < len(inputs):
            d.swipe(540, 1200, 540, 600, 0.3)
            time.sleep(0.4)

    time.sleep(0.4)
    if d(text="检查").exists(timeout=2):
        d(text="检查").click()
        print(f"    填空完成，点击检查")
        time.sleep(0.6)
        return True
    return False


'''

marker = '# ==================== ⑧ 入口（批量调度） ===================='
new_content = content.replace(marker, fill_func + marker)
with open('engine.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('OK, fill 函数:', new_content.count('def _handle_fill_blank'))
