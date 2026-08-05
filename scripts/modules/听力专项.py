"""
英语宝 · 听力专项 模块
=====================
独立可运行：python -m modules.听力专项  （或在 scripts/ 下 python modules/听力专项.py）

流程：启动 → 关广告 → 确认年级 → 进听力专项
  第一部分「练习」：遍历 U1-U9
    → 点"去练习" → 基础巩固 → 左滑 → 综合进阶 → 左滑 → 难点突破
    → 每个子模块答题 → 练习报告 → 继续练习(前2个) / back(最后1个)
  第二部分「测试」：测试 tab → 遍历 U1-U5
    → 去答题 → 好的我知道啦 → 开始答题 → 答题循环(17题) → 查看报告 → back

批量调用：from modules.听力专项 import run_module; run_module(d)
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, back_to_home, scroll_and_find,
)
from engine import run_single_module

# ═══════════ 模块配置 ═══════════
APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

UNITS = [1]  # 练习部分：U1-U9；测试先跑 U1
TEST_UNITS = [1]  # 测试部分：U1-U5；测试先跑 U1

CONFIG = {
    "entry_text": "听力专项",
    "units": UNITS,
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
        "after_report": [{"type": "click", "text": "继续练习", "timeout": 3}],
    },
    "next_button_texts": ["下一题", "继续"],
    "finish_texts": ["完成", "提交"],
    "empty_text": ["暂无数据"],
    "has_pagination": True,
    "question_types": {
        "sort": {
            # 排序题：把句子（所有可点击选项）全部点完才会出现"检查"按钮
            "detect_text": ["排序", "按顺序", "排序题", "给句子排序", "将句子排成", "排成正确的顺序", "按正确顺序排列"],
            "action": "sort_questions",
        },
        "match": {
            "detect_text": ["匹配", "配对", "为人物选择", "选择正确的描述"],
            "action": "match_questions",
        },
    },
}


def run_module(d):
    """第一部分：练习模块——跑完听力专项全部单元+子模块，返回题数"""
    t0 = time.time()
    print(f"\n📋 听力专项·练习 · 单元 {UNITS[0]}-{UNITS[-1]} · {len(UNITS)}个单元")
    q = run_single_module(d, "听力专项", CONFIG)
    print(f"✅ 练习部分完成: {q} 题, 耗时 {time.time()-t0:.0f}s")
    return q


# ═══════════ 第二部分：测试模块 ═══════════

def _test_answer_loop(d, max_q=30):
    """测试卷答题循环：点选项→检查→(答对自动跳/答错点下一题)→最后一题查看报告
    
    处理题型：选择/判断(TF)、匹配(点方框+字母)、排序(点方框+序号)、中途"继续答题"弹窗
    """
    q = 0
    for i in range(max_q):
        # 中途弹窗"继续答题（0S）" → 点击
        if d(textContains="继续答题").exists(timeout=0.8):
            d(textContains="继续答题").click()
            print("      → 继续答题弹窗")
            time.sleep(1.5)
            continue
        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.8):
            d(text="查看报告").click()
            print("      → 查看报告！测试完成")
            time.sleep(2)
            return q
        # 答错后"下一题" → 点它
        if d(text="下一题").exists(timeout=0.8):
            d(text="下一题").click()
            print("      → 下一题(答错)")
            time.sleep(1.5)
            continue
        # 新题：找选项
        opt = None
        for kw in ("T", "F", "A", "B", "C", "D", "E"):
            try:
                if d(text=kw).exists(timeout=0.4):
                    opt = kw
                    break
            except Exception:
                pass
        if opt:
            d(text=opt).click()
            print(f"      → 选 {opt}")
            time.sleep(0.8)
            # 等检查出现
            for _ in range(10):
                try:
                    if d(text="检查").exists(timeout=0.5):
                        d(text="检查").click()
                        print(f"      → 检查")
                        time.sleep(1.5)
                        break
                except Exception:
                    pass
                time.sleep(0.4)
            q += 1
            continue
        # 匹配题：点第一个方框 → 点字母
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "
        if any(kw in texts for kw in ("匹配", "配对")):
            from engine import _handle_match_question
            _handle_match_question(d, {})
            q += 1
            continue
        # 排序题：点第一个方框 → 依次点序号
        if any(kw in texts for kw in ("排序", "给图片排序", "给句子排序")):
            from engine import _handle_sort_question
            _handle_sort_question(d, {})
            q += 1
            continue
        # 无选项无按钮 → 检查页面
        texts2 = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        print(f"    ⚠ 无选项: {texts2[:6]}")
        time.sleep(1)
    return q


def run_test_module(d):
    """第二部分：测试模块——测试 tab 遍历单元，返回题数"""
    t0 = time.time()
    total = 0
    print(f"\n📋 听力专项·测试 · 单元 {TEST_UNITS[0]}-{TEST_UNITS[-1]} · {len(TEST_UNITS)}个单元")

    # 确认在听力专项页 → 点"测试" tab
    if not d(text="测试").exists(timeout=3):
        if not scroll_and_find(d, "听力专项"):
            print("  ❌ 找不到听力专项入口"); return 0
        d(text="听力专项").click(); time.sleep(3)
    if not d(text="测试").exists(timeout=3):
        print("  ❌ 找不到测试 tab"); return 0
    d(text="测试").click(); time.sleep(3)
    print("  ✅ 已进入测试 tab")

    for ui, unit_num in enumerate(TEST_UNITS):
        print(f"\n  🎯 测试 Unit {unit_num} [{ui+1}/{len(TEST_UNITS)}]")
        # 在测试列表找该单元的"去答题"
        found = False
        for _ in range(10):
            # 找单元标题 + 去答题
            rows = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                    if f"Unit {unit_num}" in (e.text or "") or f"U{unit_num}" in (e.text or "")]
            if rows and d(text="去答题").exists(timeout=1):
                d(text="去答题").click()
                found = True
                break
            if not found:
                S_swipe(d, 500, 1800, 500, 600, 0.3); time.sleep(1)
        if not found:
            print(f"  ❌ U{unit_num} 找不到去答题"); continue
        time.sleep(2)
        # 规则弹窗"好的，我知道啦~"
        if d(text="好的，我知道啦~").exists(timeout=3):
            d(text="好的，我知道啦~").click(); time.sleep(2)
        # 开始答题
        if d(text="开始答题").exists(timeout=3):
            d(text="开始答题").click(); time.sleep(3)
        # 答题循环
        q = _test_answer_loop(d)
        total += q
        print(f"  ✅ U{unit_num} 测试完成: {q} 题")
        # back 回测试列表
        for _ in range(3):
            if d(text="去答题").exists(timeout=1.5):
                break
            d.press("back"); time.sleep(1.5)
        # 回到测试 tab
        if d(text="测试").exists(timeout=2):
            d(text="测试").click(); time.sleep(2)

    print(f"✅ 测试部分完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
    return total


def run_all(d):
    """练习 + 测试 完整流程"""
    q1 = run_module(d)        # 练习
    q2 = run_test_module(d)   # 测试
    print(f"\n📊 听力专项汇总: 练习 {q1} 题 + 测试 {q2} 题")
    return q1 + q2


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

    # 3. 跑听力专项（练习 + 测试）
    run_all(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())

