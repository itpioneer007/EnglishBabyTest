with open('engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        # 填一个方框（避免 back 后布局变化丢失目标）
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
        print(f"    填 (y={y1}) 字={word}")'''

new = '''        # 填一个方框：点方框 → 等键盘 → 用 shell input 输字母（更可靠）→ back 收起键盘
        cx, cy, y1 = new_inputs[0]
        d.click(cx, cy)
        time.sleep(1.5)
        word = random.choice(words)
        # 用 d.shell input text 模拟键盘输入（点击字母坐标在 uiautomator 中不稳定）
        d.shell(f"input text {word}")
        time.sleep(0.5)
        # back 收起键盘（不是点"英文"按钮，那是切换中英文）
        d.press("back")
        time.sleep(1.5)
        filled.add(y1)
        print(f"    填 (y={y1}) 字={word}")'''

if old in content:
    content = content.replace(old, new)
    with open('engine.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')
