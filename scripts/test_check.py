# -*- coding: utf-8 -*-
import sys, re, uiautomator2 as u2
sys.path.insert(0, '.')
d = u2.connect('SKSCIF4T7PFMQS5X')
xml = d.dump_hierarchy()
for m in re.finditer(r'text="([^"]*)"[^>]*resource-id="[^"]*switch_textbook_tv"', xml):
    t = m.group(1)
    print('匹配到文本:', repr(t))
    print("'湘少版' in t:", '湘少版' in t)
    print("'五年级上册' in t:", '五年级上册' in t)
    print("'版' in t:", '版' in t)
    print("'上册' in t:", '上册' in t)
