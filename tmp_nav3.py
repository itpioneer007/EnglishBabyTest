# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
# 当前在测试tab，点第一个去答题
if d(text='去答题').exists(timeout=1):
    d(text='去答题').click(); time.sleep(2)
xml = d.dump_hierarchy()
print('=== 点去答题后 ===')
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
    t = m.group(1)
    if t.strip() and len(t) < 14:
        print('  %r b=[%s,%s][%s,%s]' % (t, m.group(2), m.group(3), m.group(4), m.group(5)))
