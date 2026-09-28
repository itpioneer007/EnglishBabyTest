# -*- coding: utf-8 -*-
"""探测 Windows 音频端点（播放/录音），找虚拟声卡（VB-CABLE 等）。

为什么不用 PowerShell：本会话 PowerShell 工具 stdout 常被吞，改用 winreg 直接读注册表，
结果落盘后回读，稳定可复现。
"""
import os
import winreg

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tmp_gen", "probe_audio_host.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

PROP = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"   # 设备友好名
STATE = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"  # 设备类名


def enum(root, sub):
    out = []
    try:
        k = winreg.OpenKey(root, sub)
    except OSError:
        return out
    i = 0
    while True:
        try:
            name = winreg.EnumKey(k, i)
            i += 1
        except OSError:
            break
        rec = {"id": name}
        try:
            pk = winreg.OpenKey(k, name + r"\Properties")
            for label, key in (("name", PROP), ("cls", STATE)):
                try:
                    v, _ = winreg.QueryValueEx(pk, key)
                    rec[label] = v
                except OSError:
                    pass
            winreg.CloseKey(pk)
        except OSError:
            pass
        # 设备状态（1=启用 2=禁用 ...）
        try:
            sk = winreg.OpenKey(k, name)
            try:
                v, _ = winreg.QueryValueEx(sk, "DeviceState")
                rec["state"] = v
            except OSError:
                pass
            winreg.CloseKey(sk)
        except OSError:
            pass
        out.append(rec)
    winreg.CloseKey(k)
    return out


lines = []
RR = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
CC = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"

for label, sub in (("RENDER 播放设备", RR), ("CAPTURE 录音设备", CC)):
    lines.append("=== %s ===" % label)
    recs = enum(winreg.HKEY_LOCAL_MACHINE, sub)
    if not recs:
        lines.append("  (无)")
    for r in recs:
        lines.append("  state=%s | %s | cls=%s" % (
            r.get("state", "?"), r.get("name", "?"), r.get("cls", "?")))

# 驱动文件
drv = r"C:\Windows\System32\drivers"
try:
    hits = sorted(f for f in os.listdir(drv)
                  if any(k in f.lower() for k in ("vb", "cable", "virtual", "vac")))
except OSError:
    hits = []
lines.append("=== 虚拟声卡驱动文件 (System32\\drivers) ===")
lines.append("  " + (", ".join(hits) if hits else "(无)"))

# 关键字命中判定
blob = "\n".join(lines).lower()
for kw in ("cable input", "cable output", "vb-audio", "virtual audio", "voicemeeter"):
    lines.append("关键字 [%s]: %s" % (kw, "命中" if kw in blob else "未命中"))

text = "\n".join(lines)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(text)
print(text)
