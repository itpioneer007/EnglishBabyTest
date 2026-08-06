"""自动替换硬编码坐标 → S(d, x, y) 动态换算"""
import re, os

# 要处理的文件
files = [
    'engine.py',
    'modules/听力专项.py',
    'modules/口语训练.py',
    'modules/单元自检.py',
    'modules/知识过关.py',
    'modules/巧记单词.py',
    'modules/语音评测.py',
]

BASE_W, BASE_H = 1080, 2400

def fix_file(path):
    with open(path, encoding='utf-8') as f:
        content = f.read()
    orig = content
    
    # 1. d.click(数字, 数字) → d.click(*S(d, 数字, 数字))
    content = re.sub(
        r'd\.click\(\s*(\d{2,4})\s*,\s*(\d{2,4})\s*\)',
        lambda m: f'd.click(*S(d, {m.group(1)}, {m.group(2)}))',
        content
    )
    
    # 2. d.swipe(数字,数字,数字,数字[,时长]) → S_swipe(d, ...)
    content = re.sub(
        r'd\.swipe\(\s*(\d{2,4})\s*,\s*(\d{2,4})\s*,\s*(\d{2,4})\s*,\s*(\d{2,4})(?:\s*,\s*([\d.]+))?\s*\)',
        lambda m: f'S_swipe(d, {m.group(1)}, {m.group(2)}, {m.group(3)}, {m.group(4)}, {m.group(5) or 0.4})',
        content
    )
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # 统计改动
    orig_clicks = len(re.findall(r'd\.click\(\s*\d{2,4}\s*,\s*\d{2,4}\s*\)', orig))
    new_clicks = len(re.findall(r'd\.click\(\*S\(d,', content))
    orig_swipes = len(re.findall(r'd\.swipe\(\s*\d', orig))
    new_swipes = len(re.findall(r'S_swipe\(d,', content))
    print(f"  {path}: click {orig_clicks}→{new_clicks}, swipe {orig_swipes}→{new_swipes}")

# 主处理
print("=== 替换 d.click / d.swipe ===")
for f in files:
    fix_file(f)

# 3. 坐标常量（如 QIAOJI_CARD = (540, 1192) → QIAOJI_CARD = S(d, 540, 1192)）
print("\n=== 替换坐标常量 ===")
for f in files:
    with open(f, encoding='utf-8') as fh:
        content = fh.read()
    orig = content
    content = re.sub(
        r'([A-Z_]+)\s*=\s*\((\d{2,4})\s*,\s*(\d{2,4})\)',
        lambda m: f'{m.group(1)} = S(d, {m.group(2)}, {m.group(3)})',
        content
    )
    if content != orig:
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(content)
        print(f"  {f}: 常量已替换")

# 4. 检查 import
print("\n=== 检查 import 兼容性 ===")
for f in files:
    with open(f, encoding='utf-8') as fh:
        content = fh.read()
    if 'S(' in content and 'S_swipe' in content:
        if 'from common.tools import' not in content:
            print(f"  ⚠ {f}: 需要添加 S 导入!")
        else:
            print(f"  OK {f}: 已导入")
    elif 'S(' in content:
        if 'from common.tools import' not in content:
            print(f"  ⚠ {f}: 需要添加 S 导入!")
        else:
            print(f"  OK {f}: 已导入")

print("\n=== 完成 ===")
