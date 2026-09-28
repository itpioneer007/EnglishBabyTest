# -*- coding: utf-8 -*-
"""下载并解压 VB-CABLE 虚拟声卡驱动（VoiceMeeter 出品，1.1MB）。

用途：路线① "Windows TTS → 虚拟声卡 → MuMu 麦克风" 里，虚拟声卡是唯一的硬依赖。
本机没有 Stereo Mix（Intel SST 不暴露），所以必须装一个。

只做「下载 + 解压 + 检查安装器」，不自动装驱动（装驱动要 UAC，由调用方决定）。
"""
import os
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "tmp_gen", "vbcable")
os.makedirs(DEST, exist_ok=True)

URLS = [
    "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip",
    "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
]
ZIP = os.path.join(DEST, "VBCABLE.zip")

if not os.path.exists(ZIP) or os.path.getsize(ZIP) < 500_000:
    ok = False
    for u in URLS:
        try:
            print("下载:", u)
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(ZIP, "wb") as f:
                data = r.read()
                f.write(data)
            print("  成功 %d 字节" % len(data))
            ok = True
            break
        except Exception as e:
            print("  失败:", str(e)[:140])
    if not ok:
        raise SystemExit("全部下载源失败")
else:
    print("复用已下载:", ZIP, os.path.getsize(ZIP))

with zipfile.ZipFile(ZIP) as z:
    names = z.namelist()
    print("\n=== 压缩包内容 ===")
    for n in names:
        try:
            info = z.getinfo(n)
            print("  %-58s %9d" % (n, info.file_size))
        except KeyError:
            pass
    z.extractall(DEST)
print("\n解压到:", DEST)

print("\n=== 解压后文件 ===")
for f in sorted(os.listdir(DEST)):
    p = os.path.join(DEST, f)
    print("  %-58s %9d" % (f, os.path.getsize(p) if os.path.isfile(p) else -1))
