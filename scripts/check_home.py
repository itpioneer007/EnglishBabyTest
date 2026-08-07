# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time
d = u2.connect('SKSCIF4T7PFMQS5X')
# 回主页顶部
for _ in range(3):
    d.swipe(540, 600, 540, 1800, 0.3); time.sleep(0.4)
xml = d.dump_hierarchy()
items = []
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
    t = m.group(1)
    if t.strip():
        items.append((int(m.group(3)), t))
items.sort()
for y, t in items:
    print(f'y={y:5d} | {t}')
