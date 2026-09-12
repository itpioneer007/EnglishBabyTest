# -*- coding: utf-8 -*-
"""真机验证：版本/年级自动切换 + 两个'湘少版'能否精确区分
直接复用项目 scripts/common/setup.py 的 switch_version_grade。
"""
import sys, os, time

PROJECT = r"C:\Users\yangj\Desktop\EnglishBabyTest-yangjiangliu"
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import uiautomator2 as u2
u2.HTTP_TIMEOUT = 15
u2.WAIT_FOR_DEVICE_TIMEOUT = 10

from common.setup import switch_version_grade, _current_texts

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"

def show(tag):
    v, g = _current_texts(d)
    print(f"  [{tag}] 版本='{v}'  年级='{g}'")
    return (v or ""), (g or "")

def norm(s):
    return (s or "").replace("（", "(").replace("）", ")").replace(" ", "")

print("连接设备:", SERIAL)
d = u2.connect(SERIAL)
print("已连接, serial=", d.info.get("serial"))

# 确保英语宝在前台主页
try:
    d.app_start("com.dinoenglish.yyb")
    time.sleep(3)
except Exception as e:
    print("app_start 异常(忽略):", e)

print("\n========== 初始状态 ==========")
show("初始")

# ---------- 测试1：精确选中 湘少版(2024审定) ----------
print("\n========== 测试1: 切到 湘少版(2024审定) / 一年级下册 ==========")
t0 = time.time()
ok1 = switch_version_grade(d, "湘少版(2024审定)", "一年级下册")
v1, g1 = show("测试1后")
pass1 = ok1 and ("2024审定" in norm(v1)) and g1 == "一年级下册"
print(f"  返回值 ok={ok1}  耗时 {int(time.time()-t0)}s  => {'PASS ✅' if pass1 else 'FAIL ❌'}")

# ---------- 测试2：精确选中 普通 湘少版（验证不误选成2024版）----------
print("\n========== 测试2: 切到 湘少版 / 五年级上册（应区别于 '湘少版(2024审定)'）==========")
t0 = time.time()
ok2 = switch_version_grade(d, "湘少版", "五年级上册")
v2, g2 = show("测试2后")
pass2 = ok2 and ("2024审定" not in norm(v2)) and "湘少版" in norm(v2) and g2 == "五年级上册"
print(f"  返回值 ok={ok2}  耗时 {int(time.time()-t0)}s  => {'PASS ✅' if pass2 else 'FAIL ❌'}")

# ---------- 收尾：切回用户之前的 湘少版(2024审定) / 一年级下册 ----------
print("\n========== 收尾: 切回 湘少版(2024审定) / 一年级下册 ==========")
ok3 = switch_version_grade(d, "湘少版(2024审定)", "一年级下册")
show("收尾后")

print("\n========== 汇总 ==========")
print(f"  测试1 湘少版(2024审定)+一年级下册 : {'PASS' if pass1 else 'FAIL'}")
print(f"  测试2 湘少版(普通)+五年级上册     : {'PASS' if pass2 else 'FAIL'}")
print("  结论: 两个'湘少版'可精确区分" if (pass1 and pass2) else "  结论: 仍存在混淆/失败")
