import os, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import S, S_swipe, settle_ads, back_to_home

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
switch_version_grade(d, "湘少版（2024审定）", "五年级上册")
time.sleep(1.5); settle_ads(d, wait_total=8)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", "diag")
os.makedirs(OUT, exist_ok=True)

def shot(name):
    p = os.path.join(OUT, name)
    d.screenshot(p)
    print(f">> 截图 {name}")

def is_wechat_auth():
    xml = d.dump_hierarchy() or ""
    return "E英语宝伴学服务" in xml or "申请" in xml or "你的昵称" in xml or "允许" in xml

def try_click_entry():
    xml = d.dump_hierarchy() or ""
    m = re.search(r'text="听力专项"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not m:
        return False
    cx = (int(m.group(1)) + int(m.group(3))) // 2
    cy = (int(m.group(2)) + int(m.group(4))) // 2
    print(f">> 点听力专项 @({cx},{cy})")
    d.click(cx, cy)
    time.sleep(3)
    print(">> 点击后是否小程序授权页:", is_wechat_auth(), "activity=", d.app_current().get("activity"))
    return is_wechat_auth()

shot("before.png")
hit_ad = try_click_entry()
if hit_ad:
    print(">> 确认点到广告，返回主页尝试关闭广告")
    d.press("back"); time.sleep(1)
    d.press("back"); time.sleep(1)
    shot("after_back.png")

    # 尝试1：滑动浮层向右下角滑走
    print(">> 尝试1：从浮层中心向右外滑")
    d.swipe(950, 2150, 1200, 2400, 0.3)
    time.sleep(1)
    shot("swipe1.png")
    hit = try_click_entry()
    if hit:
        d.press("back"); time.sleep(1)
        # 尝试2：点估计的 X 坐标（从截图看卡片右上角）
        print(">> 尝试2：点估计的 X 坐标 (1130,2070)")
        d.click(1130, 2070)
        time.sleep(1)
        shot("click_x.png")
        hit = try_click_entry()
        if hit:
            d.press("back"); time.sleep(1)
            # 尝试3：长按浮层后找关闭/拖拽？较复杂，先点另一个估计坐标
            print(">> 尝试3：点估计 X (1140,2040)")
            d.click(1140, 2040)
            time.sleep(1)
            shot("click_x2.png")
            hit = try_click_entry()
            print(">> 最终结果 hit_ad=", hit)

print(">> DONE")
