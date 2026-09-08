# -*- coding: utf-8 -*-
import os
# 巧记单词
p1 = 'modules/巧记单词.py'
with open(p1, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('QIAOJI_CARD = (540, 1192)', 'QIAOJI_CARD = (540, 441)  # 新版主页教材精学第一行第2张卡片')
with open(p1, 'w', encoding='utf-8') as f:
    f.write(c)
print('巧记单词 OK')

# 语音评测
p2 = 'modules/语音评测.py'
with open(p2, 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('VOICE_CARD = (877, 1192)', 'VOICE_CARD = (876, 441)  # 新版主页教材精学第一行第3张卡片')
with open(p2, 'w', encoding='utf-8') as f:
    f.write(c)
print('语音评测 OK')
