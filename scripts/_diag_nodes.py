import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import settle_ads

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
switch_version_grade(d, "湘少版（2024审定）", "五年级上册")
time.sleep(1.5); settle_ads(d, wait_total=6)

# 找到并点击听力专项
xml = d.dump_hierarchy() or ""
m = re.search(r'text="听力专项"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
if m:
    cx = (int(m.group(1)) + int(m.group(3))) // 2
    cy = (int(m.group(2)) + int(m.group(4))) // 2
    print(f">> 点听力专项 @({cx},{cy})")
    d.click(cx, cy)
else:
    d(text="听力专项").click()
time.sleep(3)
settle_ads(d, wait_total=3)

x2 = d.dump_hierarchy() or ""
print(">> activity=", d.app_current().get("activity"))
print(">> 全部文字节点：")
texts = []
for t in re.findall(r'text="([^"]*)"', x2):
    t = t.strip()
    if t and t not in texts:
        texts.append(t)
for t in texts:
    print("  T:", t)
print(">> resource-id 含 close/iv 的节点：")
for line in x2.split(">"):
    if any(k in line for k in ("iv_close", "close_iv", "ad_close", "fl_ad_container")):
        print("  ", line[:300])
