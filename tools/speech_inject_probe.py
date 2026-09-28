# -*- coding: utf-8 -*-
"""语音评测「TTS → 虚拟声卡 → 模拟器麦克风」端到端探针。

验证目标：英语宝录音时，能否录到我们注入的 TTS 音频（而不是静音/物理麦克风噪声）。

链路（全部在本机内闭合，无任何声学路径）：
    SAPI 合成 WAV → 播放到 CABLE Input → 虚拟线 → CABLE Output
    → MuMu 以「系统默认录音设备」打开录音 → 英语宝拿到 PCM → 打分

为什么循环播放：英语宝点录音后可能有 3-2-1 倒计时或自动静音检测，
    单次播放容易错过窗口；循环 6 次（每次约 1.2s）可稳定覆盖。

用法：
    python tools/speech_inject_probe.py "Shouldn't do"
    python tools/speech_inject_probe.py "yell and cry" --loops 8 --wait 12
"""
import argparse
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


def adb(args, t=90):
    import glob
    adb_exe = glob.glob(r"C:\Users\19507\AppData\Local\Programs\Python\Python312"
                        r"\Lib\site-packages\adbutils\binaries\adb.exe")[0]
    r = subprocess.run([adb_exe, "-s", SERIAL] + args, capture_output=True,
                       timeout=t, errors="replace")
    return (r.stdout or "").strip()


def shot(path):
    import glob
    adb_exe = glob.glob(r"C:\Users\19507\AppData\Local\Programs\Python\Python312"
                        r"\Lib\site-packages\adbutils\binaries\adb.exe")[0]
    with open(path, "wb") as f:
        subprocess.run([adb_exe, "-s", SERIAL, "exec-out", "screencap", "-p"],
                       stdout=f, stderr=subprocess.PIPE, timeout=120)
    return os.path.getsize(path) if os.path.exists(path) else 0


def dump_text(d):
    """返回当前页面的文字列表（u2 dump，带重试）。"""
    for i in range(4):
        try:
            xml = d.dump_hierarchy()
            if xml and "<hierarchy" in xml:
                return [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()], xml
        except Exception:
            pass
        time.sleep(0.5)
    return [], ""


def parse_nodes(xml):
    """从 dump XML 解析节点（u2 的 resourceId selector 是精确匹配，
    短名匹配不到 'com.xxx:id/record_layout'，所以自己解析最稳）。"""
    nodes = []
    for m in re.finditer(r"<node\b[^>]*>", xml or ""):
        tag = m.group(0)

        def g(k):
            mm = re.search(k + r'="([^"]*)"', tag)
            return mm.group(1) if mm else ""

        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bm:
            continue
        b = tuple(int(v) for v in bm.groups())
        nodes.append({"text": g("text"), "desc": g("content-desc"),
                      "rid": g("resource-id").split("/")[-1],
                      "full_rid": g("resource-id"),
                      "click": g("clickable") == "true", "b": b})
    return nodes


def find_bounds(xml, rid_sub=None, text_sub=None):
    for n in parse_nodes(xml):
        if rid_sub and rid_sub in (n["rid"] or ""):
            return n["b"], n
        if text_sub and text_sub in ((n["text"] or "") + (n["desc"] or "")):
            return n["b"], n
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", help="要注入的文本（题目原文）")
    ap.add_argument("--loops", type=int, default=6)
    ap.add_argument("--gap", type=float, default=0.15)
    ap.add_argument("--wait", type=float, default=9.0)
    ap.add_argument("--record-rid", default="record_layout")
    ap.add_argument("--record-xy", default="")
    ap.add_argument("--tag", default="sp")
    ap.add_argument("--no-play", action="store_true", help="只点击不注入（对照组）")
    a = ap.parse_args()

    d = u2.connect(SERIAL)
    log = []

    # 0) 定位录音按钮
    if a.record_xy:
        rx, ry = [int(v) for v in a.record_xy.split(",")]
        src = "命令行指定"
    else:
        txt0, xml0 = dump_text(d)
        b, node = find_bounds(xml0, rid_sub=a.record_rid)
        if not b:
            b, node = find_bounds(xml0, text_sub="点击录音")
        if not b:
            print("!! 找不到录音按钮 rid=%s / 文本'点击录音'" % a.record_rid)
            print("   当前页文字:", txt0[:30])
            return 2
        rx = (b[0] + b[2]) // 2
        ry = (b[1] + b[3]) // 2
        src = "rid=%s bounds=(%d,%d)-(%d,%d)" % (
            node["rid"], b[0], b[1], b[2], b[3])
    log.append("录音按钮: (%d,%d) 来源:%s" % (rx, ry, src))

    # 1) 合成
    wav = os.path.join(T.TMP, "_speech_probe.wav")
    ok, so, se, _ = T.synth_wav(a.text, wav)
    if not ok:
        print("!! TTS 合成失败:", se[:300])
        return 3
    arr, sr, ch = T.read_wav(wav)
    log.append("TTS: %r -> %s (%.2fs, peak=%.3f, sr=%d)" % (
        a.text, os.path.basename(wav), arr.shape[0] / float(sr),
        float(abs(arr).max()) if arr.size else 0.0, sr))

    out_dev, in_dev, _ = T.find_devices()
    log.append("虚拟线: 播放端=%s 录音端=%s" % (out_dev, in_dev))

    stop = threading.Event()
    plays = []

    def loop():
        for i in range(a.loops):
            if stop.is_set():
                break
            try:
                T.play(wav, out_dev)
                plays.append(time.time())
            except Exception as e:
                log.append("play err: %s" % str(e)[:80])
                break
            time.sleep(a.gap)

    # 2) 先起播放线程，再点录音（让音频覆盖整个录音窗口）
    if not a.no_play:
        th = threading.Thread(target=loop, daemon=True)
        th.start()
        time.sleep(0.35)

    log.append("点击录音 @%.2f" % time.time())
    d.click(rx, ry)

    # 3) 等待（中途截图便于定位状态）
    t0 = time.time()
    mid = int(a.wait / 2)
    time.sleep(mid)
    shot(os.path.join(OUT, "probe_%s_mid.png" % a.tag))
    txt_mid, _ = dump_text(d)
    log.append("录音中页面文字: %s" % txt_mid[:20])
    time.sleep(a.wait - mid)
    stop.set()

    # 4) 收尾观察
    txt_after, xml_after = dump_text(d)
    shot(os.path.join(OUT, "probe_%s_after.png" % a.tag))
    with open(os.path.join(OUT, "probe_%s_dump.xml" % a.tag), "w",
              encoding="utf-8") as f:
        f.write(xml_after)

    log.append("完成后页面文字: %s" % txt_after[:30])
    log.append("播放次数: %d" % len(plays))

    print("\n".join(log))
    print("\n截图: %s" % os.path.join(OUT, "probe_%s_after.png" % a.tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
