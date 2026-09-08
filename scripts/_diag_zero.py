import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import S, S_swipe, settle_ads, back_to_home, scroll_and_find

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
APP = "com.dinoenglish.yyb"
d = u2.connect(SERIAL)
print(">> 已连接", SERIAL)

target_v, target_g = "湘少版（2024审定）", "五年级上册"
print(f">> 切到 {target_v} {target_g}")
switch_version_grade(d, target_v, target_g)
time.sleep(1.5)
settle_ads(d, wait_total=8)

print(">> 主页所有可见文字（含版/专项/开发等关键词）：")
xml = d.dump_hierarchy() or ""
for m in re.findall(r'text="([^"]{1,40})"', xml):
    if any(k in m for k in ("版", "专项", "开发", "期待", "练习", "课本", "年级", "测评", "听")):
        print("   T:", m)

print(">> 滚到听力专项入口…")
found = scroll_and_find(d, "听力专项")
print("   scroll_and_find(听力专项) =", found)
if found:
    # 点进去看页面
    for _ in range(3):
        if d(text="听力专项").exists(timeout=1):
            d(text="听力专项").click(); break
        elif d(textContains="听力专项").exists(timeout=1):
            d(textContains="听力专项").click(); break
        time.sleep(0.5)
    time.sleep(2)
    settle_ads(d, wait_total=5)
    x2 = d.dump_hierarchy() or ""
    print(">> 进入后页面关键词：")
    for m in re.findall(r'text="([^"]{1,40})"', x2):
        if any(k in m for k in ("开发", "期待", "去练习", "去答题", "练习", "测试", "听力", "敬请")):
            print("   T:", m)
    has_dev = ("正在开发" in x2) or ("敬请期待" in x2)
    has_prac = ("去练习" in x2) or ('text="去练习"' in x2)
    print("   正在开发/敬请期待 =", has_dev, " | 去练习按钮 =", has_prac)
    back_to_home(d)
print(">> DONE")
