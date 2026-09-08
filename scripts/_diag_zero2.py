import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import S, S_swipe, settle_ads, back_to_home, scroll_and_find

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
print(">> 已连接", SERIAL)

switch_version_grade(d, "湘少版（2024审定）", "五年级上册")
time.sleep(1.5); settle_ads(d, wait_total=6)

# 进入听力专项
scroll_and_find(d, "听力专项")
for _ in range(3):
    if d(text="听力专项").exists(timeout=1):
        d(text="听力专项").click(); break
    elif d(textContains="听力专项").exists(timeout=1):
        d(textContains="听力专项").click(); break
    time.sleep(0.5)
time.sleep(2.5); settle_ads(d, wait_total=5)

print(">> 当前 activity:", d.app_current().get("activity"))
print(">> === 进入后 完整文字(去重) ===")
xml = d.dump_hierarchy() or ""
texts = []
for m in re.findall(r'text="([^"]{1,40})"', xml):
    m = m.strip()
    if m and m not in texts:
        texts.append(m)
print("   共", len(texts), "个文字节点")
for t in texts[:80]:
    print("   T:", t)

# 尝试：点 '练习' tab，再 dump
for tab in ("练习", "测试", "专项突破"):
    if d(text=tab).exists(timeout=1):
        d(text=tab).click(); time.sleep(1.5)
        print(f">> 点击 tab[{tab}] 后：")
        x3 = d.dump_hierarchy() or ""
        hits = [t.strip() for t in re.findall(r'text="([^"]{1,30})"', x3)
                if any(k in t for k in ("去练习","去答题","Unit","单元","开发","期待","暂无","开始"))]
        for h in hits[:20]:
            print("    ", tab, "->", h)
        break

print(">> DONE")
