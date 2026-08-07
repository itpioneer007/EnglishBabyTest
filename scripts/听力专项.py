"""
英语宝 · 听力专项 自动化流程
============================
独立可运行文件：python 听力专项.py

流程：
  启动 → 关广告 → 确认年级 → 进听力专项
  → 遍历 U1-U9：点"去练习" → 基础巩固 → 左滑 → 综合进阶 → 左滑 → 难点突破
  → 每个子模块答完 → 练习报告 → 继续练习(前2个) / back(最后1个)
  → 回主页
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomator2 as u2
from engine import (
    close_ad, dismiss_global_popups, ensure_grade, run_single_module,
    execute_actions, back_to_home, scroll_and_find,
)

# ═══════════ 听力专项配置 ═══════════
APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

# 单元遍历范围: 由环境变量 YYB_UNIT_FROM/TO 控制 (scheduler设置), 默认 Unit 1

def _env_units():
    """从环境变量读取单元范围 (由 scheduler 设置); 未设置时默认 Unit 1"""
    f = os.environ.get("YYB_UNIT_FROM", "")
    t = os.environ.get("YYB_UNIT_TO", "")
    if f.isdigit():
        f = int(f)
        t = int(t) if t.isdigit() else f
        return list(range(f, t + 1))
    return [1]

UNITS = _env_units()

MODULE_CONFIG = {
    "entry_text": "听力专项",
    "units": UNITS,                       # 由 unit loop 点击去练习
    "entry_actions": [],
    "sub_modules": [
        {"name": "基础巩固", "enter_action": None},
        {"name": "综合进阶", "enter_action": "swipe_left_sub"},
        {"name": "难点突破",  "enter_action": "swipe_left_sub"},
    ],
    "post_entry_actions": [
        {"type": "click", "text": "开始答题", "timeout": 1},
        {"type": "click", "text": "重新答题", "timeout": 1},
    ],
    "report_action": {
        "trigger": {"type": "click", "text": "练习报告"},
        "after_report": [
            {"type": "click", "text": "继续练习", "timeout": 3},
        ],
    },
    "next_button_texts": ["下一题", "继续"],
    "finish_texts": ["完成", "提交"],
    "empty_text": ["暂无数据"],
    "has_pagination": True,
    "question_types": {
        "sort": {
            "detect_text": ["排序", "按顺序", "排序题", "给句子排序"],
            "action": "sort_questions",
        },
        "match": {
            "detect_text": ["匹配", "配对", "为人物选择", "选择正确的描述"],
            "action": "match_questions",
        },
    },
}


def main():
    d = u2.connect()
    print("✅ 设备已连接")

    # 1. 重启 App 回主页
    d.press("home"); time.sleep(1)
    d.app_stop(APP_PACKAGE); time.sleep(2)
    d.app_start(APP_PACKAGE); time.sleep(8)

    # 2. 关广告 + 确认年级
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败")
        return 1

    # 3. 跑听力专项（U1-U9 + 3 子模块）
    print(f"\n📋 听力专项 · 单元 {UNITS[0]}-{UNITS[-1]}")
    t0 = time.time()
    q = run_single_module(d, "听力专项", MODULE_CONFIG)
    print(f"\n✅ 听力专项完成: {q} 题, 耗时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
