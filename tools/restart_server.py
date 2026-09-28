# -*- coding: utf-8 -*-
"""重启 web_server（改完模块代码后必须重启，否则 sys.modules 缓存旧代码）。

⚠ 为什么必须用 WMI 而不是 subprocess.Popen：
   本会话的 shell 运行在一个 Job Object 里，普通 Popen 创建的子进程属于同一 Job，
   shell 一退出，Job 就把子进程一起杀掉（实测：服务起来 3 秒后即消失、端口不再监听）。
   Win32_Process.Create 创建的进程挂在 WmiPrvSE 下，不属于该 Job，因此能长期存活。

用法：
    python tools/restart_server.py                      # 杀旧进程 + WMI 启新进程 + 等健康
    python tools/restart_server.py --check              # 只看当前是否在监听
    python tools/restart_server.py --device 127.0.0.1:16384   # 指定目标设备（MuMu）
    python tools/restart_server.py --device real              # 用 config.yaml 里的真机 serial
    python tools/restart_server.py --switch             # 真机 ↔ MuMu 来回切

⚠ 为什么要 --device：WMI 创建的进程不继承环境变量，而 web_server 的分辨率探测
   （坐标缩放）与 u2.connect() 都读 ANDROID_SERIAL。不指定就会回到 config.yaml 的
   真机 serial；真机与 MuMu 同时在线时还会直接报 more than one device/emulator。
"""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\19507\AppData\Local\Programs\Python\Python312\python.exe"
PORT = 5000
TARGET_FILE = os.path.join(ROOT, "server_target.txt")
MUMU_SERIAL = "127.0.0.1:16384"


def read_target():
    if os.path.exists(TARGET_FILE):
        with open(TARGET_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    return ""


def write_target(serial):
    """serial 为空字符串 = 回到 config.yaml 的 serial（真机）。"""
    with open(TARGET_FILE, "w", encoding="utf-8") as fh:
        fh.write(serial or "")
    print(f"[device] 目标设备 = {serial or '(config.yaml 默认/真机)'}")


def listen_pids(port=PORT):
    """返回监听指定端口的 PID 列表（netstat 解析，不依赖 wmic）。"""
    out = subprocess.run("netstat -ano", shell=True, capture_output=True, text=True,
                         encoding="gbk", errors="ignore").stdout
    pids = []
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            pid = line.split()[-1]
            if pid not in pids:
                pids.append(pid)
    return pids


def port_up(port=PORT, timeout=3):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as r:
            return r.status == 200, r.read(200).decode("utf-8", "ignore")
    except Exception as e:
        return False, str(e)


def spawn_via_wmi():
    """用 PowerShell 的 Win32_Process.Create 启一个脱离 Job 的进程。"""
    launcher = os.path.join(ROOT, "tools", "_serve_logged.py")
    ps = (
        "$ErrorActionPreference='Stop';"
        f"$r=([wmiclass]'Win32_Process').Create('\"{PY}\" \"{launcher}\"', '{ROOT}');"
        "Write-Output ('ReturnValue=' + $r.ReturnValue + ';PID=' + $r.ProcessId)"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", ps],
                       capture_output=True, text=True, encoding="gbk", errors="ignore")
    return (r.stdout or "").strip(), (r.stderr or "").strip()


def main():
    if "--check" in sys.argv:
        up, msg = port_up()
        print(f"target={read_target() or '(config.yaml 默认/真机)'} "
              f"listening_pids={listen_pids()} http_ok={up} {msg[:120]}")
        return 0

    # 0) 设备选择（写盘 → _serve_logged.py 读回注入 ANDROID_SERIAL）
    if "--switch" in sys.argv:
        write_target("" if read_target() else MUMU_SERIAL)
    elif "--device" in sys.argv:
        _i = sys.argv.index("--device")
        _val = sys.argv[_i + 1].strip() if _i + 1 < len(sys.argv) else ""
        if _val.lower() in ("real", "phone", "真机"):
            _val = ""
        write_target(_val)

    # 1) 杀掉旧进程
    for pid in listen_pids():
        print(f"[kill] PID {pid}")
        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True,
                       text=True, encoding="gbk", errors="ignore")
    time.sleep(1.5)
    if listen_pids():
        print("[fail] 旧进程未退出，端口仍被占用")
        return 1

    # 2) WMI 启新进程
    out, err = spawn_via_wmi()
    print(f"[wmi] {out or '(无输出)'}")
    if err:
        print(f"[wmi-err] {err[:300]}")

    # 3) 等健康
    for i in range(45):
        time.sleep(1)
        up, _ = port_up()
        if up:
            print(f"[ok] 服务已就绪（{i + 1}s）PID={listen_pids()}")
            return 0
    print("[fail] 45s 内未就绪；日志尾部：")
    for f in ("server_error.log", "server_output.log"):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                print(f"--- {f} ---\n{fh.read()[-700:].decode('utf-8', 'ignore')}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
