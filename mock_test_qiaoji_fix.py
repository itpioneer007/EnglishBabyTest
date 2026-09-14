# -*- coding: utf-8 -*-
"""Mock 验证：问题一（无内容识别）+ 问题三（闯关地图 Unit 选择）

用真机 dump 出的真实 XML（scripts/screenshots/unit_map_dump.xml）作为输入，
验证定位逻辑正确性，不需要连设备。
"""
import sys, os, re
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))

from modules.巧记单词 import _is_unit_map, _enter_unit_from_map, _qiaoji_empty_reason, _UNIT_CARD_RE

PASS, FAIL = [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  ({detail})" if detail else ""))

# ---------- 真实闯关地图 XML（由 probe_unit_map.py 真机 dump 生成） ----------
_map_xml_path = os.path.join(_here, "scripts", "screenshots", "unit_map_dump.xml")
if not os.path.exists(_map_xml_path):
    print(f"⚠ 缺少真机 dump 样本 {_map_xml_path}")
    print("   请先运行: python probe_unit_map.py （重新采集闯关地图 XML）")
    sys.exit(2)
with open(_map_xml_path, encoding="utf-8") as f:
    REAL_MAP_XML = f.read()


class _NoSuchEl:
    """模拟"元素不存在"（d(text=..).exists() → False）"""
    def exists(self, timeout=0):
        return False
    def click(self):
        pass


class MockDevice:
    """最小 mock：只实现被调用到的接口"""
    def __init__(self, xml):
        self._xml = xml
        self.clicked = []
        self.swipes = 0
    def dump_hierarchy(self):
        return self._xml
    def window_size(self):
        return (1080, 2400)
    def click(self, x, y):
        self.clicked.append((x, y))
    def press(self, key):
        pass
    def __call__(self, *a, **kw):
        return _NoSuchEl()


print("=" * 62)
print("【测试组 1】问题三 · 闯关地图识别 _is_unit_map")
print("=" * 62)
check("真实闯关地图 XML → True", _is_unit_map(None, REAL_MAP_XML) is True)

# 普通关卡地图（无 Unit 卡片）应判 False，避免误把旧版当闯关地图
OLD_STYLE_XML = '''<hierarchy><node text="第1关"/><node text="boss关"/>
<node text="1"/><node text="2"/><node text="3"/></hierarchy>'''
check("旧版关卡地图 XML → False（不误判）", _is_unit_map(None, OLD_STYLE_XML) is False)
check("空 XML → False", _is_unit_map(None, "") is False)

units_found = sorted(int(m.group(1)) for m in _UNIT_CARD_RE.finditer(REAL_MAP_XML))
check(f"提取到 Unit 卡片 {units_found}", units_found == list(range(1, 11)))

print()
print("=" * 62)
print("【测试组 2】问题三 · Unit 定位点击 _enter_unit_from_map")
print("=" * 62)
# 预期坐标来自真机 dump 的卡片 bounds 中心
EXPECT = {
    1: ((783 + 982) // 2, (1965 + 2167) // 2),   # (882, 2066)
    3: ((554 + 753) // 2, (1662 + 1864) // 2),   # (653, 1763)
    5: ((245 + 444) // 2, (1334 + 1536) // 2),   # (344, 1435)
    7: ((81 + 280) // 2, (965 + 1167) // 2),     # (180, 1066)
    10: ((153 + 352) // 2, (461 + 663) // 2),    # (252, 562)
}
for u, exp in EXPECT.items():
    md = MockDevice(REAL_MAP_XML)
    ok = _enter_unit_from_map(md, u, max_swipes=0)   # 不滑动，直接定位
    got = md.clicked[0] if md.clicked else None
    check(f"Unit {u} → 点击 {got}（预期 {exp}）", ok and got == exp)
    # 关键：一次成功，不应该有滑动（之前是盲滑）
    check(f"Unit {u} 无多余滑动", md.swipes == 0)

print()
print("=" * 62)
print("【测试组 3】问题一 · 无内容识别 _qiaoji_empty_reason")
print("=" * 62)

# 五下真实形态：气泡「本书籍暂无巧记单词」+ 进度全 0/0（文本节点分离）
XML_WUXIA = '''<hierarchy>
<node text="巧记单词"/><node text="湘少版（2024审定）五年级下册"/>
<node text="掌握"/><node text="0"/><node text="/0"/><node text="词"/>
<node text="你已通关"/><node text="0/0关"/>
<node text="你已获星"/><node text="0/0颗"/>
<node text="本书籍暂无巧记单词"/>
<node text="单词同步闯关"/>
</hierarchy>'''
r = _qiaoji_empty_reason(MockDevice(XML_WUXIA))
check("五下（气泡+全0/0）→ 判定无内容", bool(r), f"原因={r!r}")

# 六上真机形态：掌握 0 /143 词（有内容）→ 必须判为"有内容"，不能误杀
XML_LIUSHANG = '''<hierarchy>
<node text="巧记单词"/><node text="湘少版（2024审定）六年级上册"/>
<node text="掌握"/><node text="0"/><node text="/143"/><node text="词"/>
<node text="你已通关"/><node text="0/50关"/>
<node text="你已获星"/><node text="0/150颗"/>
<node text="单词同步闯关"/><node text="单词分类复习"/>
</hierarchy>'''
r2 = _qiaoji_empty_reason(MockDevice(XML_LIUSHANG))
check("六上（掌握 0/143 词）→ 判为有内容（不误杀）", r2 == "", f"返回={r2!r}")

# 仅气泡无进度（部分年级只弹气泡）
XML_ONLY_BUBBLE = '''<hierarchy><node text="本书籍暂无巧记单词"/><node text="单词同步闯关"/></hierarchy>'''
check("仅气泡（无进度数据）→ 判定无内容",
      bool(_qiaoji_empty_reason(MockDevice(XML_ONLY_BUBBLE))))

# 正常有进度不误判
XML_NORMAL = '''<hierarchy><node text="掌握"/><node text="8"/><node text="/20"/><node text="词"/>
<node text="你已通关"/><node text="3/6关"/></hierarchy>'''
check("正常进度（掌握 8/20 词）→ 有内容",
      _qiaoji_empty_reason(MockDevice(XML_NORMAL)) == "")

print()
print("=" * 62)
print("【测试组 4】关卡枚举 _run_one_unit（旧公式会导致漏关+重复）")
print("=" * 62)
import modules.巧记单词 as Q

_calls = []
_orig = (Q._run_one_level, Q._find_level_positions)

# 真机实测 Unit 3 关卡地图：数字关 12~16 + boss(0)
FAKE_POS = {12: (681, 1593), 13: (767, 1312), 14: (583, 1096),
            15: (346, 923), 16: (313, 642), 0: (529, 318)}
Q._find_level_positions = lambda d: FAKE_POS
Q._run_one_level = lambda d, lv: (_calls.append(lv), 5)[1]

Q._run_one_unit(MockDevice(""), 3, start_level=13)   # 旧公式给的起始值 13
Q._run_one_level, Q._find_level_positions = _orig    # 还原

print(f"   实际进入的关卡序列: {_calls}")
check("依次覆盖页面上的 12~16（不漏第12关）", _calls[:5] == [12, 13, 14, 15, 16])
check("不重复点击同一关卡", len(_calls) == len(set(_calls)))
check("末尾进入 boss 关(0)", _calls[-1] == 0)
# 对照：旧公式 start_level=13 → 13,14,15,16,17，其中 17 不存在
print(f"   （旧公式会产生: [13, 14, 15, 16, 17] → 漏 12 关、17 兜底重复 16 关）")

print()
print("=" * 62)
print("【测试组 5】Unit 切换 _ensure_target_unit / _switch_unit_by_arrows")
print("=" * 62)
print("   场景：App 记忆上次 Unit，落点与目标不一致时用箭头逐级切换")


class _Btn:
    """绑定到设备状态的按钮（exists/click 随 Unit 变化）"""
    def __init__(self, dev, label):
        self.dev, self.label = dev, label
    def exists(self, timeout=0):
        return self.dev.has_btn(self.label)
    def click(self):
        self.dev.click_btn(self.label)


class MapMockDevice:
    """模拟「单元关卡地图」页：有 boss关 / Unit N 标题 / 上一单元 / 下一单元

    状态化：点「上一单元」→ unit-1；点「下一单元」→ unit+1；
    到边界（unit==1 / unit==max_unit）时对应按钮消失（与真机一致）。
    """
    def __init__(self, unit, max_unit=10):
        self.unit, self.max_unit = unit, max_unit
        self.click_log = []
    def has_btn(self, label):
        if label == "上一单元":
            return self.unit > 1
        if label == "下一单元":
            return self.unit < self.max_unit
        return False
    def click_btn(self, label):
        if label == "上一单元":
            self.unit -= 1
        elif label == "下一单元":
            self.unit += 1
        self.click_log.append((label, self.unit))
    def dump_hierarchy(self):
        t = ["boss关", f"Unit {self.unit} Test", "34", "33"]
        if self.unit > 1:
            t.append("上一单元")
        if self.unit < self.max_unit:
            t.append("下一单元")
        return "<hierarchy>" + "".join(f'<node text="{x}"/>' for x in t) + "</hierarchy>"
    def window_size(self):
        return (1080, 2400)
    def __call__(self, *a, **kw):
        return _Btn(self, kw.get("text") or (a[0] if a else ""))
    def press(self, k):
        pass


# ① 已在目标 Unit → 零点击直接通过
md = MapMockDevice(unit=1)
check("已在 Unit 1 → 直接 True（不点任何按钮）",
      Q._ensure_target_unit(md, 1) is True and md.click_log == [],
      f"点击={md.click_log}")

# ② Unit 3 → 目标 1：点 2 次「上一单元」
md = MapMockDevice(unit=3)
ok = Q._ensure_target_unit(md, 1)
check("Unit 3 → 目标 1（点 2 次上一单元）", ok is True and md.unit == 1,
      f"点击序列={md.click_log}")

# ③ Unit 1 → 目标 3：点 2 次「下一单元」（反向）
md = MapMockDevice(unit=1)
ok = Q._ensure_target_unit(md, 3)
check("Unit 1 → 目标 3（点 2 次下一单元）", ok is True and md.unit == 3,
      f"点击序列={md.click_log}")

# ④ Unit 2 → 目标 5：点 3 次「下一单元」
md = MapMockDevice(unit=2)
ok = Q._ensure_target_unit(md, 5)
check("Unit 2 → 目标 5（点 3 次下一单元）", ok is True and md.unit == 5,
      f"点击序列={md.click_log}")

# ⑤ 边界：Unit 1 无法再「上一单元」→ 应失败而非死循环
md = MapMockDevice(unit=1)
ok = Q._ensure_target_unit(md, 0, max_try=2)
check("边界 Unit 1 → 目标 0 不可达时安全失败（不死循环）", ok is False,
      f"当前 Unit={md.unit}, 点击={md.click_log}")

# ⑥ 单次切换函数直接验证
md = MapMockDevice(unit=3)
check("_switch_unit_by_arrows(3→1)", Q._switch_unit_by_arrows(md, 3, 1) is True and md.unit == 1)
md = MapMockDevice(unit=1)
check("_switch_unit_by_arrows(1→1) 同 Unit 直接 True",
      Q._switch_unit_by_arrows(md, 1, 1) is True and md.click_log == [])

print()
print("=" * 62)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("   -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
