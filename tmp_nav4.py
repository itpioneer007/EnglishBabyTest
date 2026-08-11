# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
# 点掉规则弹窗
if d(text='好的，我知道啦~').exists(timeout=1):
    d(text='好的，我知道啦~').click(); time.sleep(1.5)
xml = d.dump_hierarchy()
print('=== 弹窗后页面 ===')
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
    t = m.group(1)
    if t.strip() and len(t) < 16:
        print('  %r b=[%s,%s][%s,%s]' % (t, m.group(2), m.group(3), m.group(4), m.group(5)))
