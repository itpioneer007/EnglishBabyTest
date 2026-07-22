"""
智能巡检脚本 - 处理所有题型
- 听力题: 点播放→选项→检查→下一题
- 文字选择题 (A/B/C/D/T/F): 点标签旁
- 图片选择题: 点标签 A/B 旁
- 拼写题 (键盘): 点7次a+确定
- 字母选择题: 点选项区
- 排序题 (单词/句子): 单词→编号 1/2/3...
- 检查/下一题: 连续点 (540, 2174) 两次
"""
import sys, time, subprocess as sp, re, json
from pathlib import Path
sys.path.insert(0, 'src')
from adb_controller import ADBController
from config_loader import load_config

config = load_config()
adb = ADBController(serial=config.device.serial, screenshot_dir='outputs/screenshots')
SERIAL = config.device.serial
OUT = Path('outputs/questions')

def dump():
    r = sp.run(['adb','-s',SERIAL,'shell','uiautomator','dump','/sdcard/d.xml'], capture_output=True, text=True, timeout=15)
    return sp.run(['adb','-s',SERIAL,'shell','cat','/sdcard/d.xml'], capture_output=True, text=True, timeout=3).stdout

def find_progress(xml):
    for m in re.finditer(r'text="(\d+)/(\d+)"', xml):
        return int(m.group(1)), int(m.group(2))
    return None, None

def find_text(xml, pattern, y_min=0, y_max=9999, clickable_only=False):
    """找包含指定 pattern 的文本元素"""
    results = []
    for m in re.finditer(r'text="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        t = m.group(1)
        x1,y1,x2,y2 = int(m.group(2)),int(m.group(3)),int(m.group(4)),int(m.group(5))
        if pattern in t and y_min < (y1+y2)//2 < y_max:
            results.append((t, (x1+x2)//2, (y1+y2)//2, x1, y1, x2, y2))
    return results

def find_clickable(xml, y_min=0, y_max=9999, w_min=0, w_max=9999):
    results = []
    for m in re.finditer(r'clickable="true"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        x1,y1,x2,y2 = int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4))
        if y_min < y1 < y_max and w_min < (x2-x1) < w_max:
            results.append((x1+x2)//2, y1+(y2-y1)//4, x1, y1, x2, y2)
    return results

def has_keyboard(xml):
    """判断是否有拼写键盘（字母元素y>1500）"""
    for m in re.finditer(r'text="([a-zA-Z])"[^>]*?bounds="\[(\d+),(\d+)\]', xml):
        y1 = int(m.group(3))
        if y1 > 1500:
            return True
    return False

def click_check_next():
    """点检查按钮（底部）两次"""
    adb.tap(540, 2174)
    time.sleep(1.2)
    adb.tap(540, 2174)
    time.sleep(1.5)

print('🔥 智能巡检 - 处理所有题型')
print('=' * 50)

# 报告
report = []

# 从当前 Q18 开始
last = 17
for loop in range(50):
    xml = dump()
    sp.run(['adb','-s',SERIAL,'shell','rm','/sdcard/d.xml'], capture_output=True)

    cur, total = find_progress(xml)
    if not cur:
        # 弹窗: 继续答题
        if '继续答题' in xml:
            adb.tap(540, 1336)
            time.sleep(3)
            continue
        print(f'⏹ 结束 (第{loop}次循环)')
        break

    if cur == last:
        time.sleep(0.5)
        continue
    last = cur

    # 截图
    adb.screenshot(f'q{cur:02d}.png')

    # 题型识别
    q_type = '?'
    if has_keyboard(xml):
        q_type = '拼写题'
    elif find_text(xml, '听', 600, 800):
        q_type = '听力题'
    elif find_text(xml, '排序', 200, 600) or find_text(xml, '字母表', 200, 600):
        q_type = '排序题'
    elif find_text(xml, '选择正确的', 200, 600) and not find_text(xml, 'A', 700, 1800, clickable_only=False):
        q_type = '字母选择题'

    # 处理不同题型
    if has_keyboard(xml):
        # 拼写题: 点7个a + 确定
        for _ in range(7):
            adb.tap(106, 1947)
            time.sleep(0.2)
        adb.tap(890, 2128)  # 确定
        time.sleep(0.5)
    else:
        # 找 A/B/C/D/T/F 标签
        found = False
        for opt in ['A', 'B', 'C', 'D', 'T', 'F']:
            for m in re.finditer(rf'text="{opt}"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
                x1,y1,x2,y2 = int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4))
                if 700 < y1 < 1800 and (x2-x1) < 200:  # 标签（小元素）
                    adb.tap((x1+x2)//2 + 30, (y1+y2)//2 + 20)
                    found = True
                    break
            if found:
                q_type = q_type if q_type != '?' else '标签选择题'
                break

        if not found:
            # 排序题: 找选项单词+编号
            # 先看是否有编号 1/2/3/4/5 在 y=1300-1450
            numbers = []
            for n in ['1', '2', '3', '4', '5']:
                for m in re.finditer(rf'text="{n}"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
                    x1,y1 = int(m.group(1)),int(m.group(2))
                    if 1300 < y1 < 1500:
                        numbers.append((n, (x1+int(m.group(3)))//2, (y1+int(m.group(4)))//2))
                        break

            # 找单词/句子
            words = find_text(xml, 'a', 300, 1000) + find_text(xml, 'b', 300, 1000) + find_text(xml, 'c', 300, 1000) + \
                    find_text(xml, 'd', 300, 1000) + find_text(xml, 'e', 300, 1000) + find_text(xml, 'f', 300, 1000) + \
                    find_text(xml, 'g', 300, 1000) + find_text(xml, 'h', 300, 1000) + find_text(xml, 'i', 300, 1000) + \
                    find_text(xml, 'w', 300, 1000) + find_text(xml, 't', 300, 1000) + find_text(xml, 'm', 300, 1000) + \
                    find_text(xml, 'M', 300, 1000) + find_text(xml, 'H', 300, 1000)

            if numbers and words:
                q_type = '排序题'
                # 点每个单词 + 对应编号
                for i, (word_info, num_info) in enumerate(zip(words, numbers)):
                    word_text, wx, wy = word_info[0], word_info[1], word_info[2]
                    num_text, nx, ny = num_info[0], num_info[1], num_info[2]
                    # 单词标题（如 "cat", "He feeds..."）取整行，点的位置在 240
                    adb.tap(240, wy)
                    time.sleep(0.3)
                    # 对应编号
                    adb.tap(nx, ny)
                    time.sleep(0.3)
            else:
                # 兜底: 点选项区任何 clickable
                clickables = find_clickable(xml, 700, 1700, 50, 500)
                if clickables:
                    cx, cy = clickables[0][0], clickables[0][1]
                    adb.tap(cx, cy)
                    q_type = '通用题'

    time.sleep(0.5)
    click_check_next()

    report.append({'idx': cur, 'progress': f'{cur}/{total}', 'type': q_type})
    print(f'  Q{cur:2d}/{total} [{q_type}]')

    if cur >= total:
        print(f'\n✅ 全部{total}题完成!')
        break

# 保存报告
with open(OUT/'report.json', 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print()
print('=' * 50)
print(f'✅ 完成 {len(report)} 题 | 报告: {OUT}/report.json')
