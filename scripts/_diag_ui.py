"""诊断：看清「听力专项」入口点击后真实页面结构，找「测试」tab 的真实文本/位置"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomator2 as u2
from common.tools import dismiss_global_popups, close_ad

SERIAL = "SKSCIF4T7PFMQS5X"
PKG = "com.dinoenglish.yyb"


def dump(d, title):
    print(f"\n{'='*50}\n{title}\n{'='*50}")
    xml = d.dump_hierarchy()
    import re
    seen = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        tm = re.search(r'text="([^"]*)"', tag)
        rid = re.search(r'resource-id="([^"]*)"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        cls = re.search(r'class="([^"]*)"', tag)
        text = tm.group(1) if tm else ""
        if text and text not in [s[0] for s in seen]:
            b = bm.groups() if bm else ("", "", "", "")
            seen.append((text, rid.group(1) if rid else "", cls.group(1) if cls else "", b))
    for text, rid, cls, b in seen[:60]:
        print(f"  text={text!r}  id={rid!r}  class={cls}  bounds={b}")


def main():
    d = u2.connect(SERIAL)
    print("✅ 设备已连接")
    dump(d, "STEP0 当前界面")

    # 回首页
    d.press("home"); time.sleep(0.6)
    d.app_stop(PKG); time.sleep(0.6)
    d.app_start(PKG); time.sleep(3.5)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    time.sleep(1)
    dump(d, "STEP1 App首页")

    # 找 听力专项
    from common.tools import scroll_and_find
    ok = scroll_and_find(d, "听力专项")
    print(f"\nscroll_and_find(听力专项) → {ok}")
    if not ok:
        print("❌ 首页没找到 听力专项"); return
    d(text="听力专项").click()
    time.sleep(1.5)
    dump(d, "STEP2 点击听力专项后")

    # 尝试找 测试 / 练习 tab 文字
    print("\n--- 关键文本存在性检查 ---")
    for kw in ["测试", "练习", "去答题", "去练习", "单元测试", "专项测试", "Test"]:
        print(f"  d(text={kw!r}).exists → {d(text=kw).exists(timeout=1)}")


if __name__ == "__main__":
    main()
