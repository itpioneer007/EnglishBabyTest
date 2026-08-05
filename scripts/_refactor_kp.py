with open('modules/知识过关.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 EditText/letter_btns 段，替换为按题目文字区分的清晰逻辑
old = '''        # 找 EditText（填空方框）
        xml = d.dump_hierarchy()
        edit_inputs = []
        for m in re.finditer(
            r'class="android\\.widget\\.EditText"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            edit_inputs.append(((x1+x2)//2, (y1+y2)//2, y1))
        edit_inputs.sort(key=lambda t: t[2])

        # 找界面字母按钮（LinearLayout clickable 193x137）
        letter_btns = []
        for m in re.finditer(
            r'<node[^>]*class="android\\.widget\\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2-x1; h = y2-y1
            # 字母按钮：y 1100-1700（排除上方句子方框 y 815-1043）
            if 1100 < y1 < 1700 and 150 < w < 250 and 100 < h < 180:
                letter_btns.append(((x1+x2)//2, (y1+y2)//2))
        letter_btns.sort(key=lambda t: (t[1], t[0]))

        if letter_btns:
            # 填空题-界面字母：方框在题干区（不在 dump），但字母按钮可见
            # 简化策略：点 2 个字母按钮（覆盖大部分 1-2 空题）+ 检测
            n = min(2, len(letter_btns))
            print(f"    🅰 填空-界面字母 (点{n}个字母)")
            for bx, by in letter_btns[:n]:
                try:
                    d.click(bx, by)
                except Exception:
                    pass
                time.sleep(0.4)
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        if edit_inputs and not letter_btns:
            # 填空题-系统键盘：FastInputIME 注入
            print(f"    📝 填空-系统键盘 ({len(edit_inputs)}空)")
            try:
                d.set_fastinput_ime(True)
                time.sleep(0.3)
            except Exception:
                pass
            for cx, cy, y1 in edit_inputs:
                try:
                    d.click(cx, cy)
                    time.sleep(1)
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
            time.sleep(1)
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue'''

new = '''        # 题目文字（用于判断题型）
        title_text = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            t = (e.text or "").strip()
            if "字母" in t and "补全" in t:
                title_text = "fill_letters"
                break
            if "连词成句" in t:
                title_text = "sentence_sort"
                break

        # === 填字母题：根据题目文字判断 ===
        # 特征：题目文字含「字母补全」+ 字母按钮有 text（a-z 单字母）
        if title_text == "fill_letters":
            # 字母按钮：有 text 的单个字母（a-z）
            # 先 dump 找所有有 text 的字母按钮位置
            letter_btn_map = {}  # 字母 -> 坐标
            for e in (d.xpath('//*[@clickable="true"]').all() or []):
                t = (e.text or "").strip()
                if len(t) == 1 and t.isalpha() and t.islower():
                    b = e.bounds
                    letter_btn_map[t] = ((b[0]+b[2])//2, (b[1]+b[3])//2)
            # 也 dump 找 ImageButton 或其他可能有 text 字母的
            xml_letters = d.dump_hierarchy()
            import re as _re
            for m in _re.finditer(
                r'<node[^>]*text="([a-z])"[^>]*clickable="true"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
                xml_letters
            ):
                t, x1, y1, x2, y2 = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                letter_btn_map[t] = ((x1+x2)//2, (y1+y2)//2)
            # 找第一个方框（y < 700 的 LL clickable 170x114）
            xml = d.dump_hierarchy()
            first_box = None
            for m in _re.finditer(
                r'<node[^>]*class="android\\.widget\\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
                xml
            ):
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                w, h = x2-x1, y2-y1
                # 方框特征：y < 700, 宽 150-200, 高 100-130
                if 400 < y1 < 700 and 150 < w < 200 and 100 < h < 130:
                    first_box = ((x1+x2)//2, (y1+y2)//2)
                    break
            if first_box and letter_btn_map:
                print(f"    🅰 填字母 ({len(letter_btn_map)}字母)")
                # 点第一个方框激活
                try:
                    d.click(*first_box)
                except Exception:
                    pass
                time.sleep(1)
                # 依次点字母：按字母表顺序找可用字母，填每个方框
                # 每个方框按 a-z 顺序点（保证填入字母，不用关心具体哪个字母）
                # 简化：直接按 a, b, c, d, e... 顺序点字母按钮，直到检测出现
                for letter in "abcdefghijklmnopqrstuvwxyz":
                    if letter in letter_btn_map:
                        try:
                            d.click(*letter_btn_map[letter])
                        except Exception:
                            pass
                        time.sleep(0.3)
                        # 检测出现了就停
                        if d(text="检测").exists(timeout=0.3):
                            break
                time.sleep(1)
                # 点检测
                try:
                    if d(text="检测").exists(timeout=1.5):
                        d(text="检测").click()
                        time.sleep(1.5)
                except Exception:
                    pass
                q += 1
                continue

        # === 填单词题（连词成句）：调用排序处理 ===
        if title_text == "sentence_sort":
            print(f"    🧩 连词成句 → 调用排序处理")
            try:
                _handle_sort_question(d, {})
            except Exception:
                pass
            q += 1
            continue

        # 找 EditText（填空方框）+ 字母按钮（旧的字母填空，可能没题目文字触发）
        xml = d.dump_hierarchy()
        edit_inputs = []
        for m in _re.finditer(
            r'class="android\\.widget\\.EditText"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            edit_inputs.append(((x1+x2)//2, (y1+y2)//2, y1))
        edit_inputs.sort(key=lambda t: t[2])

        # 找界面字母按钮（LinearLayout clickable 193x137）
        letter_btns = []
        for m in _re.finditer(
            r'<node[^>]*class="android\\.widget\\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2-x1; h = y2-y1
            # 字母按钮：y 1100-1700（排除上方句子方框 y 815-1043）
            if 1100 < y1 < 1700 and 150 < w < 250 and 100 < h < 180:
                letter_btns.append(((x1+x2)//2, (y1+y2)//2))
        letter_btns.sort(key=lambda t: (t[1], t[0]))

        if letter_btns:
            # 兜底：填空题-界面字母（无题目文字触发）
            n = min(2, len(letter_btns))
            print(f"    🅰 填空-界面字母 (点{n}个字母，兜底)")
            for bx, by in letter_btns[:n]:
                try:
                    d.click(bx, by)
                except Exception:
                    pass
                time.sleep(0.4)
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        if edit_inputs:
            # 填空题-系统键盘：FastInputIME 注入
            print(f"    📝 填空-系统键盘 ({len(edit_inputs)}空)")
            try:
                d.set_fastinput_ime(True)
                time.sleep(0.3)
            except Exception:
                pass
            for cx, cy, y1 in edit_inputs:
                try:
                    d.click(cx, cy)
                    time.sleep(1)
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
            time.sleep(1)
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue'''

if old in content:
    content = content.replace(old, new)
    with open('modules/知识过关.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')