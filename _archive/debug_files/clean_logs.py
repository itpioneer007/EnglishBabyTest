"""清理重复 import 和重复 step_log"""
import os, re

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modules'))

for fname in ['听力专项.py', '单元自检.py', '口语训练.py']:
    with open(fname, 'r', encoding='utf-8') as f:
        content = f.read()

    # 删除重复的 import
    seen_logger = False
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        if 'from common.logger import step_log' in line:
            if seen_logger:
                continue  # skip duplicate
            seen_logger = True
        new_lines.append(line)
    content = '\n'.join(new_lines)
    
    # 删除相邻重复的 step_log 行
    lines = content.split('\n')
    new_lines = []
    for i, line in enumerate(lines):
        if 'step_log(' in line and i > 0 and 'step_log(' in lines[i-1]:
            continue  # skip adjacent duplicate
        new_lines.append(line)
    content = '\n'.join(new_lines)

    with open(fname, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'{fname} cleaned')

print('Done')
