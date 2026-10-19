# -*- coding: utf-8 -*-
"""真机验证：问题三 · 闯关地图 Unit 选择步骤（六上）

验证点：
  1. _is_unit_map 能在真机识别「闯关地图」
  2. _enter_unit_from_map 点击目标 Unit 后，确实进入「单元闯关界面」
     （出现关卡数字 / boss关 → _find_level_positions 非空）
"""
import sys, os, time, re
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))

import uiautomator2 as u2
from common.tools import close_ad, dismiss_global_popups, ensure_grade
from modules.巧记单词 import (
    _enter_qiaoji, _enter_sync_challenge, _is_unit_map,
    _enter_unit_from_map, _find_level_positions,
)

APP_PACKAGE = "com.dinoenglish.yyb"
TARGET_UNIT = 3   # 选中间偏后的 Unit 验证定位准确度


def dump_texts(d, n=30):
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return []
    return [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()][:n]


def _pick_serial():
    """选择要连接的真实设备（不再写死作者的真机串号）。

    ★ 2026-10-19：原写法在别人的电脑上必然报 "device not online"，
      这条验证于是永远跑不起来，被当成"环境问题"忽略。
    顺序：ANDROID_SERIAL → 在线真机 → 在线任意设备 → 空（u2 默认）。
    """
    s = os.environ.get("ANDROID_SERIAL", "").strip()
    if s:
        return s
    try:
        from adbutils import adb
        devs = [x.serial for x in adb.device_list()]
        real = [x for x in devs if ":" not in x]
        return (real or devs or [""])[0]
    except Exception:
        return ""


def main():
    _serial = _pick_serial()
    print("  目标设备:", _serial or "(u2 默认)")
    d = u2.connect(_serial) if _serial else u2.connect()
    print("✅ 设备已连接", d.window_size())
    d.press("home"); time.sleep(0.5)
    d.app_stop(APP_PACKAGE); time.sleep(1)
    d.app_start(APP_PACKAGE); time.sleep(4)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d); time.sleep(1)
    print("年级:", ensure_grade(d, "六年级上册", "湘少版"))

    print("\n--- 进入巧记单词 ---")
    print("_enter_qiaoji:", _enter_qiaoji(d))
    print("_enter_sync_challenge:", _enter_sync_challenge(d))
    time.sleep(1.5)

    # 验证点 1：识别闯关地图
    on_map = _is_unit_map(d)
    print(f"\n[验证1] _is_unit_map = {on_map}  {'✅' if on_map else '❌'}")
    print("   页面文本:", dump_texts(d, 12))
    if not on_map:
        print("❌ 未识别为闯关地图，终止")
        return 1

    # 验证点 2：选择 Unit N → 进入单元闯关界面
    print(f"\n[验证2] 选择 Unit {TARGET_UNIT} …")
    t0 = time.time()
    ok = _enter_unit_from_map(d, TARGET_UNIT)
    print(f"   点击结果: {ok}, 耗时 {time.time()-t0:.1f}s")
    time.sleep(1.5)
    print("   进入后页面文本:", dump_texts(d, 20))

    # 判定：进入了单元闯关界面（有关卡位置 / boss关）
    pos = _find_level_positions(d)
    nums = sorted(n for n in pos if n > 0)
    has_boss = 0 in pos
    txts = " ".join(dump_texts(d, 30))
    entered = bool(nums) or has_boss or ("闯关" in txts and "地图" not in txts)
    print(f"\n[验证3] 单元闯关界面特征: 关卡数字={nums}, boss关={has_boss}")
    print(f"   → 进入单元闯关界面: {'✅ 是' if entered else '❌ 否'}")
    if pos:
        print(f"   关卡位置表: { {k: v for k, v in sorted(pos.items())} }")

    print("\n" + "=" * 55)
    print(f"结论: 闯关地图识别={on_map} | Unit{TARGET_UNIT}点击={ok} | 进入闯关界面={entered}")
    print("=" * 55)
    return 0 if (on_map and ok and entered) else 1


if __name__ == "__main__":
    sys.exit(main())
