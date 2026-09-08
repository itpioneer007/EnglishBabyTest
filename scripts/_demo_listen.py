# -*- coding: utf-8 -*-
"""真机演示：选一个有听力专项的版本/年级 → 点进听力专项 → 实际做练习并出证据截图。
演示目标：湘少版 / 三年级上册（已确认该年级有听力专项）。
入口与答题均由模块自带的 run_single_module / _answer_loop 完成（多策略点击兜底）。
"""
import os
import sys
import time

BASE = r"C:\Users\yangj\Desktop\EnglishBabyTest-yangjiangliu"
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)

import uiautomator2 as u2
u2.HTTP_TIMEOUT = 30
u2.IMPLICIT_WAIT = 2

from common.setup import switch_version_grade, _current_texts, _is_home, _back_home
from common.tools import settle_ads, scroll_and_find, S
from engine import run_single_module as _orig_run_single_module, _answer_loop as _orig_answer_loop
import engine
import modules.听力专项 as LM

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
APP = "com.dinoenglish.yyb"
SHOT_DIR = os.path.join(BASE, "screenshots", "demo")
os.makedirs(SHOT_DIR, exist_ok=True)

_state = {"entered_shot": False, "answer_shot": False}


def shot(d, name):
    try:
        p = os.path.join(SHOT_DIR, name)
        d.screenshot(p)
        print(f"    📸 截图: {p}")
        return p
    except Exception as e:
        print(f"    ⚠ 截图失败 {name}: {e}")
        return None


# ★ 注入：进入模块后（首次答题循环）截一张"正在做题"证据图
def _patched_answer_loop(d, config, name):
    if not _state["answer_shot"]:
        _state["answer_shot"] = True
        shot(d, "02_doing_exercise.png")
    return _orig_answer_loop(d, config, name)


engine._answer_loop = _patched_answer_loop


def main():
    d = u2.connect(SERIAL)
    d.unlock(); time.sleep(1)
    print("\n========== [0] 启动 App 并清广告 ==========")
    d.press("home"); time.sleep(0.4)
    d.app_stop(APP); time.sleep(0.8)
    d.app_start(APP); time.sleep(3.0)
    settle_ads(d, wait_total=12)
    if not _is_home(d):
        _back_home(d); time.sleep(1.0)

    print("\n========== [1] 切到 湘少版 / 三年级上册（有听力专项）==========")
    ok = switch_version_grade(d, "湘少版", "三年级上册")
    v, g = _current_texts(d)
    print(f"    切换结果: {'PASS' if ok else 'FAIL'} | 当前 {v!r} / {g!r}")
    shot(d, "01_home.png")

    print("\n========== [2] 正式进入听力专项并做 Unit1 练习 ==========")
    t0 = time.time()
    cfg = dict(LM.CONFIG)
    cfg["units"] = [1]
    q = _orig_run_single_module(d, "听力专项", cfg)
    print(f"    练习 Unit1 作答题数: {q}")
    shot(d, "03_after_practice.png")

    print(f"\n========== 完成 ==========")
    print(f"    结果: {'成功点进并做题' if q > 0 else '未进入/未作答'} | 共 {q} 题, 耗时 {time.time()-t0:.0f}s")
    print(f"    截图目录: {SHOT_DIR}")
    return 0 if q > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
