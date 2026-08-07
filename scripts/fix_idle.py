# -*- coding: utf-8 -*-
with open('modules/巧记单词.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 在 3 处 "q += 1" 后的下一行（缩进相同）加 idle = 0
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    new_lines.append(line)
    if line.strip() == 'q += 1':
        # 找到下一个同级或更深缩进的代码行，插入 idle = 0
        indent = len(line) - len(line.lstrip())
        # 向后找到第一个非空且缩进 >= indent 的行
        j = i + 1
        while j < len(lines) and lines[j].strip() == '':
            j += 1
        if j < len(lines):
            nxt_indent = len(lines[j]) - len(lines[j].lstrip())
            if nxt_indent >= indent:
                # 在 q += 1 后插入 idle = 0（用 q += 1 的缩进）
                new_lines.append(' ' * indent + 'idle = 0\n')
    i += 1

with open('modules/巧记单词.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('done')
