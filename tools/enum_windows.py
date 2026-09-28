# -*- coding: utf-8 -*-
"""枚举 MuMu 模拟器窗口（找设置界面入口）。

目的：确认 MuMu 12 的「麦克风」设置长什么样、能否显式指定设备。
如果用 Python ctypes 拿不到 UIAutomation 树，至少拿到窗口标题与类名。
"""
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

results = []


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
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not title and cls.value in ("Button", "Static"):
        return True
    results.append((hwnd, pid.value, cls.value, title))
    return True


EnumWindows(EnumWindowsProc(cb), 0)

# 找 MuMu / Netease 进程名
import subprocess
ps = ["tasklist", "/FO", "CSV", "/NH"]
try:
    out = subprocess.run(ps, capture_output=True, text=True, timeout=30,
                         errors="replace").stdout
except Exception as e:
    out = ""
procs = {}
for line in out.splitlines():
    parts = [p.strip('"') for p in line.split('","')]
    if len(parts) >= 2:
        procs.setdefault(parts[0], parts[1])

print("=== 可见窗口（含 MuMu 相关进程）===")
for hwnd, pid, cls, title in results:
    pname = procs.get(str(pid), "?")
    if any(k in (pname or "").lower() for k in ("mumu", "nemu", "nx", "netease")) \
       or any(k in title for k in ("MuMu", "模拟器")):
        print("  hwnd=%-10d pid=%-8d proc=%-24s cls=%-26s title=%r"
              % (hwnd, pid, pname, cls, title))

print()
print("=== 全部窗口（前 40，排查用）===")
for hwnd, pid, cls, title in results[:40]:
    print("  hwnd=%-10d pid=%-8d proc=%-24s cls=%-24s title=%r"
          % (hwnd, pid, procs.get(str(pid), "?"), cls, title[:50]))

print()
print("=== MuMu 相关进程 ===")
for name, pid in sorted(procs.items()):
    if any(k in name.lower() for k in ("mumu", "nemu", "nx", "netease", "vbox")):
        print("  %-32s pid=%s" % (name, pid))
