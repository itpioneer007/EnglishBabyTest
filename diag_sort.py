#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断脚本：dump 当前手机页面 UI 树，分析句子排序题的识别情况。
仅用于排查第9题（句子排序）为什么点不进去。不会点击任何控件。
"""
import re
import sys
import uiautomator2 as u2

OUT = "diag_current.xml"


def main():
    try:
        d = u2.connect()
        xml = d.dump_hierarchy() or ""
    except Exception as e:
        print("DUMP_FAIL", repr(e))
        sys.exit(1)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(xml)
    print("DUMP_OK len=", len(xml))

    # 1) 所有文本为 1-5 的节点（底部数字键盘嫌疑）
    print("=== 数字节点 (1-5) ===")
    for m in re.finditer(
        r'<node[^>]*text="([1-5])"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml
    ):
        print("NUM", m.group(1), "bounds", m.group(2), m.group(3), m.group(4), m.group(5))

    # 2) 所有 CheckBox（圆圈）
    print("=== CheckBox 节点 ===")
    cnt = 0
    for m in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*>', xml):
        tag = m.group(0)
        tm = re.search(r'text="([^"]*)"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if tm and bm:
            print("CB", repr(tm.group(1)),
                  "bounds", bm.group(1), bm.group(2), bm.group(3), bm.group(4))
            cnt += 1
    print("CHECKBOX_COUNT", cnt)

    # 3) 宽>250 的长文本节点（候选句子）
    print("=== 长文本节点 (w>250) ===")
    for m in re.finditer(
        r'<node[^>]*class="android\.widget\.(?:CheckBox|TextView)"[^>]*text="([^"]{3,})"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    ):
        x1, y1, x2, y2 = map(int, m.groups()[1:5])
        w = x2 - x1
        if w > 250:
            print("TXT", repr(m.group(1)[:30]), "w", w, "bounds", x1, y1, x2, y2)

    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
