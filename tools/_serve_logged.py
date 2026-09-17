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

sys.stdout = io.TextIOWrapper(
    open(os.path.join(ROOT, "server_output.log"), "wb", buffering=0), encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(
    open(os.path.join(ROOT, "server_error.log"), "wb", buffering=0), encoding="utf-8", line_buffering=True)

runpy.run_path(os.path.join(ROOT, "web_server.py"), run_name="__main__")
