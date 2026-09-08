# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
# 当前在听力专项页，点测试 tab
if d(text='测试').exists(timeout=1):
    d(text='测试').click(); time.sleep(1.5)
print('=== 测试 tab 页 ===')
xml = d.dump_hierarchy()
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]', xml):
    t = m.group(1)
    if t.strip() and len(t) < 14:
        print('  %r y=%s' % (t, m.group(3)))
