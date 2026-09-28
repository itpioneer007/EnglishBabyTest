# -*- coding: utf-8 -*-
"""通用设备页面 dump 工具（真机 / MuMu 都可用）。

用法：
    python tools/dump_dev.py <tag> [--serial 127.0.0.1:16384] [--clickable]

输出：tmp_gen/dump_<tag>.xml（原始 XML）+ tmp_gen/dump_<tag>.txt（可读清单）
为什么不用 uiautomator2：u2 的连接池在模拟器上偶发卡死，这里直接用 adb，最稳。
"""
import argparse
import glob
import os
import re
import subprocess
import sys

ADB = glob.glob(r"C:\Users\19507\AppData\Local\Programs\Python\Python312"
                r"\Lib\site-packages\adbutils\binaries\adb.exe")[0]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tmp_gen")


def run(serial, args, t=120):
    r = subprocess.run([ADB, "-s", serial] + args, capture_output=True,
                       text=True, timeout=t, errors="replace")
    return (r.stdout or "").strip(), (r.stderr or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--clickable", action="store_true",
                    help="只列出可点击元素")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    run(args.serial, ["shell", "rm -f /sdcard/d.xml"])
    o, e = run(args.serial, ["shell", "uiautomator dump /sdcard/d.xml"])
    xml, _ = run(args.serial, ["shell", "cat /sdcard/d.xml"])

    xml_path = os.path.join(OUT, "dump_%s.xml" % args.tag)
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(xml)

    nodes = []
    for m in re.finditer(r"<node\b[^>]*>", xml):
        tag = m.group(0)
        def g(k):
            mm = re.search(k + r'="([^"]*)"', tag)
            return mm.group(1) if mm else ""
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        b = tuple(int(v) for v in bm.groups()) if bm else (0, 0, 0, 0)
        nodes.append({
            "text": g("text"), "rid": g("resource-id").split("/")[-1],
            "cls": g("class").split(".")[-1], "desc": g("content-desc"),
            "click": g("clickable") == "true", "b": b,
        })

    lines = ["# dump tag=%s serial=%s | dump=%s" % (args.tag, args.serial, o[:80]),
             "# 节点总数 %d" % len(nodes), ""]
    shown = 0
    for n in nodes:
        if args.clickable and not n["click"]:
            continue
        label = n["text"] or n["desc"] or n["rid"]
        if not label:
            continue
        lines.append("[%s] rid=%-22s cls=%-16s bounds=(%d,%d)-(%d,%d) desc=%s"
                     % ("可点" if n["click"] else "  -", n["rid"], n["cls"],
                        n["b"][0], n["b"][1], n["b"][2], n["b"][3],
                        (n["desc"] or "")[:30]))
        shown += 1
    lines.insert(2, "# 有标签节点 %d" % shown)

    txt_path = os.path.join(OUT, "dump_%s.txt" % args.tag)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:80]))
    print("\n落盘:", xml_path)
    print("落盘:", txt_path)


if __name__ == "__main__":
    main()
