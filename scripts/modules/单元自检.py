"""
英语宝 · 单元自检 模块
=====================
独立可运行：python modules/单元自检.py

流程：主页下滑 → 专项突破 → 单元自检 → 点"去答题"（按单元顺序）
  → 好的，我知道啦~ → 开始答题 → 答题界面（36题/单元）
  → 遇到不同题型用对应方法处理（选择/判断/排序/匹配/其他）
  → 最后一题答完点检查 → 查看报告 → back → 下一单元

批量调用：from modules.单元自检 import run_module; run_module(d)
"""
import os
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
)
from engine import _handle_match_question, _handle_sort_question

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"


def _env_units():
    """从环境变量读取单元范围 (scheduler 设置); 未设置时默认 Unit 1"""
    f = os.environ.get("YYB_UNIT_FROM", "")
    t = os.environ.get("YYB_UNIT_TO", "")
    if f.isdigit():
        f = int(f)
        t = int(t) if t.isdigit() else f
        return list(range(f, t + 1))
    return [1]

UNITS = _env_units()  # U1 验证；打通后 [1,2,3,4]


def _answer_loop(d, max_q=60):
    """单元自检答题循环：点选项→检查→(答对自动跳/答错点下一题)→最后一题查看报告
    
    题型处理：
    - 选择/判断(TF): 点选项→检查
    - 匹配: 点方框→点字母 A-E（全部点完→检查）
    - 排序: 图片(直接点)/句子(激活+序号)
    - 其他题型: 检测到后暂停提示（用户告知方法）
    """
    q = 0
    for i in range(max_q):
        # 中途弹窗"继续答题（0S）" → 点击
        if d(textContains="继续答题").exists(timeout=0.6):
            d(textContains="继续答题").click()
            print("      → 继续答题弹窗")
            time.sleep(1.5)
            continue
        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.6):
            d(text="查看报告").click()
            print("      → 查看报告！单元自检完成")
            time.sleep(2)
            return q
        # 答错后"下一题" → 点它
        if d(text="下一题").exists(timeout=0.6):
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
            # 等检查出现并点击
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

        # 其他题型：检测排序/匹配/填空
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "
        if any(kw in texts for kw in ("匹配", "配对", "为人物选择", "选择正确的描述")):
            _handle_match_question(d, {})
            q += 1
            continue
        if any(kw in texts for kw in ("排序", "给图片排序", "给句子排序", "按顺序")):
            _handle_sort_question(d, {})
            q += 1
            continue
        # 填空题检测：题干含"完成小短文"+"每空"
        if any(kw in texts for kw in ("完成小短文", "完成短文", "每空", "填空", "完成句子")):
            from engine import _handle_fill_blank
            if _handle_fill_blank(d, {}):
                q += 1
                continue

        # 未知题型 → 提示用户
        texts2 = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        print(f"    ⚠ 未知题型，请告知处理方法: {texts2[:6]}")
        d.screenshot(f"unknown_type_{q}.png")
        time.sleep(5)
    return q


def _enter_unit(d, unit_num):
    """在单元自检列表页进入指定单元的答题"""
    # 找第 unit_num 个"去答题"按钮
    btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
            if (e.text or "").strip() == "去答题"]
    btns.sort(key=lambda e: e.bounds[1])
    idx = unit_num - 1
    for _ in range(5):
        if idx < len(btns):
            break
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(1)
        btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                if (e.text or "").strip() == "去答题"]
        btns.sort(key=lambda e: e.bounds[1])
    if idx >= len(btns):
        print(f"    ❌ 找不到 U{unit_num} 的去答题")
        return False
    btns[idx].click()
    print(f"    ✅ 点击去答题 (U{unit_num})")
    time.sleep(3)
    # 弹窗
    if d(text="好的，我知道啦~").exists(timeout=3):
        d(text="好的，我知道啦~").click()
        print(f"    ✅ 好的，我知道啦~")
        time.sleep(2)
    # 开始答题
    if d(text="开始答题").exists(timeout=3):
        d(text="开始答题").click()
        print(f"    ✅ 开始答题")
        time.sleep(4)
    return True


def run_module(d):
    """核心入口：跑完单元自检全部单元，返回题数"""
    t0 = time.time()
    total = 0
    print(f"\n📋 单元自检 · 单元 {UNITS[0]}-{UNITS[-1]} · {len(UNITS)}个单元")

    # 进入单元自检：主页下滑 → 专项突破 → 单元自检
    if not d(text="单元自检").exists(timeout=2):
        # 主页下滑找专项突破下的单元自检
        found = False
        for _ in range(6):
            if d(text="单元自检").exists(timeout=1):
                found = True
                break
            S_swipe(d, 540, 1800, 540, 600, 0.4); time.sleep(1)
        if not found:
            # 尝试点专项突破后再下滑
            if d(text="专项突破").exists(timeout=1):
                d(text="专项突破").click(); time.sleep(2)
            for _ in range(6):
                if d(text="单元自检").exists(timeout=1):
                    found = True
                    break
                S_swipe(d, 540, 1800, 540, 600, 0.4); time.sleep(1)
        if not found:
            print("  ❌ 找不到单元自检入口")
            return 0
    d(text="单元自检").click()
    print("  ✅ 已进入单元自检")
    time.sleep(4)

    # 逐单元执行
    for ui, unit_num in enumerate(UNITS):
        print(f"\n  🎯 单元自检 Unit {unit_num} [{ui+1}/{len(UNITS)}]")
        if not _enter_unit(d, unit_num):
            continue
        q = _answer_loop(d)
        total += q
        print(f"  ✅ U{unit_num} 完成: {q} 题")
        # back 回单元自检列表
        for _ in range(4):
            if d(text="去答题").exists(timeout=1.5):
                break
            d.press("back"); time.sleep(1.5)

    print(f"✅ 单元自检完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
    return total


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
