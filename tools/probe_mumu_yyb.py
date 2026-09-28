# -*- coding: utf-8 -*-
"""验证「英语宝能否跑在 MuMu 模拟器上」—— 决定 GlassMic/TTS 注入路线是否可落地。

步骤：
  1. 从真机 pull 英语宝 base.apk
  2. 装到 MuMu（adb root 已生效）
  3. 启动 → 截图 → dump 当前 Activity
输出：tmp_gen/probe_mumu_yyb.txt + tmp_gen/mumu_launch.png
"""
import os, sys, time, subprocess, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tmp_gen")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "probe_mumu_yyb.txt")
APK = os.path.join(OUT, "yyb_base.apk")
PKG = "com.dinoenglish.yyb"
PHONE = "SKSCIF4T7PFMQS5X"
MUMU = "127.0.0.1:16384"

ADB = glob.glob(os.path.join(
    os.path.expanduser("~"),
    "AppData/Local/Programs/Python/Python312/Lib/site-packages/adbutils/binaries/adb.exe"))
ADB = ADB[0] if ADB else "adb"

lines = []


def log(msg):
    lines.append(str(msg))
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def run(args, timeout=1800):
    r = subprocess.run([ADB] + args, capture_output=True, text=True,
                       timeout=timeout, errors="replace")
    return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode


def main():
    log("ADB = %s" % ADB)
    o, e, rc = run(["devices"])
    log("[devices]\n" + o + ("\n" + e if e else ""))

    # ---- 0. MuMu 空间 ----
    o, _, _ = run(["-s", MUMU, "shell", "df -h /data"])
    log("\n[0] MuMu /data 空间\n" + o)

    # ---- 1. pull APK ----
    need_pull = not (os.path.exists(APK) and os.path.getsize(APK) > 300 * 1024 * 1024)
    if need_pull:
        log("\n[1] 从真机 pull base.apk (约400MB) …")
        o, e, rc = run(["-s", PHONE, "pull",
                        "/data/app/~~08sNOO9eFhlr8eIElrDzlw==/com.dinoenglish.yyb-etaxt4C-ANEY3kGcTJGzeQ==/base.apk",
                        APK], timeout=3600)
        log("rc=%s\n%s\n%s" % (rc, o[-500:], e[-800:]))
    else:
        log("\n[1] 本地已有 APK，跳过 pull")
    if not os.path.exists(APK):
        log("!! APK 不存在，终止")
        return 1
    log("APK 大小 = %.1f MB" % (os.path.getsize(APK) / 1048576))

    # ---- 2. 装到 MuMu ----
    log("\n[2] 安装到 MuMu …")
    o, e, rc = run(["-s", MUMU, "install", "-r", "-g", APK], timeout=3600)
    log("rc=%s\n%s\n%s" % (rc, o, e[-2500:]))

    o, _, _ = run(["-s", MUMU, "shell", "pm", "path", PKG])
    log("\n[2b] MuMu 上包路径: " + (o or "(未装成功)"))

    # ---- 3. 启动并观察 ----
    log("\n[3] 启动 App …")
    o, e, rc = run(["-s", MUMU, "shell", "monkey", "-p", PKG,
                    "-c", "android.intent.category.LAUNCHER", "1"], timeout=120)
    log("monkey rc=%s %s %s" % (rc, o[-300:], e[-300:]))
    time.sleep(12)

    o, _, _ = run(["-s", MUMU, "shell", "dumpsys activity activities | grep -m3 -E 'mResumedActivity|topResumedActivity'"])
    log("\n[3b] 前台 Activity:\n" + (o or "(空)"))

    o, _, _ = run(["-s", MUMU, "shell", "pidof " + PKG])
    log("\n[3c] 进程 pid: " + (o or "(无进程 → 启动失败/闪退)"))

    # 抓日志（是否有模拟器检测/崩溃）
    o, _, _ = run(["-s", MUMU, "shell",
                   "logcat -d -t 400 | grep -i -E '%s|emulator|root|crash|FATAL' | tail -40" % PKG.split(".")[-1]])
    log("\n[3d] logcat 关键行:\n" + (o or "(无)"))

    # 截图
    run(["-s", MUMU, "shell", "screencap -p /sdcard/mumu_launch.png"])
    run(["-s", MUMU, "pull", "/sdcard/mumu_launch.png", os.path.join(OUT, "mumu_launch.png")])
    log("\n[4] 截图 → tmp_gen/mumu_launch.png")

    o, _, _ = run(["-s", MUMU, "shell", "dumpsys window | grep -m2 mCurrentFocus"])
    log("[4b] 当前焦点窗口: " + (o or "(空)"))
    log("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
