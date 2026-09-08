# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
# 当前在测试tab的单元评价页，back 回测试列表，再点练习tab
d.press('back'); time.sleep(0.8)
if d(text='练习').exists(timeout=2):
    d(text='练习').click(); time.sleep(1.5)
print('=== 练习tab ===')
xml = d.dump_hierarchy()
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]', xml):
    t = m.group(1)
    if t.strip() and len(t) < 14:
        print('  %r y=%s' % (t, m.group(3)))
