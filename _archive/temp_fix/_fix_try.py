with open('modules/知识过关.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 下一题/查看报告点击加 try
content = content.replace('''        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.15):
            d(text="查看报告").click()
            print(f"    ✅ 查看报告！知识关过完成")
            time.sleep(0.8)
            return q
        # 下一题按钮
        if d(text="下一题").exists(timeout=0.15):
            d(text="下一题").click()
            time.sleep(0.6)
            continue''',
'''        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.15):
            try:
                d(text="查看报告").click()
            except Exception:
                pass
            print(f"    ✅ 查看报告！知识关过完成")
            time.sleep(0.8)
            return q
        # 下一题按钮
        if d(text="下一题").exists(timeout=0.15):
            try:
                d(text="下一题").click()
            except Exception:
                pass
            time.sleep(0.6)
            continue''')

# 2. 字母按钮点击加 try
content = content.replace('''            n = min(2, len(letter_btns))
            print(f"    🅰 填空-界面字母 (点{n}个字母)")
            for bx, by in letter_btns[:n]:
                d.click(bx, by)
                time.sleep(0.2)
            # 点检测
            if d(text="检测").exists(timeout=1.5):
                d(text="检测").click()
                time.sleep(0.6)
            q += 1
            continue''',
'''            n = min(2, len(letter_btns))
            print(f"    🅰 填空-界面字母 (点{n}个字母)")
            for bx, by in letter_btns[:n]:
                try:
                    d.click(bx, by)
                except Exception:
                    pass
                time.sleep(0.2)
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(0.6)
            except Exception:
                pass
            q += 1
            continue''')

# 3. 系统键盘填空点击加 try
content = content.replace('''            for cx, cy, y1 in edit_inputs:
                d.click(cx, cy)
                time.sleep(0.4)
                try:
                    d.send_keys("a")
                except Exception:
                    d.shell("input text a")
                time.sleep(0.3)
            d.press("back")
            time.sleep(0.4)
            # 点检测
            if d(text="检测").exists(timeout=1.5):
                d(text="检测").click()
                time.sleep(0.6)
            q += 1
            continue''',
'''            for cx, cy, y1 in edit_inputs:
                try:
                    d.click(cx, cy)
                    time.sleep(0.4)
                    d.send_keys("a")
                except Exception:
                    try:
                        d.shell("input text a")
                    except Exception:
                        pass
                time.sleep(0.3)
            try:
                d.press("back")
            except Exception:
                pass
            time.sleep(0.4)
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(0.6)
            except Exception:
                pass
            q += 1
            continue''')

# 4. 选择题点击加 try
content = content.replace('''        if d(text="A").exists(timeout=0.15):
            d(text="A").click()
            time.sleep(0.3)
            if d(text="检测").exists(timeout=1.5):
                d(text="检测").click()
                print(f"    ✓ 选择A → 检测")
                time.sleep(0.6)
            q += 1
            continue''',
'''        if d(text="A").exists(timeout=0.15):
            try:
                d(text="A").click()
            except Exception:
                pass
            time.sleep(0.3)
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    print(f"    ✓ 选择A → 检测")
                    time.sleep(0.6)
            except Exception:
                pass
            q += 1
            continue''')

with open('modules/知识过关.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('OK 全部加 try')
