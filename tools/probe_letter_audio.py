# -*- coding: utf-8 -*-
"""探针3：验证「听录音」型字母补全题能否靠 ASR 拿到内容。

对当前停留的 15/40（听录音，选择正确的字母补全单词）：
  1. 检查 scrcpy / ASR key 可用性
  2. 点喇叭 play_box 播音 → scrcpy 数字直录设备音频 → 百炼 ASR 转写
  3. 输出转写文本（决定该题型能否自动作答）
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402
from common import asr as _asr  # noqa: E402

OUT = os.path.join(ROOT, "tmp_gen", "probe_letter_audio.txt")
log = []


def w(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log.append(s)


def main():
    w("scrcpy:", _asr._find_scrcpy() or "(未找到)")
    w("asr_available:", _asr.asr_available())
    d = u2.connect()
    x = d.dump_hierarchy()
    w("当前题:", re.findall(r'text="([^"]*补全单词[^"]*)"', x))
    w("题号:", re.findall(r'text="(\d+\s*/\s*\d+)"', x))
    m = re.search(r'resource-id="[^"]*play_box"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x)
    if not m:
        w("!! 未找到 play_box（喇叭）")
        return
    px, py = (int(m.group(1)) + int(m.group(3))) // 2, (int(m.group(2)) + int(m.group(4))) // 2
    w("喇叭位置:", (px, py))

    rec = os.path.join(ROOT, "tmp_gen", "letter_audio.m4a")
    if os.path.exists(rec):
        os.remove(rec)
    proc, path = _asr.start_scrcpy_record(rec, seconds=8, serial="SKSCIF4T7PFMQS5X")
    w("scrcpy 录制进程:", bool(proc), path)
    if not proc:
        w("录制未能启动，ASR 路线不可用")
        return
    time.sleep(2.0)
    d.click(px, py)          # 点喇叭播音
    w("已点喇叭，录制中…")
    _asr.wait_scrcpy_record(proc, out_path=path, timeout=40)
    w("录制完成，文件大小:", os.path.getsize(path) if os.path.exists(path) else "无文件")
    txt = ""
    try:
        txt = _asr.asr_transcribe(path) or ""
    except Exception as e:
        txt = "ERR " + repr(e)
    w("ASR 转写结果:", repr(txt))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
