# -*- coding: utf-8 -*-
"""语音评测「全自动注入」批量脚本（路线①：TTS → VB-CABLE → 模拟器麦克风）。

已由 A/B 对照实验证明有效：
    静音录音 → 词级 0 分 / 总分 30 / 1 星，提示"听起来不太对哦"
    TTS 注入 → 总分 83.2 / 3 星满分

工作流（每题）：
    1. 读当前题文本（rid=speech_content）
    2. SAPI 合成 WAV
    3. 点击录音 → 等 start_delay 让录音真正启动 → 播放 loops 次
    4. 轮询等录音结束（页面重新出现「点击录音」）
    5. 像素判星（iv_star_1/2/3）+ 截图留证
    6. 点下一题卡片（rid=tv_count）切题

为什么注册 loops=2 + delay=0.8 是最优：
    实测 loops=8 / 无延迟 → 76.7 分(2星)，音频重复且落在窗口外
    实测 loops=2 / delay=0.8 → 83.2 分(3星满分)

用法：
    python tools/speech_autofill.py --count 9
    python tools/speech_autofill.py --count 3 --tag u1
    python tools/speech_autofill.py --dry-run          # 只列出题目不注入
"""
import argparse
import glob
import json
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

_HAS_EN = re.compile(r"[A-Za-z]")


def shot(path):
    with open(path, "wb") as f:
        subprocess.run([_ADB, "-s", SERIAL, "exec-out", "screencap", "-p"],
                       stdout=f, stderr=subprocess.PIPE, timeout=120)
    return os.path.getsize(path) if os.path.exists(path) else 0


def dump(d, retries=3):
    for _ in range(retries):
        try:
            xml = d.dump_hierarchy()
            if xml and "<hierarchy" in xml:
                return xml
        except Exception:
            pass
        time.sleep(0.3)
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


def find(xml, rid=None):
    for n in nodes(xml):
        if rid and rid == n["rid"]:
            return n
    return None


def center(b):
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def star_bounds(xml):
    return [n["b"] for n in nodes(xml)
            if n["rid"] in ("iv_star_1", "iv_star_2", "iv_star_3")]


def star_count(png, boxes):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    n = 0
    ratios = []
    for b in boxes:
        crop = im.crop((b[0] + 4, b[1] + 4, b[2] - 4, b[3] - 4))
        px = list(crop.getdata())
        yell = sum(1 for r, g, bb in px if r > 150 and g > 110 and bb < 130
                   and (r - bb) > 55)
        ratio = yell / max(1, len(px))
        ratios.append(round(ratio, 3))
        if ratio > 0.12:
            n += 1
    return n, ratios


class Runner:
    def __init__(self, d, loops=2, delay=0.8, wait=22.0):
        self.d = d
        self.loops = loops
        self.delay = delay
        self.wait = wait
        self.out_dev, self.in_dev, _ = T.find_devices()

    def synth(self, text):
        wav = os.path.join(T.TMP, "_autofill.wav")
        ok, so, se, _ = T.synth_wav(text, wav)
        return (wav if ok else None), se

    def play_loops(self, wav, stop):
        for _ in range(self.loops):
            if stop.is_set():
                return
            try:
                T.play(wav, self.out_dev)
            except Exception as e:
                print("   play err:", str(e)[:70])
                return
            time.sleep(0.25)

    def record_one(self, text, tag):
        """注入一次并返回 (星级, 截图路径)。"""
        wav, err = self.synth(text)
        if not wav:
            print("   !! TTS 合成失败:", err[:160])
            return None, None

        xml = dump(self.d)
        rec = find(xml, rid="record_layout")
        if not rec:
            print("   !! 找不到录音按钮 record_layout")
            return None, None
        rx, ry = center(rec["b"])

        stop = threading.Event()
        self.d.click(rx, ry)

        def _start():
            time.sleep(self.delay)
            self.play_loops(wav, stop)

        threading.Thread(target=_start, daemon=True).start()

        # 轮询等录音结束（页面重新出现「点击录音」）
        t0 = time.time()
        ended = False
        while time.time() - t0 < self.wait:
            time.sleep(0.3)
            tt = re.findall(r'text="([^"]+)"', dump(self.d, retries=1))
            if "点击录音" in tt:
                ended = True
                break
        stop.set()
        time.sleep(0.7)

        xml2 = dump(self.d)
        boxes = star_bounds(xml2)
        png = os.path.join(OUT, "af_%s.png" % tag)
        shot(png)
        sc, ratios = star_count(png, boxes)
        print("   录音结束=%s 耗时%.1fs 星级=%d/3 %s" % (
            ended, time.time() - t0, sc, ratios))
        return sc, png

    def next_question(self):
        """点下一题卡片切换。返回 (是否成功, 新题号)。

        ⚠ 页面里有两个 rid=tv_count：
            ① text='/9'   bounds=(84,402,126,460)   —— 当前题号的分母（不可点）
            ② text='3/9'  bounds=(60,1117,840,1175) —— 下一题卡片（可点）
        必须挑 ② 才能切题，用正则 ^\\d+/\\d+$ 区分（'/9' 不是这个形状）。
        """
        xml = dump(self.d)
        target = None
        for n in nodes(xml):
            if n["rid"] == "tv_count" and re.match(
                    r"^\d+/\d+$", (n["text"] or "").strip()):
                target = n
                break
        if not target:
            return False, None
        x, y = center(target["b"])
        self.d.click(x, y)
        time.sleep(1.3)
        xml2 = dump(self.d)
        cur = find(xml2, rid="tv_curposition")
        return True, (cur["text"] if cur else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=9, help="最多处理几题")
    ap.add_argument("--loops", type=int, default=2)
    ap.add_argument("--delay", type=float, default=0.8)
    ap.add_argument("--wait", type=float, default=22.0)
    ap.add_argument("--tag", default="AF")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    d = u2.connect(SERIAL)
    cur = d.app_current()
    print("当前: %s / %s" % (cur.get("package"), cur.get("activity")))

    R = Runner(d, loops=a.loops, delay=a.delay, wait=a.wait)
    print("虚拟线: 播放端=%s 录音端=%s" % (R.out_dev, R.in_dev))

    results = []
    xml = dump(d)
    total_txt = find(xml, rid="tv_count")
    total = 0
    if total_txt and "/" in total_txt["text"]:
        total = int(total_txt["text"].split("/")[1])
    print("本单元题数: %d" % total)

    n_done = 0
    for i in range(a.count):
        xml = dump(d)
        curpos = find(xml, rid="tv_curposition")
        stem = find(xml, rid="speech_content")
        trans = find(xml, rid="speech_translation")
        pos = curpos["text"] if curpos else "?"
        text = (stem["text"] if stem else "") or ""
        tr = (trans["text"] if trans else "") or ""

        print("\n=== [%s/%s] %r (%s) ===" % (pos, total, text, tr))
        if not _HAS_EN.search(text):
            print("   -> 无英文题干（听音频跟读类），跳过注入")
            results.append({"pos": pos, "text": text, "stars": None,
                            "skip": "no_english_stem"})
            if a.dry_run:
                pass
            else:
                ok, nxt = R.next_question()
                if not ok or nxt is None:
                    print("   已是最后一题，结束")
                    break
                n_done += 1
                continue

        if a.dry_run:
            results.append({"pos": pos, "text": text, "dry": True})
            ok, nxt = R.next_question()
            if not ok or nxt is None:
                break
            continue

        sc, png = R.record_one(text, "%s_%s" % (a.tag, pos))
        results.append({"pos": pos, "text": text, "trans": tr,
                        "stars": sc, "shot": png})

        if i < a.count - 1:
            ok, nxt = R.next_question()
            if not ok or nxt is None:
                print("   已是最后一题，结束")
                break
        n_done += 1

    rp = os.path.join(OUT, "autofill_%s.json" % a.tag)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n================ 汇总 ================")
    for r in results:
        s = r.get("stars")
        mark = "✓" if s == 3 else ("○" if s else "✗")
        print(" %s 第%s题  星级=%s  %r" % (mark, r.get("pos"),
                                          s if s is not None else "-",
                                          r.get("text")))
    print("结果: %s" % rp)
    ok3 = sum(1 for r in results if r.get("stars") == 3)
    print("满分 %d / %d 题" % (ok3, len(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
