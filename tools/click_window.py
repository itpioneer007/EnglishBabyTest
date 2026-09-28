# -*- coding: utf-8 -*-
"""在指定窗口客户区坐标上做真实鼠标点击（Qt 窗口不响应 WM_LBUTTONDOWN）。

用法：
    python tools/click_window.py --title "MuMu安卓设备" --xy 410 28
    python tools/click_window.py --hwnd 9573272 --xy 410 28 --shot after
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

import win32gui
from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tmp_gen")
user32 = ctypes.windll.user32


def find_window(title_kw):
    res = []
    Proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_kw.lower() in buf.value.lower():
                res.append((hwnd, buf.value))
        return True

    user32.EnumWindows(Proc(cb), 0)
    return res


def click_client(hwnd, cx, cy):
    """坐标以 PrintWindow 整窗口截图为准（左上角 = 窗口左上角）→ 真实鼠标点击。

    为什么不用 ClientToScreen：MuMu 是无边框自绘窗口，但 ClientToScreen 在
    某些 DPI 缩放场景下会偏移；用 GetWindowRect + 截图内坐标最直观可比对。
    """
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    sx, sy = l + int(cx), t + int(cy)
    print("窗口 rect=(%d,%d)-(%d,%d) 截图内(%d,%d) -> 屏幕(%d,%d)"
          % (l, t, r, b, cx, cy, sx, sy))
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    user32.SetCursorPos(sx, sy)
    time.sleep(0.15)
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return sx, sy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="MuMu安卓设备")
    ap.add_argument("--hwnd", type=int, default=0)
    ap.add_argument("--xy", nargs=2, type=int, required=True)
    ap.add_argument("--shot", default="", help="点击后截图 tag")
    ap.add_argument("--wait", type=float, default=1.5)
    ap.add_argument("--pre-shot", action="store_true")
    a = ap.parse_args()

    if a.hwnd:
        hwnd, title = a.hwnd, "(by hwnd)"
    else:
        ws = find_window(a.title)
        if not ws:
            print("未找到窗口:", a.title)
            return 1
        hwnd, title = ws[0]
    print("目标窗口 hwnd=%d %s" % (hwnd, title))

    if a.pre_shot:
        p = os.path.join(OUT, "click_pre_%s.png" % a.shot or "pre")
        ImageGrab.grab().save(p)
        print("点击前全屏:", p)

    click_client(hwnd, a.xy[0], a.xy[1])
    time.sleep(a.wait)

    if a.shot:
        p = os.path.join(OUT, "click_%s.png" % a.shot)
        ImageGrab.grab().save(p)
        print("点击后全屏:", p, os.path.getsize(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
