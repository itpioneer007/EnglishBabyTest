import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import settle_ads

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
switch_version_grade(d, "湘少版（2024审定）", "五年级上册")
time.sleep(1.5)
xml = d.dump_hierarchy() or ""
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", "diag")
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "ad_dump.xml"), "w", encoding="utf-8") as f:
    f.write(xml)
print(">> XML 已写入 scripts/screenshots/diag/ad_dump.xml")

# 打印所有包含广告关键词的节点及其子节点简要信息
print(">> 含广告关键词的节点：")
for m in re.finditer(r'<node[^>]*text="([^"]*)"[^>]*>', xml):
    t = m.group(1)
    if any(k in t for k in ("老师伴学", "打卡服务", "点击参与", "伴学服务")):
        print("\nNODE text=", t)
        print("  raw=", m.group(0)[:500])

# 找小尺寸 clickable/ImageView 节点（可能是 X）
print(">> 小尺寸 clickable 节点（x>800, y>1400）：")
for line in xml.split(">"):
    if 'clickable="true"' in line and 'bounds=' in line:
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', line)
        if not b: continue
        x1,y1,x2,y2 = map(int, b.groups())
        w,h = x2-x1, y2-y1
        if w<120 and h<120 and x1>800 and y1>1400:
            t = re.search(r'text="([^"]*)"', line)
            d2 = re.search(r'content-desc="([^"]*)"', line)
            rid = re.search(r'resource-id="([^"]*)"', line)
            print(f"  {w}x{h} @({x1},{y1}) text={t.group(1) if t else ''} desc={d2.group(1) if d2 else ''} rid={rid.group(1) if rid else ''}")
print(">> DONE")
