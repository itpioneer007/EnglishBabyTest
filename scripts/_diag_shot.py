import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import S, S_swipe, settle_ads, back_to_home, scroll_and_find

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", "diag")
os.makedirs(OUT, exist_ok=True)

switch_version_grade(d, "湘少版（2024审定）", "五年级上册")
time.sleep(1.5); settle_ads(d, wait_total=6)

# 滚到听力专项并截图主页
scroll_and_find(d, "听力专项")
time.sleep(1)
d.screenshot(os.path.join(OUT, "A_home.png"))
print(">> 截主页 A_home.png ; activity=", d.app_current().get("activity"))

# 用 bounds 兜底点击听力专项（取之前 scroll_and_find 让它在屏内）
xml = d.dump_hierarchy() or ""
m = re.search(r'text="听力专项"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
if m:
    cx = (int(m.group(1)) + int(m.group(3))) // 2
    cy = (int(m.group(2)) + int(m.group(4))) // 2
    print(f">> 点听力专项 @({cx},{cy})")
    d.click(cx, cy)
else:
    print(">> 未取到听力专项 bounds，用 text 点")
    d(text="听力专项").click()
time.sleep(4)
settle_ads(d, wait_total=3)
d.screenshot(os.path.join(OUT, "B_after_click.png"))
print(">> 截点击后 B_after_click.png ; activity=", d.app_current().get("activity"))
x2 = d.dump_hierarchy() or ""
print(">> 点击后 hierarchy 含 去练习:", '去练习' in x2, "| 去答题:", '去答题' in x2,
      "| 听力:", '听力' in x2, "| 开发:", '开发' in x2)
print(">> 点击后 文字节点数:", len(re.findall(r'text="', x2)))
print(">> DONE")
