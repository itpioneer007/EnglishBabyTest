import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.tools import back_to_home, settle_ads

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
d.press("home")
try:
    d.app_stop("com.dinoenglish.yyb")
    d.app_start("com.dinoenglish.yyb")
except Exception:
    pass
time.sleep(5)
settle_ads(d, wait_total=8)

xml = d.dump_hierarchy() or ""
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", "diag")
os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, "ad_dump2.xml")
with open(path, "w", encoding="utf-8") as f:
    f.write(xml)
print(">> XML 已写入", path)
print(">> 当前 activity:", d.app_current().get("activity"))

print(">> 含广告关键词的节点：")
for line in xml.split(">"):
    t = re.search(r'text="([^"]*)"', line)
    if t and any(k in t.group(1) for k in ("老师伴学", "打卡服务", "点击参与", "伴学服务")):
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', line)
        r = re.search(r'resource-id="([^"]*)"', line)
        c = re.search(r'class="([^"]*)"', line)
        cl = re.search(r'clickable="([^"]*)"', line)
        print(f"  text={t.group(1):20s} bounds={b.group(0) if b else 'none':30s} rid={r.group(1) if r else '':20s} cls={c.group(1) if c else '':20s} clickable={cl.group(1) if cl else ''}")

print(">> 小尺寸 clickable 节点（x>750, y>1300）：")
for line in xml.split(">"):
    if 'clickable="true"' in line and 'bounds=' in line:
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', line)
        if not b: continue
        x1,y1,x2,y2 = map(int, b.groups())
        w,h = x2-x1, y2-y1
        if w<130 and h<130 and x1>750 and y1>1300:
            t = re.search(r'text="([^"]*)"', line)
            d2 = re.search(r'content-desc="([^"]*)"', line)
            rid = re.search(r'resource-id="([^"]*)"', line)
            c = re.search(r'class="([^"]*)"', line)
            print(f"  {w}x{h} @({x1},{y1}) text={t.group(1) if t else ''} desc={d2.group(1) if d2 else ''} rid={rid.group(1) if rid else ''} cls={c.group(1) if c else ''}")
print(">> DONE")
