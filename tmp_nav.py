# -*- coding: utf-8 -*-
import uiautomator2 as u2, re, time, sys
sys.path.insert(0, 'scripts')
d = u2.connect('SKSCIF4T7PFMQS5X')
from common.tools import dismiss_global_popups, close_ad, S_swipe

# 回主页
for _ in range(5):
    xml = d.dump_hierarchy()
    if 'switch_textbook_tv' in xml:
        break
    d.press('back'); time.sleep(0.6)

# 找听力专项入口
for _ in range(6):
    if d(text='听力专项').exists(timeout=1):
        break
    S_swipe(d, 540, 1800, 540, 600, 0.4); time.sleep(0.4)
if d(text='听力专项').exists(timeout=1):
    d(text='听力专项').click(); time.sleep(1.5)
print('=== 听力专项页 ===')
xml = d.dump_hierarchy()
for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]', xml):
    t = m.group(1)
    if t.strip() and len(t) < 12:
        print('  %r y=%s' % (t, m.group(3)))
