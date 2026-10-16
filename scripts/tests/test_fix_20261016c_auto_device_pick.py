# -*- coding: utf-8 -*-
r"""★ 2026-10-16 回归测试：目标设备「智能对齐」（配置目标离线 → 自动改用在线设备）

━━━ 用户报告 ━━━
「我同学用部署的服务器链接操控 MuMu 上的英语宝，导航到切换书本版本就不动了……
  为什么启动 web_server 他给出的提示是这个目标（127.0.0.1:16384）？
  他不能智能检测我的设备是什么在连接吗？是不是你设置了默认就是这个设备，
  但是我现在使用数据线连接的手机进行测试。」

━━━ 根因 ━━━
_intended_serial() 只做**配置解析**：显式 → ANDROID_SERIAL → server_target.txt
→ config.yaml。它并不知道"这台设备现在到底连没连"。于是：
 ① server_target.txt 残留上一轮的目标（restart_server.py --device 127.0.0.1:16384
    落盘），优先级高于 config.yaml，把正确的真机串号 SKSCIF4T7PFMQS5X **压掉** →
    本次明明插着真机，日志却一直显示"目标=MuMu"；
 ② 目标离线时坐标按基准算，但操作者以为一切正常（无任何替换提示）。

━━━ 修法 ━━━
web_server.py 新增一层"智能对齐"：
  _is_real_device / _pick_online / _online_serials（3s TTL 缓存，只走 adb 不 import u2）
  / resolve_target_serial / _log_device_choice
规则：**只在配置目标不可达时才替代**（目标在线时绝不擅自切换，避免"操作者明明在看
MuMu 却被切到真机"）；替代结果同时透出到服务日志与 /api/status：
  device_serial / device_serial_configured / device_source / device_substituted /
  online_serials
调用点：refresh_device_scale（→ 预检 / 换设备 / 任务开始）、/api/modules/run、
/api/status、__main__ 启动块。

━━━ 本测试锁定 ━━━
  T1 _is_real_device：真机（无 host:port）True；MuMu（127.0.0.1:16384）False
  T2 _pick_online：混合列表优先真机；全模拟器取第一台
  T3 【正向】目标在线 → 原样使用，source=configured，substituted=False
  T4 【正向】目标离线 + 有在线设备 → 改为在线设备，source=auto，substituted=True，
        且 info['configured'] 仍保留原配置值（可解释）
  T5 【正向】目标离线 + 无任何在线设备 → 返回原目标，substituted=False
        （不假装成功，交由 _preflight_target_device 报错拒绝开始）
  T6 目标为空 + 有在线设备 → 自动选用（不打空串去连"默认设备"）
  T7 _online_serials：TTL 内二次调用不重复探测（缓存生效）；force=True 强制重探
  T8 refresh_device_scale 串联：info 含 configured/source/substituted/online，
        且 serial 是**替代后**的那台
  T9 _preflight_target_device：ok=False 时信息含目标串号与在线设备清单
  T10 【反向】目标在线时**不得**被替代（未注册为 fake 的串号不会被选中）
  T11 _log_device_choice：仅 substituted=True 时打印（静默路径不留噪音）
  T12 /api/status 源码必须透出四个可解释字段（防止后续被重构掉）

运行：python scripts/tests/test_fix_20261016c_auto_device_pick.py
"""
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PASS = 0
FAIL = []

MUMU = "127.0.0.1:16384"
PHONE = "SKSCIF4T7PFMQS5X"
PHONE2 = "ABCD1234EFGH"


def chk(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {extra}")


def cap(fn, *a, **kw):
    """执行 fn 并捕获 stdout（用于断言日志内容）。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rv = fn(*a, **kw)
    return rv, buf.getvalue()


# ══════════════════════════════════════════════════════════════
# 导入被测模块
# ══════════════════════════════════════════════════════════════
import common.device as cdev  # noqa: E402
import web_server as ws  # noqa: E402

_ORIG_LIST = cdev.list_devices


def _patch_online(serials):
    """把 adb 在线设备列表替换为指定串号（不碰真机、不碰运行中的服务）。"""
    cdev.list_devices = lambda: [{"serial": s, "state": "device"} for s in serials]
    ws._auto_dev_cache["t"] = 0.0        # 让下一次调用必定重新探测
    ws._auto_dev_cache["list"] = []


print("=" * 74)
print("T1 _is_real_device：真机无 host:port，模拟器/网络 adb 有")
print("=" * 74)
chk(f"真机 {PHONE} → True", ws._is_real_device(PHONE) is True)
chk(f"MuMu {MUMU} → False", ws._is_real_device(MUMU) is False)
chk("空串 → False（不是真机）", ws._is_real_device("") is False)
chk("' localhost:5555 ' 去空白后仍判非真机",
    ws._is_real_device(" localhost:5555 ") is False)

print()
print("=" * 74)
print("T2 _pick_online：优先真机")
print("=" * 74)
chk(f"混合 [{MUMU},{PHONE}] → 选真机 {PHONE}",
    ws._pick_online([MUMU, PHONE]) == PHONE)
chk("两台真机 → 取第一台", ws._pick_online([PHONE, PHONE2]) == PHONE)
chk("全模拟器 → 取第一台", ws._pick_online([MUMU, "127.0.0.1:7555"]) == MUMU)

print()
print("=" * 74)
print("T3 【正向】目标在线 → 原样使用，不擅自切换")
print("=" * 74)
_patch_online([PHONE])
_s, _i = ws.resolve_target_serial(PHONE)
chk(f"serial 保持 {PHONE}", _s == PHONE, _s)
chk("source == 'configured'", _i["source"] == "configured", _i["source"])
chk("substituted is False", _i["substituted"] is False)
chk("online 透出在线清单", _i["online"] == [PHONE], _i["online"])

print()
print("=" * 74)
print("T4 【正向】目标离线 + 有在线设备 → 自动改用在线设备")
print("=" * 74)
_patch_online([PHONE])                      # 只插了真机（MuMu 不在线）
_s, _i = ws.resolve_target_serial(MUMU)     # 配置目标却是 MuMu
chk(f"serial 改为 {PHONE}", _s == PHONE, _s)
chk("source == 'auto'", _i["source"] == "auto", _i["source"])
chk("substituted is True", _i["substituted"] is True)
chk(f"configured 仍保留原配置 {MUMU}", _i["configured"] == MUMU, _i["configured"])
chk("online 透出 ['SKSCIF...']", _i["online"] == [PHONE], _i["online"])

print()
print("=" * 74)
print("T5 【正向】目标离线 + 无在线设备 → 不假装成功，返回原目标")
print("=" * 74)
# ⚠ 这里必须直接打桩 _online_serials（而不是把 list_devices 置空）：_online_serials
#   在列表为空时会**退化调用真 adb devices**（adbutils 不可用时的兜底路径），
#   把 list_devices 置空仍会问出真机 → 断言失真。_online_serials 自身由 T7 覆盖。
_orig_online2 = ws._online_serials
ws._online_serials = lambda force=False: []
_s, _i = ws.resolve_target_serial(MUMU)
chk("serial 仍是原目标（交由预检报错）", _s == MUMU, _s)
chk("substituted is False", _i["substituted"] is False)
chk("online == []", _i["online"] == [], _i["online"])
ws._online_serials = _orig_online2

print()
print("=" * 74)
print("T6 目标为空 + 有在线设备 → 自动选用（不打空串去连'默认设备'）")
print("=" * 74)
_patch_online([PHONE])
_s, _i = ws.resolve_target_serial("")
chk(f"serial 取在线设备 {PHONE}", _s == PHONE, _s)
chk("source == 'auto'", _i["source"] == "auto", _i["source"])
chk("substituted is True", _i["substituted"] is True)

print()
print("=" * 74)
print("T7 _online_serials 缓存：TTL 内不重复探测 adb")
print("=" * 74)
_calls = {"n": 0}


def _counting_list():
    _calls["n"] += 1
    return [{"serial": PHONE, "state": "device"}]


cdev.list_devices = _counting_list
ws._auto_dev_cache["t"] = 0.0
ws._auto_dev_cache["list"] = []
_r1 = ws._online_serials(force=True)
_r2 = ws._online_serials()                 # 应命中缓存
chk(f"首次探测得到 {PHONE}", _r1 == [PHONE], _r1)
chk("TTL 内第二次调用未重复探测（adb 只被问 1 次）", _calls["n"] == 1, _calls["n"])
ws._online_serials(force=True)
chk("force=True 强制重探（累计 2 次）", _calls["n"] == 2, _calls["n"])

print()
print("=" * 74)
print("T8 refresh_device_scale 串联：info 可解释 + serial 是替代后的")
print("=" * 74)
_patch_online([PHONE])
ws._auto_dev_cache["list"] = [PHONE]
_orig_detect, _orig_scale = ws.detect_screen_resolution, ws.scale_all_coords
_orig_online = ws._online_serials
ws.detect_screen_resolution = lambda s="": (
    setattr(ws, "_detected_res", (1080, 2400)),
    setattr(ws, "_scale_x", 1.0), setattr(ws, "_scale_y", 1.0))
ws.scale_all_coords = lambda: None
ws._online_serials = lambda force=False: [PHONE]
# 不传 serial（= 目标来自配置解析）才允许替代；传了就代表调用方已明确选定。
_info, _out = cap(ws.refresh_device_scale, "", "单元测试")
chk(f"serial = 替代后的 {PHONE}", _info["serial"] == PHONE, _info["serial"])
chk(f"configured 保留配置里的 {MUMU}", _info["configured"] == MUMU, _info["configured"])
chk("source == 'auto'", _info["source"] == "auto", _info["source"])
chk("substituted is True", _info["substituted"] is True)
chk("ok is True（替代后成功探到分辨率）", _info["ok"] is True, _info)
chk("online 透出在线清单", _info["online"] == [PHONE], _info["online"])
chk("日志出现「不在线」提示", "不在线" in _out, repr(_out[-200:]))
chk("日志写明替代后的串号", PHONE in _out, repr(_out[-200:]))
ws.detect_screen_resolution, ws.scale_all_coords = _orig_detect, _orig_scale
ws._online_serials = _orig_online

print()
print("=" * 74)
print("T9 _preflight_target_device：失败信息可操作（含目标串号 + 在线清单）")
print("=" * 74)
_orig_refresh = ws.refresh_device_scale
ws.refresh_device_scale = lambda serial="", reason="": {
    "serial": MUMU, "configured": MUMU, "source": "configured",
    "substituted": False, "online": [], "resolution": None,
    "scale": [1.0, 1.0], "ok": False, "before": (None, 1.0, 1.0), "reason": reason}
_ok, _msg = ws._preflight_target_device()
chk("ok is False", _ok is False)
chk("信息含目标串号", MUMU in _msg, _msg)
chk("信息含「在线设备」字段", "在线设备" in _msg, _msg)
chk("信息含处置动作（切换/启动）", "切换" in _msg or "启动" in _msg, _msg)
ws.refresh_device_scale = _orig_refresh

print()
print("=" * 74)
print("T10 【反向】目标在线时绝不被替代（防止误切到别的设备）")
print("=" * 74)
_patch_online([MUMU, PHONE])                  # 两台都在线
_s, _i = ws.resolve_target_serial(MUMU)       # 操作者明确要 MuMu
chk(f"serial 仍是 {MUMU}（未因'真机优先'被切走）", _s == MUMU, _s)
chk("substituted is False", _i["substituted"] is False)
_s2, _i2 = ws.resolve_target_serial(PHONE)    # 明确要真机
chk(f"serial 仍是 {PHONE}", _s2 == PHONE, _s2)

print()
print("=" * 74)
print("T11 _log_device_choice：只在替代时打印（未替代不留噪音）")
print("=" * 74)
_ret, _out2 = cap(ws._log_device_choice,
                  {"substituted": False, "configured": PHONE, "serial": PHONE,
                   "online": [PHONE]}, "x")
chk("未替代 → 无输出", _out2.strip() == "", repr(_out2))
_ret, _out3 = cap(ws._log_device_choice,
                  {"substituted": True, "configured": MUMU, "serial": PHONE,
                   "online": [PHONE]}, "服务启动")
chk("已替代 → 打印", MUMU in _out3 and PHONE in _out3, repr(_out3))

print()
print("=" * 74)
print("T12 /api/status 必须透出四个可解释字段（防重构丢失）")
print("=" * 74)
_src = io.open(os.path.join(ROOT, "web_server.py"), encoding="utf-8").read()
for _f in ("device_serial_configured", "device_source",
           "device_substituted", "online_serials"):
    chk(f"/api/status 含 {_f}", f'"{_f}"' in _src)
chk("/api/status 走 resolve_target_serial()",
    "cur_serial, _dev_info = resolve_target_serial()" in _src)
chk("多模块 run 会把最终目标写回 ANDROID_SERIAL", "_set_dev(_cur_serial)" in _src)
_ism = io.open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8").read()
chk("前端展示「自动选用」", "自动选用" in _ism)
chk("前端展示 device_substituted", "device_substituted" in _ism)

# 还原环境，避免影响同进程后续用例
cdev.list_devices = _ORIG_LIST

print()
print("=" * 74)
print("T13 allow_substitute：**显式**指定设备不得被替代（否则 u2 连的与缩放算的错位）")
print("=" * 74)
_orig_d2, _orig_s2, _orig_o3 = (ws.detect_screen_resolution, ws.scale_all_coords,
                                ws._online_serials)
ws.detect_screen_resolution = lambda s="": (
    setattr(ws, "_detected_res", None), setattr(ws, "_scale_x", 1.0),
    setattr(ws, "_scale_y", 1.0))
ws.scale_all_coords = lambda: None
ws._online_serials = lambda force=False: [PHONE]      # 真机在线
_i, _o = cap(ws.refresh_device_scale, MUMU, "显式指定离线设备")
chk("显式传 serial → 不替代（仍是 MuMu）", _i["serial"] == MUMU, _i["serial"])
chk("source == 'explicit'", _i["source"] == "explicit", _i["source"])
chk("substituted is False", _i["substituted"] is False)
chk("ok is False（如实告知不可达）", _i["ok"] is False, _i)
chk("未打印『自动替代』噪音", "自动替代" not in _o, repr(_o[-160:]))
_i2, _o2 = cap(ws.refresh_device_scale, "", "未传 serial（走配置解析）")
chk(f"不传 serial → 允许替代为 {PHONE}", _i2["serial"] == PHONE, _i2["serial"])
chk("source == 'auto'", _i2["source"] == "auto", _i2["source"])
_i3, _o3 = cap(ws.refresh_device_scale, MUMU, "run 路径已 resolve 过",
               allow_substitute=False)
chk("allow_substitute=False 显式禁止 → 不替代", _i3["serial"] == MUMU, _i3["serial"])
ws.detect_screen_resolution, ws.scale_all_coords = _orig_d2, _orig_s2
ws._online_serials = _orig_o3

print()
print("=" * 74)
print("T14 _preflight_target_device：info 缺 online 时回退 _device_list()（兼容兜底）")
print("=" * 74)
_orig_refresh3, _orig_dl = ws.refresh_device_scale, ws._device_list
try:
    ws.refresh_device_scale = lambda serial="", reason="", allow_substitute=None: {
        "serial": MUMU, "configured": MUMU, "source": "explicit",
        "substituted": False, "resolution": None, "scale": [1.0, 1.0],
        "ok": False, "before": (None, 1.0, 1.0), "reason": reason}   # 无 online 字段
    ws._device_list = lambda: [{"serial": PHONE, "state": "device"}]
    _ok2, _msg2 = ws._preflight_target_device()
    chk("ok is False", _ok2 is False)
    chk("回退查到在线设备并写进报错信息", PHONE in _msg2, _msg2)
    chk("信息含「当前在线设备」", "当前在线设备" in _msg2, _msg2)
finally:
    ws.refresh_device_scale, ws._device_list = _orig_refresh3, _orig_dl

print()
print("=" * 74)
print("T15 预检通过时会把最终目标写回 ANDROID_SERIAL（多设备在线不报 more than one）")
print("=" * 74)
chk("_preflight_target_device 内含 set_device 兜底",
    "_set_dev_pre(info[\"serial\"])" in _src)

print()
print("=" * 74)
print(f"结果: {PASS} 通过 / {len(FAIL)} 失败")
if FAIL:
    for _n in FAIL:
        print(f"  - {_n}")
print("=" * 74)
sys.exit(1 if FAIL else 0)
