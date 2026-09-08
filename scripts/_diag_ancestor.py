import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import settle_ads

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
switch_version_grade(d, "湘少版（2024审定）", "五年级上册")
time.sleep(1.5); settle_ads(d, wait_total=6)

def check_entered():
    x = d.dump_hierarchy() or ""
    return any(k in x for k in ("去练习", "去答题", "练习记录", "重新答题", "开始答题"))

def dump_nodes_around(text):
    xml = d.dump_hierarchy() or ""
    # 找到该文字节点的起始位置，往上 5 层打印
    idx = xml.find(f'text="{text}"')
    if idx == -1:
        print(f"未找到 {text}")
        return
    # 截取往前 1000 字符，找 <node 开头
    snippet = xml[max(0, idx-1500):idx]
    nodes = []
    for m in re.finditer(r'<node[^>]*>', snippet):
        tag = m.group(0)
        t = re.search(r'text="([^"]*)"', tag)
        b = re.search(r'bounds="([^"]*)"', tag)
        c = re.search(r'clickable="([^"]*)"', tag)
        cls = re.search(r'class="([^"]*)"', tag)
        nodes.append((tag[:120], t.group(1) if t else "", b.group(1) if b else "", c.group(1) if c else "", cls.group(1) if cls else ""))
    print(f">> {text} 周围节点（从内到外）：")
    for tag, t, b, c, cls in nodes[-6:]:
        print(f"  clickable={c} text={t:12s} bounds={b:30s} cls={cls}")

dump_nodes_around("听力专项")

# 尝试1：点文字父容器（clickable ancestor）
try:
    anc = d.xpath('//*[@text="听力专项"]/ancestor::*[@clickable="true"][1]')
    if anc.exists:
        e = anc.get()
        b = e.bounds
        cx, cy = (b[0]+b[2])//2, (b[1]+b[3])//2
        print(f">> 尝试点 clickable ancestor @({cx},{cy}) bounds={b}")
        d.click(cx, cy)
        time.sleep(2.5)
        print(">> 是否进入:", check_entered(), "activity=", d.app_current().get("activity"))
except Exception as e:
    print(">> ancestor 点击异常:", e)

# 尝试2：点文字上方（图标区域）
xml = d.dump_hierarchy() or ""
m = re.search(r'text="听力专项"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
if m:
    x1,y1,x2,y2 = map(int, m.groups())
    cx, cy = (x1+x2)//2, y1 - 60
    print(f">> 尝试点文字上方图标 @({cx},{cy})")
    d.click(cx, cy)
    time.sleep(2.5)
    print(">> 是否进入:", check_entered(), "activity=", d.app_current().get("activity"))

# 尝试3：点整个文字 bounds 的靠上位置
if m:
    cx, cy = (x1+x2)//2, (y1+y2)//2 - 40
    print(f">> 尝试点文字 bounds 偏上 @({cx},{cy})")
    d.click(cx, cy)
    time.sleep(2.5)
    print(">> 是否进入:", check_entered(), "activity=", d.app_current().get("activity"))
print(">> DONE")
