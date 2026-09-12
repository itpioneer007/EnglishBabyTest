# -*- coding: utf-8 -*-
"""真机验证：switch_version_grade 修复后，切版本+切年级是否正常。
重点验证之前失败的『切普通湘少版』以及『六年级上册』。
"""
import sys, time
sys.path.insert(0, r"C:\Users\yangj\Desktop\EnglishBabyTest-yangjiangliu\scripts")
import uiautomator2 as u2
u2.HTTP_TIMEOUT = 15
from common.setup import switch_version_grade, _current_texts, _is_home, _back_home

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
d.unlock(); time.sleep(1)

def show_cur(tag):
    if not _is_home(d):
        _back_home(d); time.sleep(1.2)
    v, g = _current_texts(d)
    print(f"  [当前] {tag}: 版本={v!r} 年级={g!r}")
    return v, g

print("=== 测试1：切到 普通『湘少版』 + 三年级上册（必走切版本分支）===")
show_cur("起始")
ok1 = switch_version_grade(d, "湘少版", "三年级上册")
v1, g1 = show_cur("测试1后")
print(f"  结果: {'PASS' if ok1 else 'FAIL'}  期望 湘少版 / 三年级上册  | 实际 {v1} / {g1}")
time.sleep(1.5)

print("\n=== 测试2：切到 『湘少版（2024审定）』 + 六年级上册（验证2024审定+六年级）===")
ok2 = switch_version_grade(d, "湘少版（2024审定）", "六年级上册")
v2, g2 = show_cur("测试2后")
print(f"  结果: {'PASS' if ok2 else 'FAIL'}  期望 湘少版（2024审定） / 六年级上册  | 实际 {v2} / {g2}")
time.sleep(1.5)

print("\n=== 测试3：切回 『湘少版（2024审定）』 + 一年级下册（验证已匹配时跳过）===")
ok3 = switch_version_grade(d, "湘少版（2024审定）", "一年级下册")
v3, g3 = show_cur("测试3后")
print(f"  结果: {'PASS' if ok3 else 'FAIL'}  期望 湘少版（2024审定） / 一年级下册  | 实际 {v3} / {g3}")

print("\n[真机验证完成]")
