# -*- coding: utf-8 -*-
r"""★ 2026-10-08b 回归测试：口语训练「退出训练」确认框识别 + 试卷页退出（U1 之后）

━━━ 背景（一次真实的失败复跑）━━━
用户要求「口语训练 · 湘少版(2024审定) · 四年级下册 · U1、U3」。第 3 次跑：
    21:46:03 ✔ 版本/年级已确认
              📋 试卷首页检查: 通过 | 标题=口语训练新湘少版四下U1
    21:50:56 📝 开始第3大题
    21:51:35 ⚠ 未能退出口语训练试卷页（U1 之后）
    21:51:51 ❌ 口语训练 U3 入口缺失：当前页无该单元标题行
    ...
    21:53:02 ✅ 口语训练完成，共10题        ← U3 一题没测
把【工具没退出去】误报成【App 没有 U3】。

━━━ 真机取证（tools 探针 probe_oral_exit_dialog.py，MuMu 900x1600）━━━
A) 试卷页（SpokeTestActivity）顶栏：
     tv_exit  text="退出训练"  clickable=true  bounds=[36,82][198,144]
     tv_toolbar_title text="口语训练新湘少版四下U1"
     tv_question_sort text="3/4"
B) 点 tv_exit 后弹出确认框（新 page，原 page 仍在 hierarchy 之外）：
     confirm_title    text="温馨提示"
     confirm_context  text="你完成了2道题，练习未做完，&#10;中途退出别错过练习时间哦~"
     confirm_left_btn  text="确定退出"   bounds=[96,854][435,914]   ← 要点这个
     confirm_right_btn text="继续答题"   bounds=[465,854][804,914]  ← 绝不能点
C) 点 confirm_left_btn 后落到「口语训练」单元列表：
     口语训练 / 当前版本：湘少版（2024审定）四年级下册 / 全部|单元|质量监测
     口语训练新湘少版四下U1 →继续答题   新湘少版四下U2/U3/U4/U5 →开始答题
     ⇒ **U3 入口存在**，之前的"入口缺失"是纯误报。

━━━ 第一版修复为什么仍然失败（三处误判叠加）━━━
  ① 确认框按钮实测是 "确定退出"，而白名单只有 ("确定","确认","继续退出","退出")；
     uiautomator2 的 `d(text=...)` 是**精确匹配** → "确定" ≠ "确定退出" → 一个都没点中。
  ② 确认框出现时 XML 里【既无「退出训练」也无 U+数字】，
     旧判据 `"退出训练" not in xml and U\d in xml` 为假 → 落到 else 分支按 back；
     back 的语义是**取消弹窗** → 回试卷 → 再点退出训练 → 再弹窗 → 死循环 6 轮。
  ③ 旧判据靠"不在试卷页"间接推断成功，没有正向证据。

━━━ 本测试锁定 ━━━
  T1 _in_exit_confirm     ：确认框/试卷页/列表页/练习报告/空串 五态区分
  T2 _click_exit_confirm  ：必须命中 confirm_left_btn；【反向】绝不点 confirm_right_btn；
                            文本白名单不含"继续答题"；非确认框页面零点击
  T3 _is_oral_list_page   ：真机列表页 XML 为真；试卷页/确认框/练习报告 为假
  T4 真机序列重放         ：试卷页 → 确认框 → 列表 = True，且【一次 back 都不按】
  T5 【反向】确认框点不动 ：返回 False；且【绝不按下 back】（旧 bug 的机制）
  T6 【反向】精确匹配实证 ：d(text="确定") 在确认框上为假、d(text="确定退出") 为真
                            （把根因钉死，防止有人把白名单改回 "确定"）
  T7 _diag_no_record_ctrl ：纯图片题（只有 tv_exit 可点）→ 出"无可作答控件"告警；
                            有"下一题/答题卡"或倒计时态 → 不出该告警；有录音按钮 → 不出
  T8 真机 dump 可选校验   ：若 probe_out 里存有真机 XML，直接用真 XML 断言三个判据

运行：python scripts/tests/test_fix_20261008b_oral_paper_exit.py
"""
import os
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)

# 不连手机：stub uiautomator2（本测试全程用 MockD）
_u2 = types.ModuleType("uiautomator2")
sys.modules["uiautomator2"] = _u2

from modules import 口语训练 as m                # noqa: E402

# 把模块内的 time.sleep 打桩，避免 6 轮 ×1.2s 拖慢测试
_fake_time = types.ModuleType("time")
_fake_time.sleep = lambda *_a, **_k: None
_fake_time.time = lambda: 0.0
m.time = _fake_time

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


# ══════════════════════ 真机 XML 快照（按 dump 裁剪，属性顺序与真机一致）══════════
SCENES = {
    # A) 试卷页：顶栏「退出训练」+ 大题进度 + 答题卡/上一题/下一题（对齐真机 dump）
    "PAPER": (
        '<hierarchy rotation="0">'
        '<node index="0" resource-id="com.dinoenglish.yyb:id/toolbar" clickable="false">'
        '<node resource-id="com.dinoenglish.yyb:id/tv_toolbar_title" '
        'text="口语训练新湘少版四下U1" clickable="false" bounds="[275,78][625,126]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/tv_exit" text="退出训练" '
        'clickable="true" bounds="[36,82][198,144]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/tv_question_sort" text="3/4" '
        'clickable="false" bounds="[791,84][869,132]"/>'
        '</node>'
        '<node resource-id="com.dinoenglish.yyb:id/tv_answer" text="答题卡" '
        'clickable="true" bounds="[726,238][900,314]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/pic_iv" clickable="false" '
        'bounds="[97,294][579,435]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/check_btn" text="上一题" '
        'clickable="true" bounds="[24,1468][426,1576]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/next_btn" text="下一题" '
        'clickable="true" bounds="[474,1468][876,1576]"/>'
        '</hierarchy>'
    ),
    # B) 退出确认框：注意 hierarchy 里【没有】"退出训练"，也没有 U+数字
    "CONFIRM": (
        '<hierarchy rotation="0">'
        '<node index="0" resource-id="com.dinoenglish.yyb:id/confirm_title" '
        'text="温馨提示" clickable="false" bounds="[66,570][180,618]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/confirm_context" '
        'text="你完成了2道题，练习未做完，&#10;中途退出别错过练习时间哦~" '
        'clickable="false" bounds="[90,670][810,760]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/confirm_left_btn" text="确定退出" '
        'clickable="true" bounds="[96,854][435,914]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/confirm_right_btn" text="继续答题" '
        'clickable="true" bounds="[465,854][804,914]"/>'
        '</hierarchy>'
    ),
    # C) 退出后落到「口语训练」单元列表（U3 入口确实存在）
    "LIST": (
        '<hierarchy rotation="0">'
        '<node resource-id="com.dinoenglish.yyb:id/web_view_main" clickable="false">'
        '<node text="考前突破" clickable="false"/>'
        '<node text="口语训练" clickable="false"/>'
        '<node text="当前版本：湘少版（2024审定）四年级下册" clickable="false"/>'
        '<node text="全部" clickable="true"/><node text="单元" clickable="true"/>'
        '<node text="质量监测" clickable="true"/>'
        '<node text="口语训练新湘少版四下U1" clickable="false"/>'
        '<node text="继续答题" clickable="true" bounds="[708,420][846,471]"/>'
        '<node text="口语训练新湘少版四下U2" clickable="false"/>'
        '<node text="开始答题" clickable="true" bounds="[708,687][846,736]"/>'
        '<node text="口语训练新湘少版四下U3" clickable="false"/>'
        '<node text="开始答题" clickable="true" bounds="[708,951][846,1002]"/>'
        '</node></hierarchy>'
    ),
    # D) 练习报告页（含"口语训练/单元"字样，但【不是】单元列表）
    "REPORT": (
        '<hierarchy rotation="0">'
        '<node text="口语训练" clickable="false"/>'
        '<node text="练习报告" clickable="false"/>'
        '<node text="单元" clickable="false"/>'
        '<node text="得分 38" clickable="false"/>'
        '</hierarchy>'
    ),
    # E) 纯图片题大题（湘少四下 U1 大题3）：整页唯一可点击 = tv_exit
    "PAPER_NOCTRL": (
        '<hierarchy rotation="0">'
        '<node resource-id="com.dinoenglish.yyb:id/tv_toolbar_title" '
        'text="口语训练新湘少版四下U1" clickable="false"/>'
        '<node resource-id="com.dinoenglish.yyb:id/tv_exit" text="退出训练" '
        'clickable="true" bounds="[36,82][198,144]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/tv_question_sort" text="3/4" '
        'clickable="false"/>'
        '<node resource-id="com.dinoenglish.yyb:id/pic_iv" clickable="false" '
        'bounds="[97,495][579,915]"/>'
        '<node resource-id="com.dinoenglish.yyb:id/tv_title_score" text="(3分)" '
        'clickable="false"/>'
        '</hierarchy>'
    ),
    # F) 过渡态（倒计时）
    "TRANSITION": (
        '<hierarchy rotation="0">'
        '<node text="请阅读题目" clickable="false" bounds="[0,700][900,800]"/>'
        '</hierarchy>'
    ),
    # G) 有录音按钮的普通作答大题（不该报"无可作答控件"）
    "PAPER_REC": (
        '<hierarchy rotation="0">'
        '<node text="你将有20秒钟的时间阅读屏幕上的句子" clickable="false"/>'
        '<node resource-id="com.dinoenglish.yyb:id/record_btn" clickable="true" '
        'bounds="[425,1371][655,1652]"/>'
        '<node text="下一题" clickable="true" bounds="[474,1468][876,1576]"/>'
        '</hierarchy>'
    ),
}

# 真机交互映射：点谁 → 切到哪个页面
TRANS_OK = {
    ("rid", "tv_exit"): "CONFIRM",
    ("rid", "confirm_left_btn"): "LIST",
    ("rid", "confirm_right_btn"): "PAPER",     # 继续答题 → 回试卷
    ("text", "退出训练"): "CONFIRM",
    ("text", "确定退出"): "LIST",
    ("text", "继续答题"): "PAPER",
}


class MockEl(object):
    def __init__(self, dev, kind, key):
        self.dev, self.kind, self.key = dev, kind, key

    def exists(self, timeout=0):
        return self.dev._has(self.kind, self.key)

    def click(self):
        self.dev._click(self.kind, self.key)

    @property
    def info(self):
        return {"bounds": {"left": 0, "top": 0, "right": 100, "bottom": 100}}


class MockD(object):
    """状态机假设备：dump_hierarchy 返回当前页 XML，click 按 TRANS 切页。"""

    def __init__(self, scene, trans=None, back_to=None):
        self.scene = scene
        self.trans = dict(TRANS_OK if trans is None else trans)
        self.back_to = dict(back_to or {})
        self.clicks = []
        self.presses = []

    def dump_hierarchy(self):
        return SCENES[self.scene]

    def __call__(self, **kw):
        if "resourceId" in kw:
            return MockEl(self, "rid", kw["resourceId"].rstrip("/").split("/")[-1])
        if "text" in kw:
            return MockEl(self, "text", kw["text"])
        if "description" in kw:
            return MockEl(self, "desc", kw["description"])
        return MockEl(self, "other", "")

    def _has(self, kind, key):
        xml = SCENES[self.scene]
        if kind == "rid":
            return f'resource-id="com.dinoenglish.yyb:id/{key}"' in xml
        if kind == "text":
            return f'text="{key}"' in xml
        return False

    def _click(self, kind, key):
        self.clicks.append((kind, key))
        nxt = self.trans.get((kind, key))
        if nxt:
            self.scene = nxt

    def press(self, key):
        self.presses.append(key)
        if key in self.back_to:
            self.scene = self.back_to[key]


def cap_step_log():
    """打桩 step_log，返回捕获列表"""
    lines = []

    def _fake(msg, level="info"):
        lines.append((level, msg))

    m.step_log = _fake
    return lines


print("\n" + "=" * 74)
print("T1 _in_exit_confirm：五态区分")
print("=" * 74)
chk("确认框 XML → True", m._in_exit_confirm(SCENES["CONFIRM"]) is True)
chk("试卷页 XML → False", m._in_exit_confirm(SCENES["PAPER"]) is False)
chk("单元列表 XML → False", m._in_exit_confirm(SCENES["LIST"]) is False)
chk("练习报告 XML → False", m._in_exit_confirm(SCENES["REPORT"]) is False)
chk("空串 → False", m._in_exit_confirm("") is False)
chk("None → False", m._in_exit_confirm(None) is False)
chk("【反向】只有『确定退出』无『温馨提示』→ 不认作确认框",
    m._in_exit_confirm('<node text="确定退出"/>') is False)

print("\n" + "=" * 74)
print("T2 _click_exit_confirm：必须点左键，绝不点『继续答题』")
print("=" * 74)
d = MockD("CONFIRM")
got = m._click_exit_confirm(d, SCENES["CONFIRM"])
chk("返回 True", got is True)
chk("命中 confirm_left_btn（resource-id 优先）",
    d.clicks == [("rid", "confirm_left_btn")], f"实际 clicks={d.clicks}")
chk("点完页面切到 LIST", d.scene == "LIST")
chk("【反向】clicks 里绝无 confirm_right_btn",
    all(k != "confirm_right_btn" for _kk, k in d.clicks), f"{d.clicks}")
chk("【反向】clicks 里绝无 '继续答题'",
    all(k != "继续答题" for _kk, k in d.clicks), f"{d.clicks}")
chk("【反向】文本白名单不含『继续答题』",
    "继续答题" not in m._EXIT_CONFIRM_TEXTS, f"{m._EXIT_CONFIRM_TEXTS}")
chk("文本白名单首项是『确定退出』（长词优先）",
    m._EXIT_CONFIRM_TEXTS[0] == "确定退出", f"{m._EXIT_CONFIRM_TEXTS}")
d2 = MockD("PAPER")
chk("【反向】非确认框页面：返回 False 且零点击",
    m._click_exit_confirm(d2, SCENES["PAPER"]) is False and d2.clicks == [],
    f"{d2.clicks}")
d3 = MockD("CONFIRM")
chk("xml 未知（空串）→ 允许尝试，且仍然只点 confirm_left_btn",
    m._click_exit_confirm(d3, "") is True
    and d3.clicks == [("rid", "confirm_left_btn")], f"{d3.clicks}")

print("\n" + "=" * 74)
print("T3 _is_oral_list_page：正向特征判定")
print("=" * 74)
chk("真机单元列表 XML → True", m._is_oral_list_page(SCENES["LIST"]) is True)
chk("试卷页 XML → False", m._is_oral_list_page(SCENES["PAPER"]) is False)
chk("确认框 XML → False", m._is_oral_list_page(SCENES["CONFIRM"]) is False)
chk("练习报告 XML → False（含『口语训练/单元』也不算）",
    m._is_oral_list_page(SCENES["REPORT"]) is False)
chk("空串 → False", m._is_oral_list_page("") is False)
chk("纯图片题试卷页 → False", m._is_oral_list_page(SCENES["PAPER_NOCTRL"]) is False)
_need_scroll = ('<node text="口语训练"/><node text="单元"/><node text="全部"/>'
                '<node text="口语训练新湘少版四下U9"/>'
                '<node text="开始答题" clickable="true"/>')
chk("单元多到按钮需滚动（仅有 U9 标题）→ True",
    m._is_oral_list_page(_need_scroll) is True)

print("\n" + "=" * 74)
print("T4 真机序列重放：试卷页 → 确认框 → 列表")
print("=" * 74)
d = MockD("PAPER")
got = m._exit_paper_to_list(d)
chk("返回 True", got is True, f"最终 scene={d.scene}")
chk("页面落在 LIST", d.scene == "LIST")
chk("点击序列 = [tv_exit, confirm_left_btn]",
    d.clicks == [("rid", "tv_exit"), ("rid", "confirm_left_btn")], f"{d.clicks}")
chk("【关键反向】全程一次 back 都没按（旧 bug 就是 back 取消了弹窗）",
    d.presses == [], f"{d.presses}")

print("\n" + "=" * 74)
print("T5 【反向】确认框点不动：必须返回 False，且绝不按 back")
print("=" * 74)
trans_broken = dict(TRANS_OK)
trans_broken.pop(("rid", "confirm_left_btn"))
trans_broken.pop(("text", "确定退出"))
d = MockD("PAPER", trans=trans_broken)
got = m._exit_paper_to_list(d, allow_restart=False)
chk("返回 False", got is False)
chk("【关键反向】仍然一次 back 都没按（back = 取消弹窗 → 死循环）",
    d.presses == [], f"{d.presses}")
chk("失败时停在 CONFIRM（没被误判成已退出）", d.scene == "CONFIRM", d.scene)

# 兜底重启：被调用且成功 → 返回 True
_called = {"n": 0}
_orig_restart = m._restart_to_oral_module
m._restart_to_oral_module = lambda dd: (_called.__setitem__("n", _called["n"] + 1), True)[1]
d = MockD("PAPER", trans=trans_broken)
got = m._exit_paper_to_list(d, allow_restart=True)
chk("allow_restart=True：调用兜底重启并返回 True",
    got is True and _called["n"] == 1, f"got={got} n={_called['n']}")
_called["n"] = 0
m._restart_to_oral_module = lambda dd: (_called.__setitem__("n", _called["n"] + 1), False)[1]
d = MockD("PAPER", trans=trans_broken)
got = m._exit_paper_to_list(d, allow_restart=True)
chk("兜底重启也失败 → 返回 False（调用过 1 次）",
    got is False and _called["n"] == 1, f"got={got} n={_called['n']}")
m._restart_to_oral_module = _orig_restart

print("\n" + "=" * 74)
print("T6 【根因钉死】uiautomator2 的 text= 是精确匹配")
print("=" * 74)
d = MockD("CONFIRM")
chk('确认框上 d(text="确定") 不存在（精确匹配 → 匹配不到"确定退出"）',
    d(text="确定").exists() is False)
chk('确认框上 d(text="确定退出") 存在', d(text="确定退出").exists() is True)
chk('确认框上 d(text="继续答题") 存在（危险按钮，绝不能被白名单带进去）',
    d(text="继续答题").exists() is True)
_src = open(os.path.join(SCRIPTS, "modules", "口语训练.py"), encoding="utf-8").read()
chk("源码不含旧白名单 ('确定', '确认', '继续退出', '退出')",
    '("确定", "确认", "继续退出", "退出")' not in _src)
chk("源码含 confirm_left_btn 精确点选",
    "confirm_left_btn" in _src)

print("\n" + "=" * 74)
print("T7 _diag_no_record_ctrl：区分『没就绪』与『压根没有可作答控件』")
print("=" * 74)
lines = cap_step_log()
m._diag_no_record_ctrl(MockD("PAPER_NOCTRL"), 3)
warn = [x for x in lines if x[0] == "warning"]
chk("纯图片题（只有 tv_exit 可点）→ 出 1 条 warning", len(warn) == 1, f"{lines}")
chk("告警文案含『无可作答控件』", bool(warn) and "无可作答控件" in warn[0][1],
    warn[0][1] if warn else "")
chk("告警文案列出可点击元素（退出训练）",
    bool(warn) and "退出训练" in warn[0][1], warn[0][1] if warn else "")

lines = cap_step_log()
m._diag_no_record_ctrl(MockD("PAPER_REC"), 1)
chk("【反向】有录音按钮 → 不出告警", lines == [], f"{lines}")

lines = cap_step_log()
m._diag_no_record_ctrl(MockD("TRANSITION"), 1)
warn = [x for x in lines if x[0] == "warning"]
chk("倒计时过渡态 → 出『倒计时/上传』告警（不误报页面坏）",
    len(warn) == 1 and "倒计时" in warn[0][1], f"{lines}")

lines = cap_step_log()
m._diag_no_record_ctrl(MockD("PAPER"), 1)
chk("【反向】试卷页仍有『答题卡』等过渡控件 → 不出告警", lines == [], f"{lines}")

lines = cap_step_log()
class _Boom(object):
    def dump_hierarchy(self):
        raise RuntimeError("设备瞬断")
m._diag_no_record_ctrl(_Boom(), 1)
chk("【反向】dump 抛异常 → 不崩、不误报", lines == [], f"{lines}")

print("\n" + "=" * 74)
print("T8 真机 dump 可选校验（probe_out 存在时直接跑真 XML）")
print("=" * 74)
_probe = r"C:\Users\19507\WorkBuddy\安全处理空间\.workbuddy\probe_out"
_pairs = [
    ("probe2_D_试卷页.xml", "not_list", "试卷页"),
    ("probe2_E1_after_exit.xml", "confirm", "确认框"),
    ("probe2_G1_after_confirm.xml", "list", "点确定退出后的落点"),
]
_ran = 0
for _fn, _kind, _label in _pairs:
    _p = os.path.join(_probe, _fn)
    if not os.path.exists(_p):
        continue
    with open(_p, encoding="utf-8") as fh:
        _x = fh.read()
    _ran += 1
    if _kind == "confirm":
        chk(f"真机 {_label} → _in_exit_confirm True", m._in_exit_confirm(_x) is True)
        chk(f"真机 {_label} → _click_exit_confirm 认它为确认框",
            m._click_exit_confirm(MockD("CONFIRM"), _x) is True)
    elif _kind == "list":
        chk(f"真机 {_label} → _is_oral_list_page True",
            m._is_oral_list_page(_x) is True)
        chk(f"真机 {_label} 含 U3 入口", "U3" in _x)
    else:
        chk(f"真机 {_label} → _is_oral_list_page False",
            m._is_oral_list_page(_x) is False)
        chk(f"真机 {_label} → _in_exit_confirm False",
            m._in_exit_confirm(_x) is False)
if _ran == 0:
    print("  [--] probe_out 无真机 dump，跳过（不影响其余用例）")

print("\n" + "=" * 74)
print(f"结果: {PASS} 通过 / {FAIL} 失败")
print("=" * 74)
sys.exit(1 if FAIL else 0)
