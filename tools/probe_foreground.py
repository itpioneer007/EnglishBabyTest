# -*- coding: utf-8 -*-
"""把英语宝拉到 MuMu 前台，并枚举当前页面文字与音频相关属性。

背景：此 MuMu 实例是用户日常实例，实例里有游戏 com.holyblade.sjlm.ganxt，
它会抢占前台（游戏是 SurfaceView，uiautomator dump 拿到 0 条文字 → 会误判为"页面空白"）。
这里只做"拉前台 + 读取"，不杀游戏，先看能否直接覆盖。
"""
import glob
import os
import re
import subprocess
import sys
import time

ADB = glob.glob(r"C:\Users\19507\AppData\Local\Programs\Python\Python312"
                r"\Lib\site-packages\adbutils\binaries\adb.exe")[0]
M = "127.0.0.1:16384"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tmp_gen")
os.makedirs(OUT, exist_ok=True)


def run(args, t=120):
    r = subprocess.run([ADB] + args, capture_output=True, text=True,
                       timeout=t, errors="replace")
    return (r.stdout or "").strip(), (r.stderr or "").strip()


def sh(cmd, t=120):
    """返回 stdout 单值（注意 run 返回 (out, err) 二元组）。"""
    return run(["-s", M, "shell", cmd], t)[0]


def she(cmd, t=120):
    """返回 (out, err)。"""
    return run(["-s", M, "shell", cmd], t)


lines = []
lines.append("=== 1. 拉起英语宝 ===")
o, e = run(["-s", M, "shell",
            "am start -n com.dinoenglish.yyb/.base.SplashActivity"])
lines.append("start: " + o[:200] + " | " + e[:200])
time.sleep(7)
lines.append(sh("dumpsys activity activities | grep -m2 -E "
               "'topResumedActivity|mResumedActivity'"))

lines.append("")
lines.append("=== 2. 页面文字 ===")
sh("rm -f /sdcard/cur.xml")
o, e = she("uiautomator dump /sdcard/cur.xml")
x = sh("cat /sdcard/cur.xml")
txt = [t for t in re.findall(r'text="([^"]+)"', x) if t.strip()]
lines.append("dump: %s | 文字 %d 条" % (o[:70], len(txt)))
for t in txt[:60]:
    lines.append("   " + t)

lines.append("")
lines.append("=== 3. 音频相关 === ")
lines.append("audio input devices:")
lines.append(sh("dumpsys audio | grep -i -A3 'input device' | head -30"))
lines.append("当前默认录音路由:")
lines.append(sh("dumpsys audio | grep -i -A6 'AudioDeviceInfo' | head -30"))
lines.append("TTS 引擎:")
lines.append(sh("settings get secure tts_default_synth") + " | " +
             sh("pm list packages | grep -i -E 'tts|speech|voice'"))

lines.append("")
lines.append("=== 4. 分辨率 ===")
lines.append(sh("wm size") + " | " + sh("wm density"))

text = "\n".join(lines)
with open(os.path.join(OUT, "probe_foreground.txt"), "w", encoding="utf-8") as f:
    f.write(text)

# 截图
o, e = she("screencap -p /sdcard/fg.png")
p = os.path.join(OUT, "fg.png")
run(["-s", M, "pull", "/sdcard/fg.png", p])
print(text)
print("\n截图:", p, os.path.getsize(p) if os.path.exists(p) else 0)
