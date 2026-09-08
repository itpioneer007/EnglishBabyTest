with open('modules/知识过关.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 _answer_loop 整个函数并替换
import re
start = content.find('def _answer_loop(d, max_q=120):')
# 找下一个 def 开头
end = content.find('\ndef _enter_unit', start)
if start == -1 or end == -1:
    print('NOT FOUND')
else:
    new_func = '''def _answer_loop(d, max_q=120):
    """知识过关答题循环：所有题型统一处理

    题型检测与处理：
    - 录音题：点原音 → 点录音 → 点结束
    - 填空题-系统键盘：FastInputIME 注入
    - 填空题-界面字母：LinearLayout clickable（193x137）按方框顺序点
    - 选择题：点 A → 检测 → 下一题
    """
    q = 0
    for _ in range(max_q):
        # 中途弹窗
        for kw in ('继续答题（0S）', '继续答题', '确定', '好的'):
            if d(text=kw).exists(timeout=0.1):
                d(text=kw).click()
                time.sleep(0.6)
                break
        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.15):
            d(text="查看报告").click()
            print(f"    ✅ 查看报告！知识关过完成")
            time.sleep(0.8)
            return q
        # 下一题按钮
        if d(text="下一题").exists(timeout=0.15):
            d(text="下一题").click()
            time.sleep(0.6)
            continue

        # 题型识别（页面文字）
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "

        # 1. 录音题
        if d(text="点原音").exists(timeout=0.1) or d(text="点读原音").exists(timeout=0.1):
            print(f"    🎤 录音题")
            if d(text="点原音").exists(timeout=0.1):
                d(text="点原音").click()
            elif d(text="点读原音").exists(timeout=0.1):
                d(text="点读原音").click()
            time.sleep(0.8)
            if d(text="点击录音").exists(timeout=0.8):
                d(text="点击录音").click()
                time.sleep(0.6)
            if d(text="点击结束").exists(timeout=0.8):
                d(text="点击结束").click()
                time.sleep(0.8)
            q += 1
            continue

        # 找 EditText（填空方框）
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
            if 500 < y1 < 1700 and 150 < w < 250 and 100 < h < 180:
                letter_btns.append(((x1+x2)//2, (y1+y2)//2))
        letter_btns.sort(key=lambda t: (t[1], t[0]))

        if letter_btns and edit_inputs:
            # 填空题-界面字母：每个方框点一个字母
            print(f"    🅰 填空-界面字母 ({len(edit_inputs)}空)")
            for idx, inp in enumerate(edit_inputs):
                if idx < len(letter_btns):
                    bx, by = letter_btns[idx]
                    d.click(bx, by)
                    time.sleep(0.2)
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
                d.click(cx, cy)
                time.sleep(0.4)
                try:
                    d.send_keys("a")
                except Exception:
                    d.shell("input text a")
                time.sleep(0.3)
            d.press("back")
            time.sleep(0.4)
            q += 1
            continue

        # 2. 选择题（A 选项 + 检测按钮）
        if d(text="A").exists(timeout=0.15):
            d(text="A").click()
            time.sleep(0.3)
            if d(text="检测").exists(timeout=1.5):
                d(text="检测").click()
                print(f"    ✓ 选择A → 检测")
                time.sleep(0.6)
            q += 1
            continue

        # 未知
        d.screenshot(f"unknown_kp_{q}.png")
        print(f"    ⚠ 未知: {texts[:5]}")
        time.sleep(0.8)
    return q


'''
    new_content = content[:start] + new_func + content[end:]
    with open('modules/知识过关.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('OK, 函数替换')
