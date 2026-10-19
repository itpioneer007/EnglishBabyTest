"""★ 2026-10-08 回归测试：设备瞬断自愈 + 版本年级预检不再静默失败。

━━━ 背景（一次真实的失败复跑）━━━
用户要求跑「口语训练 · 湘少版(2024审定) · 四年级下册 · U1、U3」。结果：
    21:25:05 🔄 重启 App
    21:25:10 🔧 切换版本/年级: 湘少版(2024审定) 四年级下册
              ✘ 无法回到主页，切换中止          ← 切换其实失败了
    21:25:36 ▶ 开始检测 口语训练（单元: 1,3）
              🎯 口语训练 Unit 1
    21:26:52 ❌ 口语训练 检测失败: Remote end closed connection without response
    21:27:52 ✅ 全部检测完成！1 个模块, 0 个成功, 累计 0 题
两个独立缺陷叠加，且【都在日志里看不出来】。

━━━ 缺陷 1：设备瞬断裸抛，库自带的自愈不触发 ━━━
uiautomator2 3.7.0 core.py 里 AdbHTTPConnection 继承 http.client.HTTPConnection，
但 socket 来自 adbutils（不是 requests）。底层抛的是 http.client 家族异常：
    RemoteDisconnected → ConnectionResetError → ConnectionError → OSError
                      → BadStatusLine → HTTPException → Exception
实测 issubclass(RemoteDisconnected, requests.RequestException) is False。
而 _http_request() 的 except 只兜 requests.Timeout / requests.RequestException
→ 异常裸逃逸；jsonrpc_call() 的自愈分支只捕获
(HTTPError, UiAutomationNotConnectedError) → 不触发 stop/start + 重试。
→ 一个瞬断掀翻整个模块。

修法（common/u2_resilience.py）：把 http.client/ConnectionError 家族映射成库自己的
HTTPError —— 补全库本就想做、只是漏做的映射，从而激活既有自愈路径。

━━━ 缺陷 2：版本/年级切换失败被静默吞掉 ━━━
scheduler._switch_if_needed 旧实现只处理 `ok is True`，且文案恒为"无需切换"
（切成功了也这么说）；`ok is False` 完全没有分支 → 整轮跑在上一个年级上，
结论全部作废却毫无提示。叠加"重启 App 后固定 sleep(3) 就切换"（冷启动 +
开屏广告普遍 >3s）→ _is_home() 为假 → back 反而把启动中的 App 顶到桌面。

本测试锁定：
  A 异常映射补全：四类底层异常 → HTTPError；且【普通异常不被吞】（反向用例）
  B 映射后自愈真的跑起来：stop → start → 重试成功；非守护异常仍原样上抛（反向用例）
  C 预检语义：空参数 no-op / 成功 / 失败重试一次 / 始终失败则返回 False 并报 error
  D 反向用例：切换失败【绝不能】只打 info、更不能静默
  E 主页就绪轮询：就绪即返回 / 超时返回 False / _is_home 抛异常不崩
  F run_all 在预检失败时提前拦停，不驱动设备、不产出"0 题假成功"

运行：python scripts/tests/test_fix_20261008_scheduler_preflight_and_u2_resilience.py
"""
import http.client
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PASS = 0
FAIL = 0


def chk(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [XX] {name}   {detail}")


import uiautomator2 as u2                      # noqa: E402
from uiautomator2 import core as u2core        # noqa: E402
from uiautomator2.exceptions import HTTPError as U2HTTPError   # noqa: E402
from common import u2_resilience               # noqa: E402  （导入即 install）
import common.setup as setup_mod               # noqa: E402
import scheduler as sch                        # noqa: E402


# ══════════════════════════════════════════════════════════════
# A/B  异常映射补全 + 自愈链路
# ══════════════════════════════════════════════════════════════
print("\n[A] uiautomator2 异常映射补全")
chk("补丁已安装（core._http_request 带 _yyb_patched 标记）",
    getattr(u2core._http_request, "_yyb_patched", False) is True)
chk("install() 幂等（重复调用返回 False）", u2_resilience.install() is False)


def _map_of(exc):
    """在隔离环境里重建补丁，喂入 exc，返回实际抛出的异常类型。"""
    saved = u2core._http_request

    def _boom(*a, **k):
        raise exc

    u2core._http_request = _boom
    u2_resilience._INSTALLED = False
    u2_resilience.install()
    try:
        u2core._http_request(None, 1, "GET", "/x")
        return None
    except BaseException as e:      # noqa: BLE001
        return e
    finally:
        u2core._http_request = saved
        u2_resilience._INSTALLED = False
        u2_resilience.install()


for _exc, _label in (
    (http.client.RemoteDisconnected("Remote end closed connection without response"),
     "RemoteDisconnected（本次事故的直接原因）"),
    (ConnectionResetError("reset by peer"), "ConnectionResetError"),
    (http.client.BadStatusLine(""), "BadStatusLine"),
    (TimeoutError("timed out"), "TimeoutError"),
):
    _got = _map_of(_exc)
    chk(f"{_label} → HTTPError", isinstance(_got, U2HTTPError),
        f"实际={type(_got).__name__ if _got else '未抛出'}")

# ★ 反向用例：补丁不得过度兜底 —— 业务异常必须原样上抛，
#   否则真 bug 会被伪装成"设备问题"而被自愈重试掩盖。
_ve = _map_of(ValueError("这不是传输层错误"))
chk("反向：ValueError 不被吞（仍原样上抛）",
    isinstance(_ve, ValueError) and not isinstance(_ve, U2HTTPError),
    f"实际={type(_ve).__name__ if _ve else '未抛出'}")

print("\n[B] 映射后 jsonrpc_call 的自愈真的跑起来")
_calls = []
_orig_jsonrpc = u2core._jsonrpc_call
_seq = {"n": 0}


def _fake_jsonrpc(*a, **k):
    _seq["n"] += 1
    if _seq["n"] == 1:
        raise U2HTTPError("HTTP request failed: RemoteDisconnected")
    return "REAL_OK"


u2core._jsonrpc_call = _fake_jsonrpc
srv = object.__new__(u2core.BasicUiautomatorServer)
srv._dev = None
srv._device_server_port = 7912
srv._debug = False
srv.stop_uiautomator = lambda: _calls.append("stop")
srv.start_uiautomator = lambda: _calls.append("start")
try:
    _res = srv.jsonrpc_call("dumpWindowHierarchy")
    chk("瞬断后自愈成功（返回重试结果）", _res == "REAL_OK", f"实际={_res!r}")
    chk("自愈动作顺序 = stop → start", _calls == ["stop", "start"], f"实际={_calls}")
except Exception as e:      # noqa: BLE001
    chk("瞬断后自愈成功（返回重试结果）", False, f"抛异常 {type(e).__name__}: {e}")
    chk("自愈动作顺序 = stop → start", False, f"实际={_calls}")

# ★ 反向用例：非守护异常不该触发"重启设备服务"（那是设备层的手段）
_calls.clear()
_seq["n"] = 0


def _fake_jsonrpc_val(*a, **k):
    _seq["n"] += 1
    raise ValueError("业务错误")


u2core._jsonrpc_call = _fake_jsonrpc_val
try:
    srv.jsonrpc_call("x")
    chk("反向：非守护异常原样上抛（不误触发设备重启）", False, "未抛出")
except ValueError:
    chk("反向：非守护异常原样上抛（不误触发设备重启）", _calls == [], f"实际动作={_calls}")
except Exception as e:      # noqa: BLE001
    chk("反向：非守护异常原样上抛（不误触发设备重启）", False, f"实际抛 {type(e).__name__}")
finally:
    u2core._jsonrpc_call = _orig_jsonrpc


# ══════════════════════════════════════════════════════════════
# C/D  版本年级预检：不再静默失败
# ══════════════════════════════════════════════════════════════
print("\n[C] _switch_if_needed 的返回值与日志语义")

_logs = []
_orig_step_log = sch.step_log
sch.step_log = lambda msg, level="info": _logs.append((level, msg))
_orig_switch = sch.switch_version_grade
_orig_back = sch._back_to_home
sch._back_to_home = lambda d: None          # 测试里不碰设备


def _run_switch(results, version="湘少版(2024审定)", grade="四年级下册"):
    """results: 依次返回的 switch_version_grade 结果列表。"""
    _logs.clear()
    it = iter(results)
    calls = {"n": 0}

    def _fake(d, v, g, skip_if_ok=True):
        calls["n"] += 1
        try:
            return next(it)
        except StopIteration:
            return results[-1]

    sch.switch_version_grade = _fake
    rv = sch._switch_if_needed(None, version, grade)
    return rv, calls["n"]


# C1 空参数 → no-op（不该调用切换）
sch.switch_version_grade = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该被调用"))
rv = sch._switch_if_needed(None, "", "")
chk("C1 空版本/年级 → 直接返回 True 且不调用切换", rv is True)

# C2 一次即成功
rv, n = _run_switch([True])
chk("C2 一次成功 → True，只调用一次", rv is True and n == 1, f"rv={rv} n={n}")
chk("C2 文案不再谎称『无需切换』",
    any("已确认" in m for _l, m in _logs) and not any("无需切换" in m for _l, m in _logs),
    f"logs={_logs}")

# C3 第一次失败、第二次成功 → 应重试
rv, n = _run_switch([False, True])
chk("C3 失败后重试一次并成功 → True，调用 2 次", rv is True and n == 2, f"rv={rv} n={n}")
chk("C3 重试前给出 warning", any(l == "warning" for l, _m in _logs), f"logs={_logs}")

# C4 始终失败 → False + error（★ 反向用例：绝不能静默/只能用 info 打发）
rv, n = _run_switch([False, False])
chk("C4 始终失败 → False", rv is False, f"rv={rv}")
chk("C4 失败必须报 error 级别（不被静默吞掉）",
    any(l == "error" for l, _m in _logs), f"logs={_logs}")
chk("C4 报错文案点明结果不可用/已中止",
    any(("中止" in m or "不可用" in m) for _l, m in _logs), f"logs={_logs}")

# C5 异常也不能静默（旧实现只 print，前端看不到）
def _raise(*a, **k):
    raise RuntimeError("切换过程抛异常")


sch.switch_version_grade = _raise
_logs.clear()
rv = sch._switch_if_needed(None, "湘少版(2024审定)", "四年级下册")
chk("C5 切换抛异常 → 仍返回 False 且报 error", rv is False and any(l == "error" for l, _m in _logs),
    f"rv={rv} logs={_logs}")

sch.switch_version_grade = _orig_switch
sch._back_to_home = _orig_back


# ══════════════════════════════════════════════════════════════
# E  主页就绪轮询
# ══════════════════════════════════════════════════════════════
print("\n[E] _wait_home_ready")
_orig_is_home = getattr(setup_mod, "_is_home", None)

setup_mod._is_home = lambda d: True
chk("E1 主页立即可用 → True", sch._wait_home_ready(None, timeout=2) is True)

setup_mod._is_home = lambda d: False
chk("E2 始终不是主页 → 超时返回 False", sch._wait_home_ready(None, timeout=1) is False)


def _is_home_raises(d):
    raise RuntimeError("dump 失败")


setup_mod._is_home = _is_home_raises
chk("E3 反向：_is_home 抛异常不崩溃，按超时处理",
    sch._wait_home_ready(None, timeout=1) is False)

if _orig_is_home is not None:
    setup_mod._is_home = _orig_is_home


# ══════════════════════════════════════════════════════════════
# F  run_all 在预检失败时提前拦停
# ══════════════════════════════════════════════════════════════
print("\n[F] run_all 预检失败 → 拦停（不再产出 0 题假成功）")


class _FakeDev:
    def __init__(self):
        self.calls = []

    @property
    def info(self):
        return {"screenOn": True}

    def app_stop(self, *a):
        self.calls.append("app_stop")

    def app_start(self, *a):
        self.calls.append("app_start")

    def screen_on(self):
        self.calls.append("screen_on")

    def window_size(self):
        return (900, 1600)

    def dump_hierarchy(self):
        self.calls.append("dump_hierarchy")
        return "<hierarchy/>"


_dev = _FakeDev()
_logs.clear()
sch.step_log = lambda msg, level="info": _logs.append((level, msg))
setup_mod._is_home = lambda d: True
sch._switch_if_needed = lambda d, v, g: False       # 强制预检失败
_orig_run_module = None
try:
    res = sch.run_all(["口语训练"], d=_dev,
                      version="湘少版(2024审定)", grade="四年级下册", units={})
    chk("F1 返回结构包含全部模块且 ok=False",
        isinstance(res, dict) and set(res) == {"口语训练"}
        and res["口语训练"]["ok"] is False,
        f"实际={res}")
    _err = str(res["口语训练"].get("error", ""))
    chk("F2 拦停原因写明『版本/年级切换失败』",
        "切换" in _err and ("失败" in _err or "没有切换成功" in _err),
        f"实际={res}")
    chk("F3 未进入模块执行（没有 dump_hierarchy 等设备操作）",
        "dump_hierarchy" not in _dev.calls, f"实际={_dev.calls}")
    chk("F4 拦停前确实重启过 App（顺序正确）",
        _dev.calls[:2] == ["app_stop", "app_start"], f"实际={_dev.calls}")
finally:
    sch.step_log = _orig_step_log
    if _orig_is_home is not None:
        setup_mod._is_home = _orig_is_home

# ★ 反向用例：预检成功时必须继续进入模块（否则就是"修成了永远不跑"）
import types as _types      # noqa: E402
_il = sch.importlib         # scheduler 顶层 `import importlib`，此处即全局模块对象
_real_import = _il.import_module
_fake_mod = _types.SimpleNamespace(run_module=lambda d, units=None: 3)
_orig_back2 = sch._back_to_home
_orig_is_home2 = getattr(setup_mod, "_is_home", None)
sch._back_to_home = lambda d: None          # 不碰真设备
setup_mod._is_home = lambda d: True         # 主页就绪立即通过（否则白等 25s 超时）
_dev2 = _FakeDev()
_logs.clear()
sch._switch_if_needed = lambda d, v, g: True
try:
    sch.MODULE_MAP["__测试模块__"] = "__测试模块__"

    def _fake_import(name, *a, **k):
        if name == "__测试模块__":
            return _fake_mod
        return _real_import(name, *a, **k)

    _il.import_module = _fake_import
    res2 = sch.run_all(["__测试模块__"], d=_dev2,
                       version="湘少版(2024审定)", grade="四年级下册", units={})
    ok_mod = res2.get("__测试模块__", {}).get("ok") is True and res2["__测试模块__"]["q"] == 3
    chk("F5 反向：预检成功 → 正常进入模块并记数", ok_mod, f"实际={res2}")
finally:
    sch.MODULE_MAP.pop("__测试模块__", None)
    _il.import_module = _real_import
    sch._back_to_home = _orig_back2
    if _orig_is_home2 is not None:
        setup_mod._is_home = _orig_is_home2


# ══════════════════════════════════════════════════════════════
print()
print("=" * 70)
print(f"结果：PASS {PASS} / FAIL {FAIL}")
if FAIL:
    print("  注：FAIL 项见上方 [XX] 行")
print("=" * 70)
sys.exit(1 if FAIL else 0)
