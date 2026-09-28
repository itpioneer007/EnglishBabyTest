# -*- coding: utf-8 -*-
"""语音评测「音频注入」A/B 对照实验。

目的：证明英语宝的评分确实来自我们注入的 TTS 音频，而不是安慰分/上一题残留。

对照设计（同一道题，重复录）：
    A 组（静音对照）：只点录音，不播任何音频  -> 期望 0 分 / 无识别
    B 组（注入实验）：循环播放 TTS 后点录音    -> 期望 有效分

读分方式：点击 score_box 弹「评测得分:xx」浮层，抓 3 次 dump + 截图兜底。

用法：
    python tools/speech_ab_test.py --text "yell and cry" --group A
    python tools/speech_ab_test.py --text "yell and cry" --group B --loops 3
    python tools/speech_ab_test.py --read          # 只读当前题分数
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "tmp_gen")
os.makedirs(OUT, exist_ok=True)

import tts_inject as T          # noqa: E402
import uiautomator2 as u2       # noqa: E402

SERIAL = "127.0.0.1:16384"
_ADB = glob.glob(r"C:\Users\19507\AppData\Local\Programs\Python\Python312"
                 r"\Lib\site-packages\adbutils\binaries\adb.exe")[0]


def shot(path):
    with open(path, "wb") as f:
        subprocess.run([_ADB, "-s", SERIAL, "exec-out", "screencap", "-p"],
                       stdout=f, stderr=subprocess.PIPE, timeout=120)
    return os.path.getsize(path) if os.path.exists(path) else 0


def dump(d, retries=4):
    for _ in range(retries):
        try:
            xml = d.dump_hierarchy()
            if xml and "<hierarchy" in xml:
                return xml
        except Exception:
            pass
        time.sleep(0.4)
    return ""


def nodes(xml):
    out = []
    for m in re.finditer(r"<node\b[^>]*>", xml or ""):
        tag = m.group(0)

        def g(k):
            mm = re.search(k + r'="([^"]*)"', tag)
            return mm.group(1) if mm else ""

        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bm:
            continue
        out.append({"text": g("text"), "desc": g("content-desc"),
                    "rid": g("resource-id").split("/")[-1],
                    "b": tuple(int(v) for v in bm.groups())})
    return out


def center(b):
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def find(xml, rid=None, text=None):
    for n in nodes(xml):
        if rid and rid in n["rid"]:
            return n
        if text and text in (n["text"] or "") + (n["desc"] or ""):
            return n
    return None


def star_bounds(xml):
    return [n["b"] for n in nodes(xml)
            if n["rid"] in ("iv_star_1", "iv_star_2", "iv_star_3")]


def star_count(png, boxes):
    """像素判星：亮星=黄色(R/G 高 B 低 且 R-B 差大)，灭星=灰(三通道接近)。

    为什么不用 uiautomator：星星是 ImageView，dump 里拿不到"亮/灭"，
    只能看图片资源名，而 u2 dump 不输出 src。像素法最可靠。
    """
    from PIL import Image
    im = Image.open(png).convert("RGB")
    n = 0
    detail = []
    for b in boxes:
        crop = im.crop((b[0] + 4, b[1] + 4, b[2] - 4, b[3] - 4))
        px = list(crop.getdata())
        yell = sum(1 for r, g, bb in px if r > 150 and g > 110 and bb < 130
                   and (r - bb) > 55)
        ratio = yell / max(1, len(px))
        detail.append(round(ratio, 3))
        if ratio > 0.12:
            n += 1
    return n, detail


def read_score(d, tag):
    """点 score_box 弹分数浮层，抓文字 + 截图。"""
    xml = dump(d)
    box = find(xml, rid="score_box")
    if not box:
        return None, None
    x, y = center(box["b"])
    d.click(x, y)
    got = None
    for i in range(6):
        time.sleep(0.35)
        t = dump(d)
        tt = [v for v in re.findall(r'text="([^"]+)"', t) if "得分" in v or "分" == v.strip()[-1:]]
        if tt:
            got = tt
            break
    p = os.path.join(OUT, "ab_%s_score.png" % tag)
    shot(p)
    return got, p


def do_record(d, text, loops, wait, tag, play=True, start_delay=0.8):
    xml = dump(d)
    rec = find(xml, rid="record_layout")
    if not rec:
        print("!! 找不到 record_layout；页面文字:",
              [n["text"] for n in nodes(xml) if n["text"]][:20])
        return None
    rx, ry = center(rec["b"])
    print("录音按钮: (%d,%d) bounds=%s" % (rx, ry, rec["b"]))

    out_dev = in_dev = None
    wav = None
    if play:
        wav = os.path.join(T.TMP, "_speech_probe.wav")
        ok, so, se, _ = T.synth_wav(text, wav)
        if not ok:
            print("!! TTS 合成失败:", se[:200])
            return None
        arr, sr, ch = T.read_wav(wav)
        print("TTS: %r -> %.2fs peak=%.3f sr=%d" % (
            text, arr.shape[0] / float(sr), float(abs(arr).max()), sr))
        out_dev, in_dev, _ = T.find_devices()
        print("虚拟线: 播放端=%s 录音端=%s" % (out_dev, in_dev))

    stop = threading.Event()
    plays = []

    print("点击录音 @%.2f" % time.time())
    d.click(rx, ry)

    if play:
        def _start():
            # 等录音真正启动再注入，避免音频落在窗口外
            time.sleep(start_delay)
            for _ in range(loops):
                if stop.is_set():
                    break
                try:
                    T.play(wav, out_dev)
                    plays.append(time.time())
                except Exception as e:
                    print("play err:", str(e)[:80])
                    break
                time.sleep(0.25)

        threading.Thread(target=_start, daemon=True).start()

    # 轮询等待录音真正结束：结束标志 = 页面重新出现「点击录音」
    # （录音中该位置文本是「点击完成」；英语宝录音有时限，到点自动结束并评分）
    score_hits = []
    t0 = time.time()
    ended = False
    while time.time() - t0 < wait:
        time.sleep(0.35)
        xx = dump(d, retries=1)
        vs = re.findall(r'text="([^"]*得分[^"]*)"', xx)
        for v in vs:
            if v not in score_hits:
                score_hits.append(v)
        tt = re.findall(r'text="([^"]+)"', xx)
        if "点击录音" in tt:          # 已回到待录状态 -> 本次录音结束
            ended = True
            break
    stop.set()
    time.sleep(0.8)

    xml2 = dump(d)
    txt = [n["text"] for n in nodes(xml2) if n["text"]]
    boxes = star_bounds(xml2)
    png = os.path.join(OUT, "ab_%s_recorded.png" % tag)
    shot(png)
    sc, ratio = star_count(png, boxes)
    print("录音结束: %s (耗时 %.1fs)" % (ended, time.time() - t0))
    print("录音后页面文字:", txt[:30])
    print("播放次数: %d" % len(plays))
    if score_hits:
        print("抓到得分浮层: %s" % score_hits)
    print(">>> 本题得分星级: %d/3  (各星黄色占比 %s)" % (sc, ratio))
    print(">>> 截图: %s" % png)
    return len(plays), sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="yell and cry")
    ap.add_argument("--group", default="B", choices=["A", "B", "read"])
    ap.add_argument("--loops", type=int, default=3)
    ap.add_argument("--wait", type=float, default=15.0)
    ap.add_argument("--start-delay", type=float, default=0.8)
    ap.add_argument("--tag", default="x")
    a = ap.parse_args()

    d = u2.connect(SERIAL)
    cur = d.app_current()
    print("当前: %s / %s" % (cur.get("package"), cur.get("activity")))
    xml = dump(d)
    t = [n["text"] for n in nodes(xml) if n["text"]]
    boxes = star_bounds(xml)
    p0 = os.path.join(OUT, "ab_%s_before.png" % a.tag)
    shot(p0)
    sc0, r0 = star_count(p0, boxes)
    print("页面文字:", t[:25])
    print("录音前星级: %d/3 (占比 %s)" % (sc0, r0))

    if a.group == "read":
        got, p = read_score(d, a.tag)
        print("分数浮层:", got, "| 截图:", p)
        return 0

    if a.group == "A":
        print("=== A 组：静音对照（不播音频）===")
        do_record(d, a.text, 0, a.wait, a.tag, play=False)
    else:
        print("=== B 组：TTS 注入 ===")
        do_record(d, a.text, a.loops, a.wait, a.tag, play=True,
                  start_delay=a.start_delay)

    time.sleep(1.0)
    got, p = read_score(d, a.tag)
    print(">>> %s 组分数浮层内容: %s" % (a.group, got))
    print(">>> 截图: %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
