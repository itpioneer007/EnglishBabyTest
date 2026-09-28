# -*- coding: utf-8 -*-
"""探测本机权限与虚拟声卡安装条件。

关键问题：路线①（Windows TTS → 虚拟声卡 → MuMu 麦克风）需要装 VB-CABLE，
而装驱动需要管理员权限。这里先确认：
  1) 当前进程是否已是管理员
  2) 是否具备下载能力（VB-CABLE 约 1MB）
  3) NetworkManager / AudioSrv 是否可写（驱动安装前提）
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tmp_gen", "probe_perm.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

lines = []

# 1) 管理员
try:
    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception as e:
    admin = "ERR:%s" % e
lines.append("IsUserAnAdmin = %s" % admin)

# 2) 服务状态
for svc in ("Audiosrv", "AudioEndpointBuilder", "DeviceInstall", "TrustedInstaller"):
    try:
        r = subprocess.run(["sc", "query", svc], capture_output=True, text=True,
                           timeout=15, errors="replace")
        state = [l.strip() for l in (r.stdout or "").splitlines()
                 if "STATE" in l.upper()]
        lines.append("svc %-22s %s" % (svc, state[0] if state else (r.stdout or "")[:80]))
    except Exception as e:
        lines.append("svc %-22s ERR %s" % (svc, e))

# 3) 网络可达性（VB-Audio 官网 / 国内镜像）
lines.append("")
lines.append("=== 网络可达性 ===")
for url in ("https://vb-audio.com/Cable/VBCABLE_Driver_Pack43.zip",
            "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip",
            "https://www.baidu.com"):
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            lines.append("  %-70s -> HTTP %s len=%s" % (
                url, resp.status, resp.headers.get("Content-Length")))
    except Exception as e:
        lines.append("  %-70s -> ERR %s" % (url, str(e)[:90]))

# 4) 找已有的 VB-CABLE 安装残留
lines.append("")
lines.append("=== 已有安装痕迹 ===")
for p in (r"C:\Program Files\VB\CABLE",
          r"C:\Program Files (x86)\VB\CABLE",
          r"C:\Program Files\VB-Audio",
          os.path.expandvars(r"%TEMP%\VBCABLE")):
    lines.append("  %-45s exists=%s" % (p, os.path.isdir(p)))

# 5) 系统盘剩余空间
try:
    import shutil
    t, u, f = shutil.disk_usage("C:\\")
    lines.append("")
    lines.append("C盘 剩余 %.1f GB" % (f / 1073741824))
except Exception:
    pass

text = "\n".join(lines)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(text)
print(text)
