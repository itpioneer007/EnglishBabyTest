"""环境自检与能力探测（跨设备差异的唯一解释入口）

为什么需要这一层
----------------
同一份代码在不同设备/不同电脑上跑出不同结论，绝大多数不是"代码随机"，而是
**运行条件不同却被当成同一条件**：

  1. 屏幕尺寸/dp 不同 → Android 布局是"重排"而不是等比拉伸，
     任何按像素比例换算的坐标都只能近似（真机 1080x2400@480dpi 恰为基准才精确）；
  2. 模拟器没有真实音频输入/性能低 → 录音类题（语音评测、口语训练）表现完全不同；
  3. App 版本不同 → 首页卡片、resource-id、题页结构都可能变；
  4. 参考图库/脚本/知识库路径是本机绝对路径 → 别人机器上直接缺失，
     于是"视觉配图核对""脚本比对"这些维度静默降级，报告却照样写着"检测完成"；
  5. LLM 密钥额度/模型漂移 → 有 AI 审查和没有 AI 审查，结论天差地别。

本模块只做一件事：**在开跑之前把这些条件摸清楚，并把"能力边界"显式说出来**。
它不修业务逻辑，也不调 LLM；只用 adb，毫秒级，可在预检里反复调用。

对外接口
--------
    run_check(serial="")   → 结构化结果（blockers / warnings / capabilities / device / local）
    format_lines(result)   → 给使用者看的若干行文字（第三人称陈述 + 请…建议）
    summary(result)        → 一句话摘要（前端状态条用）
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

# scripts/common/env_check.py → scripts/common → scripts → 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

APP_PACKAGE = "com.dinoenglish.yyb"
REFERENCE_RES = (1080, 2400)     # 坐标基准分辨率（历史口径，勿改）
REFERENCE_DPI = 480              # 基准 dpi → dp = 360 x 800
REFERENCE_DP = (360, 800)

# 判定"布局是否与基准一致"的容差（dp）。超过即说明是该设备重排过的布局。
_DP_TOL = 24

_SIG_FILE = PROJECT_ROOT / "data" / "env_last.json"


# ============================================================
# adb 基础
# ============================================================

def _find_adb() -> str:
    """定位 adb（与 src/adb_controller.ADBController._find_adb 同序，但不 import 它，
    避免 scripts/common 反向依赖 src 造成的路径问题）。"""
    p = shutil_which("adb")
    if p:
        return p
    try:
        from adbutils import adb as _adb_mod
        p = str(_adb_mod.path())
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    try:
        import uiautomator2 as _u2
        p = os.path.join(os.path.dirname(os.path.dirname(_u2.__file__)),
                         "adbutils", "binaries", "adb.exe")
        if os.path.exists(p):
            return p
    except Exception:
        pass
    try:
        _wg = os.path.join(os.path.expanduser("~"),
                           "AppData", "Local", "Microsoft", "WinGet", "Packages")
        if os.path.isdir(_wg):
            for _e in os.listdir(_wg):
                if _e.startswith("Google.PlatformTools"):
                    p = os.path.join(_wg, _e, "platform-tools", "adb.exe")
                    if os.path.exists(p):
                        return p
    except Exception:
        pass
    for _env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        _sdk = os.environ.get(_env, "")
        if _sdk:
            p = os.path.join(_sdk, "platform-tools", "adb.exe")
            if os.path.exists(p):
                return p
    return ""


def shutil_which(name):
    try:
        import shutil
        return shutil.which(name) or ""
    except Exception:
        return ""


def _run(adb: str, serial: str, args, timeout=6) -> tuple:
    """执行一条 adb 命令，返回 (returncode, stdout)。异常一律折成 (-1, "")。"""
    import subprocess
    cmd = [adb]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "")
    except Exception:
        return -1, ""


def _online_serials(adb: str) -> list:
    """当前在线（state=device）设备串号。"""
    rc, out = _run(adb, "", ["devices"], timeout=6)
    if rc != 0:
        return []
    res = []
    for ln in (out or "").splitlines()[1:]:
        parts = ln.split()
        if len(parts) >= 2 and parts[1] == "device" and parts[0]:
            res.append(parts[0])
    return res


# ============================================================
# 设备探测
# ============================================================

def _is_emulator(serial: str, props: str) -> bool:
    """模拟器判定。

    判据（命中任一即算）：
      1. 串号形如 host:port（MuMu / 雷电 / 网络 adb）；
      2. `ro.kernel.qemu` = 1（AOSP 类模拟器）；
      3. `ro.build.characteristics` 含 emulator；
      4. 型号/厂商含 sdk、emulator、mumu、nemu、generic。
    注意：MuMu 的串号是 127.0.0.1:16384，第 1 条即可命中。
    """
    if ":" in (serial or ""):
        return True
    low = (props or "").lower()
    if "ro.kernel.qemu=1" in low:
        return True
    if "emulator" in low:
        return True
    for kw in ("mumu", "nemu", "generic_x86", "sdk_gphone"):
        if kw in low:
            return True
    return False


def device_snapshot(serial: str = "") -> dict:
    """探测一台设备的硬件/系统/App 状态。不可达时 reachable=False 并给 blockers。"""
    d = {
        "serial": serial or "",
        "adb": "",
        "online": [],
        "reachable": False,
        "model": "", "brand": "", "android": "",
        "emulator": None,
        "size": None, "density": None, "dp": None,
        "layout_matches_reference": None,
        "app_installed": None, "app_version": "",
        "screen_on": None,
        "record_capable": None,
    }
    blockers, warnings = [], []

    adb = _find_adb()
    d["adb"] = adb
    if not adb:
        blockers.append("未找到 adb 可执行文件。App 自动化需要 Android platform-tools。"
                        "请安装 platform-tools 并加入 PATH，或安装 adbutils 后重试。")
        return {"device": d, "blockers": blockers, "warnings": warnings}

    online = _online_serials(adb)
    d["online"] = online
    if not serial:
        # 未指定 → 取真机优先
        real = [s for s in online if ":" not in s]
        serial = (real or online or [""])[0]
        d["serial"] = serial
    if not serial:
        blockers.append("当前没有已连接的设备。请用数据线连接手机并开启 USB 调试，"
                        "或先启动模拟器；待设备出现在设备列表中后重新开始检测。")
        return {"device": d, "blockers": blockers, "warnings": warnings}
    if serial not in online:
        blockers.append(f"目标设备 {serial} 不在线（adb 未识别）。请重新插拔数据线、"
                        f"在手机上确认「允许 USB 调试」，或改为选择在线设备。")
        return {"device": d, "blockers": blockers, "warnings": warnings}

    d["reachable"] = True

    # ---- 系统属性（一次取多条，省往返）----
    rc, props = _run(adb, serial, ["shell", "getprop"], timeout=8)
    props = props or ""

    def _prop(key):
        m = re.search(r"\[%s\]:\s*\[([^\]]*)\]" % re.escape(key), props)
        return m.group(1).strip() if m else ""

    d["model"] = _prop("ro.product.model") or _prop("ro.product.name")
    d["brand"] = _prop("ro.product.brand")
    d["android"] = _prop("ro.build.version.release")
    d["emulator"] = _is_emulator(serial, props)

    # ---- 屏幕：物理分辨率 + dpi → dp ----
    rc, out = _run(adb, serial, ["shell", "wm", "size"], timeout=5)
    m = re.search(r"(\d+)x(\d+)", out or "")
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        d["size"] = [w, h]
        rc2, out2 = _run(adb, serial, ["shell", "wm", "density"], timeout=5)
        m2 = re.search(r"(\d+)", out2 or "")
        dpi = int(m2.group(1)) if m2 else REFERENCE_DPI
        d["density"] = dpi
        if dpi > 0:
            dp_w, dp_h = round(w * 160 / dpi), round(h * 160 / dpi)
            d["dp"] = [dp_w, dp_h]
            d["layout_matches_reference"] = (
                abs(dp_w - REFERENCE_DP[0]) <= _DP_TOL
                and abs(dp_h - REFERENCE_DP[1]) <= _DP_TOL
            )
    else:
        blockers.append(f"无法读取设备 {serial} 的屏幕分辨率，设备可能已被占用或响应异常。"
                        f"请确认设备屏幕已点亮、未停留在锁屏，然后重新开始检测。")

    # ---- 亮屏状态 ----
    rc, out = _run(adb, serial, ["shell", "dumpsys", "power"], timeout=5)
    if rc == 0 and out:
        mm = re.search(r"mWakefulness=(\w+)", out)
        if mm:
            d["screen_on"] = (mm.group(1).lower() == "awake")

    # ---- App 是否安装 + 版本 ----
    rc, out = _run(adb, serial,
                   ["shell", "dumpsys", "package", APP_PACKAGE], timeout=10)
    if rc == 0 and out and "versionName" in out:
        d["app_installed"] = True
        mv = re.search(r"versionName=([^\s]+)", out)
        d["app_version"] = mv.group(1) if mv else ""
    elif rc == 0:
        d["app_installed"] = False
        blockers.append(f"设备 {serial} 上未安装「英语宝」（{APP_PACKAGE}）。"
                        f"请先安装被测版本的 App，再重新开始检测。")
    else:
        d["app_installed"] = None
        warnings.append("未能确认 App 是否已安装（设备响应超时）。若稍后出现「找不到入口」，"
                        "请先手动打开一次英语宝确认可正常进入。")

    # ---- 录音能力（麦克风 / 录音权限）----
    #   Android 的 microphone feature 在部分模拟器上也会声明，所以这里只作为
    #   "有/无/未知" 三态，不做绝对断言；模拟器额外给出提示，不阻断。
    rc, feats = _run(adb, serial, ["shell", "pm", "list", "features"], timeout=6)
    has_mic = bool(rc == 0 and "android.hardware.microphone" in (feats or ""))
    if rc != 0:
        d["record_capable"] = None
    elif has_mic:
        d["record_capable"] = True
    else:
        d["record_capable"] = False

    if d["emulator"]:
        warnings.append("当前为模拟器设备。模拟器与真机的布局、渲染和音频输入都存在差异："
                        "坐标类操作会优先改用页面元素定位；录音类题（语音评测、口语训练）"
                        "需要模拟器已开启麦克风输入，请先在模拟器设置中确认。")
        if d["record_capable"] is not True:
            warnings.append("模拟器未声明麦克风能力，录音类题可能无法完成。"
                            "请在模拟器设置中开启麦克风，或将录音类题留到真机上验证。")
    elif d["record_capable"] is False:
        warnings.append("该设备未声明麦克风能力，录音类题（语音评测、口语训练）无法完成。"
                        "请改用带麦克风的真机，或在模块列表中取消这两项。")

    # ---- 布局差异（"结果不一样"的最常见硬件原因）----
    if d["layout_matches_reference"] is False:
        warnings.append(
            f"该设备逻辑尺寸为 {d['dp'][0]}x{d['dp'][1]}dp，与坐标基准 360x800dp 不同，"
            f"Android 会重排首页布局而不是等比缩放。页面元素定位不受影响，"
            f"但少量仍按比例换算的坐标只能近似，可能点偏。"
            f"若本设备上出现「点了没反应/进入错误页面」，请优先怀疑这一项。")

    return {"device": d, "blockers": blockers, "warnings": warnings}


# ============================================================
# 本机环境探测
# ============================================================

def _load_image_dirs() -> list:
    """读参考图库目录：config.yaml 的 image_dir + .env 的 YYB_IMAGE_DIR（追加）。

    相对路径按**项目根**解析，不依赖启动时的工作目录 —— 否则从别的目录启动服务
    （比如双击 .bat）时相对路径会指向错误位置，视觉配图核对会静默失效。
    """
    out = []
    try:
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        v = (cfg.get("image_dir") or [])
        if isinstance(v, str):
            v = [v]
        out.extend(str(x) for x in v if str(x).strip())
    except Exception:
        pass
    extra = (_env_file().get("YYB_IMAGE_DIR") or "").strip()
    if extra:
        out.extend(x.strip() for x in re.split(r"[;|]", extra) if x.strip())
    res = []
    for p in out:
        pp = Path(p)
        if not pp.is_absolute():
            pp = PROJECT_ROOT / pp
        res.append(str(pp))
    return res


def _env_file() -> dict:
    out = {}
    try:
        for ln in (PROJECT_ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def local_snapshot() -> dict:
    """探测本机（跑脚本这台电脑）的依赖、目录、参考图库、LLM 配置。"""
    res = {
        "root": str(PROJECT_ROOT),
        "root_writable": False,
        "dirs": {},
        "ref_images": {"configured": [], "existing": []},
        "deps": {},
        "llm": {},
    }
    blockers, warnings = [], []

    # 目录可写（截图/报告/状态都要落盘）
    for name in ("outputs", "data", "uploads", "screenshots"):
        p = PROJECT_ROOT / name
        try:
            p.mkdir(exist_ok=True)
            probe = p / ".__w"
            probe.write_text("1", encoding="utf-8")
            probe.unlink()
            res["dirs"][name] = True
        except Exception:
            res["dirs"][name] = False
    res["root_writable"] = all(res["dirs"].values())
    _bad = [k for k, v in res["dirs"].items() if not v]
    if _bad:
        blockers.append(f"项目目录不可写：{('、'.join(_bad))}。"
                        f"截图与报告无法保存。请检查目录权限，或把项目移到有写权限的位置。")

    # 参考图库（视觉配图核对依赖它）
    dirs = _load_image_dirs()
    res["ref_images"]["configured"] = dirs
    exists = [x for x in dirs if os.path.isdir(x)]
    res["ref_images"]["existing"] = exists
    if dirs and not exists:
        warnings.append("参考图库路径不存在（config.yaml 的 image_dir 可能仍指向原作者电脑）。"
                        "本轮将跳过「配图/图片内容核对」，该维度会记为未判定。"
                        "请把参考图放到本机可访问的目录后修改 image_dir。")
    elif not dirs:
        warnings.append("未配置参考图库（config.yaml 的 image_dir 为空）。"
                        "本轮将跳过「配图/图片内容核对」，该维度会记为未判定。")

    # 关键依赖
    for mod in ("uiautomator2", "adbutils", "flask", "docx", "PIL", "yaml"):
        try:
            __import__(mod)
            res["deps"][mod] = True
        except Exception:
            res["deps"][mod] = False
    _miss = [k for k, v in res["deps"].items() if not v]
    if _miss:
        blockers.append(f"缺少运行依赖：{('、'.join(_miss))}。请在本机执行 "
                        f"pip install -r requirements.txt 后重新启动服务。")

    # LLM 配置（AI 六维核查依赖它；缺失时只能做基础层结论）
    env = _env_file()
    llm_cfg = {}
    try:
        llm_cfg = json.loads((PROJECT_ROOT / "llm_config.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    res["llm"] = {
        "text_key": bool(env.get("LLM_API_KEY")),
        "text_model": env.get("LLM_MODEL") or llm_cfg.get("model", ""),
        "vision_key": bool(env.get("VISION_API_KEY")),
        "vision_model": env.get("VISION_MODEL") or llm_cfg.get("vision_model", ""),
        "daily_budget": env.get("LLM_DAILY_BUDGET_YUAN", ""),
    }
    if not res["llm"]["text_key"]:
        warnings.append("未配置大模型密钥（.env 的 LLM_API_KEY）。"
                        "本轮只能给出基础层结论，AI 六维核查与知识点检查将全部记为未判定。")
    if not res["llm"]["vision_key"]:
        warnings.append("未配置视觉模型密钥（.env 的 VISION_API_KEY）。"
                        "本轮将跳过图片题内容核对与配图判断。")

    # 账号（共享账号会互相顶登录、共享学习进度 → 题目状态不同）
    try:
        import yaml
        _cfg = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        _acc = (_cfg.get("account") or {})
        res["account"] = {
            "username": env.get("YYB_USERNAME") or _acc.get("username") or "",
        }
    except Exception:
        res["account"] = {"username": env.get("YYB_USERNAME", "")}

    return {"local": res, "blockers": blockers, "warnings": warnings}


# ============================================================
# 汇总
# ============================================================

def _capabilities(dev: dict, loc: dict) -> dict:
    """把探测结果翻译成"本轮能做哪些维度"的开关。"""
    llm = loc.get("llm", {})
    return {
        # 参考图库存在且至少一个目录可读 → 才能做"配图/图片内容核对"
        "vision_ref": bool(loc.get("ref_images", {}).get("existing")),
        "llm_text": bool(llm.get("text_key")),
        "llm_vision": bool(llm.get("vision_key")),
        # True / False / None(未知)
        "record": dev.get("record_capable"),
        "emulator": dev.get("emulator"),
        "layout_matches_reference": dev.get("layout_matches_reference"),
    }


def _signature(dev: dict, loc: dict) -> str:
    """设备+App 的指纹：用来判断"这次和上次是不是同一环境"。"""
    parts = [
        str(dev.get("brand") or ""), str(dev.get("model") or ""),
        str(dev.get("android") or ""),
        "x".join(str(x) for x in (dev.get("size") or [])),
        str(dev.get("density") or ""),
        str(dev.get("app_version") or ""),
        "emu" if dev.get("emulator") else "real",
        str(loc.get("llm", {}).get("text_model") or ""),
        str(loc.get("llm", {}).get("vision_model") or ""),
    ]
    return "|".join(parts)


def _diff_previous(sig: str) -> dict:
    """与上一次运行的环境指纹比较；返回 {changed, previous}。

    用途：同一份脚本在 A 手机上跑出 12 题、B 手机上跑出 3 题时，
    报告里必须能一眼看到"环境变了"，否则只能怀疑是代码随机。
    """
    prev = {}
    try:
        prev = json.loads(_SIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    changed = bool(prev.get("signature")) and prev.get("signature") != sig
    try:
        _SIG_FILE.parent.mkdir(exist_ok=True)
        _SIG_FILE.write_text(json.dumps(
            {"signature": sig, "time": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return {"changed": changed, "previous": prev.get("signature", "") if prev else ""}


def run_check(serial: str = "", remember: bool = True) -> dict:
    """跑完整自检。返回：

        {
          "ok": bool,                  # 无阻断项即可开跑
          "device": {...}, "local": {...},
          "capabilities": {...},
          "blockers": [...], "warnings": [...],
          "signature": str, "env_changed": bool, "previous_signature": str,
          "time": "YYYY-mm-dd HH:MM:SS",
        }
    """
    ds = device_snapshot(serial)
    ls = local_snapshot()
    dev, loc = ds["device"], ls["local"]
    blockers = list(ds["blockers"]) + list(ls["blockers"])
    warnings = list(ds["warnings"]) + list(ls["warnings"])

    sig = _signature(dev, loc)
    diff = _diff_previous(sig) if remember else {"changed": False, "previous": ""}
    if diff["changed"]:
        warnings.append(
            "本次运行的设备或 App 与上一次不同（可能是换了手机、换了模拟器，"
            "或 App 升级）。两次的题目数量与结论不具备直接可比性，"
            "请以本轮报告为准，不要与上一轮逐条对照。")

    # 共享账号提醒：多人用同一个灰度账号时，App 会同步同一份学习进度 ——
    # 已做过的单元会变成"继续答题"，题目状态与"从第 1 题开始"不同；
    # 两端同时登录还会互相顶掉。这类差异既不是代码问题，也不是设备问题，
    # 但会直接改变"测到几题、哪些题"。
    try:
        _u = (loc.get("account") or {}).get("username") or ""
        if _u:
            warnings.append(
                f"当前使用固定账号 {_u}。多人/多设备共用同一账号时，App 会共享同一份"
                f"学习进度（已做过的单元会显示「继续答题」），并且两端同时登录会互相顶掉。"
                f"若两人同时检测出现「首页被退回登录页」「题目数量对不上」，请先排除这一项："
                f"改为每人一个账号，或错开时间使用。")
    except Exception:
        pass

    return {
        "ok": not blockers,
        "device": dev,
        "local": loc,
        "capabilities": _capabilities(dev, loc),
        "blockers": blockers,
        "warnings": warnings,
        "signature": sig,
        "env_changed": diff["changed"],
        "previous_signature": diff["previous"],
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ============================================================
# 面向使用者的文字
# ============================================================

_CAP_LABEL = {
    "vision_ref": "配图内容核对",
    "llm_text": "文字类 AI 核查",
    "llm_vision": "图片题视觉核对",
}


def capability_lines(caps: dict) -> list:
    """把能力开关翻成两行文字（能做什么 / 不能做什么）。"""
    on, off = [], []
    for k, label in _CAP_LABEL.items():
        (on if caps.get(k) else off).append(label)
    if caps.get("record") is True:
        on.append("录音类题")
    elif caps.get("record") is False:
        off.append("录音类题")
    else:
        off.append("录音类题（设备能力未知）")
    lines = []
    if on:
        lines.append("本轮可做：" + "、".join(on) + "。")
    if off:
        lines.append("本轮不做：" + "、".join(off) + "（对应维度记为未判定，不计为不通过）。")
    return lines


def format_lines(result: dict) -> list:
    """给前端日志用的若干行：先讲阻断，再讲降级，最后讲环境。"""
    lines = []
    dev = result.get("device") or {}
    for b in result.get("blockers") or []:
        lines.append("检测未开始：" + b)
    if result.get("blockers"):
        return lines

    head = []
    if dev.get("model"):
        head.append(f"{dev.get('brand') or ''} {dev.get('model')}".strip())
    if dev.get("size"):
        head.append(f"{dev['size'][0]}x{dev['size'][1]}")
    if dev.get("density"):
        head.append(f"{dev['density']}dpi")
    if dev.get("app_version"):
        head.append(f"App {dev['app_version']}")
    if dev.get("emulator"):
        head.append("模拟器")
    if head:
        lines.append("检测环境：" + "，".join(head) + "。")

    for w in result.get("warnings") or []:
        lines.append("能力边界：" + w)
    lines.extend("能力边界：" + x for x in capability_lines(result.get("capabilities") or {}))
    return lines


def summary(result: dict) -> str:
    """一句话摘要（前端状态条用）。"""
    if not result.get("ok"):
        n = len(result.get("blockers") or [])
        return f"环境检查未通过（{n} 项阻断）"
    dev = result.get("device") or {}
    bits = []
    if dev.get("model"):
        bits.append(str(dev["model"]))
    if dev.get("app_version"):
        bits.append("App " + str(dev["app_version"]))
    if dev.get("emulator"):
        bits.append("模拟器")
    if dev.get("layout_matches_reference") is False:
        bits.append("布局与基准不同")
    n_w = len(result.get("warnings") or [])
    tail = f"；{n_w} 项环境提示" if n_w else ""
    return ("，".join(bits) or "环境正常") + tail


def write_step_log(result: dict, step_log=None) -> None:
    """把自检结果写进前端日志（有 step_log 时）。"""
    if step_log is None:
        try:
            from common.logger import step_log as _sl
            step_log = _sl
        except Exception:
            return
    for ln in format_lines(result):
        level = "error" if ln.startswith("检测未开始") else (
            "warning" if ln.startswith("能力边界") else "info")
        try:
            step_log(ln, level)
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    r = run_check(sys.argv[1] if len(sys.argv) > 1 else "", remember=False)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print()
    for ln in format_lines(r):
        print(" ", ln)
