# -*- coding: utf-8 -*-
"""截取指定窗口（按标题/进程名匹配）为 PNG。用于看清 MuMu 设置界面。

为什么要它：MuMu 12 的「麦克风」设置没有可靠的命令行接口，
需要先看清 GUI 上有什么选项才能决定接法（PyQt 窗口，UIAutomation 树很浅）。

用法：
    python tools/shot_window.py                 # 截 MuMu 相关窗口
    python tools/shot_window.py --title "MuMu"  # 指定标题关键字
    python tools/shot_window.py --hwnd 68056
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

import win32gui
import win32ui
import win32con
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tmp_gen")
os.makedirs(OUT, exist_ok=True)

user32 = ctypes.windll.user32


def list_windows():
    res = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if title:
            res.append((hwnd, title, cls.value))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return res


def grab(hwnd, path, client_only=False):
    """PrintWindow + BitBlt 双路取图，取非全黑的那张。"""
    win32gui.SetForegroundWindow(hwnd) if False else None
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    time.sleep(0.6)

    rect = win32gui.GetClientRect(hwnd) if client_only else win32gui.GetWindowRect(hwnd)
    if client_only:
        l, t = win32gui.ClientToScreen(hwnd, (0, 0))
        w, h = rect[2], rect[3]
    else:
        l, t, r, b = rect
        w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None, "窗口尺寸异常 %sx%s" % (w, h)

    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(bmp)
    # PW_RENDERFULLCONTENT = 2
    user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           bits, "raw", "BGRX", 0, 1)
    # 判黑：如果全黑则用 BitBlt 兜底
    extrema = img.convert("L").getextrema()
    method = "PrintWindow"
    if extrema == (0, 0):
        saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)
        bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                               bits, "raw", "BGRX", 0, 1)
        method = "BitBlt"
    img.save(path)
    win32gui.DeleteObject(bmp.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)
    return path, method


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="MuMu")
    ap.add_argument("--hwnd", type=int, default=0)
    ap.add_argument("--tag", default="win")
    a = ap.parse_args()

    wins = list_windows()
    if a.hwnd:
        target = [(h, t, c) for h, t, c in wins if h == a.hwnd]
    else:
        target = [(h, t, c) for h, t, c in wins if a.title.lower() in t.lower()]

    if not target:
        print("未找到匹配窗口。当前可见窗口：")
        for h, t, c in wins:
            print("   hwnd=%-10d cls=%-28s title=%r" % (h, c, t[:60]))
        return 1

    for h, t, c in target:
        p = os.path.join(OUT, "shot_%s_%d.png" % (a.tag, h))
        res, method = grab(h, p)
        if res:
            print("OK  hwnd=%d %-40s -> %s (%s, %d bytes)"
                  % (h, t[:40], p, method, os.path.getsize(p)))
        else:
            print("FAIL hwnd=%d %s: %s" % (h, t[:40], method))
    return 0


if __name__ == "__main__":
    sys.exit(main())
