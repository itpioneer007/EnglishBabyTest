# -*- coding: utf-8 -*-
"""探测：关卡地图页「上一单元 / 下一单元」能否切换 Unit（用于修正 Unit 定位策略）

背景：六上点「单词同步闯关」会因 App 记忆上次单元而直接落到 Unit 3 关卡地图，
      back 回主页重进仍回到 Unit 3 → 必须用页面内的切换按钮。
本脚本真机验证切换按钮可用性与每次切换后的页面状态。
"""
import sys, os, time, re
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))

import uiautomator2 as u2
from common.tools import close_ad, dismiss_global_popups, ensure_grade
from modules.巧记单词 import (
    _enter_qiaoji, _enter_sync_challenge, _is_unit_map, _current_map_unit,
)

APP_PACKAGE = "com.dinoenglish.yyb"


def snap(d):
    xml = d.dump_hierarchy()
    txts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
    return xml, txts


def main():
    d = u2.connect("SKSCIF4T7PFMQS5X")
    print("✅ 设备已连接", d.window_size())
    d.press("home"); time.sleep(0.5)
    d.app_stop(APP_PACKAGE); time.sleep(1)
    d.app_start(APP_PACKAGE); time.sleep(4)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d); time.sleep(1)
    print("年级:", ensure_grade(d, "六年级上册", "湘少版"))

    print("\n--- 进入巧记单词 → 单词同步闯关 ---")
    print("_enter_qiaoji:", _enter_qiaoji(d))
    print("_enter_sync_challenge:", _enter_sync_challenge(d))
    time.sleep(1.5)

    xml, txts = snap(d)
    print(f"落点: _is_unit_map={_is_unit_map(d, xml)} | _current_map_unit={_current_map_unit(d, xml)}")
    print("页面文本:", txts[:12])

    has_prev = '上一单元' in " ".join(txts)
    has_next = '下一单元' in " ".join(txts)
    print(f"切换按钮: 上一单元={has_prev} | 下一单元={has_next}")

    # 试切换：连续点「上一单元」最多 3 次，每次看 Unit 是否变化
    if has_prev:
        print("\n--- 连点「上一单元」观察 Unit 变化 ---")
        for i in range(3):
            ok = d(text="上一单元").exists(timeout=1.5)
            if not ok:
                print(f"  第{i+1}次: 按钮不存在，停止")
                break
            d(text="上一单元").click()
            time.sleep(1.6)
            xml, txts = snap(d)
            u = _current_map_unit(d, xml)
            print(f"  第{i+1}次点击后 → Unit {u} | {txts[:3]}")
    else:
        print("\n⚠ 页面无「上一单元」按钮")

    print("\n--- 反向：连点「下一单元」1 次 ---")
    if d(text="下一单元").exists(timeout=1.5):
        d(text="下一单元").click()
        time.sleep(1.6)
        xml, txts = snap(d)
        print(f"  点击后 → Unit {_current_map_unit(d, xml)} | {txts[:3]}")
    else:
        print("  ⚠ 无「下一单元」按钮")

    return 0


if __name__ == "__main__":
    sys.exit(main())
