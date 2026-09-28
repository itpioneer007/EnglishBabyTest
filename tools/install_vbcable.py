# -*- coding: utf-8 -*-
"""安装 VB-CABLE 虚拟声卡（静默、可验证、可回滚）。

为什么需要它：
   路线① 「Windows TTS → 虚拟声卡 → MuMu 麦克风」里，虚拟声卡是唯一硬依赖。
   本机音频端点枚举里没有 Stereo Mix（Intel SST 智音技术不暴露），必须自建一个。

安装器实测是 WiX bundle（含 UpdateDriverForPlugAndPlayDevices），
因此支持 /quiet /norestart 静默安装。

⚠ 需要管理员权限：脚本会用 ShellExecuteExW(runas) 触发一次 UAC，请点「是」。
   若点了「否」，ShellExecuteExW 会以 ERROR_CANCELLED(1223) 返回，脚本会明确提示。

用法：
    python tools/install_vbcable.py            # 安装
    python tools/install_vbcable.py --check    # 只看状态
"""
import ctypes
import os
import subprocess
import sys
import time
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "tmp_gen", "vbcable", "VBCABLE_Setup_x64.exe")
OUT = os.path.join(ROOT, "tmp_gen", "install_vbcable.txt")

PROP = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
CAPTURE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"


def endpoints():
    """返回 (render_names, capture_names)。"""
    res = {}
    for label, sub in (("render", RENDER), ("capture", CAPTURE)):
        names = []
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub)
        except OSError:
            res[label] = names
            continue
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(k, i)
                i += 1
            except OSError:
                break
            try:
                pk = winreg.OpenKey(k, guid + r"\Properties")
                try:
                    v, _ = winreg.QueryValueEx(pk, PROP)
                    names.append(v)
                except OSError:
                    pass
                winreg.CloseKey(pk)
            except OSError:
                pass
        winreg.CloseKey(k)
        res[label] = names
    return res


def cable_state():
    ep = endpoints()
    return ([n for n in ep["render"] if "CABLE" in n.upper()],
            [n for n in ep["capture"] if "CABLE" in n.upper()])


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_elevated(exe, params, cwd):
    """ShellExecuteExW(runas) 并等待进程结束。返回 (ok, code, msg)。"""
    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p),
            ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p),
            ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p),
            ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p),
            ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong),
            ("hIcon", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NOASYNC = 0x00000100
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = params
    info.lpDirectory = cwd
    info.nShow = 1

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == 1223:
            return False, err, "用户在 UAC 弹窗点了「否」（ERROR_CANCELLED）"
        return False, err, "ShellExecuteExW 失败 err=%d" % err

    h = info.hProcess
    if not h:
        return True, 0, "已启动（无句柄，无法等待）"
    WAIT_TIMEOUT = 0x00000102
    r = ctypes.windll.kernel32.WaitForSingleObject(h, 300_000)  # 最多 5 分钟
    code = ctypes.c_ulong(0)
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    if r == WAIT_TIMEOUT:
        return False, code.value, "等待安装进程超时"
    return True, code.value, "进程已退出"


def main():
    check_only = "--check" in sys.argv
    lines = []
    lines.append("is_admin(当前进程) = %s" % is_admin())

    r0, c0 = cable_state()
    lines.append("安装前 CABLE 端点: 播放=%s 录音=%s" % (r0, c0))
    if r0 and c0:
        lines.append(">>> 已安装，无需重复安装")
        text = "\n".join(lines)
        open(OUT, "w", encoding="utf-8").write(text)
        print(text)
        return 0

    if check_only:
        lines.append(">>> 未安装（--check 模式不执行安装）")
        text = "\n".join(lines)
        open(OUT, "w", encoding="utf-8").write(text)
        print(text)
        return 1

    if not os.path.exists(SETUP):
        lines.append("!! 找不到安装器: %s" % SETUP)
        text = "\n".join(lines)
        open(OUT, "w", encoding="utf-8").write(text)
        print(text)
        return 2

    lines.append("")
    lines.append(">>> 触发 UAC 提权安装（请在弹出的窗口点「是」）")
    lines.append("    %s /quiet /norestart" % SETUP)
    ok, code, msg = run_elevated(SETUP, "/quiet /norestart",
                                 os.path.dirname(SETUP))
    lines.append("提权结果: ok=%s code=%s msg=%s" % (ok, code, msg))

    # 轮询端点出现（驱动创建设备可能滞后几秒）
    appeared = False
    for i in range(20):
        time.sleep(3)
        r, c = cable_state()
        if r or c:
            lines.append("第 %ds 检测到 CABLE: 播放=%s 录音=%s" % ((i + 1) * 3, r, c))
            appeared = True
            break
    if not appeared:
        r, c = cable_state()
        lines.append("120s 内未出现 CABLE 端点（播放=%s 录音=%s）" % (r, c))

    lines.append("")
    lines.append("=== 安装后全量端点 ===")
    ep = endpoints()
    for k in ("render", "capture"):
        lines.append("[%s]" % k)
        for n in ep[k]:
            lines.append("   %s" % n)

    text = "\n".join(lines)
    open(OUT, "w", encoding="utf-8").write(text)
    print(text)
    return 0 if appeared else 3


if __name__ == "__main__":
    sys.exit(main())
