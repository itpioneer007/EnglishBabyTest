# -*- coding: utf-8 -*-
r"""★ 2026-10-16 回归测试：「换设备/切书本版本就出错」的三项根因修复

━━━ 背景（用户报告）━━━
「同学用部署的服务器链接（cpolar 内网穿透）操控 MuMu 上的英语宝，导航到
 切换书本版本就不动了，一直报错。」

━━━ 排查结论（三项缺陷，本测试逐条锁定）━━━
① 坐标缩放是「启动时定型」的隐式状态
   web_server.py 只在进程启动那一刻 detect_screen_resolution() + scale_all_coords()，
   全代码库再无第二处。/api/device/select 允许运行中换设备却**不重算缩放**。
   启动时目标设备若未就绪 → wm size 无返回 → 缩放停在 1.0 →
   MODULE_COORDS/TABS/SETTINGS_ICON/AD_CLOSE/MODULE_PATTERNS 全部按真机 1080x2400
   使用，在 900x1600 的模拟器上必然点偏，且前端看不到任何提示。
   ⚠ 连带缺陷：scale_all_coords() 是【就地缩放】，原来不可重复调用 —— 第二次调用
     会在"已缩放"的值上再乘一次缩放比。

② 目标设备不可解释（静默回落真机）
   /api/status 原来取 `ANDROID_SERIAL or config.device.serial`；env 一旦没生效
   （重启没走 tools/_serve_logged.py、或启动时设备没就绪），就静默用了 config.yaml
   里的真机串号 —— 操作者以为在控 MuMu，实际在控真机。

③ 切版本/年级全靠写死像素坐标
   scripts/common/setup.py 的 switch_version / switch_grade 用 S(972,2220)/S(250,300)/
   S(321,275) 这类比例换算坐标；任一步点不中就直接 return False，前端只看到 HTTP 500。

━━━ 修法 ━━━
① _COORD_REFS 原始快照 + scale_all_coords() 幂等；新增 refresh_device_scale()，
   在 /api/device/select 与任务开始前调用（设备后连上也能自愈，无需重启服务）。
② 新增 _intended_serial()：显式 → ANDROID_SERIAL → server_target.txt → config.yaml；
   /api/status 透出 target_resolution / coord_scale / coord_scale_ok；
   _preflight_target_device() 预检不过就拒绝开始（不再静默回落真机）。
③ setup 新增 _node_bounds/_tap_bounds/_tap_rid/_tap_bottom_tab：元素优先定位，
   写死坐标仅作兜底；每步带正向校验与可读失败原因。

━━━ 本测试锁定 ━━━
  T1 scale_all_coords 幂等（反复调用不二次缩放）
  T2 detect_screen_resolution 失败必定复位为 1:1
  T3 _intended_serial 优先级（含 server_target.txt 一档）
  T4 refresh_device_scale：探测失败 ok=False 且 scale=1:1
  T5 _preflight_target_device：失败信息可操作（含目标串号 + 在线设备）
  T6 setup._node_bounds 匹配语义（含【反向】短名不误匹配 / y 区间过滤）
  T7 switch_grade 元素优先（点中「切换课本」页里的年级节点中心）
  T8 【兜底】无 switch_textbook_tv 时仍走 S() 坐标且能成功
  T9 switch_version 正常路径（「我」按文字定位、版本前缀匹配、返回 True）
  T10 【反向】顶部区域的「我」不被当成底部 tab（y 约束生效）
  T11 switch_version 失败时返回 False 且有可读原因

运行：python scripts/tests/test_fix_20261016b_device_scale_and_switch.py
"""
import contextlib
import io
import os
import re
import sys
import tempfile

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


def _xml(nodes):
    """nodes: [(rid, text, (x1,y1,x2,y2))] → hierarchy xml（rid 传短名）"""
    out = ['<hierarchy rotation="0">']
    for rid, text, b in nodes:
        r = f' resource-id="com.dinoenglish.yyb:id/{rid}"' if rid else ''
        out.append(f'<node index="0"{r} text="{text}" clickable="true" '
                   f'bounds="[{b[0]},{b[1]}][{b[2]},{b[3]}]"/>')
    out.append('</hierarchy>')
    return ''.join(out)


# ══════════════════════════════════════════════════════════════
# ① web_server 坐标缩放层
# ══════════════════════════════════════════════════════════════
import web_server as ws  # noqa: E402

print("=" * 74)
print("T1 scale_all_coords() 幂等：重复调用不得二次缩放")
print("=" * 74)
_ref = ws._capture_coord_refs()["MODULE_COORDS"]
_pristine = _ref["口语训练"]
ws._detected_res = (900, 1600)                 # 模拟 MuMu
ws._scale_x, ws._scale_y = 900 / 1080, 1600 / 2400
ws.scale_all_coords()
_first = ws.MODULE_COORDS["口语训练"]
_exp = (int(_pristine[0] * ws._scale_x + 0.5), int(_pristine[1] * ws._scale_y + 0.5))
chk(f"首次缩放 = 基准×缩放比（{_pristine} → {_exp}）", _first == _exp, f"{_first} != {_exp}")
_snap1 = (dict(ws.MODULE_COORDS), dict(ws.TABS), tuple(ws.SETTINGS_ICON), tuple(ws.AD_CLOSE))
ws.scale_all_coords()
_snap2 = (dict(ws.MODULE_COORDS), dict(ws.TABS), tuple(ws.SETTINGS_ICON), tuple(ws.AD_CLOSE))
chk("【关键】二次调用 MODULE_COORDS/TABS/SETTINGS_ICON/AD_CLOSE 完全不变", _snap1 == _snap2)
_wrong = (int(_exp[0] * ws._scale_x + 0.5), int(_exp[1] * ws._scale_y + 0.5))
chk(f"【反向】结果 != 再乘一次的值 {_wrong}（证明用的是原始快照）", _first != _wrong)
_pat_ref = ws._capture_coord_refs()["MODULE_PATTERNS"][("巧记单词", "巧记")][2]
chk(f"MODULE_PATTERNS 坐标为基准缩放一次（{_pat_ref} → "
    f"{ws.MODULE_PATTERNS[('巧记单词', '巧记')][2]}）",
    ws.MODULE_PATTERNS[("巧记单词", "巧记")][2] ==
    (int(_pat_ref[0] * ws._scale_x + 0.5), int(_pat_ref[1] * ws._scale_y + 0.5)))

print("\n" + "=" * 74)
print("T2 detect_screen_resolution 失败必定复位为 1:1")
print("=" * 74)


class _FakeADB:
    @staticmethod
    def _find_adb():
        return "adb"


class _FakeRun:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = ""


_OLD_ADB, _OLD_RUN = ws.ADBController, ws.sp.run
try:
    ws.ADBController = _FakeADB
    # 先弄脏缩放，再让探测失败 → 必须复位
    ws._scale_x, ws._scale_y, ws._detected_res = 0.5, 0.75, (900, 1600)
    ws.sp.run = lambda *a, **k: _FakeRun("adb: device 'x' not found\n")
    ws.detect_screen_resolution("127.0.0.1:16384")
    chk("探测失败 → _detected_res 复位为 None", ws._detected_res is None, str(ws._detected_res))
    chk("探测失败 → 缩放复位为 1:1（不留上一次的值）",
        (ws._scale_x, ws._scale_y) == (1.0, 1.0), f"{ws._scale_x},{ws._scale_y}")
    # 正向：解析得出 900x1600 → 缩放 0.833/0.667
    ws.sp.run = lambda *a, **k: _FakeRun("Physical size: 900x1600\n")
    ws.detect_screen_resolution("127.0.0.1:16384")
    chk("解析成功 → 900x1600 缩放 X≈0.833 Y≈0.667",
        abs(ws._scale_x - 900 / 1080) < 1e-9 and abs(ws._scale_y - 1600 / 2400) < 1e-9,
        f"{ws._scale_x},{ws._scale_y}")
finally:
    ws.ADBController, ws.sp.run = _OLD_ADB, _OLD_RUN

print("\n" + "=" * 74)
print("T3 _intended_serial 优先级：显式 → ANDROID_SERIAL → server_target.txt → config")
print("=" * 74)
_tmp = tempfile.mkdtemp(prefix="yyb_target_")
_old_root, _old_lc = ws.PROJECT_ROOT, ws.load_config
_old_env = os.environ.get("ANDROID_SERIAL")


class _CfgDev:
    serial = "CONFIG_SERIAL"


class _Cfg:
    device = _CfgDev()


try:
    ws.PROJECT_ROOT = _tmp
    ws.load_config = lambda: _Cfg()
    _tf = os.path.join(_tmp, "server_target.txt")
    # a) 无 env、无 server_target → 回落 config.yaml
    os.environ.pop("ANDROID_SERIAL", None)
    if os.path.exists(_tf):
        os.remove(_tf)
    chk("无 env / 无 server_target → config.yaml 的串号",
        ws._intended_serial() == "CONFIG_SERIAL", ws._intended_serial())
    # b) 有 server_target.txt → 用它（这是本次新增的一档，修"静默回落真机"的关键）
    with open(_tf, "w", encoding="utf-8") as fh:
        fh.write("127.0.0.1:16384\n")
    chk("有 server_target.txt → 用 server_target（不再静默回落真机）",
        ws._intended_serial() == "127.0.0.1:16384", ws._intended_serial())
    # c) env 优先于 server_target.txt
    os.environ["ANDROID_SERIAL"] = "ENV_SERIAL"
    chk("ANDROID_SERIAL 优先于 server_target.txt",
        ws._intended_serial() == "ENV_SERIAL", ws._intended_serial())
    # d) 显式入参优先一切
    chk("显式入参优先于 ANDROID_SERIAL", ws._intended_serial("EXPLICIT") == "EXPLICIT")
    chk("【反向】显式传空串不算「显式」（退回后续优先级）",
        ws._intended_serial("   ") == "ENV_SERIAL", ws._intended_serial("   "))
    os.environ.pop("ANDROID_SERIAL", None)
finally:
    ws.PROJECT_ROOT, ws.load_config = _old_root, _old_lc
    if _old_env is None:
        os.environ.pop("ANDROID_SERIAL", None)
    else:
        os.environ["ANDROID_SERIAL"] = _old_env

print("\n" + "=" * 74)
print("T4 refresh_device_scale：探测失败 ok=False 且缩放=1:1")
print("=" * 74)
try:
    ws.ADBController = _FakeADB
    ws.sp.run = lambda *a, **k: _FakeRun("")
    _info = ws.refresh_device_scale("127.0.0.1:16384", reason="单测")
    chk("ok=False（明确告知缩放不可信）", _info["ok"] is False, str(_info))
    chk("resolution=None", _info["resolution"] is None, str(_info["resolution"]))
    chk("scale=[1.0, 1.0]（按基准使用，可解释）", _info["scale"] == [1.0, 1.0], str(_info["scale"]))
    chk("返回目标串号（便于日志/前端核对）", _info["serial"] == "127.0.0.1:16384", _info["serial"])
    _info2 = ws.refresh_device_scale("X", reason="单测2")
    chk("失败时 before 记录了旧值（便于排查「之前是按哪台算的」）",
        isinstance(_info2.get("before"), list) and len(_info2["before"]) == 3, str(_info2.get("before")))
finally:
    ws.ADBController, ws.sp.run = _OLD_ADB, _OLD_RUN

print("\n" + "=" * 74)
print("T5 _preflight_target_device：失败信息可操作")
print("=" * 74)
_old_refresh, _old_devlist = ws.refresh_device_scale, ws._device_list
try:
    ws.refresh_device_scale = lambda serial="", reason="": {
        "serial": "127.0.0.1:16384", "resolution": None, "scale": [1.0, 1.0],
        "ok": False, "before": [None, 1.0, 1.0], "reason": reason}
    ws._device_list = lambda: [{"serial": "SKSCIF4T7PFMQS5X", "state": "device"}]
    _ok, _msg = ws._preflight_target_device()
    chk("目标不可达 → ok=False", _ok is False)
    chk("信息含目标串号", "127.0.0.1:16384" in _msg, _msg)
    chk("信息含当前在线设备（告诉人该切到哪台）", "SKSCIF4T7PFMQS5X" in _msg, _msg)
    chk("信息给了处置动作（启动/切换设备）", ("启动" in _msg and "切换" in _msg), _msg)
    # 正向：可达时不拦
    ws.refresh_device_scale = lambda serial="", reason="": {
        "serial": "S", "resolution": [1080, 2400], "scale": [1.0, 1.0], "ok": True}
    chk("可达 → ok=True 且无信息", ws._preflight_target_device() == (True, ""))
finally:
    ws.refresh_device_scale, ws._device_list = _old_refresh, _old_devlist

# 复原缩放状态，避免污染后续（同进程内其他断言）
ws._detected_res, ws._scale_x, ws._scale_y = (1080, 2400), 1.0, 1.0
ws.scale_all_coords()

# ══════════════════════════════════════════════════════════════
# ② setup.py 切版本/年级：元素优先
# ══════════════════════════════════════════════════════════════
import common.setup as setup  # noqa: E402

print("\n" + "=" * 74)
print("T6 setup._node_bounds 匹配语义")
print("=" * 74)
_x = _xml([("switch_textbook_tv", "湘少版（2024审定）   三年级上册", (250, 250, 830, 300)),
           ("tab_me", "我", (830, 1480, 970, 1530))])
chk("rid 短名精确匹配",
    setup._node_bounds(_x, rid="switch_textbook_tv") == (250, 250, 830, 300),
    str(setup._node_bounds(_x, rid="switch_textbook_tv")))
chk("【反向】rid 短名不误匹配（switch_textbook_tvX 不命中 tv）",
    setup._node_bounds(_x, rid="switch_textbook_tvX") is None)
chk("【反向】rid 只认短名，不匹配整条 resource-id",
    setup._node_bounds(_x, rid="com.dinoenglish.yyb:id/switch_textbook_tv") is None)
chk("text_eq 精确匹配", setup._node_bounds(_x, text_eq="我") == (830, 1480, 970, 1530))
chk("【反向】text_eq 不做包含（「我」不匹配「我们」）",
    setup._node_bounds(_xml([(None, "我们", (0, 1500, 100, 1560))]), text_eq="我") is None)
chk("text_contains 包含匹配",
    setup._node_bounds(_x, text_contains="三年级") == (250, 250, 830, 300))
chk("y_min 过滤：顶部节点被排除（底部 tab 约束）",
    setup._node_bounds(_x, text_eq="我", y_min=1152) == (830, 1480, 970, 1530))
chk("【反向】y 约束生效：把「我」放顶部则找不到（防误当底部 tab）",
    setup._node_bounds(_xml([(None, "我", (250, 200, 390, 250))]), text_eq="我", y_min=1152) is None)
chk("bounds 缺失的节点被跳过",
    setup._node_bounds('<hierarchy><node text="我" resource-id="a"/></hierarchy>',
                       text_eq="我") is None)
# _tap_bottom_tab 端到端：底部命中 / 顶部不命中
class _D0:
    def __init__(self, xml):
        self._xml = xml
        self.clicks = []

    def dump_hierarchy(self):
        return self._xml

    def window_size(self):
        return (900, 1600)

    def click(self, *xy):
        self.clicks.append(tuple(xy))


_d0 = _D0(_x)
chk("_tap_bottom_tab 命中底部「我」并点其中心 (900,1505)",
    setup._tap_bottom_tab(_d0, "我") is True and _d0.clicks == [(900, 1505)], str(_d0.clicks))
_d1 = _D0(_xml([(None, "我", (250, 200, 390, 250))]))
chk("【反向】_tap_bottom_tab 不点顶部的「我」",
    setup._tap_bottom_tab(_d1, "我") is False and _d1.clicks == [], str(_d1.clicks))

print("\n" + "=" * 74)
print("T7 switch_grade 元素优先：点中「切换课本」页里的年级节点")
print("=" * 74)


class _El:
    def __init__(self, text, bounds, dev):
        self.text = text
        self.bounds = list(bounds)
        self._dev = dev

    def click(self):
        self._dev._on_text(self.text)


class _XP:
    def __init__(self, els):
        self._els = els

    def all(self):
        return self._els


class _Node:
    def __init__(self, ok, text, dev):
        self._ok, self._text, self._dev = ok, text, dev

    def exists(self, timeout=0):
        return self._ok

    def click(self):
        self._dev._on_text(self._text)


class MockDev:
    """以"页面 XML + 迁移表"驱动的极简设备桩。click 既记录坐标、也触发迁移。"""

    def __init__(self, pages, start, text_trans=None, coord_trans=None, w=900, h=1600):
        self.pages, self.page = pages, start
        self.text_trans = text_trans or {}      # {(page, text): next_page}
        self.coord_trans = coord_trans or {}    # {(page, (x, y)): next_page}
        self.clicks, self.presses = [], []
        self.w, self.h = w, h

    def dump_hierarchy(self):
        return self.pages[self.page]

    def window_size(self):
        return (self.w, self.h)

    def click(self, x, y=None):
        if y is None and isinstance(x, (tuple, list)):
            x, y = x
        self.clicks.append((x, y))
        nxt = self.coord_trans.get((self.page, (x, y)))
        if nxt:
            self.page = nxt

    def press(self, k):
        self.presses.append(k)
        if k == "back":
            self.page = self.text_trans.get((self.page, "__back__"), self.page)

    def _on_text(self, text):
        nxt = self.text_trans.get((self.page, text))
        if nxt:
            self.page = nxt

    def xpath(self, expr):
        els = []
        for m in re.finditer(r"<node[^>]*>", self.pages[self.page]):
            tag = m.group(0)
            tm = re.search(r'text="([^"]*)"', tag)
            bm = re.search(r'bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"', tag)
            if not tm or not tm.group(1) or not bm:
                continue
            els.append(_El(tm.group(1), [int(bm.group(i)) for i in (1, 2, 3, 4)], self))
        return _XP(els)

    def __call__(self, text=None, **kw):
        return _Node(bool(text) and text in self.pages[self.page], text, self)


HOME_G = _xml([("switch_textbook_tv", "湘少版（2024审定）   三年级上册", (250, 250, 830, 300))])
GRADE_PAGE = _xml([(None, "切换课本", (250, 100, 830, 160)),
                   (None, "三年级上册", (200, 500, 420, 620)),
                   (None, "五年级上册", (200, 700, 420, 820))])
_dg = MockDev({"HOME": HOME_G, "GRADE": GRADE_PAGE}, "HOME",
              coord_trans={("HOME", (540, 275)): "GRADE"})   # rid 节点中心
chk("switch_grade 成功（用 switch_textbook_tv 打开页面）", setup.switch_grade(_dg, "五年级上册") is True)
chk("点的是年级节点中心 (310,760)", (310, 760) in _dg.clicks, str(_dg.clicks))
chk("【反向】没有走写死坐标兜底 (267,183)", (267, 183) not in _dg.clicks, str(_dg.clicks))
chk("页面也真的切到了 GRADE", _dg.page == "GRADE")

print("\n" + "=" * 74)
print("T8 【兜底】无 switch_textbook_tv 时仍走 S() 坐标并能成功")
print("=" * 74)
HOME_NOBAR = _xml([(None, "教材精学", (100, 600, 300, 660))])
_dg2 = MockDev({"HOME": HOME_NOBAR, "GRADE": GRADE_PAGE}, "HOME",
               coord_trans={("HOME", (267, 183)): "GRADE"})   # S(321,275) 在 900x1600 上
chk("switch_grade 兜底成功", setup.switch_grade(_dg2, "三年级上册") is True, str(_dg2.page))
chk("确实点了兜底坐标 S(321,275)=(267,183)", (267, 183) in _dg2.clicks, str(_dg2.clicks))

print("\n" + "=" * 74)
print("T9 switch_version 正常路径（元素优先 + 版本前缀匹配）")
print("=" * 74)
HOME_V = _xml([("switch_textbook_tv", "人教版(PEP)   三年级上册", (250, 250, 830, 300)),
               ("tab_me", "我", (830, 1480, 970, 1530))])
ME_PAGE = _xml([(None, "英语所学教材版本", (100, 400, 800, 460)),
                (None, "三年级上册", (100, 300, 800, 360))])
VLIST = _xml([(None, "湘少版(2024审定)", (100, 500, 800, 560)),
              (None, "人教版(PEP)", (100, 620, 800, 680))])
ME_AFTER = _xml([(None, "英语", (60, 2200, 200, 2290)),
                 (None, "三年级上册", (100, 300, 800, 360))])
_dv = MockDev({"HOME": HOME_V, "ME": ME_PAGE, "VLIST": VLIST, "ME_AFTER": ME_AFTER}, "HOME",
              text_trans={("ME", "英语所学教材版本"): "VLIST",
                          ("VLIST", "湘少版(2024审定)"): "ME_AFTER",
                          ("ME_AFTER", "__back__"): "ME_AFTER",
                          ("ME_AFTER", "英语"): "HOME"},
              coord_trans={("HOME", (900, 1505)): "ME"})   # 底部「我」tab 的中心
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    _r = setup.switch_version(_dv, "湘少版")
_out = _buf.getvalue()
chk("switch_version 返回 True", _r is True, _out[-300:])
chk("底部「我」按元素中心点击 (900,1505)", (900, 1505) in _dv.clicks, str(_dv.clicks))
chk("【反向】未使用写死坐标 (810,1480) 点「我」", (810, 1480) not in _dv.clicks, str(_dv.clicks))
chk("版本按前缀匹配到「湘少版(2024审定)」", "湘少版" in _out or _dv.page == "HOME", _out[-200:])
chk("最终回到主页", _dv.page == "HOME", _dv.page)
chk("按过一次 back 关闭面板", _dv.presses.count("back") >= 1, str(_dv.presses))

print("\n" + "=" * 74)
print("T10/T11 switch_version 失败路径：可读原因 + 返回 False")
print("=" * 74)
HOME_BAD = _xml([("switch_textbook_tv", "人教版(PEP)   三年级上册", (250, 250, 830, 300))])
_dv2 = MockDev({"HOME": HOME_BAD}, "HOME")   # 无「我」节点、也无坐标迁移
_buf2 = io.StringIO()
with contextlib.redirect_stdout(_buf2):
    _r2 = setup.switch_version(_dv2, "湘少版")
_out2 = _buf2.getvalue()
chk("失败返回 False", _r2 is False, _out2[-200:])
chk("打印了可读原因（含「切换版本失败」）", "切换版本失败" in _out2, _out2[-300:])
chk("原因指向具体步骤（底部「我」页）", "我" in _out2, _out2[-300:])

print("\n" + "=" * 74)
print(f"结果: {PASS} 通过 / {len(FAIL)} 失败")
print("=" * 74)
if FAIL:
    for _n in FAIL:
        print("  FAIL:", _n)
sys.exit(1 if FAIL else 0)
