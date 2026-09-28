# -*- coding: utf-8 -*-
"""探针：dump 口语训练「单元」tab 的真实结构（文本 / resource-id / 坐标）。

为什么要它：2026-09-20 实测「请求 U4 却打开 U3」——`_run_one_unit` 的方式1 是
  「按标题文字匹配到 row → 在 |Δy|<300 内找 开始/重新/继续答题 按钮点击」，
  这个 300px 容差在真机布局下可能点到**相邻单元卡片**的按钮。
要确认就必须看到「单元」tab 每张卡片的标题 y 与按钮 y 的实际差值。

用法：
    python tools/probe_oral_unit_tab.py            # 默认 MuMu
    python tools/probe_oral_unit_tab.py <serial>
输出：按 y 排序的 (y, x, text, resource-id) 列表 + title_pat 命中项 + 按钮候选。
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

SERIAL = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:16384"
os.environ["ANDROID_SERIAL"] = SERIAL

import uiautomator2 as u2  # noqa: E402

PKG = "com.dinoenglish.yyb"
BTNS = ("开始答题", "重新答题", "继续答题")


def main():
    d = u2.connect(SERIAL)
    print(f"[dev] {SERIAL}  info={d.info.get('displayWidth')}x{d.info.get('displayHeight')}")

    d.press("home")
    time.sleep(0.5)
    d.app_start(PKG)
    time.sleep(4)
    for _ in range(6):
        xml = d.dump_hierarchy()
        if ("教材精学" in xml or "专项突破" in xml or "听课文" in xml):
            break
        d.press("back")
        time.sleep(0.6)

    # 主页 → 口语训练
    try:
        el = d(text="口语训练")
        if not el.exists(timeout=3):
            print("[warn] 主页未找到「口语训练」文本，尝试滑动")
            for _ in range(4):
                d.swipe(450, 1300, 450, 700, 0.25)
                time.sleep(0.5)
                if d(text="口语训练").exists(timeout=1):
                    break
        el.click()
        print("[nav] 点击 口语训练")
    except Exception as e:
        print(f"[warn] 点击口语训练失败: {e}")
    time.sleep(3)

    # 切「单元」tab（复用模块实现）
    try:
        import importlib
        mod = importlib.import_module("modules.口语训练")
        mod._switch_tab(d, "单元")
    except Exception as e:
        print(f"[warn] 切 tab 失败: {e}")
        try:
            d(text="单元").click()
        except Exception:
            pass
    time.sleep(2)

    xml = d.dump_hierarchy()
    with open(os.path.join(ROOT, "tmp_gen", "oral_unit_tab.xml"), "w", encoding="utf-8") as fh:
        fh.write(xml)
    print("[dump] tmp_gen/oral_unit_tab.xml")

    nodes = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        tm = re.search(r'text="([^"]*)"', tag)
        rm = re.search(r'resource-id="([^"]*)"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        cm = re.search(r'clickable="(\w+)"', tag)
        if not bm:
            continue
        t = (tm.group(1) if tm else "").strip()
        r = (rm.group(1) if rm else "").split("/")[-1]
        if not t and not r:
            continue
        x1, y1, x2, y2 = (int(bm.group(i)) for i in (1, 2, 3, 4))
        nodes.append((y1, x1, y2, x2, t, r, cm.group(1) if cm else ""))
    nodes.sort()

    print("\n===== 页面节点（按 y 排序）=====")
    for y1, x1, y2, x2, t, r, c in nodes:
        if not t and r not in ("ll_container", "option_flexbox", "title_flexbox"):
            continue
        print(f"  y={y1:5d}-{y2:5d} x={x1:5d}  {t[:52]:<54} rid={r:<26} clickable={c}")

    pat = re.compile(r"[Uu]nits?\s*0*4(?!\d)|U0*4(?!\d)|第\s*4\s*单元")
    print("\n===== title_pat(U4) 命中 =====")
    for y1, x1, y2, x2, t, r, c in nodes:
        if t and pat.search(t):
            print(f"  ⭐ y={y1}-{y2} x={x1}  text={t!r} rid={r}")
    print("\n===== 答题按钮候选 =====")
    for y1, x1, y2, x2, t, r, c in nodes:
        if t in BTNS:
            print(f"  🔘 y={y1}-{y2} x={x1}  {t}  rid={r} clickable={c}")


if __name__ == "__main__":
    main()
