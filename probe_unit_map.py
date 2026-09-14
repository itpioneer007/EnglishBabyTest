# -*- coding: utf-8 -*-
"""探测：六上巧记单词「闯关地图」页面结构（为新增 Unit 滑动选择步骤取证）"""
import sys, os, time, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

import uiautomator2 as u2
from common.tools import close_ad, dismiss_global_popups, ensure_grade

APP_PACKAGE = "com.dinoenglish.yyb"

def main():
    d = u2.connect("SKSCIF4T7PFMQS5X")
    print("✅ 设备已连接", d.window_size())
    d.press("home"); time.sleep(0.5)
    d.app_stop(APP_PACKAGE); time.sleep(1)
    d.app_start(APP_PACKAGE); time.sleep(4)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    time.sleep(1)
    ok = ensure_grade(d, "六年级上册", "湘少版")
    print(f"年级切换(六上): {ok}")
    time.sleep(1.5)

    from modules.巧记单词 import _enter_qiaoji, _enter_sync_challenge
    print("--- 进入巧记单词 ---")
    print("_enter_qiaoji:", _enter_qiaoji(d))
    time.sleep(1)

    # 先 dump 巧记单词主页（看是否有"暂无"文案）
    xml = d.dump_hierarchy()
    txts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
    print("巧记单词主页文本:", txts[:20])

    print("--- 点单词同步闯关 ---")
    print("_enter_sync_challenge:", _enter_sync_challenge(d))
    time.sleep(2)

    xml = d.dump_hierarchy()
    txts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
    print("\n=== 闯关地图页面文本 ===")
    for t in txts[:60]:
        print("   -", t[:80])

    # 提取 Unit 卡片位置
    print("\n=== Unit 文本元素位置 ===")
    for m in re.finditer(r'text="([^"]*Unit[^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        print(f"   {m.group(1)!r:20s} bounds=[{m.group(2)},{m.group(3)}][{m.group(4)},{m.group(5)}]")

    # 所有 clickable 元素
    print("\n=== clickable 元素（前30） ===")
    n = 0
    for m in re.finditer(r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*/?>', xml):
        seg = m.group(0)
        rid = re.search(r'resource-id="([^"]*)"', seg)
        tx = re.search(r'text="([^"]*)"', seg)
        x1, y1, x2, y2 = map(int, m.groups())
        w, h = x2 - x1, y2 - y1
        print(f"   [{x1},{y1}][{x2},{y2}] {w}x{h} rid={rid.group(1).split('/')[-1] if rid else '':22s} text={tx.group(1)[:30] if tx else ''!r}")
        n += 1
        if n >= 30:
            break

    # 保存 XML 供离线分析
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "screenshots", "unit_map_dump.xml")
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"\n✅ XML 已保存: {out}")

if __name__ == "__main__":
    main()
