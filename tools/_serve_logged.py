# -*- coding: utf-8 -*-
"""内部启动器：把 web_server 的 stdout/stderr 落盘后再跑它。

存在的理由：用 WMI 创建进程时，若把 `cmd /c "... 1>log 2>log"` 这种带重定向的
命令串塞进 Win32_Process.Create，反斜杠+引号在 PowerShell/cmd 两层转义中极易出错。
改由本脚本自己接管文件描述符，WMI 命令行只需 `python tools/_serve_logged.py`。

⚠ Flask 的访问日志（werkzeug access log）走 stderr → 看 server_error.log。
"""
import io
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

# ★ 2026-09-20 新增：目标设备（真机 / MuMu 模拟器）选择。
#   为什么不能只靠环境变量：WMI 的 Win32_Process.Create **不继承**调用方的环境变量，
#   而 web_server 的分辨率探测/坐标缩放、以及 u2.connect() 都读 ANDROID_SERIAL。
#   结果：重启后服务总是回到 config.yaml 里的真机 serial（实测"检测到分辨率 1080x2400"），
#   双设备同时在线时还会直接报 more than one device/emulator。
#   改为由 restart_server.py --device 落盘到 server_target.txt，这里读回并注入环境变量。
_target = os.environ.get("ANDROID_SERIAL", "").strip()
if not _target:
    _tf = os.path.join(ROOT, "server_target.txt")
    if os.path.exists(_tf):
        with io.open(_tf, encoding="utf-8") as _fh:
            _target = _fh.read().strip()
if _target:
    os.environ["ANDROID_SERIAL"] = _target
    print(f"[target] ANDROID_SERIAL = {_target}")

sys.stdout = io.TextIOWrapper(
    open(os.path.join(ROOT, "server_output.log"), "wb", buffering=0), encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(
    open(os.path.join(ROOT, "server_error.log"), "wb", buffering=0), encoding="utf-8", line_buffering=True)

runpy.run_path(os.path.join(ROOT, "web_server.py"), run_name="__main__")
