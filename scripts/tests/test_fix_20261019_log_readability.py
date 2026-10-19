r"""★ 2026-10-19 回归测试：日志「说人话」+ 三态结算（不再拿 0 题冒充成功）

背景（试用反馈原文）：
  「设备没有的时候，日志不是给技术人员看的，而是要面向测试我们这个 app 的用户，
    你报这个错误，别人哪里看得懂；另外，如果没有测试就提示没有提示，你说检测完了 5 个，
    累计零题不是误导测试这个 app 的人吗，日志内容要看得懂并且每一步都不拐弯抹角。」

三类缺陷，本测试逐一锁定：
  ① 前端日志里出现调用栈 / 源码路径 / 异常类名 / HTTP 码 / 供应商名 → 测试员看不懂
     （现场：`device 'SKSCIF…' not found [ ' File "C:\…\adbutils\_adb.py", line 192…`）
  ② 跑完但 0 题被算作「成功」→ 出现「全部完成！5 个模块，5 个成功，累计 0 题」
  ③ 失败之后仍打「完成，返回主页」→ 与上一步自相矛盾

━━━ 本测试锁定 ━━━
  T1  human_error 异常分类（掉线/多设备/控件找不到/超时/连接中断/兜底）
  T2  【反向】用户可见文案（说明+怎么办）不含任何技术串
  T3  human_units 不再打印 dict repr
  T4  status_of 三态（0 题 → empty，不是 ok）
  T5  summary_text 的口径（0 题不许出现"成功/全部完成"）
  T6  run_all 失败：日志是人话 +「怎么办」，结果 status=failed，调用栈不进日志
  T7  run_all 0 题：status=empty，日志不出现「检测完成：0 题」
  T8  log_msg 单点兜底：混入调用栈 → 自动截断，原文进服务端日志
  T9  源码级：scheduler 不再把 traceback 拼进 step_log
  T10 前端：三态渲染 + 同一轮结果只渲染一次（不再刷屏「全部完成！」）

运行：python scripts/tests/test_fix_20261019_log_readability.py
"""
import contextlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PASS = 0
FAIL = []


def chk(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {extra}")


def cap(fn, *a, **k):
    """捕获 stdout（print 的技术细节不应污染断言用的日志通道）"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# ══════════════════════════════════════════════════════════════
# ① common/user_msg.py：异常 → 人话
# ══════════════════════════════════════════════════════════════
import common.user_msg as um  # noqa: E402


class AdbError(Exception):
    pass


print("=" * 74)
print("T1 human_error 异常分类（现场报错必须落到『掉线』这一类）")
print("=" * 74)

_hl, _act, _tech = um.human_error(
    AdbError("device 'SKSCIF4T7PFMQS5X' not found"))
chk("现场报错 → 说明是设备掉线", "掉线" in _hl, _hl)
chk("给出动作（数据线/模拟器 + 重跑）",
    ("数据线" in _act or "模拟器" in _act) and "重跑" in _act, _act)
chk("技术细节保留异常原文（供服务端日志）", "not found" in _tech, _tech)

_hl2, _a2, _ = um.human_error(RuntimeError("more than one device/emulator"))
chk("多设备 → 说明不知道该操作哪台", "不止一台" in _hl2, _hl2)
chk("多设备 → 动作是只留一台", "只保留一台" in _a2, _a2)

_hl3, _a3, _ = um.human_error(
    RuntimeError("UiObjectNotFoundError: 找不到节点 text=我"))
chk("控件找不到 → 说明 App 不在预期页面", "预期的页面" in _hl3, _hl3)
chk("控件找不到 → 动作是看屏幕/回首页", "屏幕" in _a3 or "首页" in _a3, _a3)

_hl4, _, _ = um.human_error(TimeoutError("Read timed out"))
chk("超时 → 说明等待 App 响应超时", "超时" in _hl4, _hl4)

_hl5, _, _ = um.human_error(ConnectionError("Connection reset by peer"))
chk("连接中断 → 说明连接断了", "连接" in _hl5, _hl5)

_hl6, _a6, _ = um.human_error(ValueError("some weird internal thing"))
chk("兜底 → 不把原始英文丢给测试员", "some weird internal thing" not in _hl6, _hl6)
chk("兜底 → 告诉人去找谁、带什么日志",
    "维护人员" in _a6 and "server_output.log" in _a6, _a6)

print()
print("=" * 74)
print("T2 【反向】用户可见文案不含技术串（这就是被投诉的那一类字符串）")
print("=" * 74)

_TECH_TOKENS = [
    "Traceback", "File \"", "site-packages", "line 192", "AdbError",
    "UiObjectNotFoundError", "HTTP Error", "404", "402", "403",
    "deepseek", "qwen", "api_key", "Exception", "NoneType", "Errno",
]

_samples = [
    AdbError("device 'SKSCIF4T7PFMQS5X' not found"),
    RuntimeError("more than one device/emulator"),
    RuntimeError("UiObjectNotFoundError: 找不到节点"),
    TimeoutError("Read timed out"),
    ConnectionError("Connection reset by peer"),
    ValueError("'NoneType' object has no attribute 'x'"),
]
_bad = []
for _e in _samples:
    _h, _a, _ = um.human_error(_e)
    for _tok in _TECH_TOKENS:
        if _tok in _h or _tok in _a:
            _bad.append(f"{type(_e).__name__} → {_tok}")
chk("6 类异常的『说明+怎么办』均无技术串", not _bad, str(_bad))

print()
print("=" * 74)
print("T3 human_units 不再打印 dict repr")
print("=" * 74)

_t = um.human_units({"听力专项": None, "听力专项_测试": None})
chk("全 None → 『单元：全部单元』", _t == "单元：全部单元", _t)
chk("【反向】不含花括号/引号（dict repr 特征）",
    "{" not in _t and "'" not in _t, _t)

_t2 = um.human_units({"听力专项": "2,4", "单元自检": "3-5"})
chk("枚举 → U2、U4", "听力专项 U2、U4" in _t2, _t2)
chk("区间 → U3–U5", "单元自检 U3–U5" in _t2, _t2)

_t3 = um.human_units({"听力专项": "NONE"})
chk("NONE 哨兵 → 视为全部单元", _t3 == "单元：全部单元", _t3)

print()
print("=" * 74)
print("T4 status_of 三态：0 题不是成功")
print("=" * 74)

chk("q>0 + ok → ok", um.status_of({"q": 3, "ok": True}) == "ok")
chk("q=0 + ok → empty（关键：不再是成功）",
    um.status_of({"q": 0, "ok": True}) == "empty")
chk("ok=False → failed", um.status_of({"ok": False}) == "failed")
chk("显式 status 优先于推导",
    um.status_of({"q": 0, "ok": True, "status": "failed"}) == "failed")
chk("空 dict → failed（没跑就别算成功）", um.status_of({}) == "failed")

print()
print("=" * 74)
print("T5 summary_text 口径（0 题不许出现『成功』『全部完成』）")
print("=" * 74)

_zero = {n: {"q": 0, "t": 30, "ok": True, "status": "empty"}
         for n in ["听力专项", "口语训练", "单元自检", "知识过关", "语音评测"]}
_s = um.summary_text(_zero)
chk("全 0 题 → 明写『没有一道题被检测到』", "没有一道题被检测到" in _s, _s)
chk("全 0 题 → 含『0 题』", "0 题" in _s, _s)
chk("【反向】全 0 题不提『成功』", "成功" not in _s, _s)
chk("【反向】全 0 题不提『全部完成』", "全部完成" not in _s, _s)
chk("全 0 题 → 给出核对提示", "核对" in _s, _s)

_mix = {
    "听力专项": {"q": 12, "t": 90, "ok": True, "status": "ok"},
    "单元自检": {"q": 0, "t": 20, "ok": True, "status": "empty"},
    "知识过关": {"q": 0, "t": 3, "ok": False, "status": "failed",
                 "error": "手机掉线了"},
}
_s2 = um.summary_text(_mix)
chk("混合 → 三个口径都出现", all(k in _s2 for k in ("检测完成", "没有题目", "中途失败")), _s2)
chk("混合 → 累计题数正确", "12" in _s2, _s2)

print()
print("=" * 74)
print("T6 run_all 失败分支：人话 + 怎么办，调用栈不进前端日志")
print("=" * 74)

import scheduler as sch  # noqa: E402
import common.setup as setup_mod  # noqa: E402


class _FakeDev:
    """最小设备桩：只满足 run_all 的前置探活与重启流程"""

    @property
    def info(self):
        return {"screenOn": True}

    def app_stop(self, *a):
        pass

    def app_start(self, *a):
        pass

    def screen_on(self):
        pass


_logs = []
_orig = {
    "step_log": sch.step_log,
    "switch": sch._switch_if_needed,
    "settle": sch.settle_ads,
    "back": sch._back_to_home,
    "screen": sch._ensure_screen_on,
    "wait": sch._wait_home_ready,
    "import_module": sch.importlib.import_module,
}
sch.step_log = lambda msg, level="info": _logs.append((level, msg))
sch._switch_if_needed = lambda d, v, g: True
sch.settle_ads = lambda *a, **k: None
sch._back_to_home = lambda d: None
sch._ensure_screen_on = lambda d: None
sch._wait_home_ready = lambda d, timeout=25: True


class _Boom:
    @staticmethod
    def run_module(d, units=None):
        raise AdbError(
            "device 'SKSCIF4T7PFMQS5X' not found [ ' File \"C:\\\\Python312"
            "\\\\Lib\\\\site-packages\\\\adbutils\\\\_adb.py\", line 192, in check_okay' ]")


class _Zero:
    @staticmethod
    def run_module(d, units=None):
        return 0


def _patch_import(mod, alias):
    def _f(name, *a, **k):
        if name == alias:
            return mod
        return _orig["import_module"](name, *a, **k)
    sch.importlib.import_module = _f


try:
    sch.MODULE_MAP["__BOOM__"] = "__BOOM__"
    _patch_import(_Boom, "__BOOM__")
    _logs.clear()
    _res, _out = cap(sch.run_all, ["__BOOM__"], d=_FakeDev(),
                     version="湘教班", grade="五年级上册", units={})
    _r = _res.get("__BOOM__", {})
    _text = "\n".join(m for _, m in _logs)

    chk("结果 status=failed", _r.get("status") == "failed", str(_r))
    chk("ok=False（旧字段仍准确）", _r.get("ok") is False, str(_r))
    chk("说明是人话（设备掉线）", "掉线" in str(_r.get("error", "")), str(_r))
    chk("带『怎么办』字段", bool(_r.get("error_action")), str(_r))

    chk("日志出现『没有测成』", "没有测成" in _text, _text[-300:])
    chk("日志出现『怎么办』", "怎么办" in _text, _text[-300:])
    chk("【反向】日志里没有调用栈 File \"C:\\…\"",
        'File "' not in _text, _text[-300:])
    chk("【反向】日志里没有 adbutils 路径", "site-packages" not in _text, _text[-300:])
    chk("【反向】失败后不再打『完成』",
        "完成" not in _text.replace("没有测成", ""), _text[-300:])
    chk("调用栈被 print 到服务端日志（不丢信息）",
        "AdbError" in _out and "check_okay" in _out, _out[-200:])
finally:
    sch.MODULE_MAP.pop("__BOOM__", None)

print()
print("=" * 74)
print("T7 run_all 0 题：status=empty，日志不说『检测完成』")
print("=" * 74)
try:
    sch.MODULE_MAP["__ZERO__"] = "__ZERO__"
    _patch_import(_Zero, "__ZERO__")
    _logs.clear()
    _res2, _ = cap(sch.run_all, ["__ZERO__"], d=_FakeDev(),
                   version="湘教班", grade="四年级上册", units={})
    _r2 = _res2.get("__ZERO__", {})
    _text2 = "\n".join(m for _, m in _logs)
    chk("0 题 → status=empty（不算检测完成）", _r2.get("status") == "empty", str(_r2))
    chk("日志写明『没有题目可测』", "没有题目可测" in _text2, _text2[-300:])
    chk("【反向】不出现『检测完成：0 题』",
        "检测完成：0 题" not in _text2, _text2[-300:])
finally:
    sch.MODULE_MAP.pop("__ZERO__", None)
    sch.step_log = _orig["step_log"]
    sch._switch_if_needed = _orig["switch"]
    sch.settle_ads = _orig["settle"]
    sch._back_to_home = _orig["back"]
    sch._ensure_screen_on = _orig["screen"]
    sch._wait_home_ready = _orig["wait"]
    sch.importlib.import_module = _orig["import_module"]

print()
print("=" * 74)
print("T8 log_msg 单点兜底：任何混入调用栈的日志都被截断成人话")
print("=" * 74)

import web_server as ws  # noqa: E402

_evil = (
    "单元自检 检测失败: device 'SKSCIF4T7PFMQS5X' not found [ ' File "
    "\"C:\\\\Python312\\\\Lib\\\\site-packages\\\\adbutils\\\\_adb.py\", line 192, in check_okay' ]"
)
cap(ws.log_msg, _evil, "error")
_last = ws.task_status["log"][-1]["msg"]
chk("【反向】前端日志里没有源码路径", 'File "' not in _last, _last)
chk("【反向】前端日志里没有 site-packages", "site-packages" not in _last, _last)
chk("保留可读的主干", "检测失败" in _last, _last)
chk("补一句『详细技术信息已写入服务端日志』",
    "服务端日志" in _last, _last)

print()
print("=" * 74)
print("T9 源码级：scheduler 不再把 traceback 拼进前端日志")
print("=" * 74)
_src = io.open(os.path.join(ROOT, "scripts", "scheduler.py"), encoding="utf-8").read()
chk("【反向】不再截取 traceback 行拼进 step_log",
    "splitlines()[-3:]" not in _src, "仍存在 traceback 拼接")
chk("调用栈改为 print_exc 落服务端日志", "_tb.print_exc()" in _src)

print()
print("=" * 74)
print("T10 前端：三态渲染 + 同轮结果只渲染一次")
print("=" * 74)
_html = io.open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8").read()
chk("【反向】不再出现『全部完成！』这种误导文案", "全部完成！" not in _html)
chk("有 _modStatus 三态判定", "_modStatus" in _html)
chk("有『没有题目，未检测』文案", "没有题目，未检测" in _html)
chk("有『中途失败，没有测成』文案", "中途失败，没有测成" in _html)
chk("有 run 去重标记（防刷屏）", "_serveRenderedRun" in _html)
chk("0 题时汇总明写『没有任何内容被检测』", "没有任何内容被检测" in _html)
chk("有 empty 态样式", ".serve-card.empty" in _html)

# ══════════════════════════════════════════════════════════════
# 结果
# ══════════════════════════════════════════════════════════════
print()
print("=" * 74)
print(f"结果: {PASS} 项通过, {len(FAIL)} 项失败")
if FAIL:
    for _n in FAIL:
        print(f"  - {_n}")
    sys.exit(1)
print("全部通过 ✓")
