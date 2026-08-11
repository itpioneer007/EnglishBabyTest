with open('modules/知识过关.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        # 2. 填空题（界面自带字母）：有字母按钮
        # 检测：页面有单个字母的可点击按钮（c/a/x/g...）
        letter_btns = []
        for e in (d.xpath('//*[@text!=""]').all() or []):
            t = (e.text or "").strip()
            if len(t) == 1 and t.isalpha() and t.islower():
                letter_btns.append(e)
        # 也检查 dump 找带 ImageButton 的字母（界面字母按钮可能没 text）
        xml = d.dump_hierarchy()
        for m in re.finditer(
            r'<node[^>]*class="android\\.widget\\.ImageView"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"[^>]*content-desc="([a-z])"',
            xml
        ):
            cd = m.group(5)
            if cd.isalpha() and cd.islower():
                # 找到对应坐标
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                letter_btns.append((x1+x2)//2, (y1+y2)//2, cd)
        # 也找带 content-desc 的字母方框
        for m in re.finditer(
            r'<node[^>]*content-desc="([a-z])"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            cd = m.group(1)
            if cd.isalpha() and cd.islower():
                x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                letter_btns.append((x1+x2)//2, (y1+y2)//2, cd))'''

new = '''        # 2. 填空题（界面自带字母）：字母按钮是 LinearLayout clickable（193x137）
        letter_btns = []
        for m in re.finditer(
            r'<node[^>]*class="android\\.widget\\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2-x1; h = y2-y1
            if 500 < y1 < 1700 and 150 < w < 250 and 100 < h < 180:
                letter_btns.append(((x1+x2)//2, (y1+y2)//2))
        letter_btns.sort(key=lambda t: (t[1], t[0]))'''

if old in content:
    content = content.replace(old, new)
    with open('modules/知识过关.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')
