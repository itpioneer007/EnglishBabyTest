# -*- coding: utf-8 -*-
r"""★ 2026-10-16 回归测试：语音评测答题页按钮改为 resource-id 动态定位（设备无关）

━━━ 背景（用户提问）━━━
「为什么前端用真机时每个坐标都很精确，切到 MuMu 里检测就不准了？」
排查结论：坐标层用「像素比例」换算（web_server.RES/scale、common/tools.S），
但 Android 布局按 dp 排布，而两台设备的 dp 尺寸根本不同：

    真机  1080x2400 px @ density 3.0  ->  360x800 dp    宽高比 9:20
    MuMu   900x1600 px @ density 1.5  ->  600x1067 dp   宽高比 9:16

屏幕 dp 变大，但控件自身的 dp 尺寸（字号/按钮高/边距）不变 -> 布局是【重排】
而非等比例拉伸 -> 不存在任何全局 (sx, sy) 能把真机像素坐标映射到模拟器。

真机之所以精确：缩放基准 REFERENCE_RES=(1080,2400) 就是真机分辨率，
scale=(1.000, 1.000) 退化为恒等变换（web_server.py:6833 的历史注释已记录）。

━━━ 本次修的具体故障（在 MuMu 上必然点空）━━━
scripts/modules/语音评测.py 有三处点击直接写死真机像素、且未过任何换算：
    BTN_RECORD_LAYOUT  -> (540, 975)     出现 2 次（点录音 / 超时兜底）
    BTN_CONFIRM_REPORT -> (540, 2145)    出现 1 次（完成并获取报告）
  - (540, 2145) 的 y 已超出 MuMu 屏高 1600 -> 点到屏幕外
  - (540, 975) 的 x 是真机 1080 的中线，900 宽的模拟器中线是 450 -> 偏右 90px

━━━ 修法 ━━━
新增 _rid_center(d, rid)：解析 dump_hierarchy 中节点自报的 bounds 取中心。
坐标由 App 在当前设备上给出 -> 与分辨率 / density 无关，真机与模拟器通用。
定位失败时退回 S() 比例换算并留 warning（不比原来更差，且留痕可查）。

━━━ 本测试锁定 ━━━
  T1 中心解析         ：bounds -> 中心；分别用真机 / MuMu 两组 bounds
  T2 精确匹配         ：完整包名命中；【反向】xxx_record_layout / record_layout_2 不误匹配
  T3 找不到返回 None  ：空 XML / XML 中无目标 id
  T4 单次模式零 dump  ：传 xml 时不额外 dump（calls == 0）
  T5 轮询模式         ：前两次空、第三次出现 -> 能等到；dump 次数 >= 3
  T6 dump 异常不崩    ：dump 抛异常 -> 返回 None，不向上抛
  T7 【反向】旧坐标出界：BTN_CONFIRM_REPORT y=2145 > MuMu 屏高 1600（钉死修复必要性）
  T8 源码静态检查     ：不再有裸点 d.click(*BTN_...)；三处均走 _rid_center
  T9 兜底仍在         ：S(d, *BTN_...) 比例换算兜底未被顺手删掉

运行：python scripts/tests/test_fix_20261016_voice_btn_dynamic.py
"""
import os
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)

# 不连手机：stub uiautomator2（本测试全程用 FakeD）
_u2 = types.ModuleType("uiautomator2")
sys.modules["uiautomator2"] = _u2

from modules import 语音评测 as m                # noqa: E402

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


# ══════════════════ 夹具：真机 / MuMu 两组 bounds（属性顺序与真机 dump 一致）══════════════════
def node(rid, bounds, text=""):
    return (f'<node index="0" text="{text}" resource-id="{rid}" '
            f'class="android.widget.Button" clickable="true" bounds="{bounds}"/>')


def xml_of(*nodes):
    return '<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"


# 同一控件 record_layout，在两台设备上 bounds 完全不同（由 App 自报）
REAL_XML = xml_of(
    node("com.dinoenglish.yyb:id/title", "[30,100][1050,180]"),
    node("com.dinoenglish.yyb:id/record_layout", "[330,900][570,1050]"),
)
MUMU_XML = xml_of(
    node("com.dinoenglish.yyb:id/title", "[30,100][870,180]"),
    node("com.dinoenglish.yyb:id/record_layout", "[330,600][570,700]"),
)


class FakeD:
    """假设备：按序吐出 dump 结果；calls 记录 dump 调用次数"""

    def __init__(self, seq=None, raise_exc=False):
        self.seq = list(seq or [])
        self.calls = 0
        self.raise_exc = raise_exc

    def dump_hierarchy(self):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("device offline")
        return self.seq.pop(0) if self.seq else ""


print("=" * 74)
print("T1 中心解析（bounds -> 中心）")
print("=" * 74)
chk("真机 [330,900][570,1050] -> (450,975)",
    m._rid_center(FakeD(), "record_layout", xml=REAL_XML) == (450, 975),
    str(m._rid_center(FakeD(), "record_layout", xml=REAL_XML)))
chk("MuMu [330,600][570,700] -> (450,650)",
    m._rid_center(FakeD(), "record_layout", xml=MUMU_XML) == (450, 650),
    str(m._rid_center(FakeD(), "record_layout", xml=MUMU_XML)))

print()
print("=" * 74)
print("T2 resource-id 精确匹配（短名，不是子串）")
print("=" * 74)
_SUB = xml_of(
    node("com.dinoenglish.yyb:id/xxx_record_layout", "[0,0][10,10]"),
    node("com.dinoenglish.yyb:id/record_layout_2", "[20,20][40,40]"),
)
chk("【反向】xxx_record_layout 不误匹配", m._rid_center(FakeD(), "record_layout", xml=_SUB) is None)
chk("【反向】record_layout_2 不误匹配", m._rid_center(FakeD(), "record_layout", xml=_SUB) is None)
_MIX = xml_of(
    node("com.dinoenglish.yyb:id/xxx_record_layout", "[0,0][10,10]"),
    node("com.dinoenglish.yyb:id/record_layout", "[100,100][300,300]"),
)
chk("同页混排时取精确匹配的那个 -> (200,200)",
    m._rid_center(FakeD(), "record_layout", xml=_MIX) == (200, 200),
    str(m._rid_center(FakeD(), "record_layout", xml=_MIX)))

print()
print("=" * 74)
print("T3 找不到时返回 None（不返回硬编码兜底）")
print("=" * 74)
chk("空 XML -> None", m._rid_center(FakeD(), "record_layout", xml="") is None)
chk("XML 中无目标 id -> None",
    m._rid_center(FakeD(), "speech_btn_confirm", xml=MUMU_XML) is None)

print()
print("=" * 74)
print("T4 单次模式：传 xml 时不做额外 dump")
print("=" * 74)
_d4 = FakeD([MUMU_XML])
_r4 = m._rid_center(_d4, "record_layout", xml=MUMU_XML)
chk(f"结果正确且 dump 次数为 0（实际 {_d4.calls}）", _r4 == (450, 650) and _d4.calls == 0)

_d4b = FakeD([MUMU_XML])
m._rid_center(_d4b, "record_layout", xml="")
chk(f"【反向】传空 xml 时也不 dump（实际 {_d4b.calls}）", _d4b.calls == 0)

print()
print("=" * 74)
print("T5 轮询模式：控件延迟出现时能等到")
print("=" * 74)
_d5 = FakeD(["", "", MUMU_XML])
_r5 = m._rid_center(_d5, "record_layout", timeout=2.0, poll=0.02)
chk(f"前两次空、第三次出现 -> 命中 (450,650)（dump {_d5.calls} 次）",
    _r5 == (450, 650) and _d5.calls >= 3, str(_r5))

_d5b = FakeD(["", ""])
_r5b = m._rid_center(_d5b, "record_layout", timeout=0.3, poll=0.02)
chk("【反向】始终不出现 -> 超时返回 None", _r5b is None)

print()
print("=" * 74)
print("T6 dump 抛异常时不崩（设备瞬断）")
print("=" * 74)
try:
    _r6 = m._rid_center(FakeD(raise_exc=True), "record_layout", timeout=0.3, poll=0.02)
    _ok6 = _r6 is None
    _d6 = ""
except Exception as _e:                                   # noqa: BLE001
    _ok6 = False
    _d6 = f"向上抛了 {type(_e).__name__}: {_e}"
chk("dump 持续抛异常 -> 返回 None 且不向上抛", _ok6, _d6)

print()
print("=" * 74)
print("T7 【反向】旧的真机固定坐标确实不适合模拟器（钉死修复必要性）")
print("=" * 74)
chk(f"旧 BTN_CONFIRM_REPORT y={m.BTN_CONFIRM_REPORT[1]} > MuMu 屏高 1600（点在屏外）",
    m.BTN_CONFIRM_REPORT[1] > 1600)
chk(f"旧 BTN_RECORD_LAYOUT x={m.BTN_RECORD_LAYOUT[0]} 在 900 宽上偏右 {m.BTN_RECORD_LAYOUT[0] - 450}px",
    abs(m.BTN_RECORD_LAYOUT[0] - 450) > 50)

print()
print("=" * 74)
print("T8 源码静态检查：三处调用点不再裸用固定坐标")
print("=" * 74)
_src = open(os.path.join(SCRIPTS, "modules", "语音评测.py"), encoding="utf-8").read()
chk("源码中不再出现裸点 d.click(*BTN_...)", "d.click(*BTN_" not in _src)
_n_dyn = _src.count('_rid_center(d, "')
chk(f"_rid_center 动态定位调用 3 处（实际 {_n_dyn}）", _n_dyn == 3)
chk('点录音走动态定位 record_layout', '_rid_center(d, "record_layout"' in _src)
chk('点报告走动态定位 speech_btn_confirm', '_rid_center(d, "speech_btn_confirm"' in _src)

print()
print("=" * 74)
print("T9 兜底仍在：定位失败时退回 S() 比例换算（且留 warning）")
print("=" * 74)
chk("record_layout 兜底 S(d, *BTN_RECORD_LAYOUT)", "S(d, *BTN_RECORD_LAYOUT)" in _src)
chk("speech_btn_confirm 兜底 S(d, *BTN_CONFIRM_REPORT)", "S(d, *BTN_CONFIRM_REPORT)" in _src)
chk("兜底路径有 step_log warning 留痕", _src.count("改为按屏幕比例定位") >= 2)

print()
print("=" * 74)
print(f"PASS {PASS} / FAIL {FAIL}")
print("=" * 74)
sys.exit(1 if FAIL else 0)
