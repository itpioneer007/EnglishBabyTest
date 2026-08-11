with open('engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        # 填一个方框：点方框 → 等键盘 → 用 shell input 输字母（更可靠）→ back 收起键盘
        cx, cy, y1 = new_inputs[0]
        d.click(cx, cy)
        time.sleep(0.6)
        word = random.choice(words)
        # 用 d.shell input text 模拟键盘输入（点击字母坐标在 uiautomator 中不稳定）
        d.shell(f"input text {word}")
        time.sleep(0.5)
        # back 收起键盘（不是点"英文"按钮，那是切换中英文）
        d.press("back")
        time.sleep(0.6)
        filled.add(y1)
        print(f"    填 (y={y1}) 字={word}")'''

new = '''        # 填一个方框：点方框 → 等待键盘弹稳 → shell input text → back 收起
        cx, cy, y1 = new_inputs[0]
        d.click(cx, cy)
        time.sleep(1.25)  # 重要：等键盘完全弹出
        word = random.choice(words)
        d.shell(f"input text {word}")
        time.sleep(0.4)
        d.press("back")
        time.sleep(0.8)  # 重要：等键盘完全收起
        filled.add(y1)
        print(f"    填 (y={y1}) 字={word}")'''

if old in content:
    content = content.replace(old, new)
    with open('engine.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')
