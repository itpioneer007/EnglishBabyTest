"""
英语宝 · 语音评测 模块（题目未做好，目前只进入模块）
================================================
入口流程：
1. 主页 → 教材精学 → 「语音评测」卡片（722,1114)-(1031,1269)，中心 877,1192
2. 进入「语音评测」页面（简介/目录 tab，暂无数据）

题型未做好，本模块只负责进入。

批量调用：from modules.语音评测 import run_module; run_module(d)
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

# 主页「语音评测」卡片位置（教材精学第一行第 3 张）
VOICE_CARD = (877, 1192)


def _enter_voice_eval(d):
    """主页 → 教材精学 → 语音评测卡片"""
    # 确认主页
    for _ in range(5):
        if d(text="教材精学").exists(timeout=1):
            break
        d.press("back"); time.sleep(1.5)
    d.click(*VOICE_CARD)
    print(f"    ✅ 点语音评测卡片")
    time.sleep(4)
    # 页面标题是图片（没有"语音评测"文字），通过内容特征判断：
    # 有"简介/目录" tab + "学习进度" + "暂无数据" 或教材名
    for kw in ("学习进度", "暂无数据", "简介"):
        if d(text=kw).exists(timeout=2):
            return True
    print(f"    ❌ 未进入语音评测页")
    return False


def run_module(d):
    """核心入口：进入语音评测模块"""
    t0 = time.time()
    print(f"\n📋 语音评测 · 进入模块")
    if not _enter_voice_eval(d):
        return 0
    # 题目未做好，停留几秒后返回主页
    time.sleep(2)
    print(f"✅ 语音评测进入完成, 耗时 {time.time()-t0:.0f}s")
    return 1


def main():
    d = u2.connect()
    print("✅ 设备已连接")
    d.press("home"); time.sleep(1)
    d.app_stop(APP_PACKAGE); time.sleep(2)
    d.app_start(APP_PACKAGE); time.sleep(8)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败")
        return 1
    run_module(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())