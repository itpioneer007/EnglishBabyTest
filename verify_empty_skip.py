# -*- coding: utf-8 -*-
"""真机验证：问题一 · 五下「本书籍暂无巧记单词」智能识别 + 快速跳过

验证点：
  1. 切到湘少版五年级下册后，巧记单词页能被 _qiaoji_empty_reason 识别为无内容
  2. run_module 在该情形下【快速返回 0】（不再卡住），且日志有明确报告
  3. 返回 0 → 调度器会继续下一个模块
"""
import sys, os, time, re
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))

import uiautomator2 as u2
from common.tools import close_ad, dismiss_global_popups, ensure_grade
from common.logger import set_log_callback
from modules.巧记单词 import (
    _enter_qiaoji, _enter_sync_challenge, _qiaoji_empty_reason, run_module,
)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE = "五年级下册"
_logs = []


def _cap(msg, level="info", evidence=None):
    _logs.append(f"[{level}] {msg}")
    print(f"    📋 {msg}")


def main():
    set_log_callback(_cap)
    d = u2.connect("SKSCIF4T7PFMQS5X")
    print("✅ 设备已连接", d.window_size())
    d.press("home"); time.sleep(0.5)
    d.app_stop(APP_PACKAGE); time.sleep(1)
    d.app_start(APP_PACKAGE); time.sleep(4)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d); time.sleep(1)

    print(f"\n--- 切换到 {GRADE} ---")
    ok = ensure_grade(d, GRADE, "湘少版")
    print("年级切换:", ok)
    time.sleep(1.5)
    if not ok:
        print("❌ 年级切换失败，终止")
        return 1

    # 验证点 1：单独调用检测函数
    print("\n--- 进入巧记单词 ---")
    ent = _enter_qiaoji(d)
    print("_enter_qiaoji:", ent)
    time.sleep(1)
    xml = d.dump_hierarchy()
    txts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
    print("   页面文本:", txts[:20])

    reason = _qiaoji_empty_reason(d)
    print(f"\n[验证1] _qiaoji_empty_reason = {reason!r}")
    print(f"   {'✅ 识别为无内容' if reason else '⚠ 判定为有内容'}")

    # 验证点 2：run_module 端到端（计时，必须快速返回且日志有报告）
    print("\n[验证2] 调用 run_module（验证快速跳过 + 日志报告）…")
    _logs.clear()
    t0 = time.time()
    # 从主页状态重跑一遍完整入口流程（模拟调度器调用）
    back_ok = _enter_qiaoji(d)
    print(f"   重新进入巧记单词: {back_ok}")
    t1 = time.time()
    q = run_module(d, units=[1])
    elapsed = time.time() - t0
    print(f"\n   → run_module 返回题数 = {q}, 总耗时 {elapsed:.1f}s")
    print(f"   → 日志条数 = {len(_logs)}")
    for l in _logs:
        print(f"      {l}")

    has_report = any(("暂无" in l or "跳过本模块" in l or "无巧记单词" in l) for l in _logs)
    fast = elapsed < 60     # 应从"卡住很久"变为快速返回
    print("\n" + "=" * 58)
    print(f"[验证1] 无内容识别: {'✅' if reason else '❌'}")
    print(f"[验证2] 返回 0 题: {'✅' if q == 0 else '❌'} ({q})")
    print(f"[验证3] 日志有明确报告: {'✅' if has_report else '❌'}")
    print(f"[验证4] 快速返回(<60s): {'✅' if fast else '❌'} ({elapsed:.1f}s)")
    print("=" * 58)
    return 0 if (reason and q == 0 and has_report and fast) else 1


if __name__ == "__main__":
    sys.exit(main())
