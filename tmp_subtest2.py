# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')

def texts():
    return [(e.text or '') for e in (d.xpath('//*[@text!=""]').all() or [])]

def cur_sub():
    for t in texts():
        if 'Level' in t or '基础' in t or '综合' in t or '难点' in t:
            return t
    return '?'

# 当前应在基础巩固（右滑后）
print('当前位置:', cur_sub())

# 模拟 engine 逻辑：i=1（综合进阶）→ 右滑回最左 + 左滑1次
def goto_sub(idx):
    # 右滑回最左
    for _ in range(4):
        ts = texts()
        if any('基础巩固' in t for t in ts):
            break
        d.swipe_ext('right', scale=0.5); time.sleep(0.7)
    # 左滑 idx 次
    for _ in range(idx):
        d.swipe_ext('left', scale=0.5); time.sleep(0.7)
    return cur_sub()

# 综合进阶 (i=1)
print('切到综合进阶 →', goto_sub(1))
# 难点突破 (i=2)
print('切到难点突破 →', goto_sub(2))
