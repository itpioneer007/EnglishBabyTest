# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time
d = u2.connect('SKSCIF4T7PFMQS5X')
# 点教材精学看是否展开卡片
if d(text='教材精学').exists(timeout=1):
    d(text='教材精学').click(); time.sleep(1.5)
xml = d.dump_hierarchy()
# 找 clickable 大卡片（ImageButton/LinearLayout 无文字）
print('--- clickable 大卡片 ---')
for m in re.finditer(r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
    x1,y1,x2,y2 = map(int, m.groups())
    w, h = x2-x1, y2-y1
    if w > 150 and h > 100:
        cls = re.search(r'class="([^"]*)"', m.group(0))
        print(f'  [{x1},{y1}][{x2},{y2}] w={w} h={h} cls={(cls.group(1) if cls else "").split(".")[-1]}')
