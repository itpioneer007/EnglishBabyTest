# -*- coding: utf-8 -*-
"""MuMu 英语宝导航助手（uiautomator2 通道 + adb 回退）。

★ 为什么必须用 u2 而不是 `adb shell uiautomator dump`：
   英语宝首页有常驻动画（宠物/广告轮播），`uiautomator dump` 会一直等
   "idle state" 并直接报错 `ERROR: could not get idle state.`，一个节点都拿不到。
   uiautomator2 走 atx-agent 的 /dump/hierarchy，不依赖 idle 检测，实测 0.1s 出结果。
   （真机上 u2 因息屏会卡死，所以保留 adb 回退路径。）

用法：
    python tools/mumu_nav.py dump <tag> [--all]
    python tools/mumu_nav.py tap <resource-id|文本>
    python tools/mumu_nav.py tap-xy <x> <y>
    python tools/mumu_nav.py find <关键词>
    python tools/mumu_nav.py shot <tag>
    python tools/mumu_nav.py fg
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tmp_gen")
os.makedirs(OUT, exist_ok=True)
SERIAL = "127.0.0.1:16384"

ADB = None
try:
    ADB = glob.glob(r"C:\Users\19507\AppData\Local\Programs\Python\Python312"
                    r"\Lib\site-packages\adbutils\binaries\adb.exe")[0]
except IndexError:
    pass

_DEV = None


def dev():
    global _DEV
    if _DEV is None:
        import warnings
        warnings.filterwarnings("ignore")
        import uiautomator2 as u2
        _DEV = u2.connect(SERIAL)
    return _DEV


def adb_run(args, t=90):
    if not ADB:
        return "", ""
    r = subprocess.run([ADB, "-s", SERIAL] + args, capture_output=True,
                       text=True, timeout=t, errors="replace")
    return (r.stdout or "").strip(), (r.stderr or "").strip()


def dump_xml(retries=4):
    """优先 u2；失败回退 adb。

    u2 的 dump_hierarchy 在英语宝这种「持续动画 + WebView 混排」页面上会间歇性返回空，
    所以必须重试几次再回退（实测重试 2~3 次内基本都能拿到）。
    """
    last = ""
    for i in range(retries):
        try:
            xml = dev().dump_hierarchy()
            if xml and len(xml) > 200 and "<hierarchy" in xml:
                return xml, "u2" + ("" if i == 0 else "(retry%d)" % i)
            last = "u2 返回空或过短(len=%d)" % len(xml or "")
        except Exception as e:
            last = "u2 err:" + str(e)[:80]
        time.sleep(0.5)
    # 回退 adb
    adb_run(["shell", "rm -f /sdcard/d.xml"])
    o, e = adb_run(["shell", "uiautomator dump /sdcard/d.xml"])
    x, _ = adb_run(["shell", "cat /sdcard/d.xml"])
    return x, "adb(%s|%s|last=%s)" % (o[:30] or "empty", e[:30], last[:40])


def parse_nodes(xml):
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
    return nodes


def center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def show(nodes, only_click=False, limit=80, with_text_only=False):
    lines, n = [], 0
    for nd in nodes:
        if only_click and not nd["click"]:
            continue
        label = nd["text"] or nd["desc"] or nd["rid"]
        if with_text_only and not (nd["text"] or nd["desc"]):
            continue
        if not label:
            continue
        lines.append("%s rid=%-24s cls=%-15s (%d,%d)-(%d,%d) t=%s d=%s" % (
            "●" if nd["click"] else "·", nd["rid"], nd["cls"],
            nd["b"][0], nd["b"][1], nd["b"][2], nd["b"][3],
            nd["text"][:44], nd["desc"][:22]))
        n += 1
        if n >= limit:
            break
    return "\n".join(lines)


def fg():
    o, _ = adb_run(["shell", "dumpsys activity activities | grep -m1 topResumedActivity"])
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["dump", "tap", "tap-xy", "find", "shot", "fg"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--wait", type=float, default=2.0)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.action == "fg":
        print(fg())
        return

    if a.action == "tap-xy":
        x, y = int(a.args[0]), int(a.args[1])
        dev().click(x, y)
        print("u2 click (%d,%d)" % (x, y))
        time.sleep(a.wait)
        print(fg())
        print(show(parse_nodes(dump_xml()[0]), only_click=True))
        return

    if a.action == "tap":
        key = a.args[0]
        xml, src = dump_xml()
        nodes = parse_nodes(xml)
        if not nodes:
            print("!! dump 为空（来源 %s）" % src)
            print(fg())
            return
        hit = next((n for n in nodes if n["rid"] == key and n["click"]), None)
        if not hit:
            hit = next((n for n in nodes if key in (n["text"] or "") and n["click"]), None)
        if not hit:
            hit = next((n for n in nodes if key in (n["text"] or "")), None)
        if not hit:
            print("!! 未找到:", key)
            print(show(nodes, only_click=True))
            return
        x, y = center(hit["b"])
        print("tap %r rid=%s at (%d,%d)" % (hit["text"][:20], hit["rid"], x, y))
        dev().click(x, y)
        time.sleep(a.wait)
        print(fg())
        print(show(parse_nodes(dump_xml()[0]), only_click=True))
        return

    if a.action == "dump":
        tag = a.args[0] if a.args else "nav"
        xml, src = dump_xml()
        nodes = parse_nodes(xml)
        txt = [n for n in nodes if n["text"] or n["desc"]]
        body = show(nodes, only_click=not a.all)
        p = os.path.join(OUT, "nav_%s.txt" % tag)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# %s\n# 来源=%s 节点=%d 有文字=%d\n%s"
                    % (fg(), src, len(nodes), len(txt), body))
        print(fg())
        print("# 来源=%s 节点=%d 有文字=%d" % (src, len(nodes), len(txt)))
        print(body)
        print("\n落盘:", p)
        return

    if a.action == "find":
        kw = a.args[0]
        xml, _ = dump_xml()
        for nd in parse_nodes(xml):
            if kw in (nd["text"] or "") + (nd["desc"] or ""):
                print("%s rid=%-24s cls=%-15s (%d,%d)-(%d,%d) text=%r"
                      % ("●" if nd["click"] else "·", nd["rid"], nd["cls"],
                         nd["b"][0], nd["b"][1], nd["b"][2], nd["b"][3],
                         nd["text"][:60]))
        return

    if a.action == "shot":
        tag = a.args[0] if a.args else "nav"
        p = os.path.join(OUT, "nav_%s.png" % tag)
        # ★ 必须用 exec-out 直取二进制流：
        #   `adb pull` 在本项目路径（含中文"安全处理空间"）下会报
        #   "cannot create file/directory ... No such file or directory" ——
        #   adb 的 pull 走了非 UTF-8 的 ANSI 路径转换，中文目录直接失败。
        #   exec-out 把 stdout 重定向到文件则完全绕开这个编码问题。
        #   （u2 的 screenshot 在 MuMu 上会 "Remote end closed connection"，也不用。）
        ok = False
        if ADB:
            with open(p, "wb") as f:
                r = subprocess.run([ADB, "-s", SERIAL, "exec-out",
                                    "screencap", "-p"],
                                   stdout=f, stderr=subprocess.PIPE, timeout=120)
            ok = os.path.getsize(p) > 1000
            if not ok:
                print("exec-out 失败:", (r.stderr or b"")[:150])
        if not ok:
            adb_run(["shell", "screencap -p /sdcard/s.png"])
            with open(p, "wb") as f:
                subprocess.run([ADB, "-s", SERIAL, "exec-out", "cat", "/sdcard/s.png"],
                               stdout=f, stderr=subprocess.PIPE, timeout=120)
        print("截图:", p, os.path.getsize(p) if os.path.exists(p) else 0)


if __name__ == "__main__":
    main()
