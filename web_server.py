#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
英语宝模块检测 - Web 控制面板
Flask 后端，提供 REST API 和前端页面

启动:
    cd 英语宝模块检测
    python web_server.py

打开浏览器访问: http://localhost:5000
"""

import os
import sys
import io

# Windows 控制台默认 GBK 无法输出 emoji(✅❌⚠ 等)，全局切换为 UTF-8
# ★ 必须用 reconfigure 而非替换对象：替换 sys.stdout 会让原 wrapper 被 GC
#   时连带关闭共享 buffer，导致 "I/O operation on closed file" 崩溃
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
import json
import time
import threading
import re
import subprocess as sp
from pathlib import Path
from datetime import datetime

# 添加 src 到路径
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flask import Flask, jsonify, request, send_from_directory, render_template, Response
try:
    from adb_controller import ADBController
except ImportError:
    # 依赖缺失时占位，保证服务可启动（听力专项新引擎不依赖 ADBController）
    class ADBController:
        def __init__(self, *a, **kw): pass
from config_loader import load_config

app = Flask(__name__)

# ============================================================
# 三人协作路由注册（按角色拆分）
#   A: routes/trace_routes.py  → 溯源系统
#   B: routes/batch_routes.py  → 批量自动化
#   C: routes/export_routes.py → 报告输出分发
# ============================================================
from routes import register_trace, register_batch, register_export
register_trace(app)
register_batch(app)
# ★ 导出优先读内存 _inspection_state（多模块检测含全部模块；文件会被新任务覆盖）
register_export(app, state_provider=lambda: _inspection_state)
# ★ 借鉴队友：实时错题报告路由（/api/errors/live、/api/errors/live-status）
import routes.error_log_routes as _error_log_routes
_error_log_routes.register(app)

# ============================================================
# 全局状态
# ============================================================
task_status = {
    "running": False,
    "current_task": "",
    "progress": [],
    "start_time": "",
    "end_time": "",
    "log": [],
}

_last_screenshot = ""

# ★ 协作式停止标志（多模块检测用）：前端点停止 → True → 模块循环/答题循环中断
_STOP_REQUESTED = False
_STOP_LOCK = threading.Lock()

# ★ 当前活动任务线程 id（用于"立即停止"：停止时向该线程注入异常）
_CURRENT_TASK_THREAD_ID = None
_TASK_THREAD_LOCK = threading.Lock()


def _register_task_thread():
    """记录当前任务线程 id（各 run 接口启动线程时调用）"""
    global _CURRENT_TASK_THREAD_ID
    with _TASK_THREAD_LOCK:
        _CURRENT_TASK_THREAD_ID = threading.get_ident()


def _force_stop_thread():
    """强制中断当前任务线程：向线程注入 SystemExit（立即停止，不再执行脚本内容）

    Python 线程无法直接 kill，但可通过 PyThreadState_SetAsyncExc 向目标线程
    注入异常——异常在线程下一条 Python 字节码处抛出（若阻塞在 HTTP/sleep，
    则等待其返回后立即抛出，最长受 u2 HTTP_TIMEOUT=15s 限制）。
    """
    global _CURRENT_TASK_THREAD_ID
    with _TASK_THREAD_LOCK:
        tid = _CURRENT_TASK_THREAD_ID
    if not tid:
        return False
    try:
        import ctypes
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(tid), ctypes.py_object(SystemExit))
        if res > 1:  # 注入失败（异常被吞）时撤销
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
        return res == 1
    except Exception:
        return False


def _is_stop_requested():
    """线程安全读取停止标志（供 scheduler/engine/模块循环调用）"""
    global _STOP_REQUESTED
    with _STOP_LOCK:
        return _STOP_REQUESTED


def _request_stop():
    """统一停止入口：设置协作式停止标志 + 向任务线程注入 SystemExit 强制中断

    所有停止接口（modules/stop、inspect/stop、audio/stop 等）必须走这里，
    否则只改 running=False 无法真正停止脚本（线程内部不检查 running）。
    返回 True 表示已向任务线程发送强制中断信号。
    """
    global _STOP_REQUESTED
    if not task_status["running"]:
        return False, "没有正在运行的任务"
    # 1. 设协作式标志（scheduler/engine/模块循环内的 should_stop() 立即感知）
    with _STOP_LOCK:
        _STOP_REQUESTED = True
    # 2. 立即强制中断线程（下一条 Python 字节码处抛 SystemExit；若阻塞在
    #    u2 HTTP/time.sleep，最长等 HTTP_TIMEOUT=15s 返回后立即抛出）
    forced = _force_stop_thread()
    log_msg("⏹ 收到停止请求，立即中断任务…", "warning")
    if not forced:
        log_msg("⚠ 强制中断未生效，任务将在当前步骤结束后停止", "warning")
    return forced, ("停止信号已发送，任务已中断" if forced
                    else "停止信号已发送，等待当前步骤结束")

# 模块坐标（从 uiautomator dump 获取的精确坐标）
MODULE_COORDS = {
    # 教材精学 (人教版下的坐标)
    "课本点读(左)": (203, 1191),
    "课本点读(中)": (540, 1191),
    "巧记单词":     (876, 1191),
    "语音评测":     (203, 1358),
    # 专项突破 (可见)
    "听课文":    (161, 1792),
    "课文动画":  (414, 1792),
    "基础训练":  (666, 1792),
    "一课一练":  (919, 1792),
    "课文配音":  (161, 2033),
    "口语训练":  (414, 2033),
    "复习回顾":  (666, 2033),
    "全脑记词":  (919, 2033),
    # 专项突破 (需滚动)
    "单元自检":      (414, 746),
    "单元练习计划":  (666, 746),
    # 听力专项 (需滚动更深)
    "基础巩固":   (180, 1250),   # 听力专项下的三个阶段
    "综合进阶":   (540, 1250),
    "难点突破":   (900, 1250),
    "听力专项_五上": (414, 1250),   # 五上入口
    "听力专项_五下": (414, 950),    # 五下入口
    "听力专项_六上": (414, 1150),   # 六上入口
    "听力专项_六下": (414, 1050),   # 六下入口
}

# 需要先滚动才能看到的模块
DEEP_MODULES = {
    "单元自检",
    "单元练习计划",
    "教材同步题库",
    "听力训练",
    "你听一刻",
    # 听力专项下的内容
    "基础巩固",
    "综合进阶",
    "难点突破",
    "听力专项_五上",
    "听力专项_五下",
    "听力专项_六上",
    "听力专项_六下",
}

# 底部导航坐标
TABS = {
    "英语": (108, 2233),
    "我":   (972, 2220),
}

SETTINGS_ICON = (1000, 170)
AD_CLOSE = (540, 1821)

# ---- 模块自动识别 ----

# 文件名关键词 → 模块名 + 导航方式
MODULE_PATTERNS = {
    # (关键词列表, 模块名, 区域, 点击坐标)
    ("巧记单词", "巧记",): ("巧记单词", "教材精学", (876, 1191)),
    ("听力专项", "听力",): ("听力专项", "专项突破", None),  # None = 滚动搜索
    ("知识过关", "知识",): ("知识过关", "专项突破", None),
    ("基础训练",): ("基础训练", "专项突破", (666, 1792)),
    ("一课一练",): ("一课一练", "专项突破", (919, 1792)),
    ("复习回顾",): ("复习回顾", "专项突破", (666, 2033)),
    ("全脑记词",): ("全脑记词", "专项突破", (919, 2033)),
}

def detect_module_from_filename(filename: str):
    """从文件名提取模块名和导航方式, 返回 (module_name, section, coords) 或 None"""
    for keywords, (name, section, coords) in MODULE_PATTERNS.items():
        for kw in keywords:
            if kw in filename:
                return name, section, coords
    return None, None, None


# ============================================================
# 工具函数
# ============================================================


# ============================================================
# 自动坐标缩放 — 适配不同分辨率手机
# ============================================================
REFERENCE_RES = (1080, 2400)
_detected_res = None
_scale_x = 1.0
_scale_y = 1.0

# ★ 2026-10-16：原始（1080×2400 基准）坐标快照。
#   根因：scale_all_coords() 会把 MODULE_COORDS 等**就地替换**成缩放后的值。此前它
#   只在进程启动时调用一次，所以没人发现它**不可重复调用**——第二次调用会在"已缩放"
#   的值上再乘一次缩放比（MuMu 上 = 再 ×0.833/×0.667，坐标彻底跑飞）。
#   而修复"运行中换设备后坐标不变"又必须能重复调用 → 故留存一份不可变原始值，
#   每次都从原始值重算。
_COORD_REFS = None

def _capture_coord_refs():
    """首次调用时留存原始坐标（幂等）。"""
    global _COORD_REFS
    if _COORD_REFS is None:
        _COORD_REFS = {
            "MODULE_COORDS": dict(MODULE_COORDS),
            "TABS": dict(TABS),
            "SETTINGS_ICON": tuple(SETTINGS_ICON),
            "AD_CLOSE": tuple(AD_CLOSE),
            "MODULE_PATTERNS": dict(MODULE_PATTERNS),
        }
    return _COORD_REFS

def _intended_serial(serial: str = "") -> str:
    """本次要操作的目标设备串号。

    优先级：显式入参 → ANDROID_SERIAL → server_target.txt → config.yaml

    ★ 2026-10-16 新增。原来只有 `ANDROID_SERIAL or config.device.serial`：一旦环境
      变量没生效（例如重启没走 tools/_serve_logged.py，或启动时设备还没就绪），就会
      **静默**回落到 config.yaml 里的真机串号——而操作者以为自己控的是 MuMu。
      这里把 server_target.txt（restart_server.py --device 落盘的目标）纳入优先级，
      并与 /api/status 口径统一，让"到底在控哪台"始终可解释。
    """
    if serial and str(serial).strip():
        return str(serial).strip()
    env = os.environ.get("ANDROID_SERIAL", "").strip()
    if env:
        return env
    try:
        tf = os.path.join(PROJECT_ROOT, "server_target.txt")
        if os.path.exists(tf):
            with open(tf, encoding="utf-8") as fh:
                t = fh.read().strip()
            if t:
                return t
    except Exception:
        pass
    try:
        return load_config().device.serial or ""
    except Exception:
        return ""


# ★ 2026-10-16 新增：目标设备「智能对齐」----------------------------------------
#   背景：_intended_serial() 只做**配置解析**（显式 → ANDROID_SERIAL → server_target.txt
#   → config.yaml），它并不知道"这台设备现在到底连没连"。于是出现两种不可解释的状态：
#     ① server_target.txt 残留上一轮的目标（如 127.0.0.1:16384），把 config.yaml 里
#        正确的真机串号压掉 —— 本次明明插着真机测试，日志却一直显示"目标=MuMu"；
#     ② 目标离线时坐标缩放按基准算，操作者却以为一切正常。
#   这里补一层：**目标不可达且另有在线设备时自动改用在线设备**，并把
#   "改用了谁 / 为什么" 同时透出到服务日志与 /api/status，让状态始终自解释。
_AUTO_DEV_TTL = 3.0          # adb devices 结果缓存时间（/api/status 每 2s 轮询）
_auto_dev_cache = {"t": 0.0, "list": []}


def _is_real_device(serial: str) -> bool:
    """真机判定：串号**非空**且不含 host:port（模拟器 / 网络 adb 都是 `127.0.0.1:16384` 形态）。

    ⚠ 空串必须返回 False：`":" not in ""` 为 True，若不显式排空会把"没有设备"也算成
      一台真机（回归测试 T1 抓到）。
    """
    s = (serial or "").strip()
    return bool(s) and ":" not in s


def _pick_online(online) -> str:
    """从在线设备里挑一台：优先真机（USB），其次第一台。"""
    real = [s for s in online if _is_real_device(s)]
    return (real or list(online))[0]


def _online_serials(force: bool = False):
    """当前 adb 在线设备串号（state=device）；默认 3s 内复用缓存。

    只走 adbutils / `adb devices`，**不 import u2** —— /api/status 每 2s 轮询也扛得住。
    """
    now = time.time()
    if not force and (now - _auto_dev_cache["t"]) < _AUTO_DEV_TTL:
        return list(_auto_dev_cache["list"])
    out = []
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        from common.device import list_devices
        out = [d.get("serial") for d in list_devices()
               if d.get("serial") and d.get("state") == "device"]
    except Exception:
        out = []
    if not out:      # adbutils 不可用时的退化路径：直接问 adb
        try:
            r = sp.run([ADBController._find_adb(), "devices"],
                       capture_output=True, text=True, timeout=5,
                       encoding="utf-8", errors="replace")
            for ln in (r.stdout or "").splitlines()[1:]:
                parts = ln.split()
                if len(parts) >= 2 and parts[1] == "device":
                    out.append(parts[0])
        except Exception:
            pass
    _auto_dev_cache["t"] = now
    _auto_dev_cache["list"] = list(out)
    return out


def resolve_target_serial(preferred: str = ""):
    """把「配置声明的目标」与「实际在线设备」对齐，返回 (serial, info)。

    规则（**只在目标不可达时才替代**，避免"操作者明明在看 MuMu 却被切到真机"）：
      1) preferred 在线               → 原样使用，source='configured'
      2) preferred 离线且另有在线设备 → 改用在线设备（优先真机），source='auto'
      3) preferred 为空且另有在线设备 → 改用在线设备，source='auto'
      4) 无任何在线设备               → 仍返回 preferred，source='configured'（交由预检报错）
    """
    pref = (preferred or "").strip() or _intended_serial()
    online = _online_serials()
    info = {"configured": pref, "serial": pref, "source": "configured",
            "substituted": False, "online": list(online)}
    if pref and pref in online:
        return pref, info
    if online:
        pick = _pick_online(online)
        info.update(serial=pick, source="auto", substituted=True)
        return pick, info
    return pref, info


def _log_device_choice(info: dict, reason: str = ""):
    """设备选择结果打一条可读日志（被替代时用 ⚠ 醒目标注）。"""
    if info.get("substituted"):
        print(f"  [设备选择] ⚠ 配置目标 {info['configured'] or '(未指定)'} 不在线 "
              f"→ 已自动改用在线设备 {info['serial']}"
              f"（在线: {info['online']}；原因: {reason or '目标不可达'}）")
    return info


def detect_screen_resolution(adb_serial: str = ""):
    """通过 ADB 检测手机实际分辨率，更新缩放比。

    ★ 2026-10-16：每次探测前先把缩放**复位为 1:1**。原来失败时保留上一次的值，
      更容易掩盖问题；复位后"探测失败"必定表现为 1:1，与日志告警一致、可解释。
    """
    global _detected_res, _scale_x, _scale_y
    _detected_res, _scale_x, _scale_y = None, 1.0, 1.0
    try:
        # ★ 跨机器自动定位 adb（复用 ADBController 的探测逻辑，不写死任何用户路径）
        adb_path = ADBController._find_adb()
        cmd = [adb_path]
        if adb_serial:
            cmd.extend(["-s", adb_serial])
        cmd.extend(["shell", "wm", "size"])
        r = sp.run(cmd, capture_output=True, text=True, timeout=5,
                   encoding="utf-8", errors="replace")
        m = re.search(r"(\d+)x(\d+)", r.stdout)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            _detected_res = (w, h)
            _scale_x = w / REFERENCE_RES[0]
            _scale_y = h / REFERENCE_RES[1]
            print(f"  [坐标缩放] 检测到分辨率 {w}x{h}, 缩放比 X={_scale_x:.3f} Y={_scale_y:.3f}")
        else:
            print(f"  [坐标缩放] ⚠ 无法解析分辨率（设备 {adb_serial or '默认'} 可能未连接）: "
                  f"{r.stdout.strip()!r} → 坐标按基准 "
                  f"{REFERENCE_RES[0]}x{REFERENCE_RES[1]} 使用")
    except Exception as e:
        print(f"  [坐标缩放] ⚠ 检测失败: {e}, 使用默认1:1")

def sc(x: int, y: int) -> tuple:
    """缩放单个坐标点"""
    return (int(x * _scale_x + 0.5), int(y * _scale_y + 0.5))

def sc_xy(xy: tuple) -> tuple:
    """缩放一个 (x, y) 元组"""
    return sc(xy[0], xy[1])

def scale_all_coords():
    """按当前缩放比重算所有坐标字典，使之适配当前手机分辨率。

    ★ 2026-10-16 起**可重复调用**（每次都从 _capture_coord_refs() 的原始快照重算，
      不会二次缩放）。原来开头有 `if _scale_x == 1.0 and _scale_y == 1.0: return`
      的早退，重复调用时行为不一致，已移除。
    """
    global MODULE_COORDS, TABS, SETTINGS_ICON, AD_CLOSE, MODULE_PATTERNS
    ref = _capture_coord_refs()
    MODULE_COORDS = {k: sc_xy(v) for k, v in ref["MODULE_COORDS"].items()}
    TABS = {k: sc_xy(v) for k, v in ref["TABS"].items()}
    SETTINGS_ICON = sc_xy(ref["SETTINGS_ICON"])
    AD_CLOSE = sc_xy(ref["AD_CLOSE"])
    # ★ 修复：MODULE_PATTERNS 中的坐标也需要缩放
    MODULE_PATTERNS = {k: (v[0], v[1], sc_xy(v[2]) if v[2] else None)
                       for k, v in ref["MODULE_PATTERNS"].items()}
    print(f"  [坐标缩放] 所有坐标已重算 ({REFERENCE_RES[0]}x{REFERENCE_RES[1]} -> "
          f"{_detected_res or '未探测到，按基准'})")

def refresh_device_scale(serial: str = "", reason: str = "", allow_substitute=None) -> dict:
    """按当前（或指定）目标设备重新探测分辨率并重算坐标缩放；可随时调用。

    ★ 2026-10-16 新增。根因：坐标缩放原来只在进程启动那一刻算一次（见文件末尾
      __main__ 块），而 /api/device/select 允许运行中换设备、ANDROID_SERIAL 也可能在
      启动之后才有效 —— 一旦"启动时目标设备未就绪"，缩放就永久停在 1:1（或停在旧
      设备的值），所有走 sc() 的坐标全部失准，且前端看不到任何提示。

    ★ 2026-10-16 追加：`allow_substitute` 决定是否允许与**实际在线设备**对齐。
      - 不传（默认）：**显式传了 serial 就不替代、没传就替代**。
      - 为什么这样分：`serial` 是非空即代表"调用方已明确选定这台"（如
        /api/device/select 的用户选择、run 路径已 resolve 过的结果），此时擅自换成
        别的设备会让"u2 连的"与"缩放算的"错位；而不传 serial 时目标来自配置解析
        （env / server_target.txt / config.yaml），target 离线就该让位给在线设备。
      - run 路径显式传 allow_substitute=False：那里已由 resolve_target_serial() 对齐过，
        再折一次只会把结果搅乱。
    """
    _configured = _intended_serial(serial)
    if allow_substitute is None:
        allow_substitute = not (serial or "").strip()
    if allow_substitute:
        _s, _dev = resolve_target_serial(_configured)
        _log_device_choice(_dev, reason=reason or "刷新坐标缩放")
    else:
        _s = _configured
        _dev = {"configured": _configured, "serial": _s, "source": "explicit",
                "substituted": False, "online": _online_serials()}
    before = (_detected_res, _scale_x, _scale_y)
    detect_screen_resolution(_s)
    scale_all_coords()
    info = {
        "serial": _s,
        "configured": _configured,
        "source": _dev["source"],
        "substituted": _dev["substituted"],
        "online": _dev["online"],
        "resolution": list(_detected_res) if _detected_res else None,
        "scale": [_scale_x, _scale_y],
        "ok": _detected_res is not None,
        "before": list(before),
        "reason": reason or "手动",
    }
    print(f"  [坐标缩放] 刷新（{info['reason']}）: 目标={_s}"
          + (f"（配置目标 {_configured} 不在线，已自动替代）" if _dev["substituted"] else "")
          + f" 分辨率={info['resolution']} 缩放=X{_scale_x:.3f}/Y{_scale_y:.3f}")
    return info

def _preflight_target_device():
    """任务开始前的设备预检：目标设备必须可达，同时刷新坐标缩放。

    返回 (ok, message)。判据用 `adb shell wm size`（毫秒级）；拿不到分辨率即说明
    目标设备不可达 —— 此时**明确报错拒绝开始**，而不是静默回落到 config.yaml 的真机
    去操作一台操作者根本没在看设备。
    """
    try:
        info = refresh_device_scale(reason="任务开始前预检")
    except Exception as e:
        return False, f"设备预检异常: {e}"
    # 把最终目标写回 ANDROID_SERIAL：u2.connect() 与刚探测到的分辨率必须指向同一台，
    # 否则多设备在线时读环境变量为空会直接报 "more than one device/emulator"。
    if info.get("serial"):
        try:
            sys.path.insert(0, str(Path(__file__).parent / "scripts"))
            from common.device import set_device as _set_dev_pre
            _set_dev_pre(info["serial"])
        except Exception:
            pass
    if info["ok"]:
        return True, ""
    _s = info["serial"] or "(未指定)"
    _cfg = info.get("configured") or ""
    online = info.get("online")
    if not online:
        # 兼容性兜底：调用方只提供了 serial/ok（老桩或旧调用点）时，现查一次在线设备，
        # 保证报错信息始终告诉人"该切到哪台"。
        try:
            online = [d.get("serial") for d in _device_list() if d.get("serial")]
        except Exception:
            online = []
    _extra = ""
    if info.get("substituted"):
        _extra = f"（配置目标 {_cfg} 不在线，已尝试自动改用在线设备 {_s}）"
    return False, (
        f"目标设备 {_s} 不可达（adb wm size 无返回，分辨率探测失败）。{_extra}"
        f"当前在线设备: {online if online else '无'}。"
        f"请先启动目标模拟器/连接真机并确认 ADB 已就绪，或在页面上把设备切换为在线设备。"
    )


def get_adb():
    """获取 ADBController 实例 (截图保存到 screenshots/)"""
    config = load_config()
    # 用相对路径避免 adb pull 在 Windows 上拼接出错
    return ADBController(serial=config.device.serial, screenshot_dir="screenshots")




# ★ 2026-08-30 修复脚本审查日志重复：模块级去重 + "完成"字严格匹配
    #   之前任何消息含"完成"就触发，导致"全部检测完成"也触发了一次重查。改成按
    #   (模块, 阶段) 维度去重 + 严格"模块完成"正则匹配。
_detect_content_invoked: set = set()
_DIM_INVOKED_KW = re.compile(r"^[✅⏹❌]*\s*[A-Za-z0-9一-鿿·（）()]+?\s*完成[:：]")  # 形如"巧记单词 完成："
def _detect_content_dimension(module: str = ""):
    """自动补充内容检查（LLM 批量知识性审查）

    ★ 修复：必须按当前模块匹配脚本，否则无脚本模块会拿任意最新脚本错配比对
      - module 为空 → 不比对（无模块上下文）
      - 该模块在 docx_map 中无匹配脚本 → 跳过（仅基础完整性）
      - 有匹配脚本 → 用该模块的脚本比对
    ★ 2026-08-30 修复：模块级去重（_detect_content_invoked 集合）
    """
    try:
        if not module:
            return
        # ★ 模块级去重：同一模块的脚本审查只触发一次
        _cur_stage = ""
        try:
            from common.logger import get_current_module as _gcm2
            _, _cur_stage = _gcm2()
        except Exception:
            pass
        _key = (module, _cur_stage)
        if _key in _detect_content_invoked:
            return  # 同一模块同一阶段已审查过 → 跳过（不再因后续"完成"字触发）
        # ★ 该模块的匹配脚本（多模块检测时 docx_map 已构建；单模块/快速检查无映射则跳过）
        _docx = (_GLOBAL_DOCX_MAP or {}).get(module, "")
        if not _docx:
            _set_script_provenance(module, "", False, "未挂载脚本（docxMap 无该模块映射）")
            return
        docx_path = PROJECT_ROOT / "uploads" / _docx
        if not docx_path.exists():
            _set_script_provenance(module, _docx, False, f"脚本文件不存在：{_docx}")
            return
        # ★ 2026-09-20：版本/年级守卫（与 _run_llm_script_review 同源，防拿错脚本乱报）
        _mismatch = _script_matches_run(_docx,
                                        _inspection_state.get("version", ""),
                                        _inspection_state.get("grade", ""))
        if _mismatch:
            log_msg(f"⛔ {module}：{_mismatch} → 跳过批量内容检查"
                    f"（拿错年级/版本的脚本比对会报出根本没测过的题）", "warning")
            _set_script_provenance(module, _docx, False, _mismatch)
            return
        _set_script_provenance(module, _docx, True)
        # ★ 按当前模块单元过滤脚本（用户要求：脚本含多单元，只比对所选单元）
        #   从 _inspection_state 读当前单元（多模块检测启动时记录）
        # ★ 从 _inspection_state 读当前单元（多模块检测启动时记录）——防御"NONE"/非数字
        try:
            _unit_cur = int(str(_inspection_state.get("unit", 0) or 0).split("-")[0])
        except Exception:
            _unit_cur = 0
        from src.review_agent import ReviewAgent, ReviewConfig
        cfg = ReviewConfig(docx_path=str(docx_path), unit=_unit_cur, screenshot_dir="", verbose=False)
        agent = ReviewAgent(cfg)
        if not agent.script_questions: return
        _detect_content_invoked.add(_key)
        log_msg(f"📄 {module} 自动补充内容检查 (批量, {_docx}, 单元{_unit_cur or '全部'}, {len(agent.script_questions)}题)", "info")
        batch = []; qid_map = {}
        # ★ 听力专项多子模块：只审查当前 stage 的题（用户反馈：错题日志错误记录
        #   练习/测试的题——之前不过滤，练习的题也拿测试脚本去比对→脚本错配）
        _cur_mod, _cur_stage = "", ""
        try:
            from common.logger import get_current_module
            _cur_mod, _cur_stage = get_current_module()
        except Exception:
            pass
        for qid, q in list(_inspection_state.get("questions", {}).items()):
            # ★ stage 过滤：仅审查当前回调对应的 stage 题目
            #   ★ 2026-09-10 修复：必须限定在【脚本子模块名】白名单内才过滤。
            #   背景：巧记单词等模块现在会把 stage 设成定位标签（"U1 第1关"/"U1 boss关"），
            #   而内容审查回调发生在模块结束时（此时 stage = 最后一个关卡）→
            #   若不加白名单，会只剩最后一关的题进入内容审查（其余题被全部过滤掉，
            #   表现为"内容维度大面积缺失"）。关卡标签不是子模块名，故白名单可精确区分。
            _q_stage = (q or {}).get("stage", "") or ""
            if _should_skip_by_stage(_cur_stage, _q_stage):
                continue
            idx = (q or {}).get("idx", 0)
            if not idx: continue
            # ★ 口语训练题卡对齐（2026-08-24 修复"脚本审查乱报"根因二）：
            #   口语训练模块记录 idx=小题号(1-5)+big(1-4)，而脚本 global_idx 是全局题号(1-20)。
            #   ⚠ 不能先按 global_idx 匹配：第3大题·第2小题(idx=2)会错配到脚本 Q02（朗读单词），
            #   必须优先按 (unit, big, stage_idx) 精确定位；无 big 的题卡（听力专项等）再走 global_idx。
            _q_big = (q or {}).get("big") or 0
            _q_no = (q or {}).get("module_qno") or 0
            sqs = []
            if _q_big and _q_no:
                sqs = [s for s in agent.script_questions
                       if s.unit == _unit_cur and s.big == _q_big and s.stage_idx == _q_no]
            if not sqs:
                sqs = [s for s in agent.script_questions if s.global_idx == idx]
            if not sqs: continue
            sq = sqs[0]
            stem = (getattr(sq, "stem", "") or "").strip()
            opts = "; ".join([o for o in (sq.options or []) if o]) or "(无)"
            ans = (getattr(sq, "answer", "") or "").strip() or "(无)"
            typ = (getattr(sq, "type_2", "") or "").strip() or "未知"
            # ★ 口语训练：定位描述用"第N大题·第M小题"（与 App 证据卡一致），非口语题保持 Q{idx}
            _pos = f"第{sq.big}大题·第{sq.stage_idx}小题" if getattr(sq, "big", 0) else f"Q{idx}"
            _caption = (getattr(sq, "caption", "") or "").strip()
            # ★ 唯一序号：口语训练多题共用 idx=小题号(1-5)，qid_map 不能用 idx 当 key（会互相覆盖）
            _batch_idx = len(batch) + 1
            batch.append(f"{_batch_idx}. {_pos}: 题型={typ}, 大题说明={(_caption or '(无)')[:45]}, 题干={stem or '(无)'}, 答案={ans}")
            qid_map[_batch_idx] = qid
        if not batch: return
        rules = ("规则:对每题做内容检查-1.知识性(PASS/REVIEW/REJECT)必须有依据才判错;"
                 "2.语言质量(拼写/语法/选项/搭配/语义)。"
                 '输出JSON数组:[{"idx":1,"verdict":"PASS/REVIEW/REJECT","basis":"判断依据","lang":["问题描述"]},...]'
                 "其中 idx 为上面列表中每题的序号(1,2,3...)。")
        prompt_text = f"批量内容审查:共{len(batch)}题\n" + "\n".join(batch) + "\n\n" + rules + "\n只输出JSON数组。"
        try:
            raw = (agent.llm.ask(prompt_text) or "").strip()
            if not raw:
                raise ValueError("LLM 返回空内容（可能请求超时/密钥失效）")
            # ★ 健壮解析：LLM 可能返回 markdown 围栏 / 前后说明文字 / 部分对象
            #   依次尝试：①整串JSON ②去markdown围栏 ③取 [] 区间 ④逐行对象
            data = None
            # ① 整串
            try:
                data = json.loads(raw)
            except Exception:
                pass
            # ② 去 markdown ```json ... ```
            if data is None:
                _m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
                if _m:
                    try:
                        data = json.loads(_m.group(1).strip())
                    except Exception:
                        pass
            # ③ 取 [ 到 ] 区间
            if data is None:
                _l, _r = raw.find("["), raw.rfind("]")
                if _l >= 0 and _r > _l:
                    try:
                        data = json.loads(raw[_l:_r+1])
                    except Exception:
                        pass
            # ④ 逐行找 { "idx":... } 对象
            if data is None:
                _objs = re.findall(r"\{[^{}]*\"idx\"\s*:\s*\d+[^{}]*\}", raw)
                if _objs:
                    try:
                        data = [json.loads(o) for o in _objs]
                    except Exception:
                        pass
            if data is None:
                raise ValueError(f"LLM 返回内容无法解析为 JSON: {raw[:80]!r}…")
            count = 0
            # ★ 查重：idx+stage 已存在时复用 qid（避免 LLM 审查与 engine.py 重复记录同一题）
            for item in data:
                qi = item.get("idx", 0)
                qid = qid_map.get(qi)
                if not qid or not _inspection_state["questions"].get(qid):
                    # 兜底：按 stage+idx 找已有 qid（避免 LLM qid 失效时丢失写入）
                    _existing_qid = None
                    for _k, _v in list(_inspection_state["questions"].items()):
                        if (_v.get("idx") == qi
                                and (_v.get("stage") or "") == (_cur_stage or "")):
                            _existing_qid = _k
                            break
                    if _existing_qid:
                        qid = _existing_qid
                    else:
                        continue
                q_obj = _inspection_state["questions"][qid]
                v = str(item.get("verdict","REVIEW")).upper()
                ls = item.get("lang") or []
                has_lang = len(ls) > 0
                # ★ REVIEW=待审（信息不足无法判断，如选项内容为空）→ 计未检(None)而非不通过
                #   用户实测：待审被当不通过 → 明明其他维度过却综合判定不通过
                # ★ 2026-09-20（用户反馈"有一点不符就判不通过不太好，要真能找出
                #   影响用户作答的内容"）：LLM 给 PASS、只是附带语言提醒（lang 非空）
                #   → 判**通过**，提醒附在 reason 里；只有 LLM 明确 REJECT 才判不通过。
                if v == "REVIEW":
                    passed = None
                    vv = "待审"
                elif v == "PASS":
                    passed = True
                    vv = "通过（附语言提示）" if has_lang else "通过"
                elif v == "REJECT":
                    passed = False
                    vv = "不通过"
                else:
                    passed = None
                    vv = "待审"
                b = (item.get("basis") or "")[:150]
                d = f"{vv}: {b}"
                for li in ls[:3]:
                    d += f"; 提示[{str(li)[:60]}]"
                q_obj["ai_content"] = passed
                q_obj["content_reason"] = d[:300]
                count += 1
            log_msg(f"🧪 内容检查已补充: {count}题 ({'通过' if count > 0 else ''})", "success")
        except Exception as e:
            _err = str(e)
            # ★ 友好识别常见 LLM 错误（配额/密钥/网络），给出可操作提示而非笼统报错
            if "403" in _err or "Free quota" in _err or "AllocationQuota" in _err:
                log_msg("⚠ 批量内容检查失败: 阿里云百炼免费额度已用完(403 Forbidden)。请在百炼控制台充值或关闭『仅使用免费额度』模式后重试", "warning")
            elif "401" in _err or "Invalid" in _err or "Authentication" in _err:
                log_msg("⚠ 批量内容检查失败: LLM API 密钥无效或过期(401)。请检查 .env 中的 LLM_API_KEY", "warning")
            elif "timed out" in _err.lower() or "Timeout" in _err:
                log_msg("⚠ 批量内容检查失败: LLM 请求超时。可稍后重试或分批检查", "warning")
            elif "返回空内容" in _err:
                log_msg(f"⚠ 批量内容检查失败: {_err[:100]}", "warning")
            else:
                log_msg(f"⚠ 批量内容检查失败: {_err[:80]}", "warning")
    except Exception as e:
        # ★ 2026-09-10 修复「⚠ 内容补充异常: 解析 .doc 需要 olefile 库」含义不清问题：
        #   根因是当前解释器缺 olefile（老式 .doc 为 OLE 复合文档，python-docx 不支持）。
        #   在 uploads/ 放了 .doc 脚本时必现；此处给出明确的安装指引 + 影响范围说明，
        #   而不是笼统的"内容补充异常"（用户无法判断是日志问题还是真问题）。
        _err = str(e)
        if "olefile" in _err or "解析 .doc" in _err or ".doc 需要" in _err:
            log_msg(
                "⚠ 内容补充异常: 脚本为 .doc 老格式(OLE)，当前 Python 缺 olefile 库。"
                "修复: 在 web_server 所用解释器执行 pip install olefile 后重试。"
                "（本次仅跳过 LLM 内容检查，不影响设备端 UI/作答检查）",
                "warning",
            )
        else:
            log_msg(f"⚠ 内容补充异常: {e}", "warning")




def log_msg(msg: str, level: str = "info", evidence: list = None):
    """添加日志, 可选附带结构化证据(审查差异高亮展示)"""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
        "level": level,
    }
    if evidence:
        entry["evidence"] = evidence
    task_status["log"].append(entry)

    # ★ 2026-08-30 修复重复日志：模块完成才能触发内容补充检查（不是任意"完成"字串）。
    #   用户实测 14:39:36 "巧记单词 自动补充内容检查 (批量 ...)" 重复2次：一次因为
    #   "巧记单词 完成：0题" 触发，另一次因为后面的"全部检测完成！..." 误触发了。
    #   改为:仅"X模块 完成"开头才触发（不会匹配"全部检测完成"）
    if isinstance(msg, str) and _DIM_INVOKED_KW.match(msg.strip()):
        # ★ 传当前模块：_detect_content_dimension 只在该模块有匹配脚本时比对
        _cm_cur = ""
        try:
            from common.logger import get_current_module as _gcm
            _cm_cur, _ = _gcm()
        except Exception:
            pass
        threading.Thread(target=_detect_content_dimension, args=(_cm_cur,), daemon=True).start()
    try:
        print(f"[{entry['time']}] [{level}] {msg}")
    except UnicodeEncodeError:
        # Windows GBK 控制台无法编码 emoji(✅❌ 等)，降级输出
        safe_msg = msg.encode("gbk", errors="replace").decode("gbk")
        print(f"[{entry['time']}] [{level}] {safe_msg}")

    # ★ 每题界面级完整性检查证据 → 同步写入审查结果区（多模块检测也能看到 AI 判断）
    #   触发条件：消息含"第N题 检查"且带 evidence（来自 engine.py _collect_ui_evidence）
    # ★ 2026-09-20 根因修复（口语训练 20 题只剩 4 题）：
    #   旧守卫 `if evidence and isinstance(evidence, list) and evidence:` 把
    #   **显式传入的空列表** 也当成"没传证据"→ 直接跳过登记。而口语训练为了
    #   避免重复证据卡，会把后续小题的证据消重成 [] 再 step_log →
    #   这些题从未进入 questions（只有每个大题第 1 小题被登记）。
    #   语义修正：None = 未传（普通流程日志）；[] = 传了（这确实是一道题，
    #   只是本轮没有可展示的证据，六个维度记为"未检"）。二者必须区分。
    if isinstance(evidence, list):
        try:
            # ★ 修复：兼容实际消息格式——"第1题 检查"(可能带前导空格) 与
            #   "第1题 完整性检查"(测试循环) 都能命中
            #   ★ 口语训练："第2大题·第3小题 完整性检查"（大题·小题精确定位）
            #   ★ 2026-08-25 修复：口语训练实际消息是
            #     "第1大题·第2小题（句型提示：xxx）完整性检查"——"小题"和"检查"之间
            #     夹着（题干内容）！旧正则要求紧跟导致匹配失败 → 界面证据从未写入，
            #     前端只有脚本审查结果（用户实测"没有实际测试记录，全是脚本审查"）
            #   ★★ 2026-09-20 根因修复（口语训练 20 题只剩 19 题）：
            #     08-25 那版仍是「中间恰好一个全角括号组」的写死结构
            #     —— `(?:（[^）]*）)?`。而 `[^）]*` 碰到题干自带的右括号就停，
            #     例：第3大题第1小题题干 = "第11题（仿照例句，说一说。）"，
            #     日志变成 "…小题（第11题（仿照例句，说一说。））完整性检查"，
            #     正则只吃到内层"）"，随后要求紧跟"完整性检查"→ 整体匹配失败
            #     → 该题证据被 except 静默吞掉，审查结果里凭空少一题。
            #     题目内容本来就是自由文本（可能含括号、标点、换行），
            #     不可能用"括号结构"去描述它 → 改成契约式匹配：
            #       「行首是第N[大]题·第M小题」+「消息里出现"检查"」
            #     题号提取与题干文本彻底解耦，对任意题干/任意模块都成立。
            m = re.match(r"\s*(?:第(\d+)大题·)?第(\d+)(?:题|小题)", msg)
            if m and "检查" in msg:
                _big = int(m.group(1)) if m.group(1) else None
                qidx = int(m.group(2))
                _record_module_evidence(qidx, msg, evidence, big=_big)
            elif "检查" in msg:
                # 带着证据、又明说"检查"，却定位不到题号 → 必须暴露，
                # 不能再像旧版那样静默丢弃（用户只会看到"少了几题"）
                log_msg(f"⚠ 逐题证据未入库（无法从日志定位题号）: {msg.strip()[:60]}",
                        "warning")
        except Exception as _e_ev:
            log_msg(f"⚠ 逐题证据入库异常: {str(_e_ev)[:120]}", "warning")

    # ★ 答错题目截图 → 同步到审查结果区（前端「最近截图」展示）
    #   触发条件：消息含"第N题 答错截图"且 evidence 带 type="wrong_shot" + screenshot 文件名
    if evidence and isinstance(evidence, list) and evidence:
        try:
            m = re.match(r"\s*(?:第(\d+)大题·)?第(\d+)(?:题|小题)\s*答错截图", msg)
            if m:
                qidx = int(m.group(2))
                shot = ""
                for e in evidence:
                    if e.get("type") == "wrong_shot":
                        shot = e.get("screenshot", "") or ""
                        break
                if shot:
                    key = f"auto-Q{qidx:03d}"
                    qs = _inspection_state.setdefault("questions", {})
                    # ★ 模块上下文（错题定位用）
                    try:
                        from common.logger import get_current_module
                        _cm, _cs = get_current_module()
                    except Exception:
                        _cm, _cs = "", ""
                    if not _cm:
                        _cm = _inspection_state.get("module", "")
                    if key in qs:
                        qs[key]["screenshot"] = shot
                    else:
                        # 该题无完整性检查记录（答题循环未发证据）→ 建一条错题记录
                        qs[key] = {
                            "idx": qidx,
                            "total": len(qs) + 1,
                            "module": _cm,
                            "stage": _cs,
                            "module_qno": qidx,
                            "question_type": "错题截图",
                            "screenshot": shot,
                            "progress": f"Q{qidx}",
                            "ai_stem": None, "ai_content": None, "ai_image": None,
                            "ai_answer": None, "ai_audio": None, "ai_post_error": None,
                            "overall_passed": None, "overall_score": 0.0,
                            "stem_reason": "", "content_reason": "", "image_reason": "",
                            "answer_reason": "", "audio_reason": "", "post_error_reason": "",
                            "stem": f"第{qidx}题（答错，已截图）", "options": "",
                            "script_answer": "", "note": "",
                        }
                    try:
                        _save_inspection_state()
                    except Exception:
                        pass
        except Exception:
            pass

# 注入共享日志通道：让 scheduler 和模块内部的流程日志也能送到前端
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from common.logger import set_log_callback, set_stop_check
set_log_callback(log_msg)
# 注入停止检查：让 engine/模块答题循环能感知前端"停止"请求
set_stop_check(lambda: _is_stop_requested())


# ★ 设备连接缓存：_connect_device 每次可能 5-20s（u2 初始化），错题自动截图
#   每题调用会严重拖慢 → 缓存成功连接，断连后自动重连
_DEV_CACHE = {"d": None}

def _connect_device():
    """连接当前选中的设备（带就绪检查 + 短超时 + 连接缓存）

    - 设置 u2 全局超时（默认 300s，设备断连时每个操作挂 5 分钟 = 看起来卡死）
    - 检查设备在线，未连接/离线 → 抛 RuntimeError（上层记 error 日志）
    - 整个连接过程硬超时 20s：u2.connect 初始化（装ATX/起server）可能很慢
    """
    import threading
    # ★ 缓存复用：已连接且设备在线 → 直接返回（错题截图每秒调用时避免 5-20s 重连）
    try:
        _cached = _DEV_CACHE.get("d")
        if _cached is not None:
            try:
                if _cached.info:
                    return _cached
            except Exception:
                _DEV_CACHE["d"] = None  # 连接失效 → 重连
    except Exception:
        pass
    result = {}
    def _do_connect():
        try:
            import uiautomator2 as u2
            u2.HTTP_TIMEOUT = 15
            u2.WAIT_FOR_DEVICE_TIMEOUT = 10
            try:
                from common.device import device_ok
                if not device_ok():
                    result["err"] = "设备未连接或离线，请先连接设备"
                    return
            except ImportError:
                pass
            d = u2.connect()
            if not d.info:
                result["err"] = "设备连接失败（u2 无响应）"
                return
            result["d"] = d
            _DEV_CACHE["d"] = d  # ★ 缓存成功连接
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
        except Exception as e:
            result["err"] = f"设备连接异常: {e}"
    t = threading.Thread(target=_do_connect, daemon=True)
    t.start()
    t.join(timeout=20)
    if t.is_alive():
        raise RuntimeError("设备连接超时（20s），请检查设备 uiautomator2 服务是否正常")
    if "err" in result:
        raise RuntimeError(result["err"])
    return result["d"]


def clear_status():
    """清空状态"""
    task_status["running"] = False
    task_status["current_task"] = ""
    task_status["progress"] = []
    task_status["start_time"] = ""
    task_status["end_time"] = ""
    task_status["log"] = []


def set_running(task_name: str):
    """设置为运行中"""
    clear_status()
    task_status["running"] = True
    task_status["current_task"] = task_name
    task_status["start_time"] = datetime.now().strftime("%H:%M:%S")


def set_done():
    """设置为完成"""
    task_status["running"] = False
    task_status["end_time"] = datetime.now().strftime("%H:%M:%S")


def _cleanup_task_state():
    """任务线程统一收尾：清 running 状态 + 重置停止标志（供正常/停止/异常所有路径调用）"""
    global _STOP_REQUESTED
    with _STOP_LOCK:
        _STOP_REQUESTED = False
    set_done()


def update_progress(step: int, total: int, msg: str):
    """更新进度"""
    entry = {"step": step, "total": total, "msg": msg}
    task_status["progress"].append(entry)


# ============================================================
# 后台任务函数
# ============================================================

def run_login_task():
    """后台执行登录"""
    try:
        set_running("login")
        adb = get_adb()
        config = load_config()

        log_msg("启动英语宝APP...")
        update_progress(1, 6, "启动APP")
        adb.launch_app(config.app.package)
        time.sleep(5)

        log_msg("关闭启动广告...")
        update_progress(2, 6, "关闭广告")
        adb.tap(*AD_CLOSE)
        time.sleep(2)

        log_msg("勾选协议...")
        update_progress(3, 6, "勾选协议")
        adb.click_element(text="我已阅读并同意", exact=False)
        time.sleep(1)

        log_msg("点击登录...")
        update_progress(4, 6, "点击登录")
        # 先按 exact 尝试
        if not adb.click_element(text="登录", exact=True):
            adb.tap(*sc(540, 1232))  # fallback: 登录按钮已知坐标
        time.sleep(3)

        log_msg("处理协议弹窗...")
        update_progress(5, 6, "协议弹窗")
        if adb.wait_for_element(text="同意", timeout=3):
            adb.click_element(resource_id="agree_tv", exact=False)
            time.sleep(3)

        log_msg("关闭广告弹窗...")
        adb.tap(*AD_CLOSE)
        time.sleep(2)

        adb.screenshot("login_done.png")
        log_msg("✅ 登录完成！", "success")
        update_progress(6, 6, "登录成功")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 登录失败: {e}", "error")
    finally:
        set_done()


def run_version_detect_task():
    """后台检测可用版本"""
    try:
        set_running("version_detect")
        config = load_config()
        adb = get_adb()

        log_msg("导航到版本选择页...")
        update_progress(1, 5, "进入'我'页")
        adb.tap(*TABS["我"])
        time.sleep(3)

        update_progress(2, 5, "进入设置")
        adb.tap(*SETTINGS_ICON)
        time.sleep(2)

        update_progress(3, 5, "进入个人信息")
        adb.click_element(text="个人信息", exact=True)
        time.sleep(2)

        update_progress(4, 5, "点击英语所学教材版本")
        adb.click_element(text="英语所学教材版本", exact=True)
        time.sleep(2)

        log_msg("截图版本选择页...")
        adb.screenshot("versions_page.png")
        update_progress(5, 5, "版本页已打开")

        # dump UI 获取版本列表
        elements = adb.dump_ui()
        versions = []
        for elem in elements:
            if elem.text and ("版" in elem.text or "年级" in elem.text):
                versions.append({
                    "text": elem.text,
                    "center": list(elem.center),
                    "bounds": list(elem.bounds),
                })

        # 保存到临时文件供 API 读取
        versions_file = PROJECT_ROOT / "outputs" / "web" / "versions.json"
        with open(versions_file, "w", encoding="utf-8") as f:
            json.dump(versions, f, ensure_ascii=False, indent=2)

        log_msg(f"✅ 检测到 {len(versions)} 个版本元素", "success")
        log_msg(f"  可用版本: {[v['text'] for v in versions]}")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 版本检测失败: {e}", "error")
    finally:
        set_done()


def run_full_task(version: str, grade: str, modules: list):
    """一键全流程：登录 → 切换版本 → 选年级 → 测模块 (加速版)"""
    try:
        set_running("full")
        config = load_config()
        adb = get_adb()

        total = 8 + len(modules) * 3
        cur = 0

        # 1. 启动APP
        cur += 1
        log_msg(f"{cur}/{total} 启动APP")
        adb.launch_app(config.app.package)
        time.sleep(4)

        # 2. 关广告
        cur += 1
        log_msg(f"{cur}/{total} 关广告")
        adb.tap(*AD_CLOSE)
        time.sleep(1)

        # 3. 登录 (仅当需要时)
        cur += 1
        log_msg(f"{cur}/{total} 检查登录状态")
        elements = adb.dump_ui()
        needs_login = any('登录' in (e.text or '') for e in elements)
        if needs_login:
            log_msg(f"  需要登录")
            adb.click_element(text="我已阅读并同意", exact=False)
            time.sleep(0.5)
            adb.click_element(text="登录", exact=True)
            time.sleep(2)
            if adb.wait_for_element(text="同意", timeout=3):
                adb.tap(*sc(540, 1550))
                time.sleep(1.5)
        else:
            log_msg(f"  已登录, 跳过", "success")
        adb.tap(*AD_CLOSE)
        time.sleep(1)

        # 4. 切版本 (仅当需要时)
        cur += 1
        log_msg(f"{cur}/{total} 切换版本: {version}")
        # 先检查主页面上的版本文字
        elements = adb.dump_ui()
        on_correct_version = False
        for e in elements:
            t = (e.text or "").replace('（', '(').replace('）', ')')
            v = version.replace('（', '(').replace('）', ')')
            if v in t:
                on_correct_version = True
                break
        if on_correct_version:
            log_msg(f"  已是 {version}, 跳过切换", "success")
        else:
            adb.tap(*TABS["我"]); time.sleep(2)
            adb.tap(*SETTINGS_ICON); time.sleep(1.5)
            adb.click_element(text="个人信息", exact=True); time.sleep(1.5)
            adb.click_element(text="英语所学教材版本", exact=True); time.sleep(1.5)
            adb.click_element(text=version, exact=True); time.sleep(1.5)

        # 5. 回首页
        cur += 1
        log_msg(f"{cur}/{total} 返回首页")
        for _ in range(3):
            adb.press_back(); time.sleep(1)
        adb.tap(*TABS["英语"]); time.sleep(3)
        adb.tap(*AD_CLOSE); time.sleep(1)

        # 6. 选年级
        if grade:
            cur += 1
            log_msg(f"{cur}/{total} 选择年级: {grade}")
            adb.tap(*sc(346, 275)); time.sleep(1.5)

            found = False
            for attempt in range(4):
                elements = adb.dump_ui()
                for e in elements:
                    if grade in (e.text or ""):
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  ✅ 已选 {grade}", "success")
                        found = True
                        break
                if found: break
                adb.swipe(*sc(540, 1700), *sc(540, 900), 300); time.sleep(1)

            # 关闭弹窗
            adb.press_back(); time.sleep(1)
            adb.press_back(); time.sleep(1)
            adb.tap(*TABS["英语"]); time.sleep(3)
            adb.tap(*AD_CLOSE); time.sleep(1)

        # 7. 稳定
        cur += 1
        log_msg(f"{cur}/{total} 页面就绪")
        time.sleep(1)

        # 8. 测试模块
        for i, module in enumerate(modules):
            if module not in MODULE_COORDS:
                log_msg(f"⚠ 跳过: {module}", "warning")
                continue

            cx, cy = MODULE_COORDS[module]

            if module in DEEP_MODULES:
                log_msg(f"  ⏬ 滚动到 {module}")
                found_deep = False
                # ★ 2026-08-30 修复：滚动寻找更稳健——
                #   1) 找到"教材精学/专项突破"提示才认为进入正确区
                #   2) 找不到模块时字符串化日志 "未找到模块X,跳过" 含banner标题,便于定位换年级bug
                _section_banner = ""
                for scroll_step in range(5):
                    adb.swipe(*sc(200, 1600), *sc(200, 1200), 400)
                    time.sleep(1)
                    elements = adb.dump_ui()
                    for e in elements:
                        if e.text and '专项突破' in (e.text or ''):
                            _section_banner = "专项突破"; break
                        if e.text and '教材精学' in (e.text or ''):
                            _section_banner = "教材精学"; break
                    for e in elements:
                        if e.text and e.text.strip() == module:
                            cx, cy = e.center
                            log_msg(f"    滚{scroll_step+1}次找到 {module}（{_section_banner or '未标识区'}）", "success")
                            found_deep = True; break
                    if found_deep: break
                    if not any('专项突破' in (e.text or '') for e in elements) and \
                       not any('教材精学' in (e.text or '') for e in elements):
                        # ★ 不在"教材精学/专项突破"两个 banner 下，意味着该年级根本无此模块
                        break
                if not found_deep:
                    log_msg(f"    ⚠ 未找到模块「{module}」(年级={grade}, 区={_section_banner or '未识别'}) → 跳过此模块，继续下一个", "warning")
                    continue

            cur += 1
            log_msg(f"[{i+1}/{len(modules)}] 进入: {module} ({cur}/{total})")
            adb.tap(cx, cy); time.sleep(1.5)

            cur += 1
            safe_name = f"mod_{i+1:02d}.png"
            adb.screenshot(safe_name)
            log_msg(f"  ✅ {module} 截图 ({cur}/{total}) → {safe_name}", "success")

            cur += 1
            adb.press_back(); time.sleep(1.5)
            adb.tap(*AD_CLOSE); time.sleep(1)

        log_msg(f"✅ 完成! {version} {grade} {len(modules)}模块", "success")
        adb.screenshot("99_complete.png")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 失败: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


def run_grade_scan_task():
    """全版本年级扫描（调用 grade_scanner.py）"""
    try:
        set_running("grade_scan")
        log_msg("开始全版本年级扫描...")
        scanner = PROJECT_ROOT / "grade_scanner.py"
        r = sp.run(
            [sys.executable, str(scanner)],
            capture_output=True, text=True, timeout=600,
            cwd=str(PROJECT_ROOT),
        )
        if r.returncode == 0:
            log_msg("✅ 全版本年级扫描完成", "success")
        else:
            log_msg(f"⚠ 扫描部分失败: {r.stderr[-200:]}", "warning")
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 扫描失败: {e}", "error")
    finally:
        set_done()
    try:
        set_running("full")
        config = load_config()
        adb = get_adb()

        total = 8 + len(modules) * 3
        cur = 0

        # 1. 启动APP
        cur += 1
        log_msg(f"1/{total} 启动APP")
        update_progress(cur, total, "启动APP")
        adb.launch_app(config.app.package)
        time.sleep(5)

        # 2. 关闭广告
        cur += 1
        log_msg(f"2/{total} 关闭广告")
        update_progress(cur, total, "关闭广告")
        adb.tap(*AD_CLOSE)
        time.sleep(2)

        # 3. 登录流程
        cur += 1
        log_msg(f"3/{total} 自动登录")
        update_progress(cur, total, "自动登录")
        # 勾协议
        adb.click_element(text="我已阅读并同意", exact=False)
        time.sleep(1)
        # 点登录
        adb.click_element(text="登录", exact=True)
        time.sleep(3)
        # 处理弹窗
        if adb.wait_for_element(text="同意", timeout=3):
            adb.click_element(resource_id="agree_tv", exact=False)
            time.sleep(3)
        adb.tap(*AD_CLOSE)
        time.sleep(2)
        adb.screenshot("01_login_done.png")

        # 4. 切到版本选择页 → 选版本
        cur += 1
        log_msg(f"4/{total} 切换版本: {version}")
        update_progress(cur, total, f"切换版本: {version}")
        adb.tap(*TABS["我"])
        time.sleep(3)
        adb.tap(*SETTINGS_ICON)
        time.sleep(2)
        adb.click_element(text="个人信息", exact=True)
        time.sleep(2)
        adb.click_element(text="英语所学教材版本", exact=True)
        time.sleep(2)
        adb.click_element(text=version, exact=True)
        time.sleep(3)

        # 5. 返回主页面
        cur += 1
        log_msg(f"5/{total} 返回主页面")
        update_progress(cur, total, "返回主页面")
        for _ in range(3):
            adb.press_back()
            time.sleep(1)
        adb.tap(*TABS["英语"])
        time.sleep(6)
        adb.tap(*AD_CLOSE)
        time.sleep(2)
        adb.screenshot("02_back_home.png")

        # 6. 选择年级（在主页面顶部点年级切换器）
        if grade:
            cur += 1
            log_msg(f"6/{total} 选择年级: {grade}")
            update_progress(cur, total, f"选择年级: {grade}")
            adb.tap(*sc(346, 275))
            time.sleep(3)

            # 动态查找年级文字（支持滚动）
            found = False
            for attempt in range(4):
                elements = adb.dump_ui()
                for elem in elements:
                    if grade in elem.text:
                        adb.tap(elem.center[0], elem.center[1])
                        log_msg(f"  ✅ 已选 \"{grade}\" at {elem.center}", "success")
                        found = True
                        break
                if found:
                    break
                # 没找到，滚屏
                adb.swipe(*sc(540, 1700), *sc(540, 900), 300)
                time.sleep(2)

            if not found:
                log_msg(f"  ⚠ 未找到年级 \"{grade}\"", "warning")
            time.sleep(3)
            # 关闭弹窗（点左上角）
            adb.tap(*sc(108, 100))
            time.sleep(1)
            adb.screenshot("03_grade_selected.png")

        # 7. 等待页面稳定
        cur += 1
        log_msg(f"{'7' if grade else '6'}/{total} 页面稳定")
        update_progress(cur, total, "页面已就绪")
        time.sleep(3)

        # 8. 逐模块检测
        for i, module in enumerate(modules):
            if module not in MODULE_COORDS:
                log_msg(f"⚠ 跳过未知模块: {module}", "warning")
                continue

            cx, cy = MODULE_COORDS[module]

            # 深度模块需先滚到专项突破底部
            if module in DEEP_MODULES:
                log_msg(f"  ⏬ 滚动到深度模块 {module}")
                for _ in range(2):
                    adb.swipe(*sc(540, 1900), *sc(540, 600), 500)
                    time.sleep(2)
                # 重新读取位置 (滚动后坐标可能变)
                elements = adb.dump_ui()
                for elem in elements:
                    if elem.text and elem.text.strip() == module:
                        cx, cy = elem.center
                        log_msg(f"  📍 找到 {module} at ({cx},{cy})", "success")
                        break

            cur += 1
            log_msg(f"[{i+1}/{len(modules)}] 进入: {module} ({cur}/{total})")
            update_progress(cur, total, f"进入 {module}")
            adb.tap(cx, cy)
            time.sleep(3)

            cur += 1
            adb.screenshot(f"module_{module}.png")
            log_msg(f"  ✅ {module} 截图完成 ({cur}/{total})", "success")
            update_progress(cur, total, f"{module} 截图完成")

            cur += 1
            adb.press_back()
            time.sleep(3)
            adb.tap(*AD_CLOSE)
            time.sleep(2)
            log_msg(f"  返回首页 ({cur}/{total})")
            update_progress(cur, total, "返回首页")

        log_msg(f"✅ 全流程完成！版本={version}, 年级={grade}, 模块={len(modules)}个", "success")
        adb.screenshot("99_complete.png")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 流程失败: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


def run_inspect_loop():
    """
    逐题巡检循环 (稳定版)
    
    核心逻辑:
      1. 导航到 AI检测 考试页
      2. 对每题: 截图→点右侧选项(970, y)→点底部按钮×2(检查+下一题)
      3. 遇到问题就停，不卡住
    
    按钮约定:
      - 底部按钮 (540, 2174): 选完选项后点一次→显示答案, 再点一次→跳下一题
      - 选项位置: 右侧选项标签区 (x≈900-1000) 不是图片中央
    """
    try:
        set_running("inspect_loop")
        config = load_config()
        adb = get_adb()

        # 1. 启动 + 导航
        log_msg("启动APP")
        adb.launch_app(config.app.package)
        time.sleep(4)
        adb.tap(*AD_CLOSE)  # 关广告
        time.sleep(0.5)
        adb.tap(*TABS["英语"])  # 英语tab
        time.sleep(3)
        adb.tap(*AD_CLOSE)

        # 2. 滚到单元自检
        log_msg("滚动到单元自检")
        for i in range(4):
            adb.swipe(*sc(200, 1600), *sc(200, 1200), 400)
            time.sleep(0.5)
            elements = adb.dump_ui()
            for e in elements:
                if e.text and '单元自检' in e.text:
                    adb.tap(e.center[0], e.center[1])
                    break
            if any('单元自检' in (e.text or '') for e in elements):
                break
        time.sleep(3)
        adb.tap(*AD_CLOSE)

        # 3. 等加载 + 点AI检测去答题
        log_msg("进入AI检测")
        time.sleep(6)
        elements = adb.dump_ui()
        for e in elements:
            if e.text == '去答题' and e.clickable and e.center[1] < 800:
                adb.tap(e.center[0], e.center[1])
                break
        time.sleep(5)

        # 4. 关规则弹窗 + 开始答题
        adb.tap(*sc(540, 1578))
        time.sleep(0.5)
        adb.tap(*sc(554, 2116))
        time.sleep(10)

        # 5. 逐题巡检
        log_msg("逐题巡检")
        questions = []
        last = 0
        
        for step in range(80):
            if not task_status["running"]:
                break

            elements = adb.dump_ui(retries=2)
            cur = None
            for e in elements:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    cur = int(m.group(1))
                    break
            
            if not cur:
                log_msg("不在考题页，结束", "warning")
                break
            if cur == last:
                time.sleep(0.3)
                continue
            last = cur

            adb.screenshot(f"q{cur:02d}.png")
            questions.append({"idx": cur, "screenshot": f"q{cur:02d}.png"})
            log_msg(f"Q{cur}", "success")
            update_progress(cur, 40, f"Q{cur}")

            # 点右侧选项或中央（取决于布局）
            for e in elements:
                if e.clickable and 700 < e.bounds[1] < 1700:
                    if e.center[0] > 450:
                        adb.tap(e.center[0], e.bounds[1] + 30)
                    else:
                        adb.tap((e.bounds[0] + e.bounds[2]) // 2, (e.bounds[1] + e.bounds[3]) // 2)
                    break
            time.sleep(1)

            # 连点两次底部按钮 (检查→下一题)
            adb.tap(*sc(540, 2174))
            time.sleep(1.5)
            adb.tap(*sc(540, 2174))
            time.sleep(1.5)

            if cur >= 40:
                log_msg("✅ 40题完成!", "success")
                break

        # 6. 保存报告
        out = PROJECT_ROOT / "outputs" / "questions" / "inspect_report.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)
        log_msg(f"✅ 报告: {out.name} ({len(questions)}题)", "success")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 异常: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()



def run_quick_inspect_task(docx_file: str = "", unit: int = 0):
    """⚡ 快速检查：从手机当前页面直接开始逐题巡检（跳过启动/关广告/登录/导航）

    前提: 用户已手动将手机调到题目页 (如 听力专项-基础巩固-第1题)
    流程: 截图 → AI六维审查(若提供脚本) → 写入巡检状态 → 点选项 → 点底部按钮x2 → 循环
    坐标自动缩放 (适配不同分辨率手机)
    """
    try:
        set_running("quick_inspect")
        config = load_config()
        adb = get_adb()

        # 清空旧巡检状态
        _inspection_state["questions"] = {}
        _inspection_state["workflow_steps"] = []
        _inspection_state["current_question_idx"] = 0
        _save_inspection_state()

        # 加载脚本 + AI审查agent (可选)
        agent = None
        if docx_file:
            docx_path = str(UPLOAD_DIR / docx_file)
            if Path(docx_path).exists():
                try:
                    from src.review_agent import ReviewAgent, ReviewConfig
                    cfg = ReviewConfig(docx_path=docx_path, unit=int(unit or 0),
                                       screenshot_dir=str(PROJECT_ROOT / "screenshots"),
                                       verbose=False)
                    agent = ReviewAgent(cfg)
                    log_msg(f"📄 脚本已加载: {docx_file} (共{len(agent.script_questions)}题) → AI六维审查开启", "success")
                except Exception as e:
                    log_msg(f"⚠ 脚本加载失败: {e}，降级为仅截图", "warning")
            else:
                log_msg(f"⚠ 脚本不存在: {docx_path}，降级为仅截图", "warning")
        else:
            log_msg("⚡ 未指定脚本，仅截图+推进（选脚本可开启AI六维审查）", "info")

        # ★ 2026-08-30 修复：快速检查优先走"模块真实答题循环"（听力专项 _test_answer_loop），
        #   废弃的简易"点选项→点按钮x2"逻辑不识别图片选项(卡Q1)/不收集evidence/不设模块上下文。
        #   判断当前是否听力专项答题页：有题号 X/Y + 题干含"听" + 无封面按钮(去练习/开始答题)
        try:
            _els0 = adb.dump_ui(retries=2)
            _t_all0 = " ".join((e.text or "") for e in _els0)
            _m_xy0 = re.search(r"(\d+)/(\d+)", _t_all0)
            _no_cover0 = ("去练习" not in _t_all0 and "开始答题" not in _t_all0
                          and "重新答题" not in _t_all0)
            if _m_xy0 and "听" in _t_all0 and _no_cover0:
                log_msg(f"✅ 检测到听力专项答题页（{_m_xy0.group(0)}），走真实答题循环…", "success")
                try:
                    from common.logger import set_current_module
                    set_current_module("听力专项", "快速检查")
                    # ★ 同时写 _inspection_state 的 module/stage（_record_module_evidence
                    #   fallback 读取；线程间 logger 全局偶尔读不到，双保险）
                    _inspection_state["module"] = "听力专项"
                    _inspection_state["stage"] = "快速检查"
                    _dd = _connect_device()
                    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                    from modules.听力专项 import _test_answer_loop as _listen_loop
                    _q_done = _listen_loop(_dd, max_q=60)
                    log_msg(f"✅ 听力专项快速检查完成: {_q_done} 题", "success")
                except Exception as _e2:
                    log_msg(f"⚠ 听力专项答题循环异常: {_e2}", "warning")
                    import traceback
                    traceback.print_exc()
                set_done()
                return
        except Exception:
            pass

        log_msg("⚡ 快速检查启动（从当前页面开始，跳过导航）", "success")
        time.sleep(1)

        # 1. 尝试检测当前题目进度 (如 1/40)
        elements = adb.dump_ui(retries=2)
        cur = None
        total_q = 0
        for e in elements:
            m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
            if m:
                cur = int(m.group(1))
                total_q = int(m.group(2))
                break

        if cur:
            log_msg(f"✅ 检测到题目进度 {cur}/{total_q or 40}，开始逐题检查", "success")
        else:
            log_msg("⚠ 未检测到题目进度(如 1/40)。若您已在题目页将正常检查，", "warning")
            log_msg("   否则请先手动进入题目页再点「快速检查」", "warning")
            time.sleep(2)

        # 2. 逐题巡检
        last = 0
        q_count = 0
        for step in range(80):
            if not task_status["running"]:
                break

            idx = cur if cur else (last + 1)

            # 截图 (保存到 outputs/web, 前端可预览)
            shot = f"q{idx:02d}.png"
            adb.screenshot(shot)
            log_msg(f"📸 Q{idx} 已截图", "success")
            update_progress(idx, total_q or 40, f"Q{idx}")
            q_count += 1

            # ====== AI 六维审查 (若有脚本) ======
            ai = {
                "ai_stem": None, "ai_content": None, "ai_image": None,
                "ai_answer": None, "ai_audio": None, "ai_post_error": None,
                "overall_passed": None, "overall_score": None,
                "stem_reason": "", "content_reason": "", "image_reason": "",
                "answer_reason": "", "audio_reason": "", "post_error_reason": "",
                "question_type": "快速检查",
                "script_answer": "", "stem": "",
            }
            if agent:
                try:
                    # ★ 修复：截图保存在 screenshots/（adb.screenshot），
                    #   原代码读 outputs/web/ 导致找不到图 → 降级纯文字模式
                    shot_path = str(PROJECT_ROOT / "screenshots" / shot)
                    matching = [q for q in agent.script_questions if q.global_idx == idx]
                    if matching:
                        script_q = matching[0]
                        r = agent._review_one(script_q, shot_path)
                        ai = {
                            "ai_stem": r.stem_check.passed,
                            "ai_content": r.content_check.passed,
                            "ai_image": r.image_check.passed,
                            "ai_answer": r.answer_check.passed,
                            "ai_audio": r.audio_check.passed if r.audio_check is not None else None,
                            "ai_post_error": r.post_error_check.passed if r.post_error_check is not None else None,
                            "overall_passed": r.overall_passed,
                            "overall_score": round(r.overall_score, 2),
                            "stem_reason": r.stem_check.details[0][:100] if r.stem_check.details else "",
                            "content_reason": r.content_check.details[0][:100] if r.content_check.details else "",
                            "image_reason": r.image_check.details[0][:100] if r.image_check.details else "",
                            "answer_reason": r.answer_check.details[0][:100] if r.answer_check.details else "",
                            "audio_reason": r.audio_check.details[0][:100] if r.audio_check and r.audio_check.details else "",
                            "post_error_reason": r.post_error_check.details[0][:100] if r.post_error_check and r.post_error_check.details else "",
                            "question_type": script_q.type_2 or "快速检查",
                            "script_answer": script_q.answer or "",
                            "stem": script_q.stem[:60] if script_q.stem else "",
                        }
                        log_msg(f"  AI: 题干{ai['ai_stem']} 内容{ai['ai_content']} 配图{ai['ai_image']} 作答{ai['ai_answer']} 音频{ai['ai_audio']} 答错后{ai['ai_post_error']} 得分{ai['overall_score']}")
                    else:
                        log_msg(f"  ⚠ 脚本中无 Q{idx}，跳过AI审查", "warning")
                except Exception as e:
                    log_msg(f"  ⚠ AI审查失败 Q{idx}: {e}", "warning")

            # ====== 写入巡检状态 → 前端中栏显示 ======
            qid = f"quick-Q{idx:02d}"
            _inspection_state["questions"][qid] = {
                "idx": idx,
                "total": total_q or 40,
                "question_type": ai["question_type"],
                "screenshot": shot,
                "progress": f"{idx}/{total_q or 40}",
                "ai_stem": ai["ai_stem"], "ai_content": ai["ai_content"],
                "ai_image": ai["ai_image"], "ai_answer": ai["ai_answer"],
                "ai_audio": ai["ai_audio"], "ai_post_error": ai["ai_post_error"],
                "overall_passed": ai["overall_passed"],
                "overall_score": ai["overall_score"],
                "stem_reason": ai["stem_reason"], "content_reason": ai["content_reason"],
                "image_reason": ai["image_reason"], "answer_reason": ai["answer_reason"],
                "audio_reason": ai["audio_reason"], "post_error_reason": ai["post_error_reason"],
                "script_answer": ai["script_answer"],
                "stem": ai["stem"],
                "note": "",
                "human_label": None,
                "human_note": "",
                "timestamp": datetime.now().isoformat(),
            }
            _inspection_state["current_question_idx"] = idx
            _save_inspection_state()

            # 点选项: 优先找UI元素，找不到则点默认右侧选项区(缩放)
            elements = adb.dump_ui(retries=2)
            clicked_option = False
            for e in elements:
                if e.clickable and 700 < e.bounds[1] < 1700:
                    if e.center[0] > 450:
                        adb.tap(e.center[0], e.bounds[1] + 30)
                    else:
                        adb.tap((e.bounds[0] + e.bounds[2]) // 2,
                                (e.bounds[1] + e.bounds[3]) // 2)
                    clicked_option = True
                    break
            if not clicked_option:
                tx, ty = sc(970, 1500)   # 默认点右侧选项区
                adb.tap(tx, ty)
            time.sleep(1)

            # 点底部按钮 x2 (检查答案 → 下一题)
            bx, by = sc(540, 2174)
            adb.tap(bx, by)
            time.sleep(1.5)
            adb.tap(bx, by)
            time.sleep(1.5)

            # 检测进度变化
            elements_after = adb.dump_ui(retries=2)
            new_cur = None
            new_total = 0
            for e in elements_after:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    new_cur = int(m.group(1))
                    new_total = int(m.group(2))
                    break

            if new_cur and new_cur == last and cur:
                log_msg(f"  ⚠ Q{new_cur} 进度未变，重试一次", "warning")
                time.sleep(2)
                adb.tap(bx, by)
                time.sleep(1.5)
                continue

            if new_cur:
                last = new_cur
                cur = new_cur
                total_q = new_total or total_q
                if new_cur >= (total_q or 40):
                    log_msg(f"✅ {new_cur}题完成!", "success")
                    break
            else:
                last += 1
                log_msg(f"  未检测到进度文字, 继续下一题 (Q{last})", "info")

        # 3. 保存报告
        out = PROJECT_ROOT / "outputs" / "questions" / "quick_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"questions": list(_inspection_state["questions"].values())},
                      f, ensure_ascii=False, indent=2)
        log_msg(f"✅ 快速检查完成: 共 {q_count} 题", "success")

    except Exception as e:
        log_msg(f"❌ 异常: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


def run_inspect_questions_task():
    """自动化巡检 AI检测 题目：
    1. 启动APP, 关广告, 进英语tab
    2. 滚到专项突破底部 → 单元自检
    3. 点 AI检测的 去答题 (870, 756)
    4. 关规则弹窗 (540, 1578) → 点开始答题 (554, 2116)
    5. 逐题截图+解析, 推进直到没有"下一题"按钮
    """
    report = {"questions": []}
    try:
        set_running("inspect_questions")
        config = load_config()
        adb = get_adb()
        # ★ 跨机器可移植：自动定位 adb（不再写死任何人的绝对路径）
        adb_path = ADBController._find_adb()

        # 1. 启动APP
        log_msg("启动APP...")
        sp.run([adb_path, '-s', config.device.serial, 'shell', 'am', 'force-stop', 'com.dinoenglish.yyb'])
        time.sleep(2)
        sp.run([adb_path, '-s', config.device.serial, 'shell', 'am', 'start', '-n', 'com.dinoenglish.yyb/.base.SplashActivity'])
        time.sleep(5)
        adb.tap(*AD_CLOSE)  # 关启动广告
        time.sleep(3)
        adb.tap(*sc(948, 1821))  # 关可能的第二个
        time.sleep(2)

        # 2. 滚到专项突破底部 → 单元自检
        log_msg("滚动到单元自检...")
        adb.tap(*TABS["英语"])  # 英语tab
        time.sleep(5)
        for _ in range(2):
            adb.swipe(*sc(540, 1500), *sc(540, 800), 400)
            time.sleep(2)
        # 小幅调整
        adb.swipe(*sc(540, 1500), *sc(540, 1100), 400)
        time.sleep(2)

        # 动态找 单元自检
        elements = adb.dump_ui()
        for elem in elements:
            if elem.text and '单元自检' in elem.text:
                adb.tap(elem.center[0], elem.center[1])
                log_msg(f"  ✅ 进入单元自检 at {elem.center}", "success")
                break
        time.sleep(4)

        # 3. 点 AI检测的 去答题
        log_msg("点 AI检测 去答题...")
        adb.tap(*sc(870, 756))
        time.sleep(6)

        # 4. 关规则弹窗
        log_msg("关闭训练规则弹窗...")
        adb.tap(*sc(540, 1578))
        time.sleep(2)

        # 5. 点开始答题
        log_msg("点开始答题...")
        adb.tap(*sc(554, 2116))
        time.sleep(8)  # AI生成题目

        # 6. 逐题巡检
        log_msg("开始逐题巡检...")
        out_dir = PROJECT_ROOT / "outputs" / "questions"
        out_dir.mkdir(parents=True, exist_ok=True)

        for q_idx in range(50):  # 最多 50 题
            elements = adb.dump_ui()
            # 找当前进度
            progress = ""
            question_text = ""
            for e in elements:
                t = e.text or ""
                if re.match(r'^\d+/\d+$', t.strip()):
                    progress = t
                if ('听' in t or '看' in t or '选' in t or '读' in t or '写' in t or '听音' in t) and len(t) > 5 and len(t) < 80:
                    if not question_text:
                        question_text = t

            # 截图
            shot_path = out_dir / f"q_{q_idx+1:02d}.png"
            sp.run([adb_path, '-s', config.device.serial, 'shell', 'screencap', '-p', '/sdcard/_q.png'])
            sp.run([adb_path, '-s', config.device.serial, 'pull', '/sdcard/_q.png', str(shot_path)])
            sp.run([adb_path, '-s', config.device.serial, 'shell', 'rm', '/sdcard/_q.png'])

            # 检测题目类型
            question_type = "未知"
            if any('听录音' in e.text or '🔊' in e.text for e in elements):
                question_type = "听力题"
            elif any('A.' in e.text or 'B.' in e.text or 'C.' in e.text for e in elements):
                question_type = "选择题"
            elif any('读' in e.text and '单词' in e.text for e in elements):
                question_type = "朗读题"
            elif any('写' in e.text and ('单词' in e.text or '字母' in e.text) for e in elements):
                question_type = "拼写题"

            has_image = any(e.text in ['A', 'B', 'C', 'D'] and e.clickable for e in elements)

            report["questions"].append({
                "idx": q_idx + 1,
                "progress": progress,
                "text": question_text,
                "type": question_type,
                "screenshot": str(shot_path.name),
            })

            log_msg(f"题 {q_idx+1}: {progress} | {question_type} | {question_text[:40]}", "info")

            # 检查是否有"下一题"按钮
            has_next = any('下一' in e.text or '提交' in e.text for e in elements)
            if not has_next:
                # 直接看截图/UI找下一题按钮
                # 通常右下角有"下一题"按钮
                for e in elements:
                    if e.clickable and e.text:
                        # 猜的"下一题"按钮位置
                        pass

            # 假设"下一题"按钮在右下角 (约 950, 1700~1900)
            adb.tap(*sc(960, 1850))
            time.sleep(2)

            # 检查是否还在题目页 (有 X/40)
            elements_after = adb.dump_ui()
            on_question = any(re.match(r'^\d+/\d+$', (e.text or '').strip()) for e in elements_after)
            if not on_question:
                log_msg(f"  题目已结束 (q_idx={q_idx+1})", "info")
                break

        # 保存报告
        report_path = PROJECT_ROOT / "outputs" / "questions" / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        log_msg(f"✅ 巡检完成: 共 {len(report['questions'])} 题", "success")
        log_msg(f"报告: {report_path}", "info")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 巡检失败: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


# ============================================================
# Flask 路由
# ============================================================


@app.after_request
def _no_cache(resp):
    """禁用页面缓存：确保浏览器始终加载最新 HTML/JS"""
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def index():
    """前端页面"""
    return render_template("index.html")


@app.route("/trace")
def trace_page():
    """错题溯源页面"""
    return render_template("trace.html")


@app.route("/api/status")
def api_status():
    """设备状态 + 任务状态"""
    # ★ 2026-10-16：目标设备口径统一走 _intended_serial()
    #   （ANDROID_SERIAL → server_target.txt → config.yaml），不再只认环境变量+配置，
    #   避免"以为在控 MuMu、其实连的是真机"这种不可解释的状态。
    # ★ 2026-10-16 追加：再与**实际在线设备**对齐（resolve_target_serial）——
    #   配置目标离线时 cur_serial 落到在线设备并置 device_substituted=True，
    #   前端据此显示「已自动改用 X（配置目标 Y 离线）」，状态始终自解释。
    cur_serial, _dev_info = resolve_target_serial()
    device_ok = False
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        from common.device import device_ok as _check_ok
        device_ok = _check_ok(cur_serial)
    except Exception:
        pass

    return jsonify({
        "device_connected": device_ok,
        "device_serial": cur_serial,
        "device_serial_configured": _dev_info["configured"],
        "device_source": _dev_info["source"],
        "device_substituted": _dev_info["substituted"],
        "online_serials": _dev_info["online"],
        "devices": _device_list(),
        # ★ 坐标缩放可观测（原来只在服务端 stdout 打一行，前端完全看不到）
        "target_resolution": list(_detected_res) if _detected_res else None,
        "coord_scale": [_scale_x, _scale_y],
        "coord_scale_ok": _detected_res is not None,
        "current_version": _get_current_version_from_config(),
        "task_status": task_status,
    })


@app.route("/api/budget")
def api_budget():
    """每日 LLM 预算阀门状态（见 llm_budget.py）"""
    from llm_budget import budget_status
    return jsonify(budget_status())


@app.route("/api/budget/limit", methods=["POST"])
def api_budget_limit():
    """临时调整今日预算上限（写回 .env 的 LLM_DAILY_BUDGET_YUAN）"""
    from llm_budget import budget_status
    body = request.get_json(silent=True) or {}
    try:
        val = float(body.get("limit_yuan"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "limit_yuan 必须是数字"}), 400
    if val <= 0:
        return jsonify({"ok": False, "error": "limit_yuan 必须大于 0"}), 400

    env_path = Path(__file__).parent / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        new_lines, replaced = [], False
        for line in lines:
            if line.strip().startswith("LLM_DAILY_BUDGET_YUAN="):
                new_lines.append(f"LLM_DAILY_BUDGET_YUAN={val}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"LLM_DAILY_BUDGET_YUAN={val}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        return jsonify({"ok": False, "error": f"写入 .env 失败: {e}"}), 500
    return jsonify({"ok": True, "limit_yuan": val, "status": budget_status()})


def _device_list():
    """列出所有已连接设备（供前端下拉选择）"""
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        from common.device import list_devices
        return list_devices()
    except Exception:
        return []


@app.route("/api/devices", methods=["GET"])
def api_devices():
    """获取所有已连接的 adb 设备列表"""
    return jsonify({"devices": _device_list()})


@app.route("/api/device/select", methods=["POST"])
def api_device_select():
    """选择当前设备序列号（写 ANDROID_SERIAL，全局生效）

    ★ 2026-10-16：换设备后**必须重算坐标缩放**。此前只写 ANDROID_SERIAL，缩放比
      仍停留在启动那一刻（或上一台设备）的值 → 运行中换设备后，所有走 sc() 的坐标
      继续按旧设备算，表现就是"换了设备就不准/点了没反应"。
    """
    data = request.get_json() or {}
    serial = (data.get("serial") or "").strip()
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        from common.device import set_device, device_ok
        set_device(serial or None)
        scale = refresh_device_scale(serial or "", reason="切换设备")
        ok = device_ok()
        if not ok:
            log_msg(f"⚠ 设备 {serial or '(默认)'} 未就绪，坐标缩放已按探测结果重置", "warning")
        return jsonify({"status": "ok", "serial": serial or "", "connected": ok,
                        "resolution": scale["resolution"], "scale": scale["scale"]})
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/login", methods=["POST"])
def api_login():
    """触发自动登录"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_login_task, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "login"})


@app.route("/api/errors/summary", methods=["GET"])
def api_errors_summary():
    """返回当前检测中的错题汇总（供前端 renderServe 展示）

    ★ 2026-08-25 统计口径修复：只统计【实际测试的题】（auto-Q* 界面证据题），
      不统计【脚本全量审查的题】（*-脚本-Q*，LLM 把整个 docx 所有题都审一遍，
      很多题根本没在手机上测过）。
      → 分母 = 实际测试的题数；分子 = 其中判定不通过(overall_passed is False)的题数。
      ★ 同时修复 not overall_passed 把 None(未审查) 误计为不通过的问题。

    ★ 2026-08-25 数据源修复：优先读内存 _inspection_state（本次运行的实时数据）。
      旧逻辑只读磁盘 data/inspection_state.json —— 多模块入口启动时只清内存不清磁盘，
      磁盘残留上次运行的题（如五年级20题+4不通过）→ 用户跑三年级未上线0题，
      日志显示0题但前端 summary 却显示"不通过4/20"，前后矛盾。
      内存为空（服务重启等）才读磁盘兜底。
    """
    questions = _inspection_state.get("questions") or {}
    if not questions:
        state_path = PROJECT_ROOT / "data" / "inspection_state.json"
        if not state_path.exists():
            return jsonify({"error": "暂无检测数据"}), 404
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            questions = state.get("questions", {})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    try:
        if isinstance(questions, dict):
            # ★ 保留 qid(key) 才能区分 auto-Q(实际测试) / *-脚本-Q*(脚本全量审查)
            q_items = list(questions.items())
        else:
            q_items = [(str(q.get("qid") or q.get("_qid") or f"q{i}"), q)
                       for i, q in enumerate(questions)]

        # ★ 只保留"实际测试"的题：qid 以 auto-Q 开头（界面证据题 = 引擎真正跑到的题）。
        #   排除 *-脚本-Q*（LLM 脚本全量审查：整个 docx 的题都审，含未实际测试的）
        tested = [q for _qid, q in q_items
                  if str(_qid).startswith("auto-Q") or
                  (str(_qid).startswith("Q") and "脚本-Q" not in str(_qid))]

        failed = []
        # ★ 2026-08-25 修复：key 必须与 questions 里的字段名完全一致（ai_stem/ai_content/ai_image/
        #   ai_answer/ai_audio/ai_post_error）。旧代码用 key[:3]（stem→ste、content→con、post_error→pos）
        #   全部对不上 → failed_dims 永远是空数组 → 错题报告不显示"哪些维度不通过"。
        dim_keys = [
            ("题干", "ai_stem"), ("内容", "ai_content"), ("配图", "ai_image"),
            ("作答", "ai_answer"), ("答错后", "ai_post_error"), ("音频", "ai_audio")
        ]
        for q in tested:
            # ★ 修复：只看严格不通过(False)；None(未审查/信息不足)不误计
            if q.get("overall_passed") is False:
                failed_dims = [label for label, key in dim_keys
                               if q.get(key) is False]
                failed.append({
                    "qid": q.get("qid", ""),
                    "idx": q.get("idx", 0),
                    "question_type": q.get("question_type", ""),
                    "overall_score": q.get("overall_score", 0),
                    "failed_dims": failed_dims,
                })

        return jsonify({
            "total_questions": len(tested),     # ★ 分母 = 实际测试题数
            "failed_count": len(failed),        # ★ 分子 = 其中严格不通过数
            "failed_items": failed,
            "has_errors": len(failed) > 0,
            # ★ 附加信息：脚本审查另有 N 题（供前端展示"另有脚本审查错题"）
            "script_review_count": len(q_items) - len(tested),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/versions/available")
def api_versions_available():
    """可用版本列表 = App 实际展示的5个2024审定版本（真机 2026-08-26 确认），
    + 知识库中可能存在的其他版本（兜底），去重"""
    # ★ 2026-08-26：App 当前只展示这5个版本（带2024审定），preset 改为完整版本名
    #   旧 preset "新湘鲁五上"等拆分形式已停用（与 App 实际版本不一致）
    preset = [
        "湘少版(2024审定)", "湘鲁版(2024审定)", "人教版(PEP)(2024审定)",
        "教科版(2024审定)", "教研版(2024审定)",
    ]
    versions = list(preset)
    try:
        from src.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        summary = kb.summary()
        for s in summary:
            key = s.get("key", "")
            # 知识库key形如 "湘少版:五上" / "湘鲁版:六上" → 转成 "湘少版五上"
            label = key.replace(":", "") if ":" in key else key
            if label and label not in versions:
                versions.append(label)
    except Exception:
        pass
    return jsonify({"versions": versions, "preset": preset})


@app.route("/api/versions", methods=["GET", "POST"])
def api_versions():
    """检测可用版本"""
    if request.method == "GET":
        # 返回已缓存的版本列表
        versions_file = PROJECT_ROOT / "outputs" / "web" / "versions.json"
        if versions_file.exists():
            with open(versions_file, "r", encoding="utf-8") as f:
                versions = json.load(f)
            return jsonify({"versions": versions})
        return jsonify({"versions": [], "msg": "尚未检测，请先 POST /api/versions 触发检测"})

    # POST: 触发版本检测
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_version_detect_task, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "version_detect"})


@app.route("/api/version-grades")
def api_version_grades():
    """返回版本→年级配置表（scan_versions_grades.py 生成的缓存数据，秒回）"""
    # 优先新版配置表 versions_grades.json（版本 → {grades, current}）
    vg_file = PROJECT_ROOT / "outputs" / "web" / "versions_grades.json"
    if vg_file.exists():
        try:
            with open(vg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容两种结构：{table:{...}} 或 直接 {版本:{...}}
            if isinstance(data, dict) and "table" in data and isinstance(data["table"], dict):
                table = data["table"]
            else:
                table = data
            if table:
                return jsonify({"table": table, "source": "table"})
        except Exception:
            pass
    # 回退旧版 all_grades.json
    grades_file = PROJECT_ROOT / "outputs" / "web" / "all_grades.json"
    if grades_file.exists():
        with open(grades_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"table": data, "source": "all_grades"})
    return jsonify({"error": "尚未生成配置表，请先运行 scripts/scan_versions_grades.py 或扫描年级"}), 404


@app.route("/api/version-grades/current", methods=["POST"])
def api_version_grades_current():
    """★ 实时从 App 读取当前版本的年级列表（前端切换版本后联动年级下拉）

    与 App 实际内容保持一致：打开「切换课本」页 dump 解析，而非写死。
    body: {"version": "湘少版"}（可选；传入且与当前不同 → 先在 App 内切版本再读）
    返回: {"version": "湘少版", "grades": ["五年级上册", ...], "current_grade": "五年级上册"}
    """
    data = request.get_json(silent=True) or {}
    target = (data.get("version") or "").strip()
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    try:
        d = _connect_device()
    except Exception as e:
        return jsonify({"error": f"设备未连接: {e}"}), 400
    try:
        import importlib
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        setup = importlib.import_module("common.setup")

        def _homebar_text():
            """主页顶部版本+年级栏文本（resource-id=switch_textbook_tv，属性顺序不固定）"""
            try:
                _xml = d.dump_hierarchy()
                _m = re.search(r'<node[^>]*resource-id="[^"]*switch_textbook_tv"[^>]*>', _xml)
                if _m:
                    _tm = re.search(r'text="([^"]*)"', _m.group(0))
                    if _tm:
                        return _tm.group(1)
            except Exception:
                pass
            return ""

        # 1) 当前版本（主页顶部栏文本，取"X版"部分）
        homebar = _homebar_text()
        cur_version = ""
        vm = re.search(r'([\u4e00-\u9fa5]+版)', homebar) if homebar else None
        if vm:
            cur_version = vm.group(1)
        # 2) 指定版本且与当前不同 → 先切版本（走"我的"页路径）
        if target and target not in (homebar or ""):
            log_msg(f"🔄 切换版本 → {target}", "step")
            if not setup.switch_version(d, target):
                log_msg("❌ 版本切换失败", "error")
                return jsonify({"error": f"版本切换失败: {target}"}), 500
            time.sleep(1)
        # 3) 打开「切换课本」页实时读取年级列表
        grades = setup.get_grades_from_app(d)
        if not grades:
            return jsonify({"error": "未能从 App 读取年级列表（请确认设备已连接且在主页）"}), 500
        # 4) 当前年级（主页栏文本中提取 X年级上/下册）
        homebar = _homebar_text()
        cur_grade = ""
        gm = re.search(r'([一二三四五六]年级(?:上|下)册)', homebar) if homebar else None
        if gm:
            cur_grade = gm.group(1)
        if not cur_version:
            vm2 = re.search(r'([\u4e00-\u9fa5]+版)', homebar) if homebar else None
            if vm2:
                cur_version = vm2.group(1)
        log_msg(f"✅ 实时读取年级列表: {len(grades)} 个（当前: {cur_grade or '未知'}）", "success")
        return jsonify({"version": target or cur_version, "grades": grades, "current_grade": cur_grade})
    except Exception as e:
        log_msg(f"❌ 读取年级列表异常: {e}", "error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/version-grades/scan", methods=["POST"])
def api_scan_grades():
    """触发全版本年级扫描（慢，约3分钟）"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_grade_scan_task, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/run-full", methods=["POST"])
def api_run_full():
    """一键全流程运行：登录 → 切换版本 → 选年级 → 测模块"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供参数"}), 400

    version = data.get("version", "")
    grade = data.get("grade", "")
    modules = data.get("modules", [])

    if not version:
        return jsonify({"error": "请选择版本"}), 400
    if not modules:
        return jsonify({"error": "请选择至少一个模块"}), 400

    # ★ 2026-10-16：启动前预检目标设备并刷新坐标缩放（离线直接拒绝，不再静默回落
    #   到 config.yaml 的真机去操作一台操作者没在看的设备）
    _ok, _msg = _preflight_target_device()
    if not _ok:
        log_msg(f"❌ 设备预检未通过: {_msg}", "error")
        return jsonify({"error": _msg}), 400

    t = threading.Thread(target=run_full_task, args=(version, grade, modules), daemon=True)
    t.start()
    return jsonify({
        "status": "started",
        "task": "full",
        "version": version,
        "grade": grade,
        "modules": modules,
    })


@app.route("/api/inspect-questions", methods=["POST"])
def api_inspect_questions():
    """AI检测单元自检题目巡检：一题一截图+识别"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_inspect_questions_task, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "inspect_questions"})


@app.route("/api/questions/report")
def api_questions_report():
    """获取最近一次巡检报告"""
    report_path = PROJECT_ROOT / "outputs" / "questions" / "report.json"
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"questions": [], "msg": "尚未巡检"})


# ============================================================
# 四步检查 API
# ============================================================


_current_screenshot = ""



# ============================================================
# 听力专项 专属API — 与CLI脚本一致的工作流
# ============================================================

@app.route("/api/log/clear", methods=["POST"])
def api_log_clear():
    """清空操作日志"""
    task_status["log"] = []
    return jsonify({"status": "cleared"})

@app.route("/api/inspect/listening-run", methods=["POST"])
def api_inspect_listening_run():
    """
    听力专项自动巡检 (与CLI脚本 inspect_u6.py 行为一致)
    
    请求参数:
        version: "新湘鲁六上" / "新湘鲁五上" / ...
        unit: 6 (单元号)
        stage: "基础巩固" / "综合进阶" / "难点突破"   (兼容旧版单阶段)
        stages: ["基础巩固","综合进阶",...]            (新版多阶段，优先)
        docx: 脚本文件名 (已在uploads目录的)
    """
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    version_label = data.get("version", "新湘鲁六上")
    unit = data.get("unit", 6)
    stage = data.get("stage", "基础巩固")
    docx_file = data.get("docx", "")
    # ★ 多阶段支持：stages 优先；兼容旧版单 stage
    stages = data.get("stages") or []
    if isinstance(stages, str):
        stages = [s.strip() for s in stages.split(",") if s.strip()]
    if not stages:
        stages = [stage] if stage else ["基础巩固"]

    # 新巡检自动清空日志和检查状态（多阶段只清一次，后面各阶段结果累积）
    task_status["log"] = []
    _inspection_state["questions"] = {}
    _inspection_state["workflow_steps"] = []
    _inspection_state["current_question_idx"] = 0
    _save_inspection_state()

    # 启动线程
    t = threading.Thread(
        target=_run_listening_inspect_stages,
        args=(version_label, unit, stages, docx_file),
        daemon=True,
    )
    t.start()
    return jsonify({
        "status": "started",
        "task": "listening_inspect",
        "params": {"version": version_label, "unit": unit, "stages": stages},
    })


def _run_listening_inspect_stages(version_label: str, unit: int, stages: list, docx_file: str):
    """多阶段巡检：依次跑每个子模块，结果按 stage 前缀累积到六维面板。
    最后一阶段才 set_done（避免中间阶段提前让前端显示"完成"）。"""
    n = len(stages)
    for i, st in enumerate(stages):
        log_msg(f"📌 巡检阶段 [{i+1}/{n}]: {st}", "step")
        try:
            run_listening_inspect(version_label, unit, st, docx_file,
                                  keep_running=(i < n - 1))
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            break
        except Exception as e:
            log_msg(f"⚠ 阶段 {st} 巡检异常: {e}", "error")
        if _is_stop_requested():
            break
    set_done()
    log_msg(f"✅ 多阶段巡检结束: {'、'.join(stages)}", "success")


def run_listening_inspect(version_label: str, unit: int, stage: str, docx_file: str,
                          keep_running: bool = False):
    """
    通用模块巡检主循环
    
    自动从文件名识别模块(巧记单词/听力专项/知识过关...),导航到对应区域,逐题检查
    """
    def record_step(step, status, detail=""):
        """记录流程步骤到后端 (用urllib避免依赖requests)"""
        try:
            import urllib.request, json
            data = json.dumps({"step": step, "status": status, "detail": detail}).encode()
            req = urllib.request.Request("http://127.0.0.1:5000/api/inspect/workflow-step",
                                        data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    def record_q_result(qid, **kwargs):
        """记录每题结果到后端"""
        try:
            import urllib.request, json
            data = json.dumps({"qid": qid, **kwargs}).encode()
            req = urllib.request.Request("http://127.0.0.1:5000/api/inspect/question-result",
                                        data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    try:
        # 记录开始（★ 题目结果由 API 入口统一清空一次；此处不再 reset，
        #   否则多阶段遍历时后一阶段会清掉前一阶段的题）
        record_step("初始化", "running", f"{version_label} U{unit} {stage}")

        set_running("listening_inspect")
        config = load_config()
        adb = get_adb()

        # ===== B: 通用导航引擎 =====
        from src.universe_navigator import UniverseNavigator
        nav = UniverseNavigator(adb)

        log_msg(f"🚀 巡检: {version_label} Unit{unit} {stage}")
        record_step("1.启动APP", "running", "")

        # 强制回首页
        log_msg("强制回到首页")
        nav.universal_reset()
        record_step("1.启动APP", "done")
        time.sleep(1)

        # 通用导航: 首页 → 答题页
        record_step("2.导航到模块", "running")
        ok = nav.navigate_to("question_page", {
            "version": version_label,
            "unit": unit,
            "stage": stage,
        })
        if not ok:
            log_msg("⚠ 导航失败，尝试通用重置后重试...", "warning")
            nav.universal_reset()
            time.sleep(3)
            nav.navigate_to("question_page", {"version": version_label, "unit": unit, "stage": stage})
        record_step("2.导航到模块", "done")
        record_step("0.回到首页", "running", "")
        for _ in range(3):
            adb.press_back()
            time.sleep(0.5)
        time.sleep(1)
        record_step("0.回到首页", "done", "")

        # 1. 启动APP + 导航到首页
        log_msg("启动APP")
        adb.launch_app(config.app.package)
        time.sleep(4)
        record_step("1.启动APP", "done", "")

        # 1.5 检测并关闭教程页(如果有的话)
        log_msg("检查教程页")
        record_step("1.5关闭教程", "running", "")
        for _ in range(8):
            elements = adb.dump_ui()
            # 教程页特征: 出现"眺望远眺" / "下一关" / "知道了" / "开始体验"
            tutorial = False
            for e in elements:
                t = (e.text or '').strip()
                if t in ['下一关', '知道了', '开始体验', '我知道了', 'Next', '跳过']:
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  关教程: '{t}' at {e.center}")
                    tutorial = True
                    time.sleep(1.5)
                    break
            if not tutorial:
                # 兜底: 点击屏幕中部右侧(教程"下一步"按钮区)
                # 但要先确认不是已经进入APP首页
                has_main = any('英语' in (e.text or '') for e in elements)
                if has_main:
                    break  # 已在APP首页
                adb.tap(*sc(900, 2200))  # 教程页"下一步"通常在右下
                time.sleep(1.5)
        record_step("1.5关闭教程", "done", "")

        # 2. 关闭广告 (用UI识别, 找到就停)
        log_msg("关闭广告")
        record_step("2.关闭广告", "running", "")
        ad_found = False
        for _ in range(3):
            if ad_found:
                break  # 已经关掉了, 不再跑后续兜底
            elements = adb.dump_ui(retries=1)
            found_close = False
            for e in elements:
                t = (e.text or '').strip()
                if t in ['关闭', '关闭广告', '×', 'X', 'Close', '跳过', '忽略', '我知道了', '取消']:
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  关闭广告: '{t}' at {e.center}")
                    found_close = True
                    ad_found = True
                    time.sleep(1)
                    break
                if 'close' in e.resource_id.lower() or 'cancel' in e.resource_id.lower():
                    adb.tap(e.center[0], e.center[1])
                    found_close = True
                    ad_found = True
                    time.sleep(1)
                    break
            if not found_close:
                # 只在屏幕顶部边缘点击, 绝不到底部(会触发HOME)
                adb.tap(*sc(540, 40))
                time.sleep(0.5)
                adb.tap(*sc(540, 80))
            time.sleep(1)
        record_step("2.关闭广告", "done", "")

        # 3. 确保在英语tab + 检查是否跑到了"消息"页
        record_step("3.英语Tab", "running", "")
        adb.tap(*TABS["英语"])
        time.sleep(1.5)
        elements = adb.dump_ui()
        if any('消息' in (e.text or '') and e.center[1] < 300 for e in elements):
            log_msg("⚠ 进入了消息页, 按返回", "warning")
            adb.press_back()
            time.sleep(2)
            adb.tap(*TABS["英语"])
            time.sleep(1.5)
        record_step("3.英语Tab", "done", "")

        # 3.5 检查当前APP显示的版本/年级是否与用户选择的一致
        record_step("3.5版本检查", "running", f"用户选: {version_label}")
        log_msg("检查版本是否匹配")
        time.sleep(1)
        elements = adb.dump_ui()
        page_text = ' '.join([(e.text or '') for e in elements])
        # 提取APP显示的年级文本 (如"五年级上册")
        current_grade = ""
        for grade_text in ['一年级上册','一年级下册','二年级上册','二年级下册',
                           '三年级上册','三年级下册','四年级上册','四年级下册',
                           '五年级上册','五年级下册','六年级上册','六年级下册']:
            if grade_text in page_text:
                current_grade = grade_text
                break
        # 提取用户期望的年级 (从version_label如"新湘鲁六上"中提取)
        target_grade_map = {'五上':'五年级上册','五下':'五年级下册',
                            '六上':'六年级上册','六下':'六年级下册'}
        target_grade = ""
        for k, v in target_grade_map.items():
            if k in version_label:
                target_grade = v
                break

        log_msg(f"  APP当前: {current_grade or '未知'} | 用户期望: {target_grade or '未知'}")
        if current_grade and target_grade and current_grade != target_grade:
            log_msg(f"  ⚠ 版本不匹配! 需要切换到 {target_grade}", "warning")
            record_step("3.5版本检查", "running", f"切换 {current_grade} → {target_grade}")
            for e in elements:
                if current_grade in (e.text or ''):
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  点版本标签 at {e.center}")
                    break
            time.sleep(2)
            elements2 = adb.dump_ui()
            for e in elements2:
                t = (e.text or '').strip()
                if target_grade in t:
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  选择 {target_grade} at {e.center}")
                    break
            time.sleep(2)
            for e in adb.dump_ui():
                t = (e.text or '').strip()
                if t in ['确认', '确定', '完成', 'OK', '保存']:
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  确认选择 at {e.center}")
                    break
            time.sleep(2)
        record_step("3.5版本检查", "done", current_grade or "已对齐")

        # ---- 模块自动识别 ----
        module_name, module_section, module_coords = detect_module_from_filename(docx_file or "")
        if module_name:
            log_msg(f"🎯 识别到模块: {module_name}")
        else:
            module_name, module_section, module_coords = "听力专项", "专项突破", None

        # 4. 根据模块区域分流
        record_step("4.专项突破", "running", "")
        skip_special_nav = False
        if module_section == "教材精学" and module_coords:
            # 教材精学区: 不进入专项突破,直接点模块
            log_msg(f"导航到教材精学 → {module_name} at {module_coords}")
            adb.tap(module_coords[0], module_coords[1])
            time.sleep(3)
            record_step("4.专项突破", "done", f"教材精学: {module_name}")
            # 跳过专项突破+听力专项导航, 直接到阶段选择
            skip_special_nav = True
        else:
            log_msg("导航到专项突破")

        # ---- 专项突破区: 导航+找模块 (教材精学区直接跳过) ----
        if not skip_special_nav:
            found = False
            for attempt in range(3):
                elements = adb.dump_ui()
                for e in elements:
                    if e.text and '专项突破' in e.text:
                        if 400 < e.center[1] < 2000:
                            adb.tap(e.center[0], e.center[1])
                            log_msg(f"  点'专项突破' at {e.center}")
                            found = True
                            break
                if found:
                    break
                adb.swipe(*sc(540, 1500), *sc(540, 1000), 300)
                time.sleep(1)
            if not found:
                adb.tap(*sc(414, 1700))
            time.sleep(3)
            record_step("4.专项突破", "done", "")

            # 5. 滚动找模块 (动态匹配,不限定"听力专项")
            record_step("5.听力专项", "running", "")
            log_msg(f"寻找模块: {module_name}")
            found_module = False
            for scroll_i in range(10):
                elements = adb.dump_ui()
                for e in elements:
                    t = (e.text or '')
                    # 支持多种匹配: 听力专项/巧记单词闯关/知识过关
                    if module_name in t or any(kw in t for kw in module_name.split()):
                        cx, cy = e.center
                        if 200 < cy < 2200 and cx > 50 and cx < 1030:
                            log_msg(f"  发现'{t.strip()}' at {e.center}")
                            adb.tap(cx, cy)
                            found_module = True
                            break
                if found_module:
                    break
                adb.swipe(*sc(540, 1600), *sc(540, 600), 500)
                time.sleep(1)
            if not found_module:
                log_msg(f"  ⚠ 未找到模块 '{module_name}', 尝试搜索全部文本", "warning")
                # 最后尝试: dump所有文本 + 模糊匹配
                elements = adb.dump_ui()
                texts = [(e.center, e.text) for e in elements if e.text and e.clickable]
                log_msg(f"  可点击元素: {[(c,t) for c,t in texts[:10]]}")
            time.sleep(3)
            record_step("5.听力专项", "done" if found_module else "error", module_name)
        else:
            # 教材精学区: 跳过专项突破+模块搜索
            record_step("5.听力专项", "done", f"教材精学: {module_name}")

        # 5.5 关"已完成"弹窗 (如果之前跑过该单元)
        time.sleep(1)
        elements = adb.dump_ui()
        for e in elements:
            t = (e.text or '').strip()
            if t in ['先走一步', '继续练习', '已完成', '完成']:
                adb.tap(e.center[0], e.center[1])
                log_msg(f"  关完成弹窗: '{t}' at {e.center}")
                time.sleep(1.5)
                break

        # 6. 版本检查: 如果页面上已经显示正确版本, 跳过
        log_msg(f"检查版本: {version_label}")
        time.sleep(2)
        elements = adb.dump_ui()
        # 检查是否跑到消息页/错误页
        if any('消息' in (e.text or '') and e.center[1] < 200 for e in elements):
            adb.press_back()
            time.sleep(2)
            elements = adb.dump_ui()
        
        # 从version_label提取年级关键词
        grade_keywords = {"五上": "五上", "五下": "五下", "六上": "六上", "六下": "六下"}
        target_kw = ""
        full_grade_map = {"五上":"五年级上册","五下":"五年级下册","六上":"六年级上册","六下":"六年级下册"}
        target_grade_full = ""
        for k, v in grade_keywords.items():
            if k in version_label:
                target_kw = v
                target_grade_full = full_grade_map.get(k, "")
                break
        
        # 检查当前页面是否已经显示正确版本
        page_text = ' '.join([(e.text or '') for e in elements])
        version_already_set = False
        if target_grade_full and target_grade_full in page_text:
            version_already_set = True
            log_msg(f"  版本已正确: {target_grade_full}")
        elif target_kw and target_kw in page_text:
            version_already_set = True
            log_msg(f"  版本已正确(含 {target_kw})")
        
        if target_kw and not version_already_set:
            # 需要手动点击切换版本
            found_grade = False
            for e in elements:
                if e.text and target_kw in (e.text or ''):
                    cx, cy = e.center
                    if 200 < cy < 2200:
                        adb.tap(cx, cy)
                        log_msg(f"  选中 {target_kw} at ({cx},{cy})")
                        found_grade = True
                        break
            if not found_grade:
                log_msg(f"  ⚠ 未找到 {target_kw}, 尝试兜底", "warning")
                adb.tap(*sc(540, 1200))
            time.sleep(3)
        elif version_already_set:
            log_msg(f"  版本一致, 跳过选择")
            time.sleep(1)

        # 7. 选择Unit - 先关可能出现的完成弹窗
        time.sleep(1)
        elements = adb.dump_ui()
        for e in elements:
            t = (e.text or '').strip()
            if t in ['先走一步', '继续练习', '已完成', '完成']:
                adb.tap(e.center[0], e.center[1])
                log_msg(f"  关完成弹窗: '{t}' at {e.center}")
                time.sleep(1.5)
                break

        log_msg(f"选择 Unit {unit}")
        elements = adb.dump_ui()
        # 找到Unit文本的位置 (如果不在当前屏幕, 滚动查找)
        unit_y = None
        for scroll_attempt in range(6):  # 最多滚动5次
            for e in elements:
                if e.text and re.match(rf'^Unit {unit}\b', (e.text or '').strip()):
                    unit_y = e.center[1]
                    log_msg(f"  Unit {unit} 文本 at y={unit_y} (scroll={scroll_attempt})")
                    break
            if unit_y:
                break
            # 没找到, 向下滚动
            if scroll_attempt < 5:
                adb.swipe(*sc(540, 1800), *sc(540, 500), 400)  # 大幅下滚
                time.sleep(0.8)
                elements = adb.dump_ui()
        # 兜底: 模糊匹配 (针对Unit数字小但文本格式不同)
        if not unit_y:
            for e in elements:
                if e.text and f"Unit {unit}" in (e.text or ''):
                    unit_y = e.center[1]
                    log_msg(f"  Unit {unit} 文本(模糊) at y={unit_y}")
                    break

        found_unit = False
        if unit_y:
            # Unit行的"去练习"按钮固定在该unit文本下方~100px处
            # 直接找 y 在 (unit_y + 50, unit_y + 150) 范围内的"去练习"
            btn_y_min = unit_y + 40
            btn_y_max = unit_y + 160
            for e in elements:
                t = (e.text or '').strip()
                if '去练习' in t or '去答题' in t:
                    cy = e.center[1]
                    if btn_y_min < cy < btn_y_max and e.center[0] > 0:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点'去练习' for Unit {unit} at {e.center}")
                        found_unit = True
                        break
            if not found_unit:
                # 兜底: 直接用固定偏移量点
                btn_x = 881  # 常见右侧按钮x
                log_msg(f"  兜底: 点({btn_x}, {unit_y + 99})", "warning")
                adb.tap(btn_x, unit_y + 99)
                found_unit = True
        else:
            log_msg(f"  ⚠ 没找到 Unit {unit} 文本", "warning")
            adb.tap(*sc(540, 1400))
        time.sleep(4)

        # 8. 现在应该在阶段选择页 (基础巩固/综合进阶/难点突破)
        log_msg(f"选择阶段: {stage}")
        found_stage = False
        for wait_i in range(5):
            elements = adb.dump_ui()
            # 直接找阶段按钮, 不判断"是否还在Unit列表"(避免误判)
            for e in elements:
                t = (e.text or '').strip()
                if not t: continue
                # 方式1: 精确匹配
                # 方式2: stage是t的子串(如"基础巩固"在"基础巩固模式"中)
                # 方式3: 尝试用关键字符找(基础/综合/难点、巩固/进阶/突破)
                matched = False
                if t == stage: matched = True
                elif stage in t or t in stage: matched = True
                elif any(kw in t for kw in stage.replace(' ','').split('·')):
                    # 对付"基础·巩固"这类分隔符,拆开后分别匹配
                    for seg in stage.replace('·','').split():
                        if seg in t: matched = True; break
                if matched and e.clickable and 50 < e.center[1] < 2200:
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  点'{t}' at {e.center}")
                    found_stage = True
                    break
            if found_stage:
                break
            log_msg(f"  未找到 {stage} ({wait_i+1}/5)")
            time.sleep(1)
        if not found_stage:
            log_msg(f"  ⚠ 未找到 {stage},可能已是默认阶段,继续执行", "warning")
            # 阶段选择失败不致命 — 可能该页面没有阶段选择,直接进入题目
            # 或者"基础巩固"是默认已选中的
        time.sleep(3)

        # 9. 开始答题 → 轮流尝试 "开始答题"/"去答题"→ 关弹窗 → 等待考题加载
        log_msg("开始答题")
        for attempt in range(5):
            elements = adb.dump_ui()
            # 先检查是否已经在考题页
            in_question = any(re.match(r'^\d+/\d+$', (e.text or "").strip()) for e in elements)
            if in_question:
                log_msg("  已在考题页!", "success")
                break
            # 找"开始答题"/"去答题"按钮
            found_btn = False
            for e in elements:
                t = (e.text or '').strip()
                if t in ['开始答题', '去答题', '开始', 'Start']:
                    if e.clickable and e.center[1] < 2000:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点'{t}' at {e.center}")
                        found_btn = True
                        break
            if not found_btn:
                # 可能已经进入题目但还没加载, 或弹窗挡住了
                # 尝试点屏幕底部中间 (有些APP的确认在底部)
                adb.tap(*sc(540, 2100))
                # 关可能存在的弹窗
                adb.tap(*sc(540, 1800))
            time.sleep(2)

        # 再多等一会儿, 确保题目渲染完成
        time.sleep(2)

        # 10. 逐题巡检循环
        log_msg(f"逐题巡检开始: 脚本={docx_file or '无'}")
        record_step("6.逐题巡检", "running", "")
        last_q = 0
        questions_reviewed = []
        
        # 加载脚本数据 (用于LLM审查)
        from src.review_agent import ReviewAgent, ReviewConfig
        from src.parse_yingyubao_docx import parse

        agent = None
        docx_path = ""
        if docx_file:
            docx_path = str(UPLOAD_DIR / docx_file)
            if Path(docx_path).exists():
                cfg = ReviewConfig(docx_path=docx_path, unit=unit, stage=stage,
                                   screenshot_dir=str(PROJECT_ROOT / "screenshots"), verbose=False)
                agent = ReviewAgent(cfg)
                log_msg(f"  脚本已加载: {docx_file} (共{len(agent.script_questions)}题)", "success")
            else:
                log_msg(f"  ⚠ 脚本不存在: {docx_path}", "warning")

        for loop in range(80):
            if not task_status["running"]:
                log_msg("任务被手动停止", "warning")
                break

            elements = adb.dump_ui(retries=2)
            all_texts = [(e.text or '').strip() for e in elements]

            # ★ 实时题型识别（不依赖脚本，从 UI 元素判断当前是什么题）
            detected = None
            try:
                from src.type_detector import TypeDetector
                detected = TypeDetector(verbose=False).detect(elements)
                if detected and detected.type_1 != "未知":
                    log_msg(f"  🔍 实时题型: {detected.describe()} (conf={detected.confidence:.0%})", "info")
            except Exception:
                detected = None

            # ====== 检测是否在结果页 (有"正确答案"文本) ======
            if any('正确答案' in t for t in all_texts):
                log_msg("[结果页] 刚答完一题, 找'下一题'", "info")
                found_next = False
                for e in elements:
                    t = (e.text or '').strip()
                    if t in ['下一题', '完成', '继续', 'Next']:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点'{t}' at {e.center}")
                        found_next = True
                        break
                if not found_next:
                    adb.tap(*sc(540, 2100))  # 底部兜底
                time.sleep(1.5)
                continue

            # ====== 读题号 ======
            cur = None
            total_q = 0
            for e in elements:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    cur = int(m.group(1))
                    total_q = int(m.group(2))
                    break
            if not cur:
                log_msg("不在考题页,结束", "warning")
                break
            if cur == last_q:
                time.sleep(0.3)
                continue
            last_q = cur

            # 截图
            shot_name = f"q{cur:02d}.png"
            adb.screenshot(shot_name)
            shot_path = str(PROJECT_ROOT / "screenshots" / shot_name)
            log_msg(f"Q{cur:02d}", "success")
            update_progress(cur, total_q, f"Q{cur}")

            # 用ReviewAgent做四维审查 (如果脚本已加载)
            review_result = None
            if agent:
                try:
                    # 找对应脚本题目 — 用列表索引而非global_idx
                    # APP题号是相对位置的(1/15), 脚本按unit+stage过滤后也是有序的
                    script_q = None
                    if cur and 1 <= cur <= len(agent.script_questions):
                        script_q = agent.script_questions[cur - 1]
                    if script_q:
                        # 从UI dump提取屏幕文字 (供文字题走文本模型加速)
                        ui_texts = [e.text or '' for e in elements if e.text and e.text.strip()]
                        r = agent._review_one(script_q, shot_path, ui_texts=ui_texts, detected=detected)
                        review_result = {
                            "stem": "✅" if r.stem_check.passed else "❌",
                            "content": "✅" if r.content_check.passed else "❌",
                            "image": "✅" if r.image_check.passed else "❌",
                            "answer": "✅" if r.answer_check.passed else "❌",
                            "score": r.overall_score,
                            "stem_reason": r.stem_check.details[0] if r.stem_check.details else "",
                            "content_reason": r.content_check.details[0] if r.content_check.details else "",
                            "image_reason": r.image_check.details[0] if r.image_check.details else "",
                            "answer_reason": r.answer_check.details[0] if r.answer_check.details else "",
                        }
                        log_msg(f"  审查: 题干{review_result['stem']} 内容{review_result['content']} 配图{review_result['image']} 作答{review_result['answer']} 得分{review_result['score']:.2f}")

                        # ====== 发送每题结果到后端 ======
                        # ★ 多阶段：qid 带 stage 前缀，避免不同子模块同题号互相覆盖
                        qid = f"{version_label}-U{unit}-{stage}-Q{cur:02d}"
                        det_type = (detected.full_type if detected and detected.full_type else script_q.type_2)
                        record_q_result(
                            qid,
                            idx=cur,
                            total=total_q,
                            question_type=det_type,
                            stem=(detected.stem if detected and detected.stem else script_q.stem)[:40] + "..." if len((detected.stem if detected and detected.stem else script_q.stem)) > 40 else (detected.stem if detected and detected.stem else script_q.stem),
                            recording=script_q.recording,
                            script_answer=script_q.answer,
                            ai_stem=r.stem_check.passed,
                            ai_content=r.content_check.passed,
                            ai_image=r.image_check.passed,
                            ai_answer=r.answer_check.passed,
                            overall_passed=r.overall_passed,
                            overall_score=round(r.overall_score, 2),
                            stem_reason=r.stem_check.details[0][:100] if r.stem_check.details else "",
                            content_reason=r.content_check.details[0][:100] if r.content_check.details else "",
                            image_reason=r.image_check.details[0][:100] if r.image_check.details else "",
                            answer_reason=r.answer_check.details[0][:100] if r.answer_check.details else "",
                            ai_reason=r.content_check.details[0][:100] if r.content_check.details else "",
                            screenshot=shot_name,
                            knowledge_check=r.knowledge_check,
                        )

                        # 加入反馈 (临时先用AI判断)
                        from src.feedback_loop import FeedbackSample
                        agent.feedback.add(FeedbackSample(
                            question_id=qid,
                            check_dimension="all",
                            human_judgment="通过" if r.overall_passed else "不通过",
                            ai_judgment="通过" if r.overall_passed else "不通过",
                            ai_reason=r.content_check.details[0] if r.content_check.details else "",
                            question_type=script_q.type_2,
                            screenshot=shot_name,
                        ))
                except SystemExit:
                    log_msg("⏹ 任务已被立即停止", "warning")
                    raise  # ★ 必须重新抛出，让注入的 SystemExit 继续传播到任务线程外层收尾
                except Exception as e:
                    log_msg(f"  审查异常: {e}", "warning")

            questions_reviewed.append({
                "idx": cur, "screenshot": shot_name, "review": review_result
            })

            # 点击选项 — 根据脚本答案选择正确选项
            found_option = False
            if script_q and script_q.answer in 'ABC':
                # 找对应选项字母的文本 (A/B/C)
                ans_letter = script_q.answer
                for e in elements:
                    t = (e.text or '').strip()
                    # 匹配 "A." / "A、" / "A" 等格式的选项文本
                    if re.match(rf'^{ans_letter}[\.\、\)\s]', t) and e.clickable and 50 < e.center[1] < 2200:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点选项 {ans_letter} at {e.center}")
                        found_option = True
                        break
                if not found_option:
                    # 按选项位置推定: A左/B中/C右
                    opt_x = {'A': 250, 'B': 500, 'C': 750, 'D': 950}.get(ans_letter, 500)
                    candidates = [e for e in elements if e.clickable and 400 < e.bounds[1] < 2000
                                 and abs(e.center[0] - opt_x) < 200 and (e.bounds[2]-e.bounds[0]) > 60]
                    if candidates:
                        # 选最靠上的一个
                        best = min(candidates, key=lambda e: e.center[1])
                        adb.tap(best.center[0], best.center[1])
                        log_msg(f"  点选项(位置推定) {ans_letter} at {best.center}")
                        found_option = True
            
            if script_q and script_q.answer in 'TF':
                # 判断题: 点T或F
                ans_word = {'T': 'T', 'F': 'F'}.get(script_q.answer, '')
                for e in elements:
                    t = (e.text or '').strip().upper()
                    if t == ans_word and e.clickable:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点 {'正确' if ans_word=='T' else '错误'} at {e.center}")
                        found_option = True
                        break
            
            if not found_option:
                # 兜底: 点中间偏左单选区域
                for e in elements:
                    if e.clickable and 400 < e.bounds[1] < 2000 and (e.bounds[2]-e.bounds[0]) > 100:
                        if e.center[0] < 150: continue
                        adb.tap(e.center[0], e.center[1])
                        found_option = True
                        break
            if not found_option:
                adb.tap(*sc(540, 800))
            time.sleep(1.5)

            # 找"检查"按钮, 点它
            found_check = False
            for _ in range(3):
                new_elems = adb.dump_ui()
                for e in new_elems:
                    t = (e.text or '').strip()
                    if t in ['检查', 'Check', '提交', '下一题', '完成']:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  '检查'点中 ({e.center[0]},{e.center[1]})")
                        found_check = True
                        break
                if found_check:
                    break
                adb.tap(*sc(540, 2100))
                time.sleep(0.5)
            time.sleep(1.5)

            # 完成
            if cur >= total_q:
                log_msg(f"✅ 全部 {total_q} 题完成!", "success")
                record_step("6.逐题巡检", "done", f"完成 {len(questions_reviewed)}/{total_q}")
                record_step("7.生成报告", "running", "")
                break

        # 保存审查结果
        if agent and questions_reviewed:
            agent.export_report(str(PROJECT_ROOT / "outputs" / f"review_{docx_file.replace('.docx','')}.md"))
            agent.export_json(str(PROJECT_ROOT / "outputs" / f"review_{docx_file.replace('.docx','')}.json"))
            record_step("7.生成报告", "done", f"已保存到 outputs/")

        if not keep_running:
            set_done()
        log_msg(f"✅ 听力专项巡检完成! {len(questions_reviewed)}题", "success")

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        import traceback
        log_msg(f"❌ 巡检失败: {e}", "error")
        log_msg(traceback.format_exc(), "error")
        if not keep_running:
            set_done()



@app.route("/api/inspect/quick-run", methods=["POST"])
def api_inspect_quick_run():
    """⚡ 快速检查：从当前页面直接开始逐题巡检 (跳过导航)

    可选参数: docx(脚本文件名), unit(单元号) — 提供后逐题做 AI 六维审查
    """
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    data = request.get_json() or {}
    docx_file = data.get("docx", "")
    unit = data.get("unit", 0)
    t = threading.Thread(target=run_quick_inspect_task,
                         args=(docx_file, unit), daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "quick_inspect",
                    "docx": docx_file, "unit": unit})


@app.route("/api/inspect/run", methods=["POST"])
def api_inspect_run():
    """启动逐题巡检 (任务版)"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_inspect_loop, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "inspect_loop"})


@app.route("/api/inspect/stop", methods=["POST"])
def api_inspect_stop():
    """停止正在运行的任务（设置停止标志 + 强制中断线程，与 modules/stop 一致）"""
    if not task_status["running"]:
        return jsonify({"status": "idle", "message": "没有正在运行的任务"})
    # ★ 必须真正停止：只设 running=False 无法中断脚本线程（线程内部不检查 running），
    #   先执行统一停止（标志 + 注入 SystemExit），再清 running 状态
    forced, message = _request_stop()
    task_status["running"] = False
    return jsonify({"status": "stopping", "message": message})


# ============================================================
# 🔵 审查反馈 路由区 — 存储AI判断+人工标注,让审查智能体学习
# ============================================================

_inspection_state = {
    "current_question_idx": 0,
    "questions": {},           # {qid: {ai_result, human_label, timestamp, ...}}
    "workflow_steps": [],     # 当前运行的步骤
    "docx": "",
    "version": "未知版本",
    "unit": "全部",
    "stage": "全部",   # ★ 不能用 "?"（Windows 文件名非法字符）
    "live_report_path": "",    # ★ 实时错题报告(report_live.html)路径（借鉴队友）
    "_reuse_info": "",         # ★ 审查体系改造：复用标记（如"巧记单词 U1 已于2026-08-26审查，本次复用结论")
}

# ★ 实时报告重生成锁（避免多线程下并发写同一文件）
_live_report_lock = threading.Lock()

# ============================================================
# ★ 审查体系改造：脚本审查索引（script_review_index.json）
#   每个（模块+单元）只认真审一次，结论沉淀复用。
#   索引 key = "<版本>/<年级>/<模块>/<单元>"
# ============================================================
SCRIPT_REVIEW_INDEX_PATH = PROJECT_ROOT / "data" / "script_review_index.json"

def load_script_review_index() -> dict:
    """加载脚本审查索引"""
    import json
    try:
        if SCRIPT_REVIEW_INDEX_PATH.exists():
            return json.loads(SCRIPT_REVIEW_INDEX_PATH.read_text(encoding="utf-8") or "{}")
    except Exception:
        pass
    return {}

def save_script_review_index(index: dict):
    """保存脚本审查索引"""
    import json
    SCRIPT_REVIEW_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_REVIEW_INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _current_llm_signature() -> str:
    """当前 LLM 签名 = "<文本模型>|<视觉模型>"，用于脚本审查缓存的失效判定。

    ★ 2026-09-23 修复（换模型后结论不变）：
      缓存此前只按 `script_hash` 判有效，**不含模型**。而缓存里存的是
      "合并后的 auto-* 记录"，同时含脚本层（文本模型判）与界面层（视觉模型判）
      的结论 —— 所以换了文本或视觉任一模型后，旧单元会静默复用旧模型的结论，
      表现为"明明换了模型，重跑结论一模一样"。
      加入模型签名后，模型一变即视为缓存失效，重新审查并打日志说明原因。
    """
    try:
        from src.reviewer_common import LLMClient
        _c = LLMClient.from_config()
        return f"{_c.model or ''}|{_c.vision_model or ''}"
    except Exception:
        # 兜底：至少用环境变量里的文本模型名（_load_dotenv 可能尚未执行）
        try:
            from src.reviewer_common import _load_dotenv
            _load_dotenv()
        except Exception:
            pass
        return f"{os.environ.get('LLM_MODEL', '')}|{os.environ.get('VISION_MODEL', '')}"


def _script_cache_reusable(cached: dict, docx_hash: str, cur_sig: str) -> bool:
    """脚本审查缓存能否直接复用：status=done 且 脚本未变 且 **模型签名一致**。

    ★ 2026-09-23：加入模型签名维度。
      旧缓存没有 `llm_signature` 字段 → `.get(...,"")` 取到空串，
      而真实签名最小也是 "|"，两者永不相等 → 旧缓存一律视为不可复用，
      换模型后首次重跑会重新审查（这正是想要的行为）。
    """
    if not isinstance(cached, dict):
        return False
    return (cached.get("status") == "done"
            and cached.get("script_hash") == docx_hash
            and cached.get("llm_signature", "") == cur_sig)

def _script_file_hash(docx_path) -> str:
    """计算脚本文件 md5 hash，用于检测脚本是否变更"""
    import hashlib
    try:
        return hashlib.md5(open(docx_path, "rb").read()).hexdigest()
    except Exception:
        return ""

# ★ 自动生成脚本的存放目录（与手动上传的 uploads/ 区分）
GENERATED_SCRIPTS_DIR = PROJECT_ROOT / "uploads" / "generated"
GENERATED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

def _save_inspection_state():
    """保存巡检状态到文件, 审查智能体下次学习"""
    import json
    p = PROJECT_ROOT / "data" / "inspection_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(_inspection_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_inspection_state_merge():
    """★ 合并保存：保留旧文件里【其他模块】的题目（多模块检测时，
    新模块结果不与旧模块互相覆盖——否则导出的错题报告只会剩最后一个模块）。
    仅多模块检测的 LLM 审查完成后调用（此时内存含本次全部模块结果）。"""
    import json
    p = PROJECT_ROOT / "data" / "inspection_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        old = {}
        if p.exists():
            old = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        old = {}
    # 合并 questions：本次内存的覆盖同 qid；旧文件里不冲突的保留
    # ★ 2026-09-20 修复（脚本自检结果丢失）：
    #   旧写法 `_merged = dict(old)` + 只覆盖 questions/version/grade/... 几个键 →
    #   **其他所有键都以旧文件为准**，于是本次运行刚写进内存的
    #   `_script_issues`（脚本自检发现的"答案↔关键词不一致"等问题）、
    #   `_reuse_info`、`_modules_total` 等统统被丢弃，
    #   前端/报告读状态文件时看不到脚本问题（实测 API 返回 _script_issues 为空，
    #   而前端日志里明明打了 3 处）。
    #   改为"以内存为准，只从旧文件补 questions 与内存里没有的键"。
    _qs = dict(old.get("questions") or {})
    _qs.update(dict(_inspection_state.get("questions") or {}))
    _merged = dict(_inspection_state)
    _merged["questions"] = _qs
    for _k, _v in old.items():
        _merged.setdefault(_k, _v)      # 内存没有的键才用旧文件兜底
    # 时间/模块信息以最新为准
    for k in ("version", "grade", "module", "start_time", "end_time"):
        if _inspection_state.get(k):
            _merged[k] = _inspection_state[k]
    p.write_text(json.dumps(_merged, ensure_ascii=False, indent=2), encoding="utf-8")


def _live_regen_error_report():
    """
    ★ 实时重新生成"仅错误"的可折叠卡片 HTML 报告（审查中每出一道错题即调用）。
    报告写入 outputs/reports/<版本>/U<单元>_<阶段>_<日期>/report_live.html，
    并刷新 latest 入口。路径记录在 _inspection_state["live_report_path"]。
    """
    _live_report_lock.acquire()
    try:
        from src.report_exporter import ReportExporter
        state = _inspection_state
        qs_all = list(state.get("questions", {}).values())
        meta = {
            "version": state.get("version", "未知版本"),
            "unit": state.get("unit", "全部"),
            "stage": state.get("stage", "全部"),   # ★ "?" 是 Windows 非法字符，会 WinError 123
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total": len(qs_all),
            # ★ 2026-09-20：脚本自检发现的问题（答案↔关键词不一致 / 知识点占位 / 字段名
            #   不统一）必须随报告一起下发——此前只进前端日志，报告里一条都看不到，
            #   用户反馈的正是"脚本有问题没检查出来"。报告侧会：
            #     ① 位置含单元+小题号且与本单元匹配 → 归位到对应题卡；
            #     ② 其余（"全文" / 其他单元）→ 报告末尾「脚本自检」区块。
            "script_issues": state.get("_script_issues") or {},
            # ★ 2026-09-21：脚本溯源（本次拿哪份脚本比对、是否适配）——报告据此
            #   在头部写明"脚本层结论是否可信"，避免用户看到一份来源不明的错题单。
            "script_provenance": state.get("_script_provenance") or {},
        }
        exp = ReportExporter()
        path = exp.export_html_live(qs_all, meta)
        state["live_report_path"] = path
        return path
    except Exception as e:
        log_msg(f"⚠ 实时错题报告生成失败: {e}", "warning")
        return ""
    finally:
        _live_report_lock.release()


# ★ 多模块检测每题界面级证据 → 审查结果区（无脚本也能展示 AI 通过/不通过）
_SCRIPT_CACHE = {}  # ★ 脚本解析缓存 {docx名: script_questions}，避免每题重复解析100题

# ★ 2026-09-10：真正的【脚本子模块名】白名单——只有这些 stage 值才用于
#   "只审查当前子模块的题"（听力专项的练习/测试、口语训练的阶段名等）。
#   巧记单词等模块把 stage 用作定位标签（"U1 第1关"/"U1 boss关"），
#   不属于子模块名 → 内容审查时不做 stage 过滤，否则只会剩最后一关的题。
_SUBMODULE_STAGES = (
    "练习", "测试", "基础巩固", "综合进阶", "难点突破", "考前突破",
    "快速检查", "专项练习", "综合测试",
)


def _should_skip_by_stage(cur_stage: str, q_stage: str) -> bool:
    """内容补充检查是否应跳过该题（按 stage 过滤判定，抽成函数便于单测）

    规则：
      - 任一为空 → 不过滤
      - 当前 stage **不是**脚本子模块名（如巧记单词的"U1 第1关"这类定位标签）→ 不过滤
      - 两边都是子模块名且不同 → 过滤（听力专项：练习的题不能拿测试脚本比）
    """
    if not cur_stage or not q_stage:
        return False
    if cur_stage not in _SUBMODULE_STAGES:
        return False
    return q_stage != cur_stage


def _llm_health_check() -> tuple:
    """★ 2026-09-10 新增：多模块检测启动前做一次 LLM 连通性体检。

    背景：LLM 额度耗尽时（DeepSeek 402 余额耗尽 / 通义千问 403 免费额度用尽）
    整个流程**不会报错**，只是静默降级 —— AI 核查结论变成套话/兜底、
    知识点变成"待人工补充"，用户会误以为"AI 在瞎判"。

    这里在跑之前各发一次极小的探针请求，把结论写进日志（用户在前端直接可见）：
      ✅ AI 核查可用
      ⚠ AI 核查不可用（文本: xxx；视觉: yyy）→ 本次仅做界面级检查，AI 结论不可信

    Returns: (text_ok: bool, vision_ok: bool, detail: str)
    """
    _t_ok = _v_ok = False
    _t_err = _v_err = ""
    try:
        from src.reviewer_common import LLMClient, is_fatal_llm_error
        _c = LLMClient.from_config()
        # 文本探针
        try:
            _r = (_c.ask('回复"ok"两个字符即可') or "")
            _t_ok = bool(_r) and "LLM 调用失败" not in _r and "[LLM 不可用]" not in _r
            if not _t_ok:
                _t_err = _r[:70]
        except Exception as _e:
            _t_err = str(_e)[:70]
        # 视觉探针（只探"是否有额度"，不真正发图——发 1x1 图也会计费，故用文本通道探同 key）
        try:
            if _c.vision_model and _c.vision_api_key:
                if _c.vision_api_key == _c.api_key and _c.vision_base_url == _c.base_url:
                    _v_ok = _t_ok          # 同一供应商同一 key，文本通即视觉通
                else:
                    import json as _json
                    import urllib.request as _ur
                    _body = _json.dumps({
                        "model": _c.vision_model,
                        "messages": [{"role": "user", "content": "ok"}],
                        "max_tokens": 3,
                    }).encode()
                    _req = _ur.Request(
                        _c.vision_base_url.rstrip("/") + "/chat/completions",
                        data=_body,
                        headers={"Authorization": "Bearer " + _c.vision_api_key,
                                 "Content-Type": "application/json"},
                    )
                    _ur.urlopen(_req, timeout=20).read()
                    _v_ok = True
            else:
                _v_ok, _v_err = False, "未配置视觉模型（图片题将降级为纯文本/OCR）"
        except Exception as _e:
            _v_err = str(_e)[:70]
    except Exception as _e:
        return False, False, f"体检异常: {str(_e)[:80]}"
    _detail = ""
    if not _t_ok:
        _detail += f"文本模型: {_t_err}；"
    if not _v_ok:
        _detail += f"视觉模型: {_v_err or '不可用'}；"
    return _t_ok, _v_ok, _detail


def _merge_evidence_record(prev: dict, new: dict) -> dict:
    """★ 2026-09-10 修复：同一道题的多条证据必须【合并】而非覆盖。

    真机场景（巧记单词）：同一题先发一条「第N题 完整性检查」（含题干/选项/作答/音频
    四维），答错后反馈页再发一条「第N题 检查（扬声器内容）」（只含音频维）。
    旧代码直接 `questions[qid] = {...}` → 第二条把第一条整条覆盖，
    前面已检出的维度全部丢失，前端只剩"扬声器"一维 → 用户看到的结论维度过少。

    合并规则：
      1) 六维状态按「不通过 > 通过 > 未检」取优先（任一次判不通过即不通过）
      2) 文本类（题干/选项/截图）后写的非空值覆盖
      3) 人工标注（human_label/human_note）永不被自动证据覆盖
      4) 脚本层结果（script/layer）已回填则保留
    """
    dim_keys = ("ai_stem", "ai_content", "ai_image",
                "ai_answer", "ai_audio", "ai_post_error")
    for k in dim_keys:
        p, n = prev.get(k), new.get(k)
        if p is False or n is False:
            new[k] = False
        elif p is True or n is True:
            new[k] = True
        else:
            new[k] = None
    # ★ 2026-09-20：截图同样"非空优先"。同一题常常被上报多次（完整性检查 +
    #   扬声器/答错检查），旧实现不保护 screenshot → 第二条证据（无图）会把第一条
    #   抓到的截图覆盖成空，错题报告里该题就没有定位图了。
    if not (new.get("screenshot") or "").strip() and (prev.get("screenshot") or "").strip():
        new["screenshot"] = prev["screenshot"]
    # 原因文本：新的非空优先，否则沿用旧的
    for k in ("stem_reason", "content_reason", "image_reason",
              "answer_reason", "audio_reason", "post_error_reason"):
        if not (new.get(k) or "").strip():
            new[k] = prev.get(k) or ""
    # ★ 2026-09-17：建议文本与控件坐标同样按"非空优先"合并，
    #   否则同题两条证据合并后建议/坐标会丢，卡片又退回"建议=原因"。
    for k in ("stem_suggestion", "content_suggestion", "image_suggestion",
              "answer_suggestion", "audio_suggestion", "post_error_suggestion"):
        if not (new.get(k) or "").strip():
            new[k] = prev.get(k) or ""
    _pb, _nb = prev.get("_boxes") or {}, new.get("_boxes") or {}
    if _pb or _nb:
        _mb = dict(_pb)
        _mb.update(_nb)          # 新坐标优先（同一维度以最新页面为准）
        new["_boxes"] = _mb
    for k in ("_suggestions",):
        if not new.get(k) and prev.get(k):
            new[k] = prev[k]
    # 按合并后的维度重算 overall —— 必须走 `_judge_overall`（判定口径唯一出口）
    # ★ 2026-09-23 修复：这里曾用**旧口径** `len(_ck) >= 3 → True，否则 None`，
    #   与 `_judge_overall`（≥2 维明确通过 或 ≥3 维已核验 → 通过）**不一致**。
    #   后果：同一题只要被合并过（模块对同题发多条证据 → `_record_module_evidence`
    #   第 4025 行调本函数），"只剩 2 维可查"的题就被旧口径压成"未判定"。
    #   实测跑完教科五上 U7：第4大题（听录音作答）5 道题每题只有 选项+作答 两维
    #   → 页面显示"通过 14 / 不通过 1 / 未审 5"，而这 5 题本该是"通过"。
    #   （诊断路径：单条记录时 3830 行 `_judge_overall(dims)` 已判通过，说明是
    #    合并路径把它改回 None —— 口径分叉的典型症状。）
    _ck = [new[k] for k in dim_keys if new[k] is not None]
    new["overall_passed"] = _judge_overall({k: new[k] for k in dim_keys})
    new["overall_score"] = round(
        sum(1 for v in _ck if v is True) / max(len(_ck), 1), 2) if _ck else 0.0
    # conclusions 同步（保持与六维一致的 pass/fail/na）
    _cmap = {
        "stem": "ai_stem", "content": "ai_content", "image": "ai_image",
        "answerable": "ai_answer", "audio": "ai_audio",
    }
    _prev_c = prev.get("conclusions") or {}
    _new_c = dict(new.get("conclusions") or {})
    for _dim, _key in _cmap.items():
        _v = new.get(_key)
        _r = (_new_c.get(_dim) or {}).get("detail") or ""
        if not _r:
            _r = (_prev_c.get(_dim) or {}).get("detail") or ""
        _new_c[_dim] = {
            "status": "pass" if _v is True else ("fail" if _v is False else "na"),
            "detail": _r,
        }
    # flow 维度跟随 overall
    _new_c["flow"] = {
        "status": ("pass" if new["overall_passed"] is True
                   else ("fail" if new["overall_passed"] is False else "na")),
        "detail": _new_c.get("flow", {}).get("detail", "") or "",
    }
    new["conclusions"] = _new_c
    # 文本/截图：非空才覆盖
    for k in ("stem", "options", "screenshot", "question_type", "score_info"):
        if not (new.get(k) or "").strip():
            new[k] = prev.get(k) or ""
    # 人工标注 / 脚本层：绝不丢
    new["human_label"] = prev.get("human_label")
    new["human_note"] = prev.get("human_note") or ""
    new["note"] = prev.get("note") or new.get("note") or ""
    if not new.get("script") and prev.get("script"):
        new["script"] = prev["script"]
        new["layer"] = prev.get("layer") or new.get("layer")
    elif prev.get("layer") == "basic+script":
        new["layer"] = "basic+script"
    return new


# ★ 2026-09-20：六维键名（基础层与脚本层共用），以及"维度 → 脚本层建议键"的映射
_SCRIPT_DIM_KEYS = ("stem", "content", "image", "answer", "audio", "post_error")
_DIM_TO_SUGG_KEY = {
    "stem": "题干", "content": "内容", "image": "图片",
    "answer": "答案", "audio": "音频", "post_error": "答错检查",
}


def _judge_overall(dims: dict):
    """统一综合判定 → True(通过) / False(不通过) / None(未判定)。

    ★ 2026-09-20 抽出统一口径，结束"基础层用一套、脚本层用另一套"的打架局面。

    规则：
      · 任一维度明确不通过 → 不通过（"任一层 False 即记错"）
      · 至少 2 个维度明确通过，或 ≥3 个维度已核验且无异常 → 通过
      · 只有 1 个维度可查（信息太薄）→ 未判定，**绝不冒充"通过"**
    说明：旧基础层口径是"可查维度必须 ≥3 才判通过"，而口语训练每题天生只有
    题干+作答两维可查 → 20 题永远停在"未判定"，结果区显示"通过 0 / 未审 20"，
    等于所有通过结论都被丢掉。故补一条"≥2 维明确通过"的通道。
    """
    checked = [v for v in (dims or {}).values() if v is not None]
    if not checked:
        return None
    if any(v is False for v in checked):
        return False
    if sum(1 for v in checked if v is True) >= 2 or len(checked) >= 3:
        return True
    return None


def _fold_script_layer(basic: dict, scr: dict) -> None:
    """把「脚本层」（LLM 判脚本本身：题干/选项/答案/知识点）折算进基础层记录。

    ★ 2026-09-20 修复 —— 用户反馈"脚本问题日志里明明打出来了，结果/报告里一条都看不到"。

    旧代码在合并处只做了一件事：
        _basic["script"] = _state["script"]      # 挂个子字典
    六维布尔（ai_stem/ai_content/…）、原因文案、`overall_passed` **全都没动**。
    于是脚本层判"不通过"的题（实测 U4 第3大题：LLM 指出脚本题干为空、缺例句）
    在结果区依旧显示"未审"，实时错题报告里更是一条错题都没有 —— 因为报告按
    `overall_passed is False` 取错题。

    折算规则（基础层看界面、脚本层看脚本内容，两层互补）：
      · 脚本层 False → 该维置 False，原因前置「❌ 脚本层不通过：」，并带出 LLM 建议；
      · 脚本层 True  → **不冒充**"App 也通过"（脚本没问题 ≠ 界面没问题），
                       仅留档在 `_script_dims` 里参与综合判定；
      · 综合判定     → 用"基础层 ∪ 脚本层"的维度集合按 `_judge_overall` 重算。
    """
    if not isinstance(scr, dict) or not scr:
        return
    _dims = {k: basic.get(f"ai_{k}") for k in _SCRIPT_DIM_KEYS}
    _scr_dims = {}
    for k in _SCRIPT_DIM_KEYS:
        v = scr.get(k)
        if v is None:
            continue
        _scr_dims[k] = v
        # 幂等：已经折算过（ai_ 已是 False）就不再重复拼接原因
        if v is False and _dims.get(k) is not False:
            _dims[k] = False
            basic[f"ai_{k}"] = False
            _r = (scr.get(f"{k}_reason") or "").strip()
            # 去掉 LLM 自带的前缀噪音（"[不通过 | 置信度:92] | " / 开头的 ❌⚠ 等）
            _r = re.sub(r"^\[(不通过|通过)\s*\|[^\]]*\]\s*\|\s*", "", _r).strip()
            _r = re.sub(r"^[❌⚠✅✕✓\s]+", "", _r).strip()
            _old = re.sub(r"^[✅\s]+", "", (basic.get(f"{k}_reason") or "").strip()).strip()
            # 界面层文字常是"✅ …一致/…可点击"这类**通过**叙述，直接接在后面会自相矛盾
            # → 用"｜界面层："显式分段，让检查人员看清"哪一层说了什么"
            basic[f"{k}_reason"] = (
                "❌ 脚本层不通过：" + (_r or "脚本内容本身存在问题（详见脚本核验）")
                + (f"｜界面层：{_old}" if _old else ""))
            if not (basic.get(f"{k}_suggestion") or "").strip():
                _s = ((scr.get("suggestions") or {}).get(_DIM_TO_SUGG_KEY[k]) or "").strip()
                basic[f"{k}_suggestion"] = _s[:220]
    # 综合判定用"基础层维度 + 脚本层判错"的集合。
    # ⚠ 脚本层的 True **绝不能**顶替基础层缺失的维度：脚本本身没问题 ≠ App 界面
    #   与脚本一致。实测大4（听音跟读）App 侧题目内容根本没比对（只在音频里），
    #   若让脚本层 True 顶上去，5 道未核验的题会被判成"通过" —— 正是用户最反感的
    #   "假通过"。所以脚本层只参与"判错"，不参与"判过"；脚本层的逐维结论留档在
    #   `_script_dims` 里供检查人员查看。
    _union = dict(_dims)
    basic["_script_dims"] = _scr_dims
    basic["overall_passed"] = _judge_overall(_union)
    _n_checked = sum(1 for v in _union.values() if v is not None)
    basic["overall_score"] = round(
        sum(1 for v in _union.values() if v is True) / max(_n_checked, 1), 2)
    # conclusions 同步（前端卡片与报告读的是它，不是 ai_*）
    _cons = basic.get("conclusions")
    if isinstance(_cons, dict):
        for _k, _rk in (("stem", "stem"), ("content", "content"), ("image", "image"),
                        ("answer", "answerable"), ("audio", "audio")):
            if _union.get(_k) is None or not isinstance(_cons.get(_rk), dict):
                continue
            _cons[_rk]["status"] = "pass" if _union[_k] is True else "fail"
            if _union[_k] is False:
                _cons[_rk]["detail"] = basic.get(f"{_k}_reason") or _cons[_rk].get("detail", "")
        _fl = _cons.get("flow")
        if isinstance(_fl, dict) and basic["overall_passed"] is not None:
            _fl["status"] = "pass" if basic["overall_passed"] else "fail"
            if basic["overall_passed"] is False:
                _fl["detail"] = "脚本层核验存在不通过项（详见各维度）"


def _resolve_question_unit(scope_unit, state_unit):
    """确定"这道题属于哪个单元"，供题卡 `_unit` / 错题报告定位使用。

    ★ 2026-10-08 新增（抽取自 _record_module_evidence，便于单测）。
    背景：用户一次勾了 U1、U3（范围串 "1,3"）跑口语训练，未判定清单 20 条全部
    渲染成「U1,3 · 第1大题 · 第2小题」—— U1 与 U3 的同名小题完全无法区分。

    规则（与 MEMORY §2 一致：当前单元必须由模块上报，不能从范围串推）：
      ① 优先 `scope_unit` = 模块通过 logger.set_current_unit() 上报的"正在作答单元"；
      ② 模块没上报时才回退 `state_unit`，**且只有它是单个纯数字**（"5"/"6"）才用；
      ③ 其余（"1,3" / "5-6" / "全部" / ""）一律返回 ""，交给报告层退回 meta 单元，
         绝不把范围串当单元号印出来。

    >>> _resolve_question_unit("3", "1,3")
    '3'
    >>> _resolve_question_unit("", "5")
    '5'
    >>> _resolve_question_unit("", "1,3")
    ''
    """
    _u = str(scope_unit or "").strip()
    if _u:
        return _u
    _su = str(state_unit or "").strip()
    return _su if re.fullmatch(r"\d+", _su) else ""


def _record_module_evidence(qidx: int, msg: str, evidence: list, big: int = None):
    """把 engine.py 每题收集的 5 维界面证据（题型/题干/选项/音频/作答）
    映射成前端六维卡片字段写入 _inspection_state["questions"]。

    判定规则：
      - text_ok → 通过(true)；text_mismatch → 不通过(false)；skip → 未检(None)
      - overall: 可查维度≥3且无不通过 → 通过；否则 → 不通过；全是 skip → 未审
    big: 大题号（口语训练"第2大题·第3小题"精确定位；None=无大题概念）
    """
    global _inspection_state
    # ★ 模块上下文（scheduler 设置）：模块名/子模块/模块内题号
    try:
        from common.logger import get_current_module
        _current_module_name, _current_stage_name = get_current_module()
    except Exception:
        _current_module_name, _current_stage_name = "", ""
    if not _current_module_name:
        _current_module_name = _inspection_state.get("module", "")
        _current_stage_name = _inspection_state.get("stage", "")
    # ★ 模块内题号：优先直接用 engine 传来的题号 qidx（engine 的"第N题"就是
    #   当前子模块内题号，App 页面显示 9/10 的 9），不再用跨子模块累加的计数器
    _current_module_qno = qidx
    # 证据维度 → 前端六维映射（"题型"不映射到任何六维，仅作为元信息）
    field_map = {
        "题干": "stem",
        "选项": "content",
        "音频": "audio",
        "作答": "answer",
        "作答匹配": "answer",   # ★ 题型-作答一致性（判断题给ABC等）→ 作答维度
    }
    dims = {"stem": None, "content": None, "image": None,
            "answer": None, "audio": None, "post_error": None}
    reasons = {"stem": "", "content": "", "image": "",
               "answer": "", "audio": "", "post_error": ""}
    # ★ 2026-09-17：基础层也产出「修改建议」，与原因区分开
    #   （旧版只有原因，trace_engine 只能把原因原样当建议 → 卡片上两段一模一样）
    _sugg = {"stem": "", "content": "", "image": "",
             "answer": "", "audio": "", "post_error": ""}
    # ★ 2026-09-17：证据里带的控件坐标（uiautomator node bounds）→ 用于精确红框/特写截图
    boxes = {}

    # 收集实际显示文字（题干+选项，供前端卡展示）
    stem_text = ""
    option_text = ""
    # ★ 2026-09-20 新增：口语训练「小题题干」（App 上真正呈现的题目内容本身）
    sub_stem_text = ""
    sub_stem_src = "dom"    # dom=界面真实文字 / vision=视觉识别（不可用于一致性判定）
    # ★ 2026-09-20 新增：本小题的**大题说明是否按模块设计未上报**
    #   （口语训练"同大题第2小题起不再重复上报大题说明"，只发这个标记）。
    #   用于把"设计上就没报"与"App 真没渲染出来"区分开：
    #   前者不能报警、也不能把题干维度压成"未检"；后者才需要人工连手机确认。
    _caption_suppressed = False
    question_type = "界面检查"  # 默认

    for e in evidence:
        field = e.get("field", "")
        # ★ 2026-09-20：小题题干必须在这里截获——它在 field_map 里没有对应维度，
        #   走到下面 `dim = field_map.get(field); if not dim: continue` 就被丢掉了。
        #   这正是用户反馈"基本题目内容检查不出来"的主因：App 上的单词/句子/问题原文
        #   只作为日志括号显示，从未与脚本 stem 做过一致性比对。
        if field == "小题题干":
            _st = (e.get("actual") or "").strip()
            if _st:
                sub_stem_text = _st[:200]
                sub_stem_src = (e.get("src") or "dom")
            continue
        # ★ 2026-09-20：口语训练"同大题第2小题起不再重复上报大题说明"的显式标记
        #   （同样不在 field_map 里，必须在这里截获，否则被丢弃）
        if field == "大题说明已省略":
            _caption_suppressed = True
            continue
        # ★ 分值等附加信息：写入 note（不参与六维判定），供检查人员参考
        if field == "分值":
            _sc = (e.get("actual") or e.get("diff") or "").strip()
            if _sc:
                _inspection_state["_last_score_info"] = _sc
            continue
        # ★ 2026-08-26 扬声器播放内容（听音题）：存到状态供脚本比对/题干后展示
        if field == "扬声器":
            _spk = (e.get("actual") or "").strip()
            if _spk:
                _inspection_state["_last_speaker_word"] = _spk
            continue
        # 题型识别 → 只更新 question_type
        if field == "题型":
            diff = e.get("diff") or ""
            if diff and ("[" in diff):
                question_type = diff.split("[")[1].split("]")[0] if "]" in diff else diff
            continue

        dim = field_map.get(field)
        if not dim:
            continue
        # ★ 控件坐标（evidence 里带 box 时）：供红框标注/出错区域特写用
        _bx = e.get("box")
        if isinstance(_bx, dict) and _bx.get("w") and _bx.get("h"):
            boxes[dim] = _bx
        etype = e.get("type", "")
        # ★ mismatch 优先：同一维度多条证据时，只要有一条不通过就判不通过
        #   （口语题麦克风不可点 + 通用"作答元素存在"同时写入 answer 维度时，
        #     不通过不能被后写的通过覆盖）
        if etype == "text_ok":
            if dims[dim] is not False:
                dims[dim] = True
        elif etype == "text_mismatch":
            dims[dim] = False
        else:
            if dims[dim] is None:
                dims[dim] = None

        # ★ 提取实际文字：题干/选项的实际内容
        actual = e.get("actual") or ""
        if field == "题干" and actual and actual != "(无题干文字)" and actual != "(无)":
            stem_text = actual[:150]
        if field == "选项" and actual:
            option_text = actual[:120]

        # ★ 生成自然语言原因（检查人员一眼能看懂；不通过原因优先保留）
        diff_str = e.get("diff") or ""
        if etype == "text_mismatch":
            reasons[dim] = _fmt_reason(field, diff_str, "不通过")
        elif etype == "text_ok":
            # 仅当该维度最终判定不是不通过时才写"通过"原因（避免覆盖不通过信息）
            if dims[dim] is not False:
                reasons[dim] = _fmt_reason(field, diff_str, "通过")
        else:
            reasons[dim] = f"{field}未检" if diff_str else ""

    # ★ 审查体系改造：不适用维度直接省略，不再填"需连手机截图"等占位文案
    #   配图/答错后/音频 在不适用维度时，reasons 留空 → 前端不渲染该维度

    # 2026-08-25 新增：App 实际题干 ↔ 脚本题干 匹配校验（口语训练核心需求：
    #   txt 流程第8步"答案与关键词是否正确/听力材料是否正确"→ 每道小题必须核对
    #   App 显示的题干是否与脚本一致，如"第1大题第1小题脚本=then，App 也必须显示 then"）
    # ★ 2026-08-26 巧记单词：抽题模式无序号对应，改为"内容匹配"——
    #   ① 题干类型一致：App 题干（如"听录音选释义"）在脚本同单元能找到同类题型
    #   ② 内容一致：App 关键词/选项/录音词 在脚本该题型下能找到对应单词
    def _script_match_qiaoji(_sq_list, _u_cur):
        """巧记单词内容匹配：返回 (匹配到的脚本题 or None, 相似度)。
        匹配策略：按 App 题干在脚本同单元找最相似题。
          - ratio ≥ 0.6 → 同题型，返回该题（上层写"✅题干类型一致"）
          - ratio < 0.6 → 无同类题（App 题型/题干与脚本不符），返回 None（上层报不通过）
        """
        import difflib as _dl
        _app_all = (stem_text + " " + option_text).strip()
        _cands = [s for s in _sq_list if _u_cur and s.unit == _u_cur]
        if not _cands:
            _cands = _sq_list
        _best, _best_ratio = None, 0.0
        for s in _cands:
            _ss = (getattr(s, "stem", "") or "").strip()
            if not _ss:
                continue
            _r = _dl.SequenceMatcher(None, _ss[:20], stem_text[:20]).ratio() if stem_text else 0.0
            if _r > _best_ratio:
                _best_ratio, _best = _r, s
        if _best is not None and _best_ratio >= 0.6:
            return _best, _best_ratio
        return None, _best_ratio

    _sq_cur = None          # ★ 审查体系改造：命中的脚本题（供脚本层标记/合并）
    _sq_stem_hit = ""       # 命中的脚本题干（供记录展示）
    try:
        _docx_cur = (_GLOBAL_DOCX_MAP or {}).get(_current_module_name, "")
        # ★ 2026-09-20 放宽准入：原条件 `and stem_text` 导致**App 没有文字大题说明**时
        #   整段脚本比对被跳过（实测口语训练第4大题：页面只有「序号 + 小喇叭 + (2分)」，
        #   题干 evidence = "(无题干文字)" → stem_text="" → 连小题内容都不比了，
        #   卡片只剩"界面题干: 未提取到题干文字"，脚本层等于没查）。
        #   只要有任一层文字（大题说明 或 小题内容）就进入比对。
        if _docx_cur and (stem_text or sub_stem_text) \
                and stem_text not in ("(无题干文字)", "(无)"):
            _docx_path_cur = PROJECT_ROOT / "uploads" / _docx_cur
            if _docx_path_cur.exists():
                # ★ 脚本解析缓存（每题调用一次，100题脚本重复解析太慢）
                if _docx_cur not in _SCRIPT_CACHE:
                    from src.review_agent import ReviewAgent, ReviewConfig
                    _agent_cur = ReviewAgent(ReviewConfig(
                        docx_path=str(_docx_path_cur), unit=0, screenshot_dir="", verbose=False))
                    _SCRIPT_CACHE[_docx_cur] = _agent_cur.script_questions
                _sq_list = _SCRIPT_CACHE[_docx_cur]
                # ★ 当前单元号 —— 必须是"模块正在作答的单元"，绝不是 state["unit"]
                #   ★ 2026-09-23 根因修复（用户报"乱判 App 与脚本不符"）：
                #     旧实现 `int(str(state["unit"]).split("-")[0])` 对连跑范围
                #     "5-6" 永远取到 5 → U6 的题全部拿 U5 的脚本段落比对。
                #     实测：App 上显示 "The quick queen is quite quiet."（U5 第2大题），
                #     报告却写"App「What will I do in space?」，脚本应为「The quick
                #     queen is quite quiet.」" —— 两边其实是**不同单元**的同一题号，
                #     被硬拉到一起比，整个第2大题 5 道小题全假错。
                #   取值优先级：① 模块上报的当前单元（口语训练每进一个单元就 set，
                #     权威）→ ② state["unit"] 仅当它是**单值**（"5"）才可用；
                #     带连字符（"5-6"）是范围，作最后兜底并交给下面的跨单元纠偏。
                _u_cur = 0
                try:
                    from common.logger import get_current_unit as _gcu
                    _u_cur = int(_gcu() or 0)
                except Exception:
                    _u_cur = 0
                _u_raw = str(_inspection_state.get("unit", "") or "").strip()
                if not _u_cur and re.match(r"^\d+$", _u_raw):
                    _u_cur = int(_u_raw)
                # ★ 巧记单词：内容匹配（无序号，按题型+内容找）
                _qiaoji_ratio = 0.0
                if _current_module_name == "巧记单词":
                    _sq_cur, _qiaoji_ratio = _script_match_qiaoji(_sq_list, _u_cur)
                    if _sq_cur is None:
                        # ★ 题干类型与脚本不符（App 题型在脚本中找不到同类）
                        #   → 题干维度不通过，原因写清楚（用户要求：App看图填单词但脚本听录音填单词）
                        dims["stem"] = False
                        _script_types = sorted({getattr(s, "type_2", "") or "未知"
                                                for s in (_sq_list if _u_cur else _sq_list)
                                                if getattr(s, "unit", 0) == _u_cur and (getattr(s, "type_2", "") or "") not in ("", "/")})[:5]
                        reasons["stem"] = (f"❌ 题型与脚本不符：App 题干「{stem_text[:40]}」在脚本中无同类题"
                                           f"（脚本该单元题型: {_script_types or '未知'}）")
                        _sq_cur = None
                else:
                    _sq_cur = None
                    # ★ 按 (unit, big, stage_idx) 定位脚本小题（口语训练结构）
                    if big and _u_cur:
                        for _s in _sq_list:
                            if _s.unit == _u_cur and _s.big == big and _s.stage_idx == qidx:
                                _sq_cur = _s
                                break
                    if not _sq_cur:
                        for _s in _sq_list:
                            if _s.global_idx == qidx:
                                _sq_cur = _s
                                break
                    # ★ 2026-09-23 跨单元纠偏（兜底）：
                    #   命中号对、单元不对时，用 App 实际文字在其它单元里找同号小题。
                    #   例：连跑 U5-6，U6 第2大题第3小题被 U5 的同号题命中 →
                    #   App" You'll see the moon and the stars." 在 U6 段落里逐字一致
                    #   → 改用 U6 那道，并同步纠正 _u_cur 供后续小题复用。
                    _sq_cur = _realign_script_unit(
                        _sq_list, _sq_cur, _u_cur, big, qidx,
                        (sub_stem_text or stem_text or "").strip())
                    if _sq_cur is not None:
                        try:
                            _u_cur = int(getattr(_sq_cur, "unit", 0) or _u_cur)
                        except Exception:
                            pass
                if _sq_cur:
                    _script_stem = (getattr(_sq_cur, "stem", "") or "").strip()
                    _sq_stem_hit = _script_stem
                    _script_rec = (getattr(_sq_cur, "recording", "") or "").strip()
                    if _current_module_name == "巧记单词":
                        # ★ 巧记单词匹配成功：题干类型一致
                        if dims["stem"] is not False:
                            dims["stem"] = True
                            reasons["stem"] = (f"✅ 题干类型与脚本一致（脚本同类题「{_script_stem[:40]}」，"
                                               f"App：「{stem_text[:40]}」）")
                        # ★ 2026-08-26 扬声器播放内容 ↔ 脚本 recording 对比（ASR）
                        #   扬声器词 = 从题干后提取的英文单词（_last_speaker_word，由模块写入）
                        _spk = _inspection_state.get("_last_speaker_word", "")
                        if _script_rec:
                            try:
                                from common.asr import compare_against_script
                                _cmp = compare_against_script(_spk, _script_rec)
                                _audio_reason = _cmp.get("reason", "")
                                # 扬声器内容 append 到题干原因后（用户要求：放题干后面展示）
                                if _cmp.get("consistent") is False and dims["audio"] is not False:
                                    dims["audio"] = False
                                if dims["audio"] is None and _audio_reason:
                                    reasons["audio"] = _audio_reason
                                if dims["stem"] is not False and _spk:
                                    reasons["stem"] += f"（扬声器：{_spk}）"
                            except Exception:
                                pass
                            # 扬声器词为空（页面无英文词）→ 提示需接入 ASR 才能核对
                            if not _spk and dims["audio"] is None:
                                reasons["audio"] = (f"脚本录音「{_script_rec[:60]}」；"
                                                    f"扬声器内容需接入 ASR 才能核对（当前未识别到）")
                        elif dims["audio"] is None:
                            reasons["audio"] = f"脚本录音「{_script_rec[:60]}」"
                    elif _script_stem or (getattr(_sq_cur, "caption", "") or "").strip():
                        # ★ 2026-09-17 修复（口语训练整单元 100% 误报"题干与脚本不符"）：
                        #   口语训练页面顶部显示的是**大题说明**（脚本 caption：
                        #   "请阅读短文，点击小喇叭播放问题…"，所有小题共用），
                        #   而脚本每道小题的 stem 是小题题面本身（"mum moon" /
                        #   "What will come tomorrow?"）。旧实现拿"大题说明"去比
                        #   "小题题面"→ 两者永远不同 → 每道小题都判不通过
                        #   （用户实测：20 题全挂、通过率 0%、红框还框在状态栏上）。
                        #   同一层级才有可比性 → 有 caption 就先与 caption 比。
                        _app_stem = stem_text.strip()
                        _cap = (getattr(_sq_cur, "caption", "") or "").strip()
                        _expect = _cap or _script_stem
                        _what = "大题说明" if _cap else "题干"
                        if not _app_stem and _caption_suppressed:
                            # ★ 2026-09-20：本小题是**按设计**不重复上报大题说明
                            #   （模块只在每大题第 1 小题发一次，避免重复证据卡；
                            #    这里给它加过一个"大题说明已省略"标记）。
                            #   所以这**不是缺陷**：既不能刷"⚠ 需连手机人工确认"的假告警，
                            #   也不能把题干维度压成"未检"（否则 20 题里 16 题显示不出结论）。
                            #   本小题的题干结论交给下面「小题目内容 ↔ 脚本 stem」同层级比对。
                            pass
                        elif not _app_stem:
                            # ★ 2026-09-20：App 该题没有渲染文字题干（口语训练第4大题
                            #   只有「序号 + 小喇叭 + (2分)」，问题由音频播放）。
                            #   两种来源要分开处理：
                            #     ① 基础层本来就报"未提取到题干文字" → 那是**取证失败/
                            #        该题本就无文字**，直接判"题干不通过"是**假错**
                            #        （实测 auto-Q04-01 因此成了不通过）→ 降为"未判定"
                            #        并写明脚本应有内容，交人工确认；
                            #     ② 已有真实的"与脚本不符"结论 → 保留，不能被覆盖。
                            _old_stem_reason = reasons.get("stem") or ""
                            _is_extract_fail = ("未提取到题干文字" in _old_stem_reason
                                                or "无题干文字" in _old_stem_reason)
                            if dims["stem"] is not False or _is_extract_fail:
                                dims["stem"] = None       # 未判定，不计入不通过
                                reasons["stem"] = (
                                    f"⚠ App 未取到{_what}文字（脚本{_what}：「{_expect[:50]}」）"
                                    f"——该题可能以音频/图片呈现，或页面未渲染；需连手机人工确认")
                                # ★ 2026-09-20 修复 KeyError: 'stem'（整条记录写不进去）：
                                #   这里原本是 `_sugg.pop("stem", None)` —— 清空"题干建议"。
                                #   但 pop 会把 key **整个删掉**，而函数末尾（第3704行）
                                #   `"stem_suggestion": _sugg["stem"]` 是**无条件下标取值**
                                #   → 抛 KeyError，_record_module_evidence 中途失败，
                                #   这道题既不进 questions 也留下一条"入库异常"告警。
                                #   之所以现在才暴露：本分支只在"App 未取到文字"的
                                #   **后续小题**（第2~5小题）才会走到，而这些题当年
                                #   evidence=[] 被 log_msg 当成"没传证据"直接跳过，
                                #   根本进不到这里（被"空证据被吞"那个 bug 掩盖了）。
                                #   清空用赋值，绝不能用 pop 删除后续要读的键。
                                _sugg["stem"] = ""
                        elif not _expect:
                            # ★ 2026-09-23：脚本该小题既无 caption 也无 stem/句型提示
                            #   → 没有可比对对象。此时绝不能因为"脚本侧是空的"就判
                            #   App 不通过（那是脚本没写内容，不是 App 写错）。
                            pass
                        elif _text_like(_app_stem, _expect):
                            if dims["stem"] is not False:
                                dims["stem"] = True
                                _tail = ""
                                if _cap and _script_stem:
                                    _tail = (f"；小题题面「{_script_stem[:40]}」在音频/图片中呈现，"
                                             f"需连手机核对播放内容")
                                reasons["stem"] = (f"✅ {_what}与脚本一致"
                                                   f"（脚本：{_expect[:50]}，App：{_app_stem[:50]}）{_tail}")
                                # ★ 2026-09-20 新增：脚本带「例句/句型」时，App 文字里也必须
                                #   出现该句型正文。实测教科版 U4 第3大题：App 说明是
                                #     「例句：\n请结合例句和图片说句子，点击"录音"开始作答…」
                                #   —— 只有「例句：」标签、正文为空，而脚本写明
                                #   `例句：I will bring everything inside.`；同时该题
                                #   小题题干来自**视觉识别**（DOM 无文字）→ 可判定 App 未
                                #   渲染例句文本。这里做成**提示不判错**（正文可能被拆到别的
                                #   text 节点或画在图上），需要人工确认。
                                _sp = (getattr(_sq_cur, "sentence_pattern", "") or "").strip()
                                if _sp and stem_text and ("例句" in stem_text or "句型" in stem_text):
                                    _n_app = re.sub(r"\s+", "", stem_text)
                                    _n_sp = re.sub(r"\s+", "", _sp)
                                    if _n_sp and _n_sp[:10] not in _n_app:
                                        reasons["stem"] += (
                                            f"；⚠ 脚本例句「{_sp[:50]}」未出现在 App 文字中"
                                            f"（App 只有「例句：」标签），需连手机确认是否漏显示")
                        elif _text_diff_minor(_app_stem, _expect):
                            # ★ 2026-09-20（用户反馈"有一点不符就判不通过不太好，
                            #   要真能找出影响用户作答的内容"）：差异**只**属格式
                            #   （标点有无/全半角、大小写、空格、连字符）→ 不影响学生
                            #   作答，判通过并注明"仅格式差异"，不再制造错题卡。
                            if dims["stem"] is not False:
                                dims["stem"] = True
                                reasons["stem"] = (f"✅ {_what}与脚本内容一致"
                                                   f"（仅格式差异：App「{_app_stem[:50]}」/ "
                                                   f"脚本「{_expect[:50]}」）")
                        else:
                            dims["stem"] = False   # ★ mismatch 优先：脚本比对不通过 → 题干不通过
                            # ★ 2026-08-30 修复：big=None（听力专项等无大题概念）时只显示"第N题"，
                            #   不渲染"第None大题·第N小题"
                            _pos = f"第{big}大题·第{qidx}小题" if big else f"第{qidx}题"
                            reasons["stem"] = (f"❌ {_what}与脚本不符：App「{_app_stem[:60]}」，"
                                               f"脚本应为「{_expect[:60]}」")
                            _sugg["stem"] = (f"把 App 该处{_what}改成脚本原文"
                                            f"「{_ellipsis(_expect, 70)}」；"
                                            f"若确认是脚本写错则同步修改脚本，两边须逐字一致")
                    # ★ 2026-09-20 新增：小题目内容 ↔ 脚本 stem（同层级比对）
                    #   为什么必须单独立这一维：App 顶部是"大题说明"（比 caption），
                    #   而学生真正看到/朗读的**题目内容**是小题题面——脚本 stem
                    #   （朗读单词 "mum moon"、朗读句子 "A typhoon is coming."、
                    #   阅读题的问题 "What will come tomorrow?"）。旧逻辑拿 caption
                    #   比完就收工，小题内容一个字都没对上过 → 脚本写错小题内容
                    #   也永远检查不出来。
                    #   只比"两边都有实义文字"的情形：看图题脚本 stem 是 [Image] 占位、
                    #   App 未识别到小题文字时跳过，否则会把"图片题本就无文字题面"误报。
                    _st_ph = ("[image]", "[图片]", "[img]", "(无题干文字)", "(无)", "/", "-", "none")
                    # ★ 2026-09-23：脚本侧"应有题面"= stem（题目内容）**或**句型提示。
                    #   口语训练 U6/U7 第3大题脚本只写「例句：I will talk to astronauts.」，
                    #   小题 stem 为空 → 旧实现 `_s_txt=""` → 整大题跳过比对（等于没查）。
                    #   ⚠ 绝不回退到 answer（参考答案）：那是评分参考，App 上不显示，
                    #   拿来当"应有题面"必然造成"图片题全判不符"的假错（用户明确要求）。
                    _s_pat = (getattr(_sq_cur, "sentence_pattern", "") or "").strip()
                    _s_txt = (_script_stem or _s_pat).strip()
                    _a_txt = (sub_stem_text or "").strip()
                    # ★ 2026-09-20：App 上有些"文字"其实是 UI 标签而不是题目内容
                    #   （实测口语训练第4大题的小题题干被读成「听录音作答」，而脚本
                    #   该小题是 "What will come tomorrow?"）——直接比对会把
                    #   "题目内容以音频呈现"这种**正常设计**判成"内容不符"，整单元假错。
                    #   判据两条，命中即**不判定**（只登记脚本内容供人工听音频核对）：
                    #     ① App 文字是常见 UI 标签（短，且命中标签词表）；
                    #     ② 两侧语种不一致（一方含 ASCII 字母、另一方没有）
                    #        → App 侧根本不是同一语言的内容，没有可比性。
                    #   ★ 2026-09-23：模块侧占位标签由「听音频跟读」改为「听录音作答」
                    #     （五上U6第4大题是"点小喇叭听题 → 口语作答"，不是跟读）。
                    #     两个都留在词表里，兼容历史状态文件。
                    _uikit = ("听录音作答", "听音频跟读", "点击录音", "听录音", "点击完成",
                              "点击小喇叭", "开始录音", "录音中", "点击结束", "听音频",
                              "跟读", "播放")
                    _label_like = bool(_a_txt) and len(_a_txt) <= 12 and any(k in _a_txt for k in _uikit)
                    _lang_diff = (bool(re.search(r"[A-Za-z]", _a_txt))
                                  != bool(re.search(r"[A-Za-z]", _s_txt)))
                    if _s_txt and _s_txt.lower() not in _st_ph and (_label_like or _lang_diff):
                        # 允许在"已判为未判定（⚠ 开头）"时继续追加说明，否则
                        # 第1小题（基础层已报未提取到题干）会吞掉这条信息
                        if dims["stem"] is not False or (reasons.get("stem") or "").startswith("⚠"):
                            _why = "App 显示的是界面标签" if _label_like else "App 文字与脚本语种不一致"
                            reasons["stem"] = (reasons.get("stem") or "") + (
                                f"；小题内容未做一致性判定（{_why}：「{_a_txt[:30]}」）；"
                                f"脚本该小题内容：「{_s_txt[:50]}」，需连手机听音频核对")
                    elif sub_stem_src in ("vision", "script") and _s_txt \
                            and _s_txt.lower() not in _st_ph:
                        # 图片/看图题：App 没有可判定的文字题面。
                        #   src=vision → 题面由视觉模型描述（概率性，可能是参考答案）
                        #   src=script → 模块直接取脚本内容作展示（2026-09-23 新增）
                        # 两种情况都**不做"一致/不一致"判定**，只登记脚本应有内容
                        # 供人工比对配图。绝不因为"图片题猜出来的句子≠脚本句型"判不通过。
                        if dims["stem"] is not False or (reasons.get("stem") or "").startswith("⚠"):
                            _src_txt = ("题面由视觉识别得到、未做一致性判定"
                                        if sub_stem_src == "vision"
                                        else "图片题：App 只显示图片+句型提示、不显示答案，"
                                             "此处以脚本内容为准展示、未做一致性判定")
                            reasons["stem"] = (reasons.get("stem") or "") + (
                                f"；{_src_txt}"
                                f"（脚本小题内容：{_s_txt[:50]}，需人工核对配图是否匹配）")
                    elif _s_txt.lower() not in _st_ph and _a_txt.lower() not in _st_ph \
                            and len(_s_txt) >= 2 and len(_a_txt) >= 2:
                        if _text_same_strict(_a_txt, _s_txt):
                            if dims["stem"] is not False:
                                # ★ 2026-09-20：本小题"大题说明按设计未上报"（第2小题起），
                                #   唯一可用的同层级证据就是这条「小题目内容 ↔ 脚本 stem」，
                                #   它一致 → 题干维度判**通过**。
                                #   不这么做的话整题长期停在"未检"，检查人员看不出
                                #   这题究竟查过没有。第1小题不走这里（它已用大题说明比过 caption）。
                                if _caption_suppressed:
                                    dims["stem"] = True
                                reasons["stem"] = (reasons.get("stem") or "") + (
                                    f"；小题目内容与脚本一致（脚本：{_s_txt[:50]}，App：{_a_txt[:50]}）")
                        elif _text_diff_minor(_a_txt, _s_txt):
                            # ★ 2026-09-20：仅格式差异（标点/大小写/空格）→ 不判不通过，
                            #   注明后通过；字母级差异（nose/note、take/bring）仍在上面的
                            #   严格比对里判不通过——那才是真正影响学生作答的。
                            if dims["stem"] is not False:
                                if _caption_suppressed:
                                    dims["stem"] = True
                                reasons["stem"] = (reasons.get("stem") or "") + (
                                    f"；小题目内容与脚本一致（仅格式差异："
                                    f"App「{_a_txt[:50]}」/ 脚本「{_s_txt[:50]}」）")
                        else:
                            dims["stem"] = False   # 内容不符 → 题干维度不通过
                            _pos2 = f"第{big}大题·第{qidx}小题" if big else f"第{qidx}题"
                            # ★ 2026-09-20：改用严格比对（逐字一致）后，把"差多少"也写出来，
                            #   便于一眼区分"整句都不对"和"只差一个字母的笔误"。
                            import difflib as _dl2
                            _r2 = _dl2.SequenceMatcher(
                                None, _norm_for_cmp(_a_txt), _norm_for_cmp(_s_txt)).ratio()
                            _hint = (f"（两侧高度相似 {_r2:.0%}，疑似拼写/用词笔误，请逐字核对）"
                                     if _r2 >= 0.75 else "")
                            reasons["stem"] = (
                                f"❌ 小题目内容与脚本不符：App「{_a_txt[:60]}」，"
                                f"脚本应为「{_s_txt[:60]}」{_hint}")
                            _sugg["stem"] = (f"把 App 该小题内容改成脚本原文"
                                            f"「{_ellipsis(_s_txt, 70)}」；"
                                            f"若确认是脚本写错则同步修改脚本，两边须逐字一致")
                    if _script_rec and dims["audio"] is None:
                        # ★ 听力材料（脚本 recording）有内容但无音频证据 → 留空不渲染
                        pass
    except Exception:
        pass

    # ★ 综合判定：统一走 _judge_overall（2026-09-20 抽出）
    #   旧口径"可查维度 ≥3 才判通过"把口语训练（每题天生只有 题干+作答 两维可查）
    #   全部压成"未审"→ 结果区"通过 0 / 未审 20"，实测通过结论全被丢掉。
    #   现补一条"≥2 维明确通过"的通道；只有 1 维可查仍算未判定，不冒充通过。
    checked = [d for d in dims.values() if d is not None]
    passed_cnt = sum(1 for d in dims.values() if d is True)
    overall = _judge_overall(dims)

    # ★ 2026-09-20 修复：自动截图原来在这里做，但那时 qid 还没算出来，
    #   并且条件是「overall is False」（必须当场判错）——见下方题号确定后的真实截图点。
    #   （占位：不要在此处抓图，否则拿不到题号就无法去重/补图）

    total = len(_inspection_state.get("questions", {})) + 1
    # ★ 2026-08-30 修复：按 (模块·stage) 维护题数，total 改为"各模块总题数"列表渲染，
    #   而非单一总数字（用户要求"测了听力专项的练习+测试，总览要分开展示各自动态题数"）
    _mod_key = f"{_current_module_name or '未知'}{'·' + _current_stage_name if _current_stage_name else ''}"
    _mods_total = _inspection_state.setdefault("_modules_total", {})
    # ★ 2026-08-25 修复：口语训练"第N大题·第M小题"结构下，不同大题的小题号重复
    #   （每个大题都有小题1-5）→ 旧 qid "auto-Q{小题号}" 会被后面大题的同号小题覆盖，
    #   只剩最后一大题。改为 "auto-Q{大题:02d}-{小题:02d}" 保证每题唯一；
    #   无 big（听力专项/单元自检等）保持旧格式 auto-Q{idx:03d}（与 summary 统计兼容）。
    if big:
        qid = f"auto-Q{big:02d}-{qidx:02d}"
    else:
        qid = f"auto-Q{qidx:03d}"

    # ★ 2026-09-10 通用防御（与巧记单词"跑完6关只剩15题"同一个根因）：
    #   题号来自【阶段内题号】，而每个阶段/子模块都从 1 重新开始
    #   （听力专项的「练习」+「测试」、巧记单词的 第1关~boss关…），
    #   于是同一个 qid 被后一阶段覆盖，审查结果只剩最后一个阶段的题。
    #   这里用 _qid_owner 记录每个 qid 属于哪个 (模块|阶段|大题) 作用域：
    #   发现同号却来自不同作用域 → 会互相覆盖 → 立刻分配一个全新号，并记一条可见日志。
    #   （已在模块内部做过全局编号的模块不会触发，零副作用）
    _qid_owner = _inspection_state.setdefault("_qid_owner", {})
    # (作用域 + 原始题号) → 最终 qid 的稳定映射：同一题重复上报（完整性检查 +
    # 扬声器内容检查）必须落回同一个 qid，否则一道题会被拆成两条记录。
    _qid_map = _inspection_state.setdefault("_qid_map", {})
    # ★ 2026-09-23：作用域必须含**单元号**。旧实现只有「模块|阶段|大题」，
    #   连跑 U5-6 时两个单元的第2大题第1小题都叫 auto-Q02-01 → 后跑的单元
    #   把先跑的整批题**覆盖**掉（实测 state 里 20 条全是 U6 的题，U5 的题一条不剩，
    #   而报告截图还是 U5 的 → "图上是 sit in the sun、文字却说 App 是 moon"）。
    _scope_unit = ""
    try:
        from common.logger import get_current_unit as _gcu2
        _scope_unit = str(_gcu2() or "")
    except Exception:
        _scope_unit = ""
    _scope_key = f"{_current_module_name}|{_current_stage_name}|{_scope_unit}|{big or ''}"
    _map_key = f"{_scope_key}#{qid}"
    if _map_key in _qid_map:
        qid = _qid_map[_map_key]
    else:
        _owner = _qid_owner.get(qid)
        if _owner is not None and _owner != _scope_key:
            _mx = 0
            for _k in _qid_owner:
                for _m in re.finditer(r"[Qq]0*(\d+)", str(_k)):
                    _mx = max(_mx, int(_m.group(1)))
            _new_qid = f"auto-Q{_mx + 1:03d}"
            while _new_qid in _qid_owner:      # 兜底：绝不撞已有号
                _mx += 1
                _new_qid = f"auto-Q{_mx + 1:03d}"
            try:
                log_msg(f"⚠ 题目编号冲突：「{_scope_key}」与「{_owner}」同为 {qid} → 已重编号 {_new_qid}",
                        "warning")
            except Exception:
                pass
            qid = _new_qid
        _qid_map[_map_key] = qid
    _qid_owner[qid] = _scope_key

    # ★ 2026-09-20 修复「错题报告写了题号、却没有定位截图」：
    #   旧逻辑只在「本次上报当场判 False」时才截图。可口语训练这类模块的大量小题
    #   在基础层是 None（未判定，比如小题目内容被判"仅有 UI 标签"），要等**收尾时**
    #   脚本层折算（_fold_script_layer）才翻成 False —— 那一刻 App 早就翻页了，
    #   再想补图只能拍到下一题的画面，于是错题报告里这几道题一张图都没有（实测
    #   U6 第3大题第2~5小题就是这个情况）。
    #   改法：趁 App 正停留在这道题的画面上，只要这一题还没有截图就抓一张留存。
    #   之后无论判定怎么变（界面层→脚本层折算/缓存复用），错题报告都拿得到定位图。
    _auto_shot = ""
    _prev_rec = _inspection_state.setdefault("questions", {}).get(qid)
    if _prev_rec and _prev_rec.get("screenshot"):
        _auto_shot = _prev_rec["screenshot"]          # 已有图就复用，不重复拍
    else:
        try:
            # ★ 等 0.8s：页面内容（排序项/选项）渲染有延迟，立即截图会截到空白
            time.sleep(0.8)
            _shot_dir = PROJECT_ROOT / "screenshots"
            _shot_dir.mkdir(parents=True, exist_ok=True)
            # ★ 文件名带大题号：不同大题的第1小题（Q02-01/Q03-01）原本都叫 q001，
            #   同一秒内会互相覆盖。
            _seq = f"b{big:02d}q{qidx:03d}" if big else f"q{qidx:03d}"
            _auto_shot = (f"auto_{_current_module_name or 'mod'}_{_seq}_"
                          f"{datetime.now().strftime('%H%M%S')}.png")
            _conn = _connect_device()
            if _conn is not None:
                for _r in range(3):
                    try:
                        _conn.screenshot(str(_shot_dir / _auto_shot))
                        break
                    except OSError:
                        if _r >= 2:
                            raise
                        time.sleep(0.5)
            else:
                _auto_shot = ""
        except Exception:
            _auto_shot = ""

    # 去重 key 与最终 qid 保持一致（否则重编号的题在分模块统计里会算两次）
    _qid = qid
    # ★ 去重集合用 dict（JSON 不支持 set → _save_inspection_state 会整体序列化失败丢状态！）
    _seen = _inspection_state.setdefault("_seen_qids", {})
    _seen_key = _qid + "@" + _mod_key
    if not _seen.get(_seen_key):
        _seen[_seen_key] = 1
        _mods_total[_mod_key] = _mods_total.get(_mod_key, 0) + 1

    # ★ 描述文字：让检查人员知道题目大概内容和位置
    # ★ 描述文字：让检查人员知道题目大概内容和位置
    if not stem_text:
        stem_text = f"第{qidx}题（{question_type}）"
    # ★ 大题号定位（口语训练"第2大题·第3小题"）：错题报告能定位到 大题·小题
    if big:
        stem_text = f"第{big}大题·{stem_text}" if not stem_text.startswith("第") else f"第{big}大题·{stem_text}"
        progress_str = f"大{big}-Q{qidx}"
    else:
        progress_str = f"Q{qidx}"
    _loc = {"big": big} if big else {}
    # ★ 2026-10-08：这道题所属的单元（见 _new_rec["_unit"] 处的说明与
    #   _resolve_question_unit 的 docstring）
    _now_unit = _resolve_question_unit(_scope_unit, _inspection_state.get("unit", ""))

    _new_rec = {
        "idx": qidx,
        "total": total,
        "question_type": question_type,
        "screenshot": _auto_shot,  # ★ 错题自动截图（听力专项答错截图 + 通用兜底）
        "progress": progress_str,
        # ★ 分值信息（evidence 附加项，供检查人员参考）
        "score_info": _inspection_state.get("_last_score_info", ""),
        # ★ 模块定位信息（哪个模块·哪个子模块·模块内第几题）→ 错题报告按此分组
        "module": _current_module_name,
        "stage": _current_stage_name,
        "module_qno": _current_module_qno,
        # ★ 2026-10-08 修复「报告把每个单元都标成范围串」：
        #   原实现取 `_inspection_state["unit"]`，但那是**本轮运行范围**
        #   （用户勾 U1、U3 跑 → "unit" = "1,3"），不是这道题所属的单元。
        #   实测（湘少四下 口语训练:1,3）未判定清单 20 条全部渲染成
        #   「U1,3 · 第1大题 · 第2小题」，U1 与 U3 的同名小题**完全无法区分**，
        #   审查员定位不到题（用户明确要求报告位置必须可直接定位）。
        #   正解：优先用模块自己上报的当前单元（`logger.set_current_unit()`，
        #   口语训练在 _run_unit_questions 里上报）；只有当模块没上报、且
        #   state["unit"] 本身就是**单个纯数字**时才回退——范围串/“全部”一律留空，
        #   让报告层退回 meta 单元，绝不把 "1,3" 当单元号印出来。
        "_unit": _now_unit,
        **_loc,
        # 六维判定（旧格式，兼容已有消费者）
        "ai_stem": dims["stem"], "ai_content": dims["content"],
        "ai_image": dims["image"], "ai_answer": dims["answer"],
        "ai_audio": dims["audio"], "ai_post_error": dims["post_error"],
        "overall_passed": overall,
        "overall_score": round(passed_cnt / max(len(checked), 1), 2) if checked else 0.0,
        # 详细原因（自然语言）
        "stem_reason": reasons["stem"], "content_reason": reasons["content"],
        "image_reason": reasons["image"], "answer_reason": reasons["answer"],
        "audio_reason": reasons["audio"], "post_error_reason": reasons["post_error"],
        # ★ 2026-09-17：修改建议（trace_engine 直接读取，避免"建议=原因"重复文案）
        # ★ 2026-09-20：改用 .get() —— 这条记录是"一道题的价值全部所在"，
        #   不允许因为某个建议键被误删（曾用 _sugg.pop("stem")）就整条写不进去。
        #   六个维度名不齐只会让某条建议为空，不该让整题消失。
        "stem_suggestion": _sugg.get("stem", ""), "content_suggestion": _sugg.get("content", ""),
        "image_suggestion": _sugg.get("image", ""), "answer_suggestion": _sugg.get("answer", ""),
        "audio_suggestion": _sugg.get("audio", ""), "post_error_suggestion": _sugg.get("post_error", ""),
        # ★ 控件坐标：红框精准定位 + 出错区域特写（截图"截到问题上"的关键数据）
        "_boxes": boxes,
        # ★ 审查体系改造：新结构——统一结论字典（旧字段兼容保留，迁移期并存）
        #   每个维度含 status(pass/fail/na) + detail(具体结论文本)
        #   na = 不适用（该维度无需检查），前端不渲染
        "conclusions": {
            "stem":        {"status": "pass" if dims["stem"] is True else ("fail" if dims["stem"] is False else "na"), "detail": reasons["stem"]},
            "content":     {"status": "pass" if dims["content"] is True else ("fail" if dims["content"] is False else "na"), "detail": reasons["content"]},
            "image":       {"status": "pass" if dims["image"] is True else ("fail" if dims["image"] is False else "na"), "detail": reasons["image"]},
            "answerable":  {"status": "pass" if dims["answer"] is True else ("fail" if dims["answer"] is False else "na"), "detail": reasons["answer"]},
            "answer_knowledge": {"status": "na", "detail": ""},
            "audio":       {"status": "pass" if dims["audio"] is True else ("fail" if dims["audio"] is False else "na"), "detail": reasons["audio"]},
            "flow":        {"status": "pass" if overall is True else ("fail" if overall is False else "na"), "detail": "流程无卡顿" if overall is True else ""},
            "report":      {"status": "na", "detail": ""},
        },
        # ★ 题目内容展示文字
        "stem": stem_text,
        "options": option_text,
        "script_answer": "",
        "note": "",
        "human_label": None,
        "human_note": "",
        "timestamp": datetime.now().isoformat(),
        # ★ 审查体系改造：分层标记（基础层 = UI 证据；脚本层 = 对照 docx 脚本）
        #   有匹配脚本 → basic+script（脚本层待后置 LLM 审查回填合并）
        #   无匹配脚本 → basic_only（仅基础层）
        "layer": "basic+script" if _sq_cur else "basic_only",
        "script": {
            "matched": True,
            "status": "pending",          # 待 LLM 脚本审查回填 → done
            "script_stem": _sq_stem_hit,
        } if _sq_cur else None,
    }
    # ★ 2026-09-10 修复：同一题可能发多条证据（"完整性检查" + "检查（扬声器内容）"），
    #   旧代码直接赋值 → 后一条把前一条整条覆盖，已检出的维度全丢。
    #   改为：已有记录则合并（六维取"不通过 > 通过 > 未检"优先）
    _prev_rec = _inspection_state["questions"].get(qid)
    if _prev_rec:
        _new_rec = _merge_evidence_record(_prev_rec, _new_rec)
    _inspection_state["questions"][qid] = _new_rec
    _inspection_state["current_question_idx"] = qidx
    # ★ 每 10 题保存一次到文件（供错题溯源 trace 页面读取，避免只存内存导致 trace 看不到）
    if total % 10 == 0:
        try:
            _save_inspection_state()
        except Exception:
            pass
    # ★ 检测过程中出现错题 → 触发实时错题报告（前端「📑 查看报告」实时更新）
    if overall is False:
        try:
            _live_regen_error_report()
        except Exception:
            pass


def _text_like(app: str, script: str) -> bool:
    """App 提取文字与脚本文字是否"实质相同"（容忍空格/标点/HTML 实体差异）。

    ★ 2026-09-17 新增：题干比对必须"同层级比同层级"。
      口语训练页面顶部是大题说明（caption），脚本题面是小微题面（stem），
      旧实现混着比 → 整单元误报"题干与脚本不符"。
    """
    import html as _html
    def _n(s):
        s = _html.unescape(str(s or ""))
        s = re.sub(r"[\s\u00a0]+", "", s)
        s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        return s
    # ★ 2026-09-23：先剥「句型提示：/例句：」标签，否则 App「句型提示：Hello, this is ...」
    #   与脚本「Hello, this is ...」会被判成不同（整大题假错）。
    a, b = _n(_strip_prompt_label(app)), _n(_strip_prompt_label(script))
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    import difflib as _dl
    return _dl.SequenceMatcher(None, a, b).ratio() >= 0.85


def _norm_for_cmp(s: str) -> str:
    """比对用归一化：HTML 实体、空白、引号/常见标点全半角差异都不算差异。"""
    import html as _html
    s = _html.unescape(str(s or ""))
    s = re.sub(r"[\s\u00a0]+", "", s)
    for _a, _b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"),
                   ("，", ","), ("。", "."), ("：", ":"), ("；", ";"),
                   ("？", "?"), ("！", "!"), ("、", ","), ("（", "("), ("）", ")")):
        s = s.replace(_a, _b)
    return s


def _strip_leading_index(s: str) -> str:
    """去掉 App 侧常见的前导序号："1." / "1、" / "(1)" / "第1题" / "①" 等。"""
    return re.sub(r"^(?:第?\d+\s*[、.．:：)）]?|[（(]\d+[)）]|[①-⑳])+", "", s).strip()


def _text_same_strict(app: str, script: str) -> bool:
    """题目内容"逐字一致"的**严格**比对（用户要求：两者必须逐字一致）。

    只容忍：HTML 实体、空白、引号/标点全半角、App 侧前导序号。
    **任何字母级差异都判不一致**。

    为什么不能沿用 _text_like 的 0.85 相似度：
      口语训练朗读题用的是**最小对立对**（mum moon / meet meat / nose note /
      nut net / pet pig），差一个字母就是另一道题。实测
      "nose nate" vs "nose note" 相似度 0.89 ≥ 0.85 → 会被判成"一致"，
      于是**脚本把小题目内容写错也永远查不出来**（正是用户反馈的问题）。
      长句同理：改一个词（see→saw）相似度通常 >0.9，也会被漏掉。
    说明：_text_like（宽容模式）保留给"大题说明↔caption"这类长文本比对，
      那种场景有渲染/换行差异，需要容忍度。
    """
    # ★ 2026-09-23：同 _text_like —— 先剥「句型提示：/例句：」标签再严格比对
    a = _strip_leading_index(_norm_for_cmp(_strip_prompt_label(app)))
    b = _strip_leading_index(_norm_for_cmp(_strip_prompt_label(script)))
    if not a or not b:
        return False
    return a == b


_GRADE_FILE_KW = {
    "一年级上册": ("一上", "一年级上"), "一年级下册": ("一下", "一年级下"),
    "二年级上册": ("二上", "二年级上"), "二年级下册": ("二下", "二年级下"),
    "三年级上册": ("三上", "三年级上"), "三年级下册": ("三下", "三年级下"),
    "四年级上册": ("四上", "四年级上"), "四年级下册": ("四下", "四年级下"),
    "五年级上册": ("五上", "五年级上"), "五年级下册": ("五下", "五年级下"),
    "六年级上册": ("六上", "六年级上"), "六年级下册": ("六下", "六年级下"),
}
_VERSION_FILE_KW = {
    "湘少": ("湘少",), "湘鲁": ("湘鲁", "新湘鲁"), "教科": ("教科",),
    "人教": ("人教", "PEP", "pep"), "外研": ("外研",), "译林": ("译林",),
    "教研": ("教研",),
}


def _script_matches_run(docx: str, version: str = "", grade: str = "") -> str:
    """★ 2026-09-20 新增（用户反馈：跑六上 U6 却匹配到五上 U4-7 脚本，
    把根本没测的 U4/U7 题目错误写进日志）。

    校验脚本文件名的版本/年级关键词与本次实跑是否一致。
    返回 "" = 匹配或无法判断（文件名不含任何版本/年级关键词时放行）；
    返回非空 = 不适配原因（调用方应跳过脚本比对并打日志）。
    """
    name = str(docx or "")
    if grade:
        _kws = _GRADE_FILE_KW.get(str(grade).strip())
        if _kws and not any(k in name for k in _kws):
            for _g, _ks in _GRADE_FILE_KW.items():
                if _g != str(grade).strip() and any(k in name for k in _ks):
                    return f"脚本是「{_g}」，本次实跑是「{grade}」"
    if version:
        for _v, _ks in _VERSION_FILE_KW.items():
            if _v in str(version) and not any(k in name for k in _ks):
                for _v2, _ks2 in _VERSION_FILE_KW.items():
                    if _v2 != _v and any(k in name for k in _ks2):
                        return f"脚本是「{_v2}」版，本次实跑是「{version}」"
    return ""


def _set_script_provenance(module: str, docx: str = "", matched=None, reason: str = ""):
    """★ 2026-09-21：记录「本次到底拿哪份脚本比对的、这份脚本是否适配本次运行」。

    用户连续两轮反馈"没测过的题也乱报""是不是故意输出这些内容"，根子都是
    **报告里看不出结论是拿哪份脚本比出来的**。有了溯源，报告/前端就能明确写：
      - 比对脚本：xxx.docx（版本/年级匹配 ✓）
      - ⚠ 未做脚本层比对：脚本是「五年级上册」，本次实跑是「六年级上册」
    旧状态没有这个字段 → 报告显示"未记录（旧版本产物）"，提示人工复核。
    """
    try:
        if not module:
            return
        p = _inspection_state.setdefault("_script_provenance", {})
        cur = p.get(module) or {"file": "", "matched": False, "reason": ""}
        if docx and not cur.get("file"):
            cur["file"] = docx
        if matched is True:
            cur["matched"] = True
            cur["reason"] = ""
        elif matched is False and not cur.get("matched"):
            # 已有 True 的不降级（同一模块可能有多条比对路径，一条过即可信）
            cur["matched"] = False
            cur["reason"] = reason or cur.get("reason", "")
        elif reason and not cur.get("reason"):
            cur["reason"] = reason
        p[module] = cur
    except Exception:
        pass


def _run_units() -> set:
    """本次实跑的单元集合（"6" → {6}；"2,4"/"2-4" → {2,4}；解析失败 → 空集=不过滤）"""
    try:
        _raw = str(_inspection_state.get("unit", "") or "")
        return {int(x) for x in re.findall(r"\d+", _raw)}
    except Exception:
        return set()


def _filter_issues_by_unit(issues: list) -> list:
    """★ 2026-09-20（用户要求）只保留与本次实跑单元相关的脚本自检问题。

    - location 带 U<单元号>：单元号不在本次实跑范围 → 丢弃
      （"我测试的不包括你这些题目的单元，你也给我输出这些有错误题目的单元"）
    - location 不带单元号（"全文"等结构性问题）：保留（它同样影响本次在跑的题）
    """
    _units = _run_units()
    if not _units or not isinstance(issues, list):
        return issues if isinstance(issues, list) else []
    out = []
    for it in issues:
        if not isinstance(it, dict):
            continue
        m = re.search(r"U(\d+)", str(it.get("location") or ""))
        if m and int(m.group(1)) not in _units:
            continue
        out.append(it)
    return out


def _log_script_issues(mod: str, docx: str, topn: int = 8) -> list:
    """跑「确定性脚本完整性自检」并把问题写进前端日志（零 LLM 成本）。

    ★ 2026-09-20 新增。用户反馈"脚本有问题没检查出来"，落点在这里：
      真正要保证与 App 一致的脚本字段只有三类——
        ① 题目内容（题干/小题题面/参考答案）
        ② 关键词（判分锚点，与参考答案必须自洽）
        ③ 基本知识性（知识点不能是 / 占位、不能有知识性错误）
      加上结构性前提：题号连续、字段名统一。
      这些都能确定性判定，不必花 LLM 的钱，也不会被 text[:3000] 截断。
    """
    try:
        from src.script_reviewer import check_script_completeness
        from src.review_agent import ReviewAgent, ReviewConfig
        # ★ 2026-09-20：版本/年级守卫——五上脚本不能拿去比对六上的运行
        _mismatch = _script_matches_run(docx,
                                        _inspection_state.get("version", ""),
                                        _inspection_state.get("grade", ""))
        if _mismatch:
            log_msg(f"⛔ {mod}：{_mismatch} → 跳过脚本自检"
                    f"（拿错年级/版本的脚本检查会报出根本没测过的题）", "warning")
            _set_script_provenance(mod, docx, False, _mismatch)
            return []
        _p = PROJECT_ROOT / "uploads" / docx
        if not _p.exists():
            return []
        _key = "completeness::" + docx
        if _key not in _SCRIPT_CACHE:
            _ag = ReviewAgent(ReviewConfig(docx_path=str(_p), unit=0,
                                           screenshot_dir="", verbose=False))
            _SCRIPT_CACHE[_key] = _ag.script_questions or []
        qs = _SCRIPT_CACHE[_key]
        if not qs:
            return []
        issues = check_script_completeness(str(_p), qs) or []
        # ★ 2026-09-20：只保留本次实跑单元的问题（U7/U4 的错误不该出现在 U6 的运行里）
        _n_all = len(issues)
        issues = _filter_issues_by_unit(issues)
        if _n_all > len(issues):
            log_msg(f"ℹ {mod} 脚本自检：{_n_all - len(issues)} 处问题属于其他单元，"
                    f"已按「只查在跑单元」过滤", "info")
        if not issues:
            return []
        _hi = sum(1 for i in issues if i.get("severity") == "高")
        log_msg(f"⚠ {mod} 脚本自检发现 {len(issues)} 处问题（高 {_hi} 处）", "warning")
        for i in issues[:topn]:
            log_msg(
                f"   ❗[{i.get('severity')}] {i.get('location')}："
                f"{str(i.get('detail') or '')[:80]}"
                + (f" → {str(i.get('suggestion') or '')[:60]}" if i.get("suggestion") else ""),
                "warning",
                [{"field": "脚本问题", "type": "text_mismatch",
                  "expected": i.get("suggestion") or "（按脚本规范修正）",
                  "actual": i.get("quote") or "",
                  "diff": f"{i.get('type')}（{i.get('location')}）：{i.get('detail')}"}],
            )
        if len(issues) > topn:
            log_msg(f"   … 另有 {len(issues) - topn} 处未逐条列出（详见报告）", "warning")
        _inspection_state.setdefault("_script_issues", {})[mod] = issues
        return issues
    except Exception as e:
        log_msg(f"⚠ {mod} 脚本自检异常: {str(e)[:100]}", "warning")
        return []


def _ellipsis(s, n: int = 60) -> str:
    """截断到 n 字并在末尾加「…」，绝不把句子切得看不出意思。

    ★ 2026-09-20：报告里的"改进建议"之前用 `[:40]` 硬切，把脚本原文截成
      「…每小题有10秒钟的准备时间，15秒」这种半句，检查人员照着改都不知道
      原文到哪结束。宁可给「完整原文 + 省略号」，也不要给断句。
    """
    _s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(_s) <= n:
        return _s
    return _s[:n].rstrip("，,、；;。.：: ") + "…"


def _text_diff_minor(app: str, script: str) -> bool:
    """★ 2026-09-20 新增（用户反馈"有一点不符就判不通过不太好"）：
    判断两段文字的差异是否**只**属于不影响作答的格式差异。

    判为 minor（返回 True，即不应判不通过）的差异：
      标点全半角/有无、大小写、空格/换行、连字符、引号样式、前后缀标点。
    判为实质差异（返回 False，影响学生朗读/作答 → 判不通过）：
      任何字母/数字/汉字级别的不同（哪怕一个字母：nose/note、take/bring）。

    实现：在 _norm_for_cmp（实体/空白/全半角标点）基础上，
    再去掉全部非字母数字汉字字符并统一小写 → 相等即 minor。
    """
    import html as _html
    def _core(s: str) -> str:
        s = _html.unescape(str(s or ""))
        # ★ 2026-09-23：标签（句型提示/例句）不算差异
        s = _norm_for_cmp(_strip_prompt_label(s)).lower()
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)
    return _core(app) == _core(script)


# ★ 2026-09-23 新增：App 题面里的「句型提示：/例句：」标签，脚本 stem 里没有。
#   实测教科五上 U5 第3大题：App 显示「3. 句型提示：Hello, this is ...」，
#   脚本 stem 是「Hello, this is ...」——旧比对把标签算成实质差异，
#   整个大题被判"小题目内容与脚本不符"（用户反馈的假错之一）。
_PROMPT_LABEL_RE = re.compile(
    r"^\s*(?:句型提示|参考句型|句型|例句|示例|sentence\s*pattern)\s*[:：]\s*", re.I)


def _strip_prompt_label(s: str) -> str:
    """去掉 App 侧题面的「句型提示：/例句：」等标签（多重标签也剥）。"""
    _s = str(s or "")
    for _ in range(3):          # 防御 "例句：句型提示：X"
        _n = _PROMPT_LABEL_RE.sub("", _s, count=1)
        if _n == _s:
            break
        _s = _n
    return _s.strip()


def _realign_script_unit(sq_list, cur, u_cur, big, qidx, app_text):
    """★ 2026-09-23：按 App 实际内容纠正"脚本小题命中了别的单元"。

    背景（用户报"乱判 App 与脚本不符"）：连跑多个单元时 `state["unit"]` 是范围
    （"5-6"），旧实现固定取首段 5 → U6 的所有题都拿 U5 的脚本段落比对，
    实测 App「What will I do in space?」被写成"脚本应为「The quick queen is
    quite quiet.」"，整个第2大题 5 道小题全假错。

    修法：先看当前命中的脚本小题是否与 App 文字对得上；对不上，就去**别的单元**
    找同号小题（big / stage_idx 相同）里与 App 文字逐字一致的那道 → 以它为准。
    找不到更合适的就原样返回（不能凭空判错，也不能凭空放过）。

    返回纠正后的脚本小题对象。
    """
    if cur is None or not sq_list or not app_text:
        return cur
    _canon = lambda t: _strip_prompt_label(_norm_for_cmp(t))
    _app = _canon(app_text)
    if not _app:
        return cur

    def _hit(q) -> bool:
        for _t in (getattr(q, "stem", "") or "",
                   getattr(q, "sentence_pattern", "") or "",
                   getattr(q, "caption", "") or ""):
            _c = _canon(_t)
            if _c and (_c == _app or _c in _app or _app in _c):
                return True
        return False

    if _hit(cur):
        return cur
    _cur_unit = getattr(cur, "unit", None)
    best = None
    for s in sq_list:
        try:
            if getattr(s, "unit", None) == _cur_unit:
                continue        # 当前单元已判过不合，不必重看
            if big and int(getattr(s, "big", 0) or 0) != int(big):
                continue
            if int(getattr(s, "stage_idx", 0) or 0) != int(qidx):
                continue
        except Exception:
            continue
        if _hit(s):
            if best is not None:
                return cur      # 多个单元都命中 → 有歧义，不做纠正（宁可不判）
            best = s
    return best if best is not None else cur


def _fmt_reason(field: str, diff: str, verdict: str) -> str:
    """生成自然语言原因描述，让检查人员一眼看懂"""
    prefix = {"题干": "界面题干", "选项": "可选项", "音频": "音频控件", "作答": "作答元素"}.get(field, field)
    if diff and len(diff) < 50:
        return f"{prefix}: {diff}"
    if verdict == "通过":
        return f"{prefix}正常 ✓"
    return f"{prefix}异常 ✗"


# ===== 快速检查(从当前页开始) =====
def run_quick_inspect_task(docx_file: str = "", unit: int = 0):
    """⚡ 快速检查：从手机当前页面直接开始逐题巡检（跳过启动/关广告/登录/导航）

    前提: 用户已手动将手机调到题目页 (如 听力专项-基础巩固-第1题)
    流程: 截图 → AI六维审查(若提供脚本) → 写入巡检状态 → 点选项 → 点底部按钮x2 → 循环
    坐标自动缩放 (适配不同分辨率手机)
    """
    try:
        set_running("quick_inspect")
        config = load_config()
        adb = get_adb()

        # 清空旧巡检状态
        _inspection_state["questions"] = {}
        _inspection_state["workflow_steps"] = []
        _inspection_state["current_question_idx"] = 0
        _save_inspection_state()

        # 加载脚本 + AI审查agent (可选)
        agent = None
        if docx_file:
            docx_path = str(UPLOAD_DIR / docx_file)
            if Path(docx_path).exists():
                try:
                    from src.review_agent import ReviewAgent, ReviewConfig
                    cfg = ReviewConfig(docx_path=docx_path, unit=int(unit or 0),
                                       screenshot_dir=str(PROJECT_ROOT / "screenshots"),
                                       verbose=False)
                    agent = ReviewAgent(cfg)
                    log_msg(f"📄 脚本已加载: {docx_file} (共{len(agent.script_questions)}题) → AI六维审查开启", "success")
                except Exception as e:
                    log_msg(f"⚠ 脚本加载失败: {e}，降级为仅截图", "warning")
            else:
                log_msg(f"⚠ 脚本不存在: {docx_path}，降级为仅截图", "warning")
        else:
            log_msg("⚡ 未指定脚本，仅截图+推进（选脚本可开启AI六维审查）", "info")

        # ★ 2026-08-30 修复：快速检查优先走"模块真实答题循环"（听力专项 _test_answer_loop），
        #   废弃的简易"点选项→点按钮x2"逻辑不识别图片选项(卡Q1)/不收集evidence/不设模块上下文。
        #   判断当前是否听力专项答题页：有题号 X/Y + 题干含"听" + 无封面按钮(去练习/开始答题)
        try:
            _els0 = adb.dump_ui(retries=2)
            _t_all0 = " ".join((e.text or "") for e in _els0)
            _m_xy0 = re.search(r"(\d+)/(\d+)", _t_all0)
            _no_cover0 = ("去练习" not in _t_all0 and "开始答题" not in _t_all0
                          and "重新答题" not in _t_all0)
            if _m_xy0 and "听" in _t_all0 and _no_cover0:
                log_msg(f"✅ 检测到听力专项答题页（{_m_xy0.group(0)}），走真实答题循环…", "success")
                try:
                    from common.logger import set_current_module
                    set_current_module("听力专项", "快速检查")
                    # ★ 同时写 _inspection_state 的 module/stage（_record_module_evidence
                    #   fallback 读取；线程间 logger 全局偶尔读不到，双保险）
                    _inspection_state["module"] = "听力专项"
                    _inspection_state["stage"] = "快速检查"
                    _dd = _connect_device()
                    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                    from modules.听力专项 import _test_answer_loop as _listen_loop
                    _q_done = _listen_loop(_dd, max_q=60)
                    log_msg(f"✅ 听力专项快速检查完成: {_q_done} 题", "success")
                except Exception as _e2:
                    log_msg(f"⚠ 听力专项答题循环异常: {_e2}", "warning")
                    import traceback
                    traceback.print_exc()
                set_done()
                return
        except Exception:
            pass

        log_msg("⚡ 快速检查启动（从当前页面开始，跳过导航）", "success")
        time.sleep(1)

        # 1. 尝试检测当前题目进度 (如 1/40)
        elements = adb.dump_ui(retries=2)
        cur = None
        total_q = 0
        for e in elements:
            m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
            if m:
                cur = int(m.group(1))
                total_q = int(m.group(2))
                break

        if cur:
            log_msg(f"✅ 检测到题目进度 {cur}/{total_q or 40}，开始逐题检查", "success")
        else:
            log_msg("⚠ 未检测到题目进度(如 1/40)。若您已在题目页将正常检查，", "warning")
            log_msg("   否则请先手动进入题目页再点「快速检查」", "warning")
            time.sleep(2)

        # 2. 逐题巡检
        last = 0
        q_count = 0
        for step in range(80):
            if not task_status["running"]:
                break

            idx = cur if cur else (last + 1)

            # 截图 (保存到 outputs/web, 前端可预览)
            shot = f"q{idx:02d}.png"
            adb.screenshot(shot)
            log_msg(f"📸 Q{idx} 已截图", "success")
            update_progress(idx, total_q or 40, f"Q{idx}")
            q_count += 1

            # ★ 实时题型识别（从 UI 判断当前是什么题）
            detected = None
            try:
                from src.type_detector import TypeDetector
                q_els = adb.dump_ui(retries=2)
                detected = TypeDetector(verbose=False).detect(q_els)
                if detected and detected.type_1 != "未知":
                    log_msg(f"  🔍 实时题型: {detected.describe()} (conf={detected.confidence:.0%})", "info")
            except Exception:
                detected = None

            # ====== AI 六维审查 (若有脚本) ======
            ai = {
                "ai_stem": None, "ai_content": None, "ai_image": None,
                "ai_answer": None, "ai_audio": None, "ai_post_error": None,
                "overall_passed": None, "overall_score": None,
                "stem_reason": "", "content_reason": "", "image_reason": "",
                "answer_reason": "", "audio_reason": "", "post_error_reason": "",
                "question_type": detected.full_type if detected and detected.full_type else "快速检查",
                "script_answer": "", "stem": "",
            }
            if agent:
                try:
                    # ★ 修复：截图保存在 screenshots/（adb.screenshot），
                    #   原代码读 outputs/web/ 导致找不到图 → 降级纯文字模式
                    shot_path = str(PROJECT_ROOT / "screenshots" / shot)
                    matching = [q for q in agent.script_questions if q.global_idx == idx]
                    if matching:
                        script_q = matching[0]
                        r = agent._review_one(script_q, shot_path, detected=detected)
                        ai = {
                            "ai_stem": r.stem_check.passed,
                            "ai_content": r.content_check.passed,
                            "ai_image": r.image_check.passed,
                            "ai_answer": r.answer_check.passed,
                            "ai_audio": r.audio_check.passed if r.audio_check is not None else None,
                            "ai_post_error": r.post_error_check.passed if r.post_error_check is not None else None,
                            "overall_passed": r.overall_passed,
                            "overall_score": round(r.overall_score, 2),
                            "stem_reason": r.stem_check.details[0][:100] if r.stem_check.details else "",
                            "content_reason": r.content_check.details[0][:100] if r.content_check.details else "",
                            "image_reason": r.image_check.details[0][:100] if r.image_check.details else "",
                            "answer_reason": r.answer_check.details[0][:100] if r.answer_check.details else "",
                            "audio_reason": r.audio_check.details[0][:100] if r.audio_check and r.audio_check.details else "",
                            "post_error_reason": r.post_error_check.details[0][:100] if r.post_error_check and r.post_error_check.details else "",
                            "question_type": (detected.full_type if detected and detected.full_type else (script_q.type_2 or "快速检查")),
                            "script_answer": script_q.answer or "",
                            "stem": (detected.stem if detected and detected.stem else script_q.stem)[:60] if (detected.stem if detected and detected.stem else script_q.stem) else "",
                        }
                        log_msg(f"  AI: 题干{ai['ai_stem']} 内容{ai['ai_content']} 配图{ai['ai_image']} 作答{ai['ai_answer']} 音频{ai['ai_audio']} 答错后{ai['ai_post_error']} 得分{ai['overall_score']}")
                    else:
                        log_msg(f"  ⚠ 脚本中无 Q{idx}，跳过AI审查", "warning")
                except Exception as e:
                    log_msg(f"  ⚠ AI审查失败 Q{idx}: {e}", "warning")

            # ====== 写入巡检状态 → 前端中栏显示 ======
            qid = f"quick-Q{idx:02d}"
            _inspection_state["questions"][qid] = {
                "idx": idx,
                "total": total_q or 40,
                "question_type": ai["question_type"],
                "screenshot": shot,
                "progress": f"{idx}/{total_q or 40}",
                "ai_stem": ai["ai_stem"], "ai_content": ai["ai_content"],
                "ai_image": ai["ai_image"], "ai_answer": ai["ai_answer"],
                "ai_audio": ai["ai_audio"], "ai_post_error": ai["ai_post_error"],
                "overall_passed": ai["overall_passed"],
                "overall_score": ai["overall_score"],
                "stem_reason": ai["stem_reason"], "content_reason": ai["content_reason"],
                "image_reason": ai["image_reason"], "answer_reason": ai["answer_reason"],
                "audio_reason": ai["audio_reason"], "post_error_reason": ai["post_error_reason"],
                "script_answer": ai["script_answer"],
                "stem": ai["stem"],
                "note": "",
                "human_label": None,
                "human_note": "",
                "timestamp": datetime.now().isoformat(),
            }
            _inspection_state["current_question_idx"] = idx
            _save_inspection_state()

            # 点选项: 优先找UI元素，找不到则点默认右侧选项区(缩放)
            elements = adb.dump_ui(retries=2)
            clicked_option = False
            for e in elements:
                if e.clickable and 700 < e.bounds[1] < 1700:
                    if e.center[0] > 450:
                        adb.tap(e.center[0], e.bounds[1] + 30)
                    else:
                        adb.tap((e.bounds[0] + e.bounds[2]) // 2,
                                (e.bounds[1] + e.bounds[3]) // 2)
                    clicked_option = True
                    break
            if not clicked_option:
                tx, ty = sc(970, 1500)   # 默认点右侧选项区
                adb.tap(tx, ty)
            time.sleep(1)

            # 点底部按钮 x2 (检查答案 → 下一题)
            bx, by = sc(540, 2174)
            adb.tap(bx, by)
            time.sleep(1.5)
            adb.tap(bx, by)
            time.sleep(1.5)

            # 检测进度变化
            elements_after = adb.dump_ui(retries=2)
            new_cur = None
            new_total = 0
            for e in elements_after:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    new_cur = int(m.group(1))
                    new_total = int(m.group(2))
                    break

            if new_cur and new_cur == last and cur:
                log_msg(f"  ⚠ Q{new_cur} 进度未变，重试一次", "warning")
                time.sleep(2)
                adb.tap(bx, by)
                time.sleep(1.5)
                continue

            if new_cur:
                last = new_cur
                cur = new_cur
                total_q = new_total or total_q
                if new_cur >= (total_q or 40):
                    log_msg(f"✅ {new_cur}题完成!", "success")
                    break
            else:
                last += 1
                log_msg(f"  未检测到进度文字, 继续下一题 (Q{last})", "info")

        # 3. 保存报告
        out = PROJECT_ROOT / "outputs" / "questions" / "quick_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"questions": list(_inspection_state["questions"].values())},
                      f, ensure_ascii=False, indent=2)
        log_msg(f"✅ 快速检查完成: 共 {q_count} 题", "success")

    except Exception as e:
        log_msg(f"❌ 异常: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


# ===== 快速检查(从当前页开始) =====
# ============================================================
# 错题溯源 / 透明评分 整合（复用同学C的 TraceEngine）
# ============================================================
_TRACE_ENGINE = None

def _get_trace_engine():
    """惰性加载同学C的 TraceEngine（缺 Pillow/文件时返回 None，不阻塞）。"""
    global _TRACE_ENGINE
    if _TRACE_ENGINE is None:
        try:
            from trace_engine import TraceEngine
            _TRACE_ENGINE = TraceEngine(screenshots_dir=str(PROJECT_ROOT / "screenshots"))
        except Exception:
            _TRACE_ENGINE = False
    return _TRACE_ENGINE or None


def _score_breakdown(qd: dict) -> dict:
    """透明评分（★ 统一维度，让前端展示一致）：

    ★ 主评分（一致性保证）：仅 3 个核心维度 → 题干/选项/作答
       通过数 / 已检查数 × 100。这 3 维是任何题型必检的（基础完整性）。
       其他维度（配图/音频/答错后/报告）作为"附加检查项"展示，不参与主评分。
    ★ 这样所有题"维度"统一，不会出现"3 维 vs 6 维"不一致。
    """
    # ★ 主评分：3 维（基础完整性，所有题统一必检）
    main_dims = [
        ("题干", qd.get("ai_stem"), qd.get("stem_reason"), "medium"),
        ("选项", qd.get("ai_content"), qd.get("content_reason"), "high"),
        ("作答", qd.get("ai_answer"), qd.get("answer_reason"), "high"),
    ]
    # ★ 附加检查：4 维（按题型可选，不算主分）
    extra_dims = [
        ("配图", qd.get("ai_image"), qd.get("image_reason"), "high"),
        ("音频", qd.get("ai_audio"), qd.get("audio_reason"), "low"),
        ("答错后", qd.get("ai_post_error"), qd.get("post_error_reason"), "low"),
        ("报告", qd.get("ai_report"), qd.get("report_reason"), "low"),
    ]
    checked = [d for d in main_dims if d[1] is not None]
    passed = [d for d in checked if d[1] is True]
    total = len(checked)
    score = round(len(passed) / total * 100) if total else 0
    return {
        "score": score,
        "checked_count": total,
        "passed_count": len(passed),
        "failed_count": total - len(passed),
        # ★ 公式固定为 "3 维基础完整性检查"，让检查人员一眼明白评分逻辑
        "formula": f"{len(passed)}/{total}×100={score}（基础完整性 3 维评分）" if total else "未检查，无法评分",
        "dims": [{"name": d[0], "passed": d[1], "reason": d[2] or "", "severity": d[3]} for d in checked],
        # ★ 附加检查项（前端可单独展示，不参与主分）
        "extra_dims": [{"name": d[0], "passed": d[1], "reason": d[2] or "", "severity": d[3]}
                      for d in extra_dims if d[1] is not None],
    }


def _ensure_marked(qid: str, qd: dict, checks: list):
    """生成红框标注图 + 出错区域特写图（同学C的 draw_mark / crop_evidence）。

    输出到 outputs/web/，已存在则复用（缓存）。返回 (标注图名, 特写图名)；失败返回 ("", "")。

    ★ 2026-09-17：缓存前缀改为 marked_v2_/crop_v2_。
      旧版 draw_mark 在没有真实坐标时会画一个固定占位框（框到手机状态栏上），
      按文件名缓存会导致"改了标注逻辑但界面还是旧的假框"→ 必须换前缀使旧图失效。
    """
    try:
        shot = qd.get("screenshot", "")
        if not shot:
            return "", ""
        web_dir = PROJECT_ROOT / "outputs" / "web"
        out_name = f"marked_v2_{shot}"
        out_path = web_dir / out_name
        crop_name = f"crop_v2_{shot}"
        crop_path = web_dir / crop_name
        if out_path.exists() and crop_path.exists():
            return out_name, crop_name
        eng = _get_trace_engine()
        if not eng:
            return "", ""
        if not out_path.exists():
            if checks:
                eng.draw_mark(shot, checks, str(out_path))
            else:
                out_name = ""
        # 出错区域特写：没有真实坐标时 crop_evidence 返回 ""（不硬裁），前端回退整图
        if not crop_path.exists() and checks:
            if not eng.crop_evidence(shot, checks, str(crop_path)):
                crop_name = ""
        elif not checks:
            crop_name = ""
        return (out_name if out_name and out_path.exists() else "",
                crop_name if crop_name and crop_path.exists() else "")
    except Exception:
        return "", ""


def _enrich_inspect_state(state: dict):
    """给每道错题附加溯源/评分/红框图；通过题仅附评分（供参考）。"""
    eng = _get_trace_engine()
    for qid, qd in (state.get("questions") or {}).items():
        qd["_score"] = _score_breakdown(qd)
        if qd.get("overall_passed") is not False:
            continue  # 通过题不用溯源
        if eng is None:
            continue
        try:
            trace = eng.generate(qid, qd)
            qd["_trace"] = trace
            _mk, _cr = _ensure_marked(qid, qd, trace.get("checks", []))
            qd["_marked"] = _mk          # 红框标注图（有真实坐标才画框）
            qd["_crop"] = _cr            # 出错区域特写图（截到问题所在的那几行）
        except Exception:
            pass


@app.route("/api/inspect/state", methods=["GET"])
def api_inspect_state():
    """获取当前巡检状态 (流式)。
    ★ 集成同学C的溯源引擎：对每道错题附加 _trace（维度/原因/建议/严重度/坐标）、
    _score（透明评分明细，说明评分怎么来的）、_marked（红框标注图URL）。
    """
    # 浅拷贝一层，避免污染 _inspection_state（_score/_trace/_marked 只进响应）
    # ★ 必须带全 version/unit/stage/docx/live_report_path（前端"查看报告"/分组展示依赖）
    state = {
        "questions": {k: dict(v) for k, v in (_inspection_state.get("questions") or {}).items()},
        "workflow_steps": _inspection_state.get("workflow_steps", []),
        "current_question_idx": _inspection_state.get("current_question_idx", 0),
        "version": _inspection_state.get("version", ""),
        "unit": _inspection_state.get("unit", ""),
        "stage": _inspection_state.get("stage", ""),
        "docx": _inspection_state.get("docx", ""),
        "live_report_path": _inspection_state.get("live_report_path", ""),
        # ★ 2026-08-30 修复：总览按模块+单元分组 → 必须把 module/_modules_total 透出给前端
        "module": _inspection_state.get("module", ""),
        "_modules_total": _inspection_state.get("_modules_total", {}),
        "_reuse_info": _inspection_state.get("_reuse_info", ""),
        # ★ 2026-09-20：脚本自检问题（答案↔关键词不一致 / 知识点占位 / 字段名不统一）
        #   必须透出给前端——此前只写进日志，审查结果区看不到，检查人员会以为
        #   "脚本没问题"（用户反馈："脚本有问题你没检查出来"）。
        "_script_issues": _inspection_state.get("_script_issues", {}),
        # ★ 2026-09-21：脚本溯源（比对脚本文件名 + 是否适配本次版本/年级）
        "_script_provenance": _inspection_state.get("_script_provenance", {}),
    }
    try:
        _enrich_inspect_state(state)
    except Exception:
        pass
    return jsonify(state)


@app.route("/api/inspect/question-result", methods=["POST"])
def api_inspect_question_result():
    """接收AI对一道题的判断结果, 推送审查证据到前端日志"""
    data = request.get_json() or {}
    qid = data.get("qid", "")
    if not qid:
        return jsonify({"error": "缺少题号"}), 400

    _inspection_state["questions"][qid] = {
        **data,
        "human_label": None,  # 等待人工标注
        "human_note": "",
        "timestamp": datetime.now().isoformat(),
    }
    _inspection_state["current_question_idx"] = data.get("idx", 0)
    _save_inspection_state()

    # ★ 借鉴队友：该题不通过 → 实时重生成错题报告（前端「📑 查看报告」弹窗即时更新）
    if not data.get("overall_passed"):
        _live_regen_error_report()

    # ★ 推送审查证据到前端日志(收集各维度的 evidence)
    idx = data.get("idx", "?")
    overall = "通过" if data.get("overall_passed") else "不通过"
    level = "success" if data.get("overall_passed") else "error"
    all_evidence = []
    for dim in ("stem", "content", "image", "answer", "audio", "post_error"):
        check = data.get(f"{dim}_check", {})
        if isinstance(check, dict) and check.get("evidence"):
            all_evidence.extend(check["evidence"])
    log_msg(f"📋 Q{idx} 审查{overall} | 方法:{data.get('method','')}",
            level, evidence=all_evidence if all_evidence else None)
    return jsonify({"success": True, "qid": qid})


@app.route("/api/inspect/human-label", methods=["POST"])
def api_inspect_human_label():
    """人工标注某道题的对错 + 加入反馈循环"""
    data = request.get_json() or {}
    qid = data.get("qid", "")
    label = data.get("label", "")  # "通过" / "不通过"
    note = data.get("note", "")

    if not qid or label not in ["通过", "不通过"]:
        return jsonify({"error": "参数错误"}), 400

    # 更新巡检状态
    if qid in _inspection_state["questions"]:
        _inspection_state["questions"][qid]["human_label"] = label
        _inspection_state["questions"][qid]["human_note"] = note
    _save_inspection_state()

    # 加入反馈循环 (审查智能体学习)
    q_data = _inspection_state["questions"][qid]
    ai_judgment = "通过" if q_data.get("overall_passed") else "不通过"
    try:
        from src.feedback_loop import FeedbackSample
        store = FeedbackStore()
        store.add(FeedbackSample(
            question_id=qid,
            check_dimension=q_data.get("check_dimension", "all"),
            human_judgment=label,
            ai_judgment=ai_judgment,
            ai_reason=str(q_data.get("ai_reason", ""))[:200],
            human_note=note,
            question_type=q_data.get("question_type", ""),
            screenshot=q_data.get("screenshot", ""),
        ))
        return jsonify({
            "success": True,
            "qid": qid,
            "feedback_stored": True,
            "stats": store.get_stats(),
        })
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        return jsonify({"success": True, "qid": qid, "feedback_error": str(e)})


@app.route("/api/inspect/workflow-step", methods=["POST"])
def api_inspect_workflow_step():
    """记录流程步骤状态"""
    data = request.get_json() or {}
    step_name = data.get("step", "")
    status = data.get("status", "")  # "running" / "done" / "error"
    detail = data.get("detail", "")

    # 替换或添加步骤
    found = False
    for s in _inspection_state["workflow_steps"]:
        if s["step"] == step_name:
            s["status"] = status
            s["detail"] = detail
            s["updated"] = datetime.now().isoformat()
            found = True
            break
    if not found:
        _inspection_state["workflow_steps"].append({
            "step": step_name,
            "status": status,
            "detail": detail,
            "updated": datetime.now().isoformat(),
        })
    _save_inspection_state()
    return jsonify({"success": True})


@app.route("/api/inspect/reset", methods=["POST"])
def api_inspect_reset():
    """清空当前巡检状态"""
    _inspection_state["questions"] = {}
    _inspection_state["workflow_steps"] = []
    _inspection_state["current_question_idx"] = 0
    _inspection_state["live_report_path"] = ""   # ★ 清空实时报告路径
    _save_inspection_state()
    return jsonify({"success": True})


@app.route("/api/modules")
def api_modules():
    """获取可用模块列表"""
    return jsonify({
        "教材精学": {
            "课本点读(左)": (203, 1191),
            "课本点读(中)": (540, 1191),
            "巧记单词":     (876, 1191),
            "语音评测":     (203, 1358),
        },
        "专项突破 (可见)": {
            "听课文":    (161, 1792),
            "课文动画":  (414, 1792),
            "基础训练":  (666, 1792),
            "一课一练":  (919, 1792),
            "课文配音":  (161, 2033),
            "口语训练":  (414, 2033),
            "复习回顾":  (666, 2033),
            "全脑记词":  (919, 2033),
        },
        "专项突破 (需滚动)": {
            "单元自检":     (414, 746),
            "单元练习计划": (666, 746),
        },
        "📢 听力专项": {
            "听力专项_五上": (414, 1250),
            "听力专项_五下": (414, 950),
            "听力专项_六上": (414, 1150),
            "听力专项_六下": (414, 1050),
        },
    })


@app.route("/api/grades", methods=["POST"])
def api_grades():
    """检测当前版本的可用年级列表（含新/老教材标记）"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    config = load_config()
    adb = get_adb()

    try:
        # 确保在主页，打开年级选择弹窗
        adb.tap(*sc(346, 275))  # 切换器
        time.sleep(3)

        elements = adb.dump_ui()
        if not elements:
            return jsonify({"error": "UI dump失败", "grades": []})

        # 解析年级数据
        grades = []
        seen = set()
        for elem in elements:
            text = elem.text
            if not text:
                continue
            # 检测是否含年级/册文字
            is_book = any(k in text for k in ['年级', '册'])
            is_new_tag = '新教材' in text
            if is_book or is_new_tag:
                if text not in seen:
                    seen.add(text)
                    # 找容器坐标（可点击区域）
                    container = None
                    for ce in elements:
                        if ce.clickable and elem.center[0] >= ce.bounds[0] and elem.center[0] <= ce.bounds[2] \
                                and elem.center[1] >= ce.bounds[1] and elem.center[1] <= ce.bounds[3]:
                            container = list(ce.center)
                            break

                    grades.append({
                        "text": text,
                        "center": list(elem.center),
                        "container": container,
                        "is_new_tag": is_new_tag,
                        "is_book": is_book,
                    })

        # 关闭弹窗
        adb.press_back()
        time.sleep(1)

        # 结构化输出
        book_grades = [g for g in grades if g["is_book"]]
        log_msg(f"✅ 检测到 {len(book_grades)} 个年级选项")

        return jsonify({"grades": grades, "book_grades": book_grades})

    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 年级检测失败: {e}", "error")
        return jsonify({"error": str(e), "grades": []})


@app.route("/api/screenshot/<filename>")
def api_screenshot(filename):
    """获取截图"""
    screenshot_dir = PROJECT_ROOT / "outputs" / "web"
    if (screenshot_dir / filename).exists():
        return send_from_directory(str(screenshot_dir), filename)
    # 也查 outputs/screenshots
    alt_dir = PROJECT_ROOT / "outputs" / "screenshots"
    if (alt_dir / filename).exists():
        return send_from_directory(str(alt_dir), filename)
    # ★ 截图实际保存目录（快速检查 qXX.png / 答错截图 wrong_qXX.png 都在这）
    shot_dir = PROJECT_ROOT / "screenshots"
    if (shot_dir / filename).exists():
        return send_from_directory(str(shot_dir), filename)
    return jsonify({"error": "未找到截图"}), 404


@app.route("/api/screenshot/latest")
def api_screenshot_latest():
    """获取最新截图"""
    screenshot_dir = PROJECT_ROOT / "outputs" / "web"
    png_files = sorted(screenshot_dir.glob("*.png"), key=os.path.getmtime, reverse=True)
    if png_files:
        return send_from_directory(str(screenshot_dir), png_files[0].name)
    return jsonify({"error": "无截图"}), 404


# ★ 常驻实时截图线程：web_server 启动即开始，每 3 秒截一张 outputs/web/live.png，
#   供前端「手机画面」实时预览。设备未连接时静默重试（10s 间隔），不阻塞启动。
#   （原实现只在任务运行时启动截图循环，任务一结束前端就显示最后一张旧图）
_LIVE_SHOT = {"dev": None, "fail": 0}

def _start_live_screenshot_daemon():
    def _loop():
        shot_dir = PROJECT_ROOT / "outputs" / "web"
        try:
            shot_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        while True:
            try:
                if _LIVE_SHOT["dev"] is None:
                    try:
                        _LIVE_SHOT["dev"] = _connect_device()
                        _LIVE_SHOT["fail"] = 0
                    except Exception:
                        _LIVE_SHOT["dev"] = None
                        _LIVE_SHOT["fail"] += 1
                if _LIVE_SHOT["dev"] is not None:
                    try:
                        _LIVE_SHOT["dev"].screenshot(str(shot_dir / "live.png"))
                        _LIVE_SHOT["fail"] = 0
                    except Exception:
                        _LIVE_SHOT["dev"] = None
                        _LIVE_SHOT["fail"] += 1
                time.sleep(3 if _LIVE_SHOT["fail"] == 0 else 10)
            except Exception:
                time.sleep(10)
    threading.Thread(target=_loop, daemon=True).start()


@app.route("/api/log")
def api_log():
    """获取日志"""
    return jsonify(task_status["log"])


@app.route("/api/hardware-info")
def api_hardware_info():
    """获取手机信息"""
    config = load_config()
    info = {"serial": config.device.serial, "screen": "1080x2400"}
    try:
        # ★ 跨机器可移植：自动定位 adb（不再写死任何人的绝对路径）
        adb_path = ADBController._find_adb()
        r = sp.run([adb_path, "-s", config.device.serial, "shell", "getprop", "ro.product.model"],
                   capture_output=True, text=True, timeout=5,
                   encoding="utf-8", errors="replace")
        if r.returncode == 0:
            info["model"] = r.stdout.strip()
        r2 = sp.run([adb_path, "-s", config.device.serial, "shell", "getprop", "ro.product.brand"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace")
        if r2.returncode == 0:
            info["brand"] = r2.stdout.strip()
    except Exception:
        pass
    return jsonify(info)


def _get_current_version_from_config() -> str:
    """获取当前目标版本（顶栏展示用；实际由 UI 下拉框决定，此处不再硬编码假值）"""
    return ""


# ============================================================
# 🔵 审查智能体 路由区 — 脚本上传 + 知识库 + 审查结果
# ============================================================

UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """上传 DOCX/DOC 脚本文件（仅保存到 uploads 目录，供审查智能体使用）

    前端 uploadFile() 调用此接口上传文件
    """
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    file = request.files["file"]
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("docx", "doc"):
        return jsonify({"error": "仅支持 .docx / .doc 文件"}), 400
    save_path = UPLOAD_DIR / file.filename
    file.save(str(save_path))
    log_msg(f"📤 已上传脚本: {file.filename}", "success")
    return jsonify({"success": True, "filename": file.filename})


@app.route("/api/upload-docx", methods=["POST"])
def api_upload_docx():
    """上传 DOCX/DOC 脚本文件, 自动导入知识库"""
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    file = request.files["file"]
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("docx", "doc"):
        return jsonify({"error": "仅支持 .docx / .doc 文件"}), 400
    save_path = UPLOAD_DIR / file.filename
    file.save(str(save_path))
    try:
        from src.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        stats = kb.add_bulk_from_docx(str(save_path))
        return jsonify({
            "success": True, "filename": file.filename,
            "knowledge_stats": {
                "questions_parsed": stats.get("questions", 0),
                "vocab_added": stats.get("vocab", 0),
                "patterns_added": stats.get("patterns", 0),
            },
            "message": f"已导入 {stats.get('questions',0)} 题到知识库",
        })
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        return jsonify({"error": f"解析失败: {str(e)}"}), 500


@app.route("/api/order/parse", methods=["POST"])
def api_order_parse():
    """解析上传的任务清单文件 → 提取文本

    支持格式：.txt / .docx / .xlsx
    返回: {"text": ..., "filename": ..., "format": "txt|docx|xlsx"}
    前端拿到 text 后复用 applyOrder() 做版本/年级/模块识别
    """
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    f = request.files["file"]
    name = f.filename or "task.txt"
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else "txt"
    try:
        data = f.read()
        if ext == "txt":
            text = data.decode("utf-8", errors="replace")
        elif ext in ("docx",):
            import io as _io
            from docx import Document
            doc = Document(_io.BytesIO(data))
            parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for tb in doc.tables:
                for row in tb.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            text = "\n".join(parts)
        elif ext in ("xlsx", "xls"):
            import io as _io
            import openpyxl
            wb = openpyxl.load_workbook(_io.BytesIO(data), data_only=True)
            rows = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if cells:
                        rows.append(" | ".join(cells))
            text = "\n".join(rows)
        elif ext == "doc":
            return jsonify({
                "error": "老格式 .doc 暂不支持直接解析，请另存为 .docx 或 .txt 再上传",
                "filename": name,
            }), 400
        else:
            return jsonify({"error": f"不支持的文件格式 .{ext}（支持 .txt/.docx/.xlsx）"}), 400

        text = (text or "").strip()
        if not text:
            return jsonify({"error": "文件内容为空或未提取到文字", "filename": name}), 400
        log_msg(f"📋 已解析任务清单: {name}（{ext}，{len(text)} 字符）", "success")
        return jsonify({"text": text, "filename": name, "format": ext})
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
        return jsonify({"error": "已停止"}), 500
    except Exception as e:
        log_msg(f"⚠ 任务清单解析失败 {name}: {e}", "warning")
        return jsonify({"error": f"解析失败: {str(e)[:100]}", "filename": name}), 500


@app.route("/api/upload/list")
def api_upload_list():
    """列出已上传的 DOCX 文件"""
    files = []
    for f in sorted(UPLOAD_DIR.glob("*"), key=os.path.getmtime, reverse=True):
        if f.suffix.lower() not in (".docx", ".doc"): continue
        if "_converted" in f.stem: continue  # 跳过转换生成的临时文件
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return jsonify({"files": files})


@app.route("/api/knowledge/status")
def api_knowledge_status():
    """知识库状态"""
    try:
        from src.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        summary = kb.summary()
        total_entries = sum(s["vocab"] + s["patterns"] for s in summary)
        return jsonify({
            "total_entries": total_entries,
            "grades": [s["key"] for s in summary],
            "detail": summary,
        })
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        return jsonify({"total_entries": 0, "error": str(e)})


_review_results = {}

@app.route("/api/review/run", methods=["POST"])
def api_review_run():
    """运行审查智能体"""
    data = request.get_json() or {}
    docx_file = data.get("docx", "")
    unit = data.get("unit", 0)
    stage = data.get("stage", "")
    docx_path = ""
    if docx_file:
        docx_path = str(UPLOAD_DIR / docx_file)
        if not Path(docx_path).exists():
            return jsonify({"error": f"文件 {docx_file} 不存在"}), 404
    else:
        files = [f for f in sorted(UPLOAD_DIR.glob("*"), key=os.path.getmtime, reverse=True)
                 if f.suffix.lower() in (".docx", ".doc")]
        if files: docx_path = str(files[0])
        else: return jsonify({"error": "未找到脚本文件"}), 404
    try:
        from src.review_agent import ReviewAgent, ReviewConfig
        cfg = ReviewConfig(docx_path=docx_path, unit=unit, stage=stage,
                           screenshot_dir=str(PROJECT_ROOT / "screenshots"), verbose=False)
        agent = ReviewAgent(cfg)
        results = agent.review()
        global _review_results
        _review_results = {
            "timestamp": datetime.now().isoformat(),
            "docx": Path(docx_path).name,
            "total": len(results),
            "passed": sum(1 for r in results if r.overall_passed),
            "avg_score": round(sum(r.overall_score for r in results) / len(results), 2) if results else 0,
            "results": [r.to_dict() for r in results],
        }
        return jsonify(_review_results)
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/review/results")
def api_review_results():
    return jsonify(_review_results or {"results": [], "total": 0})


@app.route("/api/review/export", methods=["POST"])
def api_review_export():
    try:
        py_content = ""
        if _review_results:
            r = _review_results
            py_content = f"# 英语宝审查报告\n\n生成时间: {r['timestamp']}\n脚本: {r['docx']}\n"
            py_content += f"总题数: {r['total']} | 通过: {r['passed']}/{r['total']} | 综合得分: {r['avg_score']}\n\n"
            py_content += "| # | 题型 | 题干 | 内容 | 配图 | 作答 | 总评 |\n|---|---|---|---|---|---|---|\n"
            for rr in r.get("results", []):
                def ic(p): return "Y" if p else "N"
                py_content += f"| Q{rr['idx']:02d} | {rr['type'][:10]} | {ic(rr['stem']['passed'])} | {ic(rr['content']['passed'])} | {ic(rr['image']['passed'])} | {ic(rr['answer']['passed'])} | {'PASS' if rr['overall_passed'] else 'FAIL'} ({rr['overall_score']}) |\n"
        return jsonify({"content": py_content})
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report/teacher")
def api_report_teacher():
    """生成教师可读的可视化HTML报告"""
    from datetime import datetime

    st = _inspection_state
    qs = st.get("questions", {})

    total = len(qs)
    passed = sum(1 for q in qs.values() if q.get("overall_passed"))
    labeled = sum(1 for q in qs.values() if q.get("human_label"))
    acc = 0
    if labeled > 0:
        corr = sum(1 for q in qs.values()
                   if q.get("human_label") == "通过" and q.get("overall_passed")
                   or q.get("human_label") == "不通过" and not q.get("overall_passed"))
        acc = int(corr / labeled * 100)

    # 构建HTML
    questions_html = ""
    for qid in sorted(qs.keys(), key=lambda x: int(re.findall(r'Q(\d+)', x)[0]) if re.findall(r'Q(\d+)', x) else 0):
        q = qs[qid]
        dims = [
            ("题干", q.get("ai_stem"), q.get("stem_reason", "")),
            ("内容", q.get("ai_content"), q.get("content_reason", "")),
            ("配图", q.get("ai_image"), q.get("image_reason", "")),
            ("作答", q.get("ai_answer"), q.get("answer_reason", "")),
        ]
        dim_html = "".join(
            f'<div class="dim {"pass" if p else "fail"}">'
            f'<div class="dim-icon">{ "✅" if p else "❌" }</div>'
            f'<div class="dim-label">{n}</div>'
            f'<div class="dim-reason">{r[:60] if r else "-"}</div>'
            f'</div>'
            for n, p, r in dims
        )
        hl = q.get("human_label", "")
        hl_html = f'<span class="hl {"hl-pass" if hl=="通过" else "hl-fail"}">人工: {hl}</span>' if hl else '<span class="hl hl-pending">待标注</span>'
        shot = q.get("screenshot", "")
        shot_html = f'<img src="/api/screenshot/{shot}" onclick="window.open(this.src)" style="cursor:pointer">' if shot else '<div class="no-shot">无截图</div>'
        questions_html += f'''
        <div class="q-card">
            <div class="q-hdr">
                <span class="q-id">Q{str(q.get("idx","?")).zfill(2)}</span>
                <span class="q-type">{q.get("question_type","?")}</span>
                <span class="q-ans">脚本答案: {q.get("script_answer","-")}</span>
                {hl_html}
                <span class="q-ovr {"ovr-pass" if q.get("overall_passed") else "ovr-fail"}">{"通过" if q.get("overall_passed") else "不通过"} ({q.get("overall_score",0):.2f})</span>
            </div>
            <div class="q-bdy">
                <div class="q-info">
                    <div class="info-line"><b>题干:</b> {q.get("stem","-")[:80]}</div>
                    <div class="info-line"><b>录音:</b> {q.get("recording","-")[:60]}</div>
                    <div class="info-line"><b>答案:</b> {q.get("script_answer","-")}</div>
                    {f'<div class="info-line kb"><b>知识库:</b> {q.get("knowledge_check","")[:80]}</div>' if q.get("knowledge_check") else ""}
                </div>
                <div class="q-shot">{shot_html}</div>
            </div>
            <div class="q-dims">{dim_html}</div>
        </div>'''

    docx_name = st.get("docx", st.get("version", "未知"))
    version = st.get("version", "未知")
    unit = st.get("unit", "?")
    stage = st.get("stage", "?")

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>审查报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#f0f2f5;color:#1e293b;padding:20px;font-size:15px;line-height:1.8}}
.hdr{{background:linear-gradient(135deg,#4a6cf7,#2952e8);color:#fff;border-radius:14px;padding:24px 32px;margin-bottom:20px}}
.hdr h1{{font-size:24px}}
.hdr .meta{{display:flex;gap:30px;margin-top:12px;font-size:14px;opacity:.9}}
.stats{{display:flex;gap:16px;padding:16px 20px;background:#fff;border-radius:12px;box-shadow:0 1px 6px rgba(0,0,0,.06);margin-bottom:20px;flex-wrap:wrap}}
.stat{{display:flex;align-items:center;gap:8px;font-size:15px}}
.stat .n{{font-weight:700;font-size:22px}}
.stat .n.g{{color:#16a34a}}
.stat .n.r{{color:#dc2626}}
.stat .n.b{{color:#4a6cf7}}
.q-card{{background:#fff;border-radius:12px;margin-bottom:12px;border:1px solid #eef0f5;overflow:hidden}}
.q-hdr{{display:flex;align-items:center;gap:12px;padding:10px 16px;background:#fafbfc;border-bottom:1px solid #f0f2f6;flex-wrap:wrap}}
.q-id{{font-size:20px;font-weight:700;color:#4a6cf7;min-width:40px}}
.q-type{{font-size:12px;padding:2px 10px;border-radius:6px;background:#eef2ff;color:#4a6cf7}}
.q-ans{{font-size:12px;color:#64748b}}
.q-ovr{{margin-left:auto;font-size:12px;padding:2px 10px;border-radius:6px;font-weight:600}}
.ovr-pass{{background:#dcfce7;color:#166534}}
.ovr-fail{{background:#fee2e2;color:#991b1b}}
.hl{{font-size:12px;padding:2px 10px;border-radius:6px}}
.hl-pass{{background:#bbf7d0;color:#14532d}}
.hl-fail{{background:#fecaca;color:#7f1d1d}}
.hl-pending{{background:#fef3c7;color:#92400e}}
.q-bdy{{display:grid;grid-template-columns:1fr 180px;gap:14px;padding:12px 16px}}
.q-info .info-line{{font-size:14px;padding:2px 0;color:#475569}}
.q-info .info-line b{{color:#334155}}
.q-info .kb{{color:#6b7280;font-size:12px;font-style:italic}}
.q-shot img{{width:100%;border-radius:8px;border:1px solid #eef0f5;max-height:160px;object-fit:contain;background:#f8fafc}}
.no-shot{{height:100px;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;background:#f8fafc;border-radius:8px}}
.q-dims{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;padding:0 16px 12px}}
.dim{{text-align:center;padding:8px;border-radius:8px;border:1px solid #eef0f5;background:#fafbfc}}
.dim.pass{{background:#f0fdf4;border-color:#bbf7d0}}
.dim.fail{{background:#fef2f2;border-color:#fecaca}}
.dim-icon{{font-size:20px}}
.dim-label{{font-size:13px;font-weight:600;color:#64748b}}
.dim-reason{{font-size:11px;color:#94a3b8;margin-top:2px;word-break:break-all}}
.actions{{text-align:center;margin:20px 0}}
.actions button{{padding:10px 24px;border:none;border-radius:8px;background:#4a6cf7;color:#fff;font-size:15px;cursor:pointer}}
.actions button:hover{{background:#2952e8}}
@media print{{.actions{{display:none}} .q-card{{break-inside:avoid}}}}
</style></head>
<body>
<div class="hdr">
    <h1>试题审查报告</h1>
    <div class="meta">
        <span>脚本: {docx_name}</span>
        <span>版本: {version}</span>
        <span>Unit {unit} · {stage}</span>
        <span>{datetime.now().strftime("%Y-%m-%d %H:%M")}</span>
    </div>
</div>
<div class="stats">
    <div class="stat">总题数: <span class="n b">{total}</span></div>
    <div class="stat">AI通过: <span class="n g">{passed}</span></div>
    <div class="stat">AI不通过: <span class="n r">{total - passed}</span></div>
    <div class="stat">已人工标注: <span class="n b">{labeled}</span></div>
    <div class="stat">人机一致率: <span class="n g">{acc}%</span></div>
</div>
{questions_html}
<div class="actions"><button onclick="window.print()">打印 / 保存为PDF</button></div>
</body></html>'''

    return Response(html, mimetype="text/html")


# ============================================================
# 听力专项 · 练习+测试 全流程自动化（新引擎）
# ============================================================

_AUDIO_RUNNER = None  # 后台线程


@app.route("/api/audio/run", methods=["POST"])
def api_audio_run():
    """启动听力专项自动化（练习+测试）
    请求: {"mode": "all"|"practice"|"test", "units": [1], "test_units": [1]}
    """
    global _AUDIO_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    mode = data.get("mode", "all")
    units = data.get("units", [1])
    test_units = data.get("test_units", units)

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running(f"听力专项[{mode}]")
            log_msg(f"启动听力专项 {mode} 模式: 练习单元{units} 测试单元{test_units}")
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from modules.听力专项 import run_module, run_test_module
            from common.tools import dismiss_global_popups, close_ad, ensure_grade, settle_ads
            import uiautomator2 as u2

            d = _connect_device()
            log_msg("设备已连接")

            # 关广告 + 确认年级
            # ★ 用 settle_ads 循环「检测→关闭→再检测」消除"点空/广告刚弹出时误点"竞态
            settle_ads(d, wait_total=12)
            ok = ensure_grade(d, "五年级上册", "湘少版")
            log_msg("年级确认: 湘少版 五年级上册" if ok else "⚠ 年级切换失败，继续尝试")

            q1 = q2 = 0
            if mode in ("all", "practice"):
                log_msg("▶ 开始练习部分...")
                q1 = run_module(d)
                log_msg(f"练习部分完成: {q1} 题")
            if mode in ("all", "test"):
                log_msg("▶ 开始测试部分...")
                q2 = run_test_module(d)
                log_msg(f"测试部分完成: {q2} 题")

            log_msg(f"✅ 听力专项全部完成: 练习{q1} + 测试{q2} = {q1+q2} 题")
            set_done()
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"❌ 任务异常: {e}", "error")
            set_done()

    _AUDIO_RUNNER = threading.Thread(target=_run, daemon=True)
    _AUDIO_RUNNER.start()
    return jsonify({"status": "started", "mode": mode,
                    "units": units, "test_units": test_units})


# ============================================================
# 口语训练 自动化（新引擎）
# ============================================================

_ORAL_RUNNER = None  # 后台线程


@app.route("/api/oral/run", methods=["POST"])
def api_oral_run():
    """启动口语训练自动化
    请求: {"units": [1,2,3,4]}
    """
    global _ORAL_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    units = data.get("units", [1])

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running(f"口语训练")
            log_msg(f"启动口语训练: 单元{units}")
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from modules.口语训练 import run_module
            from common.tools import dismiss_global_popups, close_ad, ensure_grade
            import uiautomator2 as u2

            d = _connect_device()
            log_msg("设备已连接")

            # 关广告 + 确认年级
            for _ in range(3):
                dismiss_global_popups(d)
            close_ad(d)
            ok = ensure_grade(d, "五年级上册", "湘少版")
            log_msg("年级确认: 湘少版 五年级上册" if ok else "⚠ 年级切换失败，继续尝试")

            q = run_module(d)
            log_msg(f"✅ 口语训练完成: {q} 题")
            set_done()
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"❌ 任务异常: {e}", "error")
            set_done()

    _ORAL_RUNNER = threading.Thread(target=_run, daemon=True)
    _ORAL_RUNNER.start()
    return jsonify({"status": "started", "units": units})


# ============================================================
# 单元自检 自动化（新引擎）
# ============================================================

_UNIT_RUNNER = None  # 后台线程


@app.route("/api/unit/run", methods=["POST"])
def api_unit_run():
    """启动单元自检自动化
    请求: {"units": [1,2,3,4]}
    """
    global _UNIT_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    units = data.get("units", [1])
    # ★ 2026-08-26：年级/版本从请求读取（默认继承主页当前），不再写死五年级——用户切到六上后可测六上卷
    _g = data.get("grade", "") or ""
    _v = data.get("version", "") or ""

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running(f"单元自检")
            log_msg(f"启动单元自检: 单元{units}")
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from modules.单元自检 import run_module
            from common.tools import dismiss_global_popups, close_ad, ensure_grade
            import uiautomator2 as u2

            d = _connect_device()
            log_msg("设备已连接")

            # 关广告 + 确认年级（仅当请求传了 grade 才切换；默认继承当前，不强制）
            for _ in range(3):
                dismiss_global_popups(d)
            close_ad(d)
            if _g:
                ok = ensure_grade(d, _g, _v or "湘少版")
                log_msg(f"年级确认: {_v or '湘少版'} {_g}" if ok else "⚠ 年级切换失败，继续尝试")

            q = run_module(d, units=units)
            log_msg(f"✅ 单元自检完成: {q} 题")
            set_done()
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"❌ 任务异常: {e}", "error")
            set_done()

    _UNIT_RUNNER = threading.Thread(target=_run, daemon=True)
    _UNIT_RUNNER.start()
    return jsonify({"status": "started", "units": units})


# ============================================================
# 知识过关 自动化（新引擎）
# ============================================================

_KNOWLEDGE_RUNNER = None  # 后台线程


@app.route("/api/knowledge/run", methods=["POST"])
def api_knowledge_run():
    """启动知识过关自动化（重点词汇+重点句型）
    请求: {"units": [1]}
    """
    global _KNOWLEDGE_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    units = data.get("units", [1])

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running(f"知识过关")
            log_msg(f"启动知识过关: 单元{units}")
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from modules.知识过关 import run_module
            from common.tools import dismiss_global_popups, close_ad, ensure_grade
            import uiautomator2 as u2

            d = _connect_device()
            log_msg("设备已连接")

            # 关广告 + 确认年级
            for _ in range(3):
                dismiss_global_popups(d)
            close_ad(d)
            ok = ensure_grade(d, "五年级上册", "湘少版")
            log_msg("年级确认: 湘少版 五年级上册" if ok else "⚠ 年级切换失败，继续尝试")

            q = run_module(d)
            log_msg(f"✅ 知识过关完成: {q} 题")
            set_done()
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"❌ 任务异常: {e}", "error")
            set_done()

    _KNOWLEDGE_RUNNER = threading.Thread(target=_run, daemon=True)
    _KNOWLEDGE_RUNNER.start()
    return jsonify({"status": "started", "units": units})


# ============================================================
# 语音评测 自动化（题目未做好，仅进入模块）
# ============================================================

_VOICE_RUNNER = None  # 后台线程


@app.route("/api/voice/run", methods=["POST"])
def api_voice_run():
    """启动语音评测模块（半自动：脚本驱动+用户朗读；继承主页版本/年级）
    ★ 2026-08-23：语音评测从主页继承当前版本年级（如湘少版二年级上册），
      点主页"语音评测"文字(877,1987)进入 → 目录 Unit 1-7 → 单元展开 → 部分作答
    """
    global _VOICE_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    # 请求参数：units（如 [1,2]）、grade、version（默认继承主页当前）
    _data = request.get_json(silent=True) or {}
    _units = _data.get("units") or None
    _grade = _data.get("grade", "") or ""
    _version = _data.get("version", "") or ""

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running(f"语音评测")
            log_msg(f"启动语音评测（半自动：用户朗读+脚本驱动）")
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from modules.语音评测 import run_module
            from common.tools import dismiss_global_popups, close_ad
            import uiautomator2 as u2

            d = _connect_device()
            log_msg("设备已连接")

            for _ in range(3):
                dismiss_global_popups(d)
            close_ad(d)
            # ★ 语音评测内部处理版本/年级：主页当前版本+传入期望值兜底
            r = run_module(d, units=_units,
                           expected_grade=_grade, expected_version=_version)
            log_msg(f"✅ 语音评测完成: {r} 个单元")
            set_done()
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"❌ 任务异常: {e}", "error")
            set_done()

    _VOICE_RUNNER = threading.Thread(target=_run, daemon=True)
    _VOICE_RUNNER.start()
    return jsonify({"status": "started"})


# ============================================================
# 巧记单词 自动化（单词同步闯关）
# ============================================================

_QIAOJI_RUNNER = None  # 后台线程


@app.route("/api/qiaoji/run", methods=["POST"])
def api_qiaoji_run():
    """启动巧记单词自动化（单词同步闯关）
    请求: {"units": [1]}  # 单元数，默认 U1-U9 全跑
    """
    global _QIAOJI_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    units = data.get("units", list(range(1, 10)))  # 默认全部单元

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running(f"巧记单词")
            log_msg(f"启动巧记单词: 单元{units}")
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from modules.巧记单词 import run_module
            from common.tools import dismiss_global_popups, close_ad, ensure_grade
            import uiautomator2 as u2

            d = _connect_device()
            log_msg("设备已连接")

            for _ in range(3):
                dismiss_global_popups(d)
            close_ad(d)
            ok = ensure_grade(d, "五年级上册", "湘少版")
            log_msg("年级确认: 湘少版 五年级上册" if ok else "⚠ 年级切换失败，继续尝试")

            q = run_module(d)
            log_msg(f"✅ 巧记单词完成: {q} 题")
            set_done()
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"❌ 任务异常: {e}", "error")
            set_done()

    _QIAOJI_RUNNER = threading.Thread(target=_run, daemon=True)
    _QIAOJI_RUNNER.start()
    return jsonify({"status": "started", "units": units})


# ============================================================
# 前提设置：切换版本 / 年级
# ============================================================
import importlib
_setup_mod = None

def _get_setup():
    global _setup_mod
    if _setup_mod is None:
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        _setup_mod = importlib.import_module("common.setup")
    return _setup_mod


@app.route("/api/setup", methods=["POST"])
def api_setup():
    """切换教材版本 + 年级（前提功能，模块运行前先设置）

    请求: {"version": "湘少版", "grade": "五年级上册"}
    """
    global _SETUP_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行，请等待"}), 409

    data = request.get_json() or {}
    version = (data.get("version") or "").strip()
    grade = (data.get("grade") or "").strip()
    if not version or not grade:
        return jsonify({"error": "请填写版本和年级"}), 400

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            log_msg(f"前提设置: 切换到 {version} {grade}")
            setup = _get_setup()
            import uiautomator2 as u2
            d = _connect_device()
            ok = setup.switch_version_grade(d, version, grade)
            if ok:
                log_msg(f"切换成功: 当前 {version} {grade}", "success")
            else:
                log_msg("切换失败，请重试", "error")
        except SystemExit:
            log_msg("⏹ 任务已被立即停止", "warning")
            _cleanup_task_state()  # 统一收尾: 清running + 重置停止标志
        except Exception as e:
            log_msg(f"切换异常: {e}", "error")

    _SETUP_RUNNER = threading.Thread(target=_run, daemon=True)
    _SETUP_RUNNER.start()
    return jsonify({"status": "started", "version": version, "grade": grade})


# ============================================================
# 多模块检测：版本/年级 + 多个模块依次执行
# ============================================================
_LAST_MODULES_RESULT = None
# ★ 当前多模块检测的 模块→脚本 映射（_detect_content_dimension 按模块匹配脚本用）
_GLOBAL_DOCX_MAP = {}


@app.route("/api/modules/stop", methods=["POST"])
def api_modules_stop():
    """立即停止正在运行的任务（设置停止标志 + 注入异常强制中断线程）"""
    forced, message = _request_stop()
    if not task_status["running"] and not forced:
        return jsonify({"status": "idle", "message": message})
    return jsonify({"status": "stopping", "message": message})


# ============================================================
# 脚本对照 LLM 知识性审查（有脚本的模块：基础自动化后追加）
# ============================================================

def _qreview_to_state(module: str, docx: str, unit, r, stage: str = "", q=None) -> dict:
    """把 ReviewAgent 的 QuestionReview 转成六维面板 questions 记录。"""
    # ★ 2026-08-25 错题日志定位：构造"口语训练 · U3 · 第2大题·第4小题"位置
    #   （口语题 script_question 含 big/stage_idx；听力专项无 big 用 stage+unit）
    #   缺 q 时回退到"Q{idx:02d}"，不会因为脚本格式差异导致空位
    _pos = ""
    if q is not None:
        _u = getattr(q, "unit", 0) or unit or 0
        _big = getattr(q, "big", 0) or 0
        _no = getattr(q, "stage_idx", 0) or 0
        if _u and _big and _no:
            _pos = f"U{_u}·第{_big}大题·第{_no}小题"
        elif _u and _big:
            _pos = f"U{_u}·第{_big}大题"
        elif _u and _no:
            _pos = f"U{_u}·第{_no}小题"
        elif _u:
            _pos = f"U{_u}"
    if not _pos:
        _pos = f"Q{r.idx:02d}"
    def _cr(chk):
        if chk is None:
            return None, "", "skip"
        det = "；".join((chk.details or [])[:4])
        # ★ skip = 该维度无法核对（听音/图片题无截图），计为「未检」而非「不通过」
        if getattr(chk, "method", "") == "skip":
            return None, det[:300], "skip"
        # ★ uncertain = LLM 无法解析判定（待审/需人工复核）→ 也计「未检」而非「不通过」
        #   用户实测："待审"被当成不通过 → 明明几维过却综合判定不通过
        if getattr(chk, "method", "") == "uncertain":
            return None, det[:300], "uncertain"
        return chk.passed, det[:300], chk.method or ""
    dims = {
        "stem": _cr(r.stem_check), "content": _cr(r.content_check),
        "image": _cr(r.image_check), "answer": _cr(r.answer_check),
        "audio": _cr(r.audio_check), "post_error": _cr(r.post_error_check),
    }
    # ★ 2026-09-17：把 LLM 给出的「建议修改」原样带到错题卡。
    #   旧实现没带 suggestion，trace_engine 只能拼一句
    #   "请检查并修正「题干」维度：{原因}" → 卡片上"原因"和"建议"一字不差，
    #   检查人员看不出"要改什么"（用户反馈"不够直白、太长了"）。
    def _sug(_c):
        return ((getattr(_c, "suggestion", "") or "").strip())[:220] if _c is not None else ""
    _sugg = {
        "题干": _sug(r.stem_check), "内容": _sug(r.content_check),
        "图片": _sug(r.image_check), "答案": _sug(r.answer_check),
        "音频": _sug(r.audio_check), "答错检查": _sug(r.post_error_check),
    }
    checked = [v for v, _, _ in dims.values() if v is not None]
    passed = [v for v, _, _ in dims.values() if v is True]
    overall = None
    if checked:
        # ★ 修复：用 checked（非 None 的实际判定维度）判断，None=未检维度不计入
        #   （原写法遍历全部 dims 含 None，`None is True` 恒 False → 有任一未检维度时
        #    整体永远判 None，维度全通过也显示不出来）
        if any(v is False for v in checked):
            overall = False
        elif all(v is True for v in checked):
            overall = True
        # 部分检查（无 False 但未全过，如仅 1 维）→ 保持 None（未定），不误报不通过
    # ★ module_qno：脚本 idx（后续由 report_exporter 按 stage 分组重置显示）
    # ★ progress：含具体位置（口语训练·U3·第2大题·第4小题），方便错题日志快速定位
    # ★ 审查体系改造：脚本层子结构（合并进同一条基础层记录时挂到 questions[qid]["script"]）
    _kb = r.knowledge_check or {}
    if isinstance(_kb, dict):
        _kb_ok = _kb.get("passed")
        _kb_sum = (_kb.get("detail") or _kb.get("reason") or "").strip()
        if not _kb_sum:
            _kb_sum = "知识库查证" + ("通过" if _kb_ok else ("未检" if _kb_ok is None else "异常"))
    else:
        _kb_ok = None
        _kb_sum = str(_kb)[:200]
    _dim_keys = ("stem", "content", "image", "answer", "audio", "post_error")
    _fail_layers = [(k, dims[k][1]) for k in _dim_keys if dims[k][0] is False]
    if _fail_layers:
        _reason_summary = "脚本核验不通过：" + "；".join(
            f"{k}:{d}" for k, d in _fail_layers[:3])[:300]
    else:
        _reason_summary = (f"脚本核验通过（{len(passed)}/{len(checked)} 维）"
                           if checked else "脚本核验未检（LLM 不可用）")
    return {
        "idx": r.idx, "total": 0,
        "question_type": r.question_type or "脚本题",
        "module": module,            # ★ 模块（分组展示用）
        "stage": stage or "",        # ★ 子模块阶段（基础巩固/综合进阶/难点突破）
        "module_qno": r.idx,        # 写脚本 idx；report_exporter 按 stage 重新排号
        "screenshot": "",
        "progress": f"{_pos}",      # ★ 口语训练 U3·第2大题·第4小题 / 听力专项 基础巩固 1.1
        "position": _pos,           # ★ 单独存一份，供报告导出/下载错题日志按位置排序
        "ai_stem": dims["stem"][0], "ai_content": dims["content"][0],
        "ai_image": dims["image"][0], "ai_answer": dims["answer"][0],
        "ai_audio": dims["audio"][0], "ai_post_error": dims["post_error"][0],
        "stem_reason": dims["stem"][1], "content_reason": dims["content"][1],
        "image_reason": dims["image"][1], "answer_reason": dims["answer"][1],
        "audio_reason": dims["audio"][1], "post_error_reason": dims["post_error"][1],
        # ★ 2026-09-17：建议字段（trace_engine 直接读，避免"建议=原因"的重复文案）
        "stem_suggestion": _sugg["题干"], "content_suggestion": _sugg["内容"],
        "image_suggestion": _sugg["图片"], "answer_suggestion": _sugg["答案"],
        "audio_suggestion": _sugg["音频"], "post_error_suggestion": _sugg["答错检查"],
        "_suggestions": _sugg,
        "overall_passed": overall,
        "overall_score": round(len(passed) / max(len(checked), 1), 2) if checked else 0.0,
        # ★ 题干显示实际内容（脚本题 stem；口语训练朗读题为多句子）
        "stem": (r.stem_check.actual or "").strip() if getattr(r.stem_check, "actual", "") else
                f"第{r.idx}题（{r.question_type or '脚本题'}）",
        "options": "", "script_answer": r.script_answer or "",
        "note": f"LLM 知识性审查 · 脚本 {docx}",
        # ★ 审查体系改造：分层标记 + 脚本层结论（边跑边审 → 单记录双层）
        "layer": "script_only",
        "script": {
            "matched": True,
            "status": "done",
            "stem": dims["stem"][0], "content": dims["content"][0],
            "image": dims["image"][0], "answer": dims["answer"][0],
            "audio": dims["audio"][0], "post_error": dims["post_error"][0],
            "stem_reason": dims["stem"][1], "content_reason": dims["content"][1],
            "image_reason": dims["image"][1], "answer_reason": dims["answer"][1],
            "audio_reason": dims["audio"][1], "post_error_reason": dims["post_error"][1],
            "knowledge": _kb_ok, "knowledge_reason": _kb_sum,
            "suggestions": dict(_sugg),
            "reason": _reason_summary,
            "overall_passed": overall,
            "overall_score": round(len(passed) / max(len(checked), 1), 2) if checked else 0.0,
        },
    }


def _match_basic_qid(module: str, q, rr, stage: str = "") -> str:
    """★ 审查体系改造：把脚本审查结果合并进同一条基础层记录（边跑边审 → 单记录双层）。

    优先口语训练结构 (unit, big, stage_idx) → auto-Q{big:02d}-{stage_idx:02d}；
    其他模块按脚本 idx → auto-Q{idx:03d}，要求模块名（+stage 若都有）一致才合并。
    找不到匹配 → 返回 ""（脚本题未在 App 出现过 → 保留独立脚本记录）。
    """
    qs = _inspection_state.get("questions", {})
    _big = getattr(q, "big", 0) or 0
    _no = getattr(q, "stage_idx", 0) or 0
    _idx = rr.idx or getattr(q, "global_idx", 0) or 0
    cands = []
    if _big and _no:
        cands.append(f"auto-Q{_big:02d}-{_no:02d}")
    cands.append(f"auto-Q{int(_idx):03d}")
    for c in cands:
        rec = qs.get(c)
        if rec is None:
            continue
        if rec.get("module") and module and rec.get("module") != module:
            continue
        _rec_stage = rec.get("stage") or ""
        if _rec_stage and stage and _rec_stage != stage:
            continue
        return c
    return ""


def _auto_qid_of_script_record(rec: dict) -> str:
    """★ 2026-09-20 新增：从一条【脚本层记录】反推它在基础层对应的 auto-qid。

    用途：复用历史审查结论时，旧缓存可能只存了 `{模块}-脚本-Qnn` 这种独立记录
    （上一次运行 App 侧题目没登记进去时就是这样）。若直接回灌，就会出现
    「同一道题既有 auto-Q.. 又有 -脚本-Q..」的重复条目，而且 auto- 记录拿不到
    脚本层结论。这里按记录自带的定位信息找回它的基础层身份。

    口语训练记录 progress 形如 "U4·第2大题·第4小题" → auto-Q02-04；
    其他模块形如 "Q07" → auto-Q007。取不到返回 ""（当作真正的脚本题，独立保留）。
    """
    _prog = str((rec or {}).get("progress") or "")
    m = re.search(r"第0*(\d+)大题[·\-]?第0*(\d+)小题", _prog)
    if m:
        return f"auto-Q{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m2 = re.search(r"\bQ0*(\d+)\b", _prog)
    if m2:
        return f"auto-Q{int(m2.group(1)):03d}"
    _i = (rec or {}).get("idx")
    if isinstance(_i, int) and _i > 0:
        return f"auto-Q{_i:03d}"
    return ""


def _check_passage_grammar(module: str, unit, agent) -> list:
    """★ 2026-09-20 新增（用户要求）：检查题目篇章（阅读短文等大段英文）的语法错误。

    用户原话："检查题目篇章是否有语法错误，有的话指出就行，没有就不需要输出什么内容"
      → 没有错误时**零输出**（不写日志、不产生问题条目），有错误才报。
    只查客观语法/用词错误（时态、主谓一致、冠词、介词、搭配、拼写），
    不评难度/题材/风格；没把握的不报（避免 LLM 风格化误报刷屏）。
    同一段短文被同大题多个小题共享 → 按文本去重，只查一次。
    结果结构故意与 `_script_issues` 条目一致（severity/type/location/issue/suggestion），
    直接 extend 进 `_script_issues[module]`，复用报告与前端已有的透出链路。
    """
    out = []
    try:
        llm = getattr(agent, "llm", None)
        if llm is None:
            return []
        _seen = set()
        for q in getattr(agent, "script_questions", []) or []:
            p = (getattr(q, "passage", "") or "").strip()
            if len(p) < 40 or p in _seen:      # 太短的不算篇章
                continue
            _seen.add(p)
            _big = getattr(q, "big", 0) or 0
            _loc = f"U{unit} 第{_big}大题" if _big else f"U{unit}"
            prompt = (
                "下面是中国小学英语题目中的一段短文（呈现给学生的篇章）。"
                "请只检查其中客观存在的英语语法/用词错误（时态、主谓一致、冠词、介词、"
                "搭配、拼写等），不要评论难度、题材、风格；没把握的地方不要报。\n"
                "若没有语法错误，只输出 NONE。\n"
                "若有错误，只输出 JSON 数组："
                '[{"orig":"原句片段","fix":"改正后","why":"错误说明(中文,30字内)"}]\n'
                f"短文：\n{p}"
            )
            raw = (llm.ask(prompt) or "").strip()
            if not raw:
                continue
            # "NONE"（大小写/带句号）→ 无错误，零输出
            if re.match(r"^none\b", raw.splitlines()[0].strip(), re.I):
                continue
            _m = re.search(r"\[.*\]", raw, re.DOTALL)
            if not _m:
                continue
            try:
                data = json.loads(_m.group())
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for it in data:
                if not isinstance(it, dict):
                    continue
                orig = str(it.get("orig") or "").strip()
                fix = str(it.get("fix") or "").strip()
                why = str(it.get("why") or "").strip()
                if not (orig or fix):
                    continue
                out.append({
                    "severity": "高", "type": "篇章语法错误",
                    "location": _loc,
                    "issue": (f"「{orig[:60]}」→ 应为「{fix[:60]}」"
                              + (f"（{why[:60]}）" if why else "")),
                    "suggestion": fix[:120],
                })
    except Exception as e:
        log_msg(f"⚠ {module} 篇章语法检查失败（不影响其他结论）: {e}", "warning")
    return out


def _run_llm_script_review(module: str, docx: str, version: str, unit, stage: str = ""):
    """用 ReviewAgent 对照脚本做 LLM 知识性审查（文字核对 + 有截图时图片识别），
    结果写入 _inspection_state["questions"]（前端六维面板实时展示）。

    ★ stage 参数：听力专项区分"练习/测试"，避免脚本错配
      - stage="练习" → 只审查 stage=练习 的题
      - stage="测试" → 只审查 stage=测试 的题
      - stage=""     → 不区分（其他模块）
    """
    global _inspection_state
    docx_path = PROJECT_ROOT / "uploads" / docx
    if not docx_path.exists():
        log_msg(f"❌ 脚本文件不存在: {docx}（请在页面上传脚本）", "error")
        return
    # ★ 2026-08-26 修复：后端也校验【脚本文件名 vs 模块名】是否匹配！
    #   前端单模块手动脚本兜底曾直接绑 reviewDocx 下拉的脚本（不校验模块名）→
    #   用户测"巧记单词"却拿到"听力专项U6"脚本做 LLM 审查（模块和脚本毫无关系）。
    #   这里做最终防线：文件名不含本模块关键词 → 视为无匹配脚本，仅基础完整性。
    try:
        _mod_kws = {
            "听力专项": ("听力专项", "听力"),
            "口语训练": ("口语", "朗读"),
            "单元自检": ("单元自检", "单元检测"),
            "知识过关": ("知识过关", "知识", "重点词汇", "重点句型"),
            "巧记单词": ("巧记", "单词"),
            "语音评测": ("语音评测", "语音"),
        }.get(module, (module,))
        if not any(k in docx for k in _mod_kws):
            log_msg(f"ℹ {module}：脚本「{docx}」不是{module}模块的脚本，无匹配脚本 → 仅做基础完整性检查", "info")
            _set_script_provenance(module, docx, False, f"脚本不是{module}模块的脚本")
            return
        # ★ 2026-09-20：版本/年级守卫——脚本年级/版本与本次实跑不符时**绝不比对**。
        #   实测：跑教科六上 U6 却自动匹配到「口语训练新教科五上U4-7」→ LLM 拿
        #   五上 U4-U7 的题干跟六上 App 逐题硬比 → 大面积"不符"全是假错，
        #   还把 U4/U7（根本没测的单元）的问题写进日志（用户反馈原话：
        #   "这个根本就没测试到这个题目，你就乱写在日志里面"）。
        _mismatch = _script_matches_run(docx,
                                        _inspection_state.get("version", ""),
                                        _inspection_state.get("grade", ""))
        if _mismatch:
            log_msg(f"⛔ {module}：{_mismatch} → 跳过脚本比对（避免拿错脚本乱报没测过的题）；"
                    f"请上传本次版本/年级对应的脚本后再测", "warning")
            _set_script_provenance(module, docx, False, _mismatch)
            return
        _set_script_provenance(module, docx, True)
    except Exception:
        pass
    _stage_label = f"·{stage}" if stage else ""
    # ★ 审查体系改造：索引复用检查（已审查且脚本未变 → 跳过 LLM，复用结论）
    _version = _inspection_state.get("version", "未知版本")
    _grade = _inspection_state.get("grade", "未知年级")
    _unit_key = str(unit).strip() if unit not in (None, "", 0, "0", "NONE") else "全部"
    _index_key = f"{_version}/{_grade}/{module}/{_unit_key}"
    _index = load_script_review_index()
    _docx_hash = _script_file_hash(docx_path)
    _cached = _index.get(_index_key, {})
    # ★ 2026-09-23：缓存有效性 = 脚本未变 **且** LLM 未换（见 _current_llm_signature）。
    #   只比 script_hash 时，换模型后旧单元会静默复用旧结论（"换了模型结论却一样"）。
    _cur_llm_sig = _current_llm_signature()
    _cached_llm_sig = _cached.get("llm_signature", "")
    if (_cached.get("status") == "done" and _cached.get("script_hash") == _docx_hash
            and not _script_cache_reusable(_cached, _docx_hash, _cur_llm_sig)):
        _why = (f"缓存来自 {_cached_llm_sig}" if _cached_llm_sig else "旧缓存未记录模型")
        log_msg(f"ℹ {module}（{_unit_key}）{_why}，当前为 {_cur_llm_sig} → "
                f"本次重新审查（不复用旧结论）", "info")
    if _script_cache_reusable(_cached, _docx_hash, _cur_llm_sig):
        _reuse_msg = f"{module}（{_unit_key}）已于 {_cached.get('reviewed_at','?')} 审查过，脚本未变，本次复用结论"
        log_msg(f"ℹ {_reuse_msg}", "info")
        _inspection_state["_reuse_info"] = _reuse_msg
        # 从缓存结果文件加载历史审查结论，合并到 _inspection_state["questions"]
        _cache_path = PROJECT_ROOT / "data" / "script_review_cache" / f"{_index_key.replace('/','_').replace(' ','')}.json"
        # ★ 2026-09-20 修复（索引说"审查过"、缓存文件却不在 → 静默什么都不做）：
        #   旧结构是 try/except/else，`else: return` 只要"没抛异常"就执行 ——
        #   而 `if _cache_path.exists():` 为 False 时 try 正常结束、不抛异常，
        #   于是走进 else 直接 return：既不加载历史结论、也不做 LLM 审查，
        #   日志还打着"本次复用结论"，脚本层检查**一条结果都没有**（静默失效，
        #   实测 data/script_review_cache/ 为空但索引里 status=done）。
        #   根因：索引与缓存文件是两次独立写盘，而写缓存那段是 `except: pass`
        #   （写了没写成功都不知道）→ 出现"索引有、内容无"的坏状态。
        #   这里改为显式记录"是否真的加载成功"，没加载到就继续往下做完整审查。
        _cache_loaded = False
        try:
            if _cache_path.exists():
                _cached_qs = json.loads(_cache_path.read_text(encoding="utf-8"))
                if isinstance(_cached_qs, dict) and _cached_qs:
                    # ★ 审查体系改造：合并脚本层进本轮 fresh 基础记录，而非整体覆盖。
                    #   重跑模块后 auto-* 基础记录是新的 UI 证据，脚本层复用缓存结论；
                    #   独立脚本记录直接恢复。
                    # ★ 2026-09-20 修复（重跑后同一题出现两条）：
                    #   旧缓存可能只存了 `{模块}-脚本-Qnn`（上一次运行时 App 侧题目
                    #   根本没登记进去，正是"20 题只剩 4 题"那个 bug 的产物）。
                    #   原样回灌会让同一道题同时有 auto-Q.. 和 -脚本-Q.. 两条，
                    #   而且 auto- 记录拿不到脚本层结论（报告里同一题出现两遍、
                    #   一遍只有脚本结论一遍只有界面结论）。
                    #   现在先反推缓存记录对应的 auto-qid：命中本轮 fresh 基础记录
                    #   → 合并脚本层；命中不了才是真正"App 没跑到"的脚本题 → 独立保留。
                    _merged_cache = 0
                    for _k, _v in _cached_qs.items():
                        if not isinstance(_v, dict):
                            continue
                        _tgt = _k if _k.startswith("auto-") else _auto_qid_of_script_record(_v)
                        _cur = _inspection_state["questions"].get(_tgt) if _tgt else None
                        # 模块必须一致（防止把别的模块/单元的同号题合并进来）
                        if _cur is not None and module and _cur.get("module") \
                                and _cur.get("module") != module:
                            _cur = None
                        if _cur is not None:
                            if isinstance(_v.get("script"), dict):
                                _cur["script"] = _v["script"]
                                _cur["layer"] = "basic+script"
                                if _v.get("note"):
                                    _cur["note"] = _v["note"]
                                # ★ 2026-09-20：复用路径同样要"折算"——
                                #   否则重跑一次模块，脚本层判出的不通过又全丢了
                                #   （表现：首跑报告有错题，重跑后错题变"未审"）。
                                _fold_script_layer(_cur, _v["script"])
                                _merged_cache += 1
                            # 目标基础记录已存在但缓存里没有脚本层 → 不必再插重复记录
                        else:
                            _inspection_state["questions"][_k] = _v
                    log_msg(f"✅ 已加载 {len(_cached_qs)} 题历史审查结论"
                            f"（其中 {_merged_cache} 题脚本层合并进基础记录）", "success")
                    # ★ 2026-09-20：复用时同样恢复篇章语法检查结论（缓存里的模块级 list 键）。
                    #   不恢复的话：首次审查报了篇章错误、重跑后（脚本没变，走复用）
                    #   错误条目消失——重蹈"脚本问题日志里有、结果里没有"的覆辙。
                    _pi_cached = _cached_qs.get("_passage_issues")
                    if isinstance(_pi_cached, list) and _pi_cached:
                        _inspection_state.setdefault("_script_issues", {})\
                            .setdefault(module, []).extend(_pi_cached)
                        for _pi in _pi_cached:
                            log_msg(f"❗[{_pi.get('severity', '中')}] {_pi.get('type', '篇章语法错误')}"
                                    f" · {_pi.get('location', '')}：{_pi.get('issue', '')}", "warning")
                        log_msg(f"📝 {module} 篇章语法检查（历史结论复用）："
                                f"{len(_pi_cached)} 处错误", "warning")
                    _cache_loaded = True
                else:
                    log_msg(f"⚠ 缓存审查结论为空或格式异常（{_cache_path.name}）"
                            f"→ 改为完整审查", "warning")
            else:
                log_msg(f"⚠ 索引显示已审查过，但缓存文件缺失（{_cache_path.name}）"
                        f"→ 改为完整审查（此前会出现'打着复用旗号却零结果'）", "warning")
        except Exception as _e:
            log_msg(f"⚠ 加载缓存审查结论失败: {_e}，将重新审查", "warning")
            # 缓存加载失败 → 回退到完整审查，不 return
        if _cache_loaded:
            # ★ 2026-09-20 修复（复用路径从不落盘）：
            #   旧代码只在**跑完 LLM 审查**那条路上调 `_save_inspection_state_merge()`，
            #   而复用分支直接 return → 本次运行合并进基础记录的脚本层结论、
            #   以及刚算出的 `_script_issues`（脚本自检发现的问题）**只留在内存里**：
            #   服务一重启、或报告/接口读的是状态文件，这些结果就全没了
            #   （实测前端日志打了"脚本自检发现 3 处问题"，而状态文件里一条都没有）。
            #   复用也是"本次运行产生了结果"，必须同样落盘。
            try:
                _save_inspection_state_merge()
            except Exception as _e_sv:
                log_msg(f"⚠ 复用结论后保存状态失败: {_e_sv}", "warning")
            try:
                _live_regen_error_report()
            except Exception:
                pass
            return  # 复用成功，跳过 LLM 审查
    log_msg(f"🧠 {module}{_stage_label} 正在用脚本「{docx}」做 LLM 知识性审查…（逐题核对题干/选项/答案，耗时较长）", "info")
    # ★ 听力专项多子模块：临时切换 set_current_module 上下文，确保 questions 用对的 stage 标记
    if stage:
        try:
            from common.logger import set_current_module
            set_current_module(module, stage)
        except Exception:
            pass
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.review_agent import ReviewAgent, ReviewConfig, normalize_units
        # ★ 2026-08-25 修复：支持多单元（"2,4" / "2-4"），不再截断成第一个单元
        #   用户场景：选"口语训练五上 U2、U4"，脚本"口语训练湘少五上(全单元)"
        #   → 应提取 U2+U4 的题目审查；旧逻辑 int(unit.split("-")[0]) 只审 U2
        _u = str(unit).strip() if unit not in (None, "", 0, "0", "NONE") else 0
        agent = ReviewAgent(ReviewConfig(
            docx_path=str(docx_path),
            screenshot_dir=str(PROJECT_ROOT / "screenshots"),
            unit=_u, verbose=False,
        ))
        # ★ 单元不匹配提示：脚本不含所选单元（用户实测"单元根本没脚本"，
        #   静默显示"0题"误导人）→ 明确日志：脚本实际覆盖哪些单元
        # ★ 2026-08-25 修复：部分覆盖也要提示！旧逻辑只看 script_questions 是否为空
        #   （全不匹配才提示），选 U4+U8 而脚本只有 U6-U10 时，U4 不在范围被静默忽略。
        if not agent.script_questions:
            _units_ok = sorted(u for u in getattr(agent, "script_units", set()) if u > 0)
            # ★ 2026-08-26 精简提示：用户期望直接说"无覆盖脚本"即可，
            #   不再罗列脚本名/期望单元/实际单元等细节（检查人员只需要知道"没得审"）
            log_msg(f"ℹ {module}：无覆盖所选单元的脚本 → 跳过 LLM 脚本审查，仅基础完整性"
                    f"（脚本实际单元: {_units_ok if _units_ok else '未解析到'}）", "info")
            return
        # ★ 部分覆盖提示：所选单元里只有部分被脚本覆盖（如选 4,8 脚本只有 8）
        _units_want2 = normalize_units(_u)
        _units_ok2 = set(getattr(agent, "script_units", set()))
        if _units_want2:
            _missing = sorted(u for u in _units_want2 if u not in _units_ok2)
            if _missing:
                # ★ 2026-08-26 精简提示：只说哪些单元没覆盖（去掉脚本名/细节）
                log_msg(f"ℹ {module}：单元 {_missing} 无覆盖脚本，仅做基础完整性检查", "info")
        # ★ 不传 screenshots：自动化过程只有答错截图，旧截图与本次题目对不上会误导 LLM 判定
        #   → 统一走 LLM 脚本审查（_review_script_llm：脚本信息 → LLM 六维判定，理由具体有说服力）
        results = agent.review(screenshots={})
        n_pass = sum(1 for rr in results if rr.overall_passed)
        # ★ 审查体系改造：边跑边审 → 单记录双层。
        #   脚本审查结果优先合并进同一条基础层记录（questions[auto-qid]["script"]）；
        #   未在 App 出现过的脚本题 → 保留独立脚本记录（layer=script_only）。
        _merged_cnt = 0
        _folded_fail = 0     # 脚本层把基础层"未审"判成"不通过"的题数
        _folded_pass = 0     # 脚本层补全后综合判定变成"通过"的题数
        for q, rr in zip(agent.script_questions, results):
            qid = f"{module}-脚本-Q{rr.idx:02d}"
            _state = _qreview_to_state(
                module, docx, unit, rr, stage=getattr(q, "stage", "") or "", q=q)
            _m = _match_basic_qid(module, q, rr, stage)
            if _m and _m in _inspection_state["questions"]:
                _basic = _inspection_state["questions"][_m]
                _basic["script"] = _state["script"]
                _basic["layer"] = "basic+script"
                _basic["note"] = (_basic.get("note") or "") + \
                    f"；脚本核验·{docx}" if _basic.get("note") else f"脚本核验·{docx}"
                # ★ 2026-09-20 修复：脚本层结论必须折算进六维与综合判定。
                #   旧代码只挂 `_basic["script"]` 子字典 → 脚本层判"不通过"的题
                #   在结果区/实时报告里依旧显示"未审"，等于检查白做（用户反馈
                #   "脚本问题日志里有、结果里没有"的根因就在这里）。
                _before = _basic.get("overall_passed")
                _fold_script_layer(_basic, _state.get("script") or {})
                if _basic.get("overall_passed") is False and _before is not False:
                    _folded_fail += 1
                if _basic.get("overall_passed") is True and _before is None:
                    _folded_pass += 1
                _merged_cnt += 1
            else:
                _inspection_state["questions"][qid] = _state
        # ★ 2026-09-20 新增（用户要求）：篇章语法检查——有错误才输出，没有就零输出。
        #   结果并入 `_script_issues[module]`（报告「脚本自检」区块 + 前端都能看到）。
        _passage_issues = _check_passage_grammar(module, _u, agent)
        if _passage_issues:
            _inspection_state.setdefault("_script_issues", {})\
                .setdefault(module, []).extend(_passage_issues)
            for _pi in _passage_issues:
                log_msg(f"❗[{_pi['severity']}] {_pi['type']} · {_pi['location']}：{_pi['issue']}",
                        "warning")
            log_msg(f"📝 {module} 篇章语法检查：发现 {len(_passage_issues)} 处错误",
                    "warning")
        _save_inspection_state_merge()
        # ★ 触发实时错题报告（前端「📑 查看报告」）
        try:
            _live_regen_error_report()
        except Exception:
            pass
        log_msg(f"✅ {module} LLM 知识性审查完成: {len(results)}题"
                f"（通过{n_pass}，未检维度不计入不通过，其中 {_merged_cnt} 题已合并进对应基础层记录）", "success")
        if _folded_fail or _folded_pass:
            # ★ 2026-09-20：把"脚本层折算"的结果显式打出来，检查人员才知道结果区
            #   里的不通过/通过有多少是脚本层判出来的（否则又是一次静默变更）
            log_msg(f"📐 {module} 脚本层结论已折算进六维：新增不通过 {_folded_fail} 题、"
                    f"补判通过 {_folded_pass} 题（基础层看界面、脚本层看脚本内容，互补）",
                    "info")
        # ★ 审查体系改造：审查完成后写入索引 + 缓存文件
        #   缓存同时包含：独立脚本记录 + 已合并进 auto-* 基础记录（含 script 层），
        #   供重跑同模块时复用脚本层结论（保留本轮 fresh 的 UI 证据）。
        try:
            _index = load_script_review_index()
            _index[_index_key] = {
                "script": docx, "script_hash": _docx_hash,
                # ★ 2026-09-23：记录产出本结论的模型签名，换模型即缓存失效
                "llm_signature": _current_llm_signature(),
                "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "questions": len(results),
                "status": "done",
            }
            save_script_review_index(_index)
            # 缓存审查结论到独立文件（后续复用可直接加载）
            _cache_dir = PROJECT_ROOT / "data" / "script_review_cache"
            _cache_dir.mkdir(parents=True, exist_ok=True)
            _cache_path = _cache_dir / f"{_index_key.replace('/','_').replace(' ','')}.json"
            _cache_payload = {}
            for q, rr in zip(agent.script_questions, results):
                _qid_s = f"{module}-脚本-Q{rr.idx:02d}"
                _m_s = _match_basic_qid(module, q, rr, stage)
                if _m_s and _m_s in _inspection_state["questions"]:
                    _cache_payload[_m_s] = _inspection_state["questions"][_m_s]
                elif _qid_s in _inspection_state["questions"]:
                    _cache_payload[_qid_s] = _inspection_state["questions"][_qid_s]
            # ★ 2026-09-20：篇章语法检查结果一并入缓存（模块级，非逐题）。
            #   复用加载循环会跳过非 dict 的值（`if not isinstance(_v, dict): continue`），
            #   所以这个 list 键不会混进题目记录。
            if _passage_issues:
                _cache_payload["_passage_issues"] = _passage_issues
            _cache_path.write_text(
                json.dumps(_cache_payload, ensure_ascii=False, indent=2),
                encoding="utf-8")
            # ★ 2026-09-20：写缓存成功才写明文件，便于下次复用（写失败必须可见）
            log_msg(f"💾 已缓存 {len(_cache_payload)} 题脚本层结论（{_index_key}）", "info")
        except Exception as _e:
            # ★ 2026-09-20：这里原本是 `pass` —— 缓存写失败被彻底吞掉，
            #   但索引（_index）已先写了 status=done → 下次运行时
            #   "索引说审查过、缓存文件不存在" → 复用分支加载不到内容又直接 return
            #   → 脚本层零结果且日志显示"复用结论"。失败必须可见。
            log_msg(f"⚠ 脚本层结论缓存写入失败（不影响本次结论，但下次无法复用）: {_e}",
                    "warning")
    except Exception as e:
        log_msg(f"❌ {module} LLM 知识性审查失败: {e}", "error")


@app.route("/api/modules/run", methods=["POST"])
def api_modules_run():
    """多模块检测：切换版本/年级后依次执行多个模块

    请求: {"version": "湘少版", "grade": "五年级上册", "modules": ["听力专项", "口语训练"],
           "units": {"听力专项": "1-3", "单元自检": "1-5"}}   # units 可选，指定各模块单元范围
    返回: {"status": "started", "modules": [...]}
    """
    global _MODULES_RUNNER
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    # ★ 设备预检（含重探分辨率 + 重算坐标缩放）放在**清状态之前**：
    #   注定失败的运行不该把上一轮的检测结果清掉。
    # ★ 2026-10-16：口径统一为 _intended_serial()（ANDROID_SERIAL → server_target.txt
    #   → config.yaml）。原来取 `env or ""`，env 为空时 u2.connect() 会随手连上当前
    #   在线的任意一台（实测：以为在控 MuMu，其实连的是真机），且缩放比仍是启动那一刻的旧值。
    #   ★ 2026-10-16 追加：目标先与**实际在线设备**对齐（resolve_target_serial）——
    #     配置目标离线（如 server_target.txt 残留 MuMu）时自动改用在线设备，并把最终
    #     目标写回 ANDROID_SERIAL，使 u2.connect() 与实际探测到的分辨率指向同一台设备。
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts"))
        from common.device import device_ok as _dev_ok, set_device as _set_dev
        _configured = _intended_serial()
        _cur_serial, _dev_pick = resolve_target_serial(_configured)
        # 已由 resolve_target_serial() 对齐过，这里禁止二次替代（allow_substitute=False）
        _scale_info = refresh_device_scale(_cur_serial, reason="多模块检测开始前",
                                           allow_substitute=False)
        if _dev_pick.get("substituted"):
            log_msg(f"⚠ 配置目标 {_configured or '(未指定)'} 不在线，已自动改用在线设备 "
                    f"{_cur_serial or '(未指定)'}", "warning")
        if _cur_serial:
            _set_dev(_cur_serial)      # u2.connect() 与实际操作目标保持一致
        if not _dev_ok(_cur_serial or None):
            _online = _dev_pick.get("online") or []
            log_msg(f"❌ 目标设备未就绪，无法开始检测（目标: {_cur_serial or '未指定'}；"
                    f"在线: {_online or '无'}）", "error")
            return jsonify({"error": (
                f"目标设备 {_cur_serial or '(未指定)'} 未就绪。当前在线设备: "
                f"{_online or '无'}。请在页面上切换到在线设备，或先启动目标模拟器/连接真机。"
            )}), 400
        log_msg(f"✅ 设备就绪: {_cur_serial or '(默认)'}"
                f"（分辨率 {_scale_info['resolution']}，"
                f"缩放 X{_scale_info['scale'][0]:.3f}/Y{_scale_info['scale'][1]:.3f}）", "success")
    except SystemExit:
        log_msg("⏹ 任务已被立即停止", "warning")
    except Exception as e:
        log_msg(f"❌ 设备检查失败: {e}", "error")
        return jsonify({"error": f"设备检查失败: {e}"}), 500

    # 清空审查结果区（避免上次任务的题目残留）
    # ★ 2026-08-25 修复：必须同步清空磁盘文件 data/inspection_state.json！
    #   旧逻辑只清内存 _inspection_state["questions"]，磁盘仍保留上次运行的题
    #   （如五年级口语训练20题+4不通过），而 /api/errors/summary 读的是磁盘 →
    #   用户跑"三年级未上线0题"却显示"不通过4/20"（日志0题/前端旧数据矛盾）。
    #   快速检查入口(1247行)就是先清内存再 _save_inspection_state() 写盘，此处对齐。
    _inspection_state["questions"] = {}
    _inspection_state["current_question_idx"] = 0
    _save_inspection_state()

    data = request.get_json() or {}
    version = (data.get("version") or "湘少版").strip()
    grade = (data.get("grade") or "五年级上册").strip()
    unit_from = int(data.get("unit_from") or 0)
    unit_to = int(data.get("unit_to") or 0)
    modules = data.get("modules") or []
    units = data.get("units") or {}  # 可选：{模块名: 单元范围}
    docx_map = data.get("docxMap") or data.get("docx_map") or {}  # 可选：{模块名: 上传脚本文件名}
    if not isinstance(docx_map, dict):
        docx_map = {}

    # ★ 兼容两种 modules 格式：
    #   旧: ["听力专项", "口语训练"]
    #   新: [{"name": "听力专项", "units": "1-5"}, {"name": "口语训练", "units": ""}]
    module_names = []
    for m in modules:
        if isinstance(m, dict):
            name = (m.get("name") or "").strip()
            m_units = (m.get("units") or "").strip()
            if name:
                module_names.append(name)
                if m_units:
                    units.setdefault(name, m_units)
        else:
            module_names.append(str(m).strip())
    module_names = [n for n in module_names if n]
    if not module_names:
        return jsonify({"error": "请至少选择一个模块"}), 400

    # ★ 重置停止标志（新任务开始，清除上次的停止请求）
    global _STOP_REQUESTED
    with _STOP_LOCK:
        _STOP_REQUESTED = False

    def _run():
        _register_task_thread()  # 记录线程 id，供"立即停止"注入异常
        try:
            set_running("多模块检测")
            # ★ 记录版本/单元到巡检状态（实时错题报告标题/路径需要）
            _inspection_state["version"] = version
            _inspection_state["grade"] = grade
            # ★ 环境变量同步（模块代码读 YYB_VERSION/YYB_GRADE 用于脚本命名等，
            #   避免 sys.modules 不可靠）
            os.environ["YYB_VERSION"] = str(version)
            os.environ["YYB_GRADE"] = str(grade)
            if units:
                _first_unit = str(next(iter(units.values()), "?"))
                _inspection_state["unit"] = _first_unit
            units_desc = f"（单元: {units}）" if units else ""
            log_msg(f"多模块检测启动: {version} {grade} → {'、'.join(module_names)}{units_desc}")
            # ★ 2026-09-10 LLM 体检：额度耗尽时流程不会报错、只会静默降级，
            #   所以开跑前明确告知"本次 AI 结论是否可信"，避免用户误判成"AI 瞎判"。
            try:
                _t_ok, _v_ok, _llm_detail = _llm_health_check()
                if _t_ok and _v_ok:
                    log_msg("✅ AI 核查可用（文本 + 视觉模型均正常）", "success")
                else:
                    _bad = []
                    if not _t_ok:
                        _bad.append("文本")
                    if not _v_ok:
                        _bad.append("视觉")
                    log_msg(
                        f"⚠ AI 核查不可用（{'/'.join(_bad)}模型调用失败）：{_llm_detail}"
                        f"本次将只做界面级检查，AI 相关结论不可信；"
                        f"请检查各供应商额度/密钥（DeepSeek 余额耗尽→402、"
                        f"通义千问免费额度用尽→403）后重新运行",
                        "warning",
                    )
            except Exception as _e:
                log_msg(f"⚠ LLM 体检异常（不影响自动化答题）: {str(_e)[:90]}", "warning")
            import importlib
            sys.path.insert(0, str(Path(__file__).parent / "scripts"))
            sched = importlib.import_module("scheduler")
            import uiautomator2 as u2
            # 线程内再次确认设备（防止入口检查后设备掉线）
            try:
                from common.device import device_ok as _dev_ok2
                if not _dev_ok2():
                    raise RuntimeError("设备已断开")
            except RuntimeError:
                raise
            except Exception:
                pass
            d = _connect_device()

            # ★ 逐模块分流：有匹配脚本 → 基础自动化 + 追加 LLM 知识性审查；
            #              无脚本 → 仅基础完整性检查
            # ★ 一次传全部模块给 run_all（内部统一循环）：只重启 App 一次，
            #   模块间 _back_to_home 切主页继续下一模块；LLM 审查经 on_module_done 回调
            global _GLOBAL_DOCX_MAP
            _GLOBAL_DOCX_MAP = docx_map or {}
            # ★ 2026-09-23：把"模块 → 脚本文件名"下传给模块内部（logger 全局）。
            #   口语训练图片题据此直接取脚本该小题的题面（句型提示），
            #   不再靠视觉模型猜图（省一次 LLM 调用，且避免把参考答案当题面）。
            try:
                from common.logger import set_module_scripts
                set_module_scripts(docx_map or {})
            except Exception:
                pass
            # ★ 2026-08-30 修复：合并同模块的脚本匹配日志为一条（练习+测试同模块只打一次），
            #   避免用户测听力专项·练习+·测试时看到 2 条相同"有匹配脚本"日志
            _logged_mod = set()
            def _on_module_done(_mod, _res):
                _docx = (docx_map or {}).get(_mod, "")
                _stage = (_res or {}).get("stage", "")
                if _mod in _logged_mod:
                    return  # 同模块只打一次（不再按 stage 重复）
                _logged_mod.add(_mod)
                if not _docx:
                    log_msg(f"🔍 {_mod} 无匹配脚本 → 仅基础完整性检查", "info")
                    return
                _stage_txt = f"（{_stage}）" if _stage else ""
                log_msg(f"📖 {_mod}{_stage_txt} 有匹配脚本「{_docx}」→ 自动化后追加 LLM 知识性审查", "info")
                # ★ 2026-09-20：先跑**确定性**脚本自检（题号连续/字段名统一/
                #   参考答案缺失/知识点占位/答案↔关键词一致），问题直接进日志。
                #   放在 LLM 审查之前：便宜、可复现、不截断，专治"有问题没查出来"。
                try:
                    _log_script_issues(_mod, _docx)
                except Exception:
                    pass
                # ★ 修复模块间卡顿：LLM 审查改异步线程，不阻塞 run_all 的模块循环
                #   （原同步调用：听力专项完成后在主页面卡几分钟等逐题 LLM 审查，
                #     审查完才继续口语训练 → 用户实测"主页卡好久"）
                # ★ unit 解析：听力专项·测试单元在 units["听力专项_测试"]；练习单元在 units["听力专项"]
                #   ★ 2026-08-25 修复：传完整单元范围（"2,4"/"2-4"），不再截断成第一个单元
                #     （用户选 U2、U4 时旧逻辑只审 U2，U4 被静默丢弃）
                #   ★ 防御："NONE"哨兵（前端未勾选）→ 不是数字，忽略
                _u = 0
                if _stage == "测试":
                    _u_raw = units.get("听力专项_测试", "") or units.get(_mod, "")
                else:
                    _u_raw = units.get(_mod, "") or 0
                try:
                    _u_str = str(_u_raw).strip()
                    if _u_str and _u_str.upper() != "NONE" and _u_str[0].isdigit():
                        _u = _u_str            # ★ 完整范围（"2,4" / "2-4"），归一化交给 review_agent
                    else:
                        _u = 0
                except Exception:
                    _u = 0
                try:
                    _t = threading.Thread(
                        target=_run_llm_script_review,
                        args=(_mod, _docx, version, _u, _stage),
                        daemon=True,
                    )
                    _t.start()
                except Exception as _e:
                    log_msg(f"❌ {_mod} LLM 知识性审查启动失败: {_e}", "error")

            results = sched.run_all(
                module_names, d, version=version, grade=grade,
                units=units, stop_check=_is_stop_requested,
                on_module_done=_on_module_done,
            ) or {}
            # 保存结果供前端查询
            global _LAST_MODULES_RESULT
            _LAST_MODULES_RESULT = {
                "done": True,
                "version": version,
                "grade": grade,
                "results": results,
            }
            # 逐模块汇总日志
            for name, r in results.items():
                status = "成功" if r.get("ok") else "失败"
                lv = "success" if r.get("ok") else "error"
                log_msg(f"  [{status}] {name}: {r['q']}题 {r['t']}s", lv)
            if _is_stop_requested():
                log_msg("⏹ 任务已被手动停止", "warning")
            else:
                log_msg(f"多模块检测完成: {len(results)} 个模块", "success")
        except SystemExit:
            # 前端"立即停止"注入的异常：记录并正常收尾
            log_msg("⏹ 任务已被立即停止", "warning")
            _LAST_MODULES_RESULT = {
                "done": True,
                "version": version,
                "grade": grade,
                "stopped": True,
                "error": "任务已被手动停止",
                "results": {},
            }
        except Exception as e:
            log_msg(f"多模块检测异常: {e}", "error")
            _LAST_MODULES_RESULT = {
                "done": True,
                "version": version,
                "grade": grade,
                "error": str(e),
                "results": {},
            }
        finally:
            # 清理停止标志，供下次任务使用
            global _STOP_REQUESTED
            with _STOP_LOCK:
                _STOP_REQUESTED = False
            set_done()

    # ★ 修复：新任务启动前清空上次结果，否则前端轮询 /api/modules/result 会
    #   立刻拿到旧任务的 done=true 结果（表现为"2秒全部完成+旧题数"假象），
    #   把当前真正在跑的任务结果盖掉。
    global _LAST_MODULES_RESULT
    _LAST_MODULES_RESULT = None

    _MODULES_RUNNER = threading.Thread(target=_run, daemon=True)
    _MODULES_RUNNER.start()
    return jsonify({"status": "started", "version": version, "grade": grade, "modules": module_names})


@app.route("/api/modules/result", methods=["GET"])
def api_modules_result():
    """获取最近一次多模块检测的汇总结果"""
    return jsonify(_LAST_MODULES_RESULT or {"done": False})


# ============================================================
# 题目解析脚本：遍历检测时自动生成（单元答完 → LLM 知识点 → 写 docx）
# 前端只「列出 + 下载」，不手动触发生成（避免 LLM 重复做无用功）
# ============================================================
@app.route("/api/script/list", methods=["GET"])
def api_script_list():
    """列出已生成的题目解析脚本（gen_scripts/ + outputs/reports/ 下的脚本 docx）"""
    files = []
    for _d in (PROJECT_ROOT / "gen_scripts", PROJECT_ROOT / "outputs" / "reports"):
        if _d.exists():
            for f in sorted(_d.glob("*.docx"), reverse=True):
                # 只收解析脚本（新规范名：日期+版本+年级+模块；旧名含"生成脚本"）
                if "生成脚本" not in f.name and not re.match(r"^\d{6}.{0,20}(单元自检|听力专项|口语训练|知识过关|巧记单词|语音评测)", f.name):
                    continue
                files.append({
                    "name": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "url": f"/api/export/download/{f.name}",
                })
    return jsonify({"success": True, "files": files})


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  英语宝模块检测 - Web 控制面板")
    print("=" * 50)
    print(f"  项目路径: {PROJECT_ROOT}")
    print(f"  启动: http://localhost:5000")
    print("=" * 50)
        # 自动检测屏幕分辨率并缩放坐标
    config = load_config()
    # ★ 2026-09-20 修复（缩放比取错设备）：
    #   config.device.serial 是「脚本里写死的目标机」，但真正连的可能是 ANDROID_SERIAL
    #   指定的另一台（如 MuMu 模拟器）。旧实现只按 config.device.serial 查 wm size，
    #   实测在 MuMu 上跑时日志打印 "检测到分辨率 1080x2400, 缩放比 X=1.000 Y=1.000"
    #   （那是真机的值），scale_all_coords() 退化成空操作 →
    #   首页卡片 / 广告关闭 AD_CLOSE / 版本年级栏 / MODULE_COORDS / TABS
    #   全部按真机 1080x2400 使用，在 900x1600 的模拟器上必然点偏。
    #   改为优先取「当前实际选中的设备」—— ANDROID_SERIAL 正是 u2.connect() 读的那个变量，
    #   这样缩放比与实际操作目标始终一致。
    _configured_serial = _intended_serial()
    # 不传 serial：目标来自配置解析，允许与在线设备对齐（allow_substitute 默认 True）
    _boot_info = refresh_device_scale(reason="服务启动")
    _selected_serial = _boot_info["serial"]
    if _boot_info.get("substituted"):
        # ★ 2026-10-16：配置目标离线时**自动改用在线设备**，并把原因打出来。
        #   典型场景：server_target.txt 残留上一轮的 MuMu（127.0.0.1:16384），
        #   而本次只插了真机 —— 旧行为会一直显示"目标=MuMu"，让人误以为控的是模拟器。
        print(f"  [设备选择] ⚠ 配置目标 {_configured_serial or '(未指定)'} 不在线 —— "
              f"已自动改用在线设备 {_selected_serial}（在线: {_boot_info['online']}）。")
        print(f"             如要固定为某台设备："
              f"`python tools/restart_server.py --device <串号>` 重启，"
              f"或在页面上切换设备。")
    if _detected_res is None:
        print(f"  [坐标缩放] ⚠ 目标设备 {_selected_serial or '(未指定)'} 当前不可达 —— "
              f"坐标暂按基准 {REFERENCE_RES[0]}x{REFERENCE_RES[1]} 使用"
              f"（当前在线设备: {_boot_info['online'] or '无'}）。"
              f"设备就绪后无需重启：在页面上切换一次设备、或直接开始任务"
              f"（任务开始前会自动重新探测并重算缩放）。")

    # ★ 常驻实时截图（前端「手机画面」随时可见，不再只在任务运行时才有）
    _start_live_screenshot_daemon()

    # ★ 2026-08-25：支持 PORT 环境变量（默认 5000；多实例验证/端口冲突时可换端口）
    _port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=_port, debug=False, threaded=True)
