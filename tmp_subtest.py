# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
from common.tools import S_swipe

# 当前在听力专项列表（练习tab）。点第一个去练习
if d(text='去练习').exists(timeout=1):
    d(text='去练习').click(); time.sleep(2)

def texts():
    return [(e.text or '') for e in (d.xpath('//*[@text!=""]').all() or [])]

print('进入后页面文字:', [t for t in texts() if len(t)<12][:8])

# 模拟：右滑回基础巩固（最多4次）
for i in range(4):
    ts = texts()
    if any('基础巩固' in t for t in ts):
        print(f'右滑{i}次后到基础巩固: 有基础巩固文字')
        break
    d.swipe_ext('right', scale=0.5); time.sleep(0.8)
else:
    print('右滑4次未见基础巩固')

ts = texts()
print('当前子模块相关:', [t for t in ts if 'Level' in t or '基础' in t or '综合' in t or '难点' in t][:5])
