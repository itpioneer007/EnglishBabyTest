r"""★ 2026-10-19 第二轮回归：模块层 / 主流程日志文案治理

背景（用户原话）：
  「好，那就把别的文件存在的日志信息输出问题解决或者优化一下」

上一轮只治了 scheduler 的结算文案与 web_server 的兜底，模块内部（单元自检 /
口语训练 / 听力专项 / 巧记单词 / 知识过关 / 语音评测 / engine / scheduler）
仍是给开发者看的：emoji 图标、控件坐标 `@(540,1200)`、`dump` / `rid` /
`record_layout` 这类内部字段名、`（KeyError: 'x'）` 这种异常 repr、
以及「0 题也打 XXX完成 + success」。

━━━ 本测试锁定 ━━━
  T1  clean_step_text：去 emoji / 去坐标 / 去括号异常 / 去缩进，且不误伤题干
  T2  clean_log_text：再清掉行尾裸异常、`at (x, y)`、`(conf=0.87)`
  T3  module_log：0 题不说「检测完成」，级别降为 warning
  T4  logger.step_log 出口统一清洗（模块自己没改也漏不出去）
  T5  logger.module_done：0 题不打 success
  T6  源码级【反向】：modules / engine / scheduler 的 step_log 文案无 emoji、
      无坐标、无内部字段名
  T7  源码级【反向】：不再有「共{q}题」+ success 这种 0 题冒充完成的写法
  T8  web_server._DIM_INVOKED_KW：新文案能触发脚本审查，0 题不触发，旧文案兼容
  T9  web_server.log_msg 接了 clean_log_text（不是只有 step_log 干净）

运行：python scripts/tests/test_fix_20261019b_module_log_text.py
"""
import ast
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
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


from common import user_msg as um           # noqa: E402
from common import logger as lg             # noqa: E402

# ══════════════════════════════════════════════════════════════
print("=" * 74)
print("T1 clean_step_text：机器痕迹出不去，题干信息不受伤")
print("=" * 74)

_cases = [
    ("📊 单元自检完成，共3题", "单元自检完成，共3题"),
    ("✅ 已进入 Unit 2 关卡地图", "已进入 Unit 2 关卡地图"),
    ("⚠ 第2大题等待录音按钮超时", "第2大题等待录音按钮超时"),
    ("❌ 入口缺失", "入口缺失"),
    ("🎯 选中 Unit 3 @(540,1200)", "选中 Unit 3"),
    ("  第4题 完整性检查", "第4题 完整性检查"),
    ("🖼 图片排序：直接点图片", "图片排序：直接点图片"),
    ("打开失败（KeyError: 'title'）", "打开失败"),
]
for src, want in _cases:
    got = um.clean_step_text(src)
    chk(f"{src!r} → {want!r}", got == want, f"实得 {got!r}")

# 反向：题干里的正常括号 / 英文 / 数字不能被吃掉
_keep = "第 3 题：选择 B（共 2 个选项），题干为 «My name is Tom.»"
chk("【反向】正常括号与英文原样保留", um.clean_step_text(_keep) == _keep,
    um.clean_step_text(_keep))
chk("【反向】纯中文句子不被改动",
    um.clean_step_text("检测到排序题，开始处理") == "检测到排序题，开始处理")
chk("None / 空串安全", um.clean_step_text(None) == "" and um.clean_step_text("") == "")

print()
print("=" * 74)
print("T2 clean_log_text：一句人话里的技术尾巴")
print("=" * 74)

_t2 = [
    ("登录失败: KeyError('token')", "登录失败"),
    ("巡检失败：URLError(TimeoutError())", "巡检失败"),
    ("找到 口语训练 at (540, 1200)", "找到 口语训练"),
    ("实时题型: 选择题 (conf=0.87)", "实时题型: 选择题"),
    ("✅ 设备已就绪：SKSCIF…（屏幕 1080×2400）", "设备已就绪：SKSCIF…（屏幕 1080×2400）"),
]
for src, want in _t2:
    got = um.clean_log_text(src)
    chk(f"{src!r} → {want!r}", got == want, f"实得 {got!r}")

chk("【反向】正常句尾冒号不被当成异常（保留句子）",
    "共 3 道题" in um.clean_log_text("单元自检检测完成：共 3 道题。"))

print()
print("=" * 74)
print("T3 module_log：0 题不是完成")
print("=" * 74)

_txt, _lv = um.module_log("听力专项·测试", 12)
chk("q>0 → 明写题数", _txt.startswith("听力专项·测试检测完成") and "12 道题" in _txt, _txt)
chk("q>0 → level success", _lv == "success", _lv)

_txt, _lv = um.module_log("巧记单词", 0)
chk("q=0 → 说「未检测到题目」", _txt.startswith("巧记单词未检测到题目"), _txt)
chk("q=0 → 不出现「检测完成」", "检测完成" not in _txt, _txt)
chk("q=0 → level 不是 success", _lv == "warning", _lv)

for _zero in ("0", None, "", 0):
    _t, _l = um.module_log("单元自检", _zero)
    chk(f"q={_zero!r} 同样判未检测到题目",
        "未检测到题目" in _t and _l == "warning", _t)

_txt, _ = um.module_log("口语训练", 5, "耗时 63 秒")
chk("extra 追加在题数之后", "5 道题" in _txt and "耗时 63 秒" in _txt, _txt)
_txt, _ = um.module_log("口语训练", 0, "App 提示暂无内容")
chk("extra 在 0 题时进括号", "（App 提示暂无内容）" in _txt, _txt)

print()
print("=" * 74)
print("T4 step_log 出口清洗（模块没改也漏不出去）")
print("=" * 74)

_seen = []


def _cb(msg, level, *rest):
    _seen.append((msg, level))


_old_cb = lg._log_callback
lg.set_log_callback(_cb)
try:
    lg.step_log("📊 单元自检完成，共3题 @(540,1200)", "success")
    lg.step_log("打开失败（KeyError: 'title'）", "error")
finally:
    lg.set_log_callback(_old_cb)

chk("emoji + 坐标被清掉", _seen and _seen[0][0] == "单元自检完成，共3题", str(_seen[:1]))
chk("异常 repr 被清掉", len(_seen) > 1 and _seen[1][0] == "打开失败", str(_seen[1:2]))
chk("level 原样透传", _seen and _seen[0][1] == "success")

# evidence 语义不能被清洗破坏：None = 不是一道题；[] = 是一道题但无证据
_ev_seen = []


def _cb_ev(msg, level, *rest):
    _ev_seen.append(rest)


_old_cb = lg._log_callback
lg.set_log_callback(_cb_ev)
try:
    lg.step_log("普通流程日志")
    lg.step_log("一道题但无证据", "info", [])
finally:
    lg.set_log_callback(_old_cb)
chk("evidence=None 不传第三个参数", _ev_seen[0] == ())
chk("evidence=[] 仍传空列表", _ev_seen[1] == ([],))

print()
print("=" * 74)
print("T5 module_done：0 题不打 success")
print("=" * 74)

_done = []
_old_cb = lg._log_callback
lg.set_log_callback(lambda m, l, *a: _done.append((m, l)))
try:
    lg.module_done("巧记单词", 0)
    lg.module_done("单元自检", 7)
finally:
    lg.set_log_callback(_old_cb)

chk("0 题 → 未检测到题目 + warning",
    "未检测到题目" in _done[0][0] and _done[0][1] == "warning", str(_done[:1]))
chk("有题 → 检测完成 + success",
    "检测完成" in _done[1][0] and _done[1][1] == "success", str(_done[1:2]))

print()
print("=" * 74)
print("T6 源码级【反向】：step_log 文案不再带机器痕迹")
print("=" * 74)

_EMO = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0000FE0F\U000020E3\U00002190-\U000021FF\U00002500-\U0000257F]"
)
_FORBIDDEN = ["dump", "rid", "record_layout", "speech_btn_confirm",
              "比例换算", "@(", "xpath"]

_SCAN = [os.path.join(ROOT, "scripts", "engine.py"),
         os.path.join(ROOT, "scripts", "scheduler.py")]
_MODDIR = os.path.join(ROOT, "scripts", "modules")
for _f in sorted(os.listdir(_MODDIR)):
    if _f.endswith(".py"):
        _SCAN.append(os.path.join(_MODDIR, _f))


def _lit(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{…}"
                       for v in node.values)
    return ""


_bad_emo, _bad_tech, _n = [], [], 0
for _path in _SCAN:
    _src = open(_path, encoding="utf-8").read()
    _tree = ast.parse(_src)
    for _node in ast.walk(_tree):
        if not isinstance(_node, ast.Call):
            continue
        _fn = _node.func
        _nm = _fn.id if isinstance(_fn, ast.Name) else getattr(_fn, "attr", "")
        if _nm != "step_log" or not _node.args:
            continue
        _n += 1
        _t = _lit(_node.args[0])
        if _EMO.search(_t):
            _bad_emo.append(f"{os.path.basename(_path)}:{_node.lineno} {_t[:40]}")
        _hit = [w for w in _FORBIDDEN if w in _t]
        if _hit:
            _bad_tech.append(f"{os.path.basename(_path)}:{_node.lineno} {_hit} {_t[:40]}")

chk(f"扫描到 step_log 调用（{_n} 处）", _n > 100, str(_n))
chk("【反向】无 emoji / 装饰符号", not _bad_emo, str(_bad_emo[:4]))
chk("【反向】无内部字段名 / 坐标 / xpath", not _bad_tech, str(_bad_tech[:4]))

print()
print("=" * 74)
print("T7 源码级【反向】：不存在「共 N 题」+ success 的 0 题冒充完成")
print("=" * 74)

_fake_ok = []
for _path in _SCAN:
    _tree = ast.parse(open(_path, encoding="utf-8").read())
    for _node in ast.walk(_tree):
        if not isinstance(_node, ast.Call):
            continue
        _fn = _node.func
        if (getattr(_fn, "id", getattr(_fn, "attr", "")) != "step_log"
                or len(_node.args) < 2):
            continue
        _lv = _node.args[1]
        if not (isinstance(_lv, ast.Constant) and _lv.value == "success"):
            continue
        _t = _lit(_node.args[0])
        if "共" in _t and "题" in _t:
            _fake_ok.append(f"{os.path.basename(_path)}:{_node.lineno} {_t[:50]}")

chk("【反向】没有无条件 success 的「共 N 题」",
    not _fake_ok, str(_fake_ok[:4]))

# engine/scheduler 的模块结算必须走 module_done 或显式三态
_sc = open(os.path.join(ROOT, "scripts", "scheduler.py"), encoding="utf-8").read()
chk("scheduler 0 题分支仍是 empty 文案", "未检测到题目（0 题）" in _sc)

print()
print("=" * 74)
print("T8 _DIM_INVOKED_KW：新文案触发，0 题不触发")
print("=" * 74)

_ws = open(os.path.join(ROOT, "web_server.py"), encoding="utf-8").read()
_pat = None
for _node in ast.parse(_ws).body:
    if isinstance(_node, ast.Assign) and any(
            getattr(t, "id", "") == "_DIM_INVOKED_KW" for t in _node.targets):
        _parts = [a.value for a in _node.value.args if isinstance(a, ast.Constant)]
        _pat = re.compile("".join(_parts))
chk("取到 _DIM_INVOKED_KW 编译结果", _pat is not None)

if _pat is not None:
    chk("新文案（有题）触发脚本审查",
        bool(_pat.match("听力专项·测试检测完成，共 12 道题。")),
        "听力专项·测试检测完成，共 12 道题。")
    chk("【反向】0 题不触发",
        not _pat.match("巧记单词检测完成，共 0 道题。"))
    chk("旧文案兼容",
        bool(_pat.match("巧记单词 完成: 3 题")))
    chk("【反向】本轮总结不误触",
        not _pat.match("本轮结束：3 个模块全部检测完成，累计 12 道题。"))

print()
print("=" * 74)
print("T9 web_server.log_msg 也接了清洗（不只 step_log）")
print("=" * 74)

chk("log_msg 调用了 _humanize_log",
    "_humanize_log(_strip_traceback_from_log(msg))" in _ws)
chk("_humanize_log 用 clean_log_text", "clean_log_text" in _ws)

# 裸异常由 _humanize_log 在出口抹掉，源码里允许 `f"...失败: {e}"` 的写法；
# 这里断言的是「出口确实挂上了」，而不是逐行改写 188 处调用点。
chk("出口清洗能抹掉裸异常尾巴",
    um.clean_log_text("巡检失败: KeyError('x')") == "巡检失败")

_log_lines = [ln.strip() for ln in _ws.split("\n") if ln.strip().startswith("log_msg(")]
chk("【反向】log_msg 文案不含感叹号",
    not any(("！" in ln or "!" in ln) for ln in _log_lines),
    str([ln for ln in _log_lines if "！" in ln or "!" in ln][:3]))

print()
print("=" * 74)
print(f"结果：PASS {PASS} / FAIL {len(FAIL)}")
if FAIL:
    for _x in FAIL:
        print("  - " + _x)
print("=" * 74)
sys.exit(0 if not FAIL else 1)
