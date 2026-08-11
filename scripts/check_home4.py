# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time
d = u2.connect('SKSCIF4T7PFMQS5X')
# 点第一行第2张卡片 (540,441) 看是什么
for name, pos in [('第2张', (540, 441)), ('第3张', (876, 441))]:
    d.click(*pos); time.sleep(2)
    xml = d.dump_hierarchy()
    items = []
    for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]', xml):
        t = m.group(1)
        if t.strip() and len(t) < 15:
            items.append(t)
    print(f'--- 点{name}卡片后: {items[:6]} ---')
    d.press('back'); time.sleep(1.5)
