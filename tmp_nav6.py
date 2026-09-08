# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
# 点第一个去练习
if d(text='去练习').exists(timeout=1):
    d(text='去练习').click(); time.sleep(2)
xml = d.dump_hierarchy()
print('=== 点去练习后 ===')
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
    t = m.group(1)
    if t.strip() and len(t) < 16:
        print('  %r b=[%s,%s][%s,%s]' % (t, m.group(2), m.group(3), m.group(4), m.group(5)))
