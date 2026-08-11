"""
听力专项 U6-U9 完整自动化（含所有子模块）
=========================================
湘少版五年级上册 · 听力专项 · Unit 6-9

子模块: 听力专项、口语训练、单元自检
每个子模块：Level 1(基础巩固) → Level 2(综合进阶) → ...
"""

import uiautomator2 as u2
import time, os, sys

SERIAL = "SKSCIF4T7PFMQS5X"
d = u2.connect()

# ================ 工具函数 ================
def sw():
    """向上滑一次（内容向下滚动）"""
    d.swipe(500, 1400, 500, 400, duration=0.3)
    time.sleep(0.4)

def back(n=1):
    for _ in range(n):
        d.press("back"); time.sleep(0.5)

def wait_for(target, timeout=10):
    for _ in range(timeout):
        if d(text=target).exists(timeout=1):
            return True
        time.sleep(0.35)
    return False

def click_if_exist(target, wait_after=2):
    if d(text=target).exists(timeout=2):
        d(text=target).click()
        time.sleep(wait_after)
        return True
    return False

def answer_loop(max_q=10):
    """答题循环：选A→检查→下一题，支持TF判断"""
    q = 0
    for q in range(max_q):
        # 先检查是否完成
        if d(text="重新答题").exists(timeout=1):
            break
        if d(text="练习报告").exists(timeout=1):
            break

        # 选答案
        for opt in ("A","B","C","T","F"):
            if click_if_exist(opt, 1): break

        # 检查
        click_if_exist("检查", 1.5)
        time.sleep(0.4)

        # 下一题
        if click_if_exist("下一题", 2):
            continue
        if click_if_exist("继续", 1.5):
            continue
        # 可能最后一题
        if d(text="重新答题").exists(timeout=2): break
        if d(text="练习报告").exists(timeout=2): break
        break
    return q + 1

def go_main():
    """返回主页"""
    for _ in range(8):
        els = d.xpath('//*[@text!=""]').all()
        texts = [e.text for e in els] if els else []
        if "教材精学" in texts or ("专项突破" in texts and "考前突破" in texts):
            return True
        back(1)
    return False

# ================ 主流程 ================
print("=" * 50)
print("听力专项 U6-U9 自动化")
print("湘少版五年级上册")
print("=" * 50)

go_main()
wait_for("教材精学", timeout=10)

# 1. 进听力专项
print("\n[1] 听力专项模块")
for _ in range(10):
    if d(text="听力专项").exists(timeout=1.5): break
    sw()
d(text="听力专项").click(timeout=3)
time.sleep(1.6)

results = []

# 2. 遍历 U6-U9
for unit in [6, 7, 8, 9]:
    print(f"\n{'='*40}")
    print(f"[U{unit}] 开始")
    print(f"{'='*40}")

    # 2a. 滚到目标 Unit + 点去练习
    for _ in range(15):
        btns = [e for e in (d.xpath('//*[@text="去练习"]').all() or [])]
        # 看看哪些Unit可见
        visible_units = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if (e.text or "").startswith(f"Unit ")]
        if any(f"Unit {unit}" in u for u in visible_units):
            break
        sw()

    # 点目标 Unit 的去练习：取出所有"去练习"，找对应的 Unit 行
    unit_btns = [(e, e.bounds[2], e.bounds[1]) for e in (d.xpath('//*[@text="去练习"]').all() or [])]
    unit_texts = [(e, e.text, e.bounds[1]) for e in (d.xpath('//*[@text!=""]').all() or []) if (e.text or "").startswith(f"Unit ")]
    # 匹配：Unit 的行 → 最近的 去练习（同y区间）
    target_btn = None
    for ue, uname, uy in unit_texts:
        if f"Unit {unit}" in (uname or ""):
            for be, bx, by in unit_btns:
                if abs(by - uy) < 100:  # 同一行
                    be.click()
                    target_btn = be
                    break
            break
    if not target_btn:
        print(f"  ❌ 找不到 U{unit} 的去练习")
        continue

    time.sleep(1.6)
    print(f"  ✅ 进入 U{unit}")

    # 2b. U{unit} 概览页 → 遍历子模块
    sub_modules = ["听力专项", "口语训练", "单元自检"]
    for sub in sub_modules:
        print(f"    [{sub}]")
        # 点子模块 tab
        if click_if_exist(sub, 3):
            print(f"      ✅ 进入子模块 {sub}")

        # 找 Level/阶段 的"去练习"：可能有 Level 1, Level 2...
        for level in range(1, 4):
            level_kw = f"Level {level}"
            found_level = False
            for _ in range(5):
                if d(textContains=level_kw).exists(timeout=1.5):
                    found_level = True
                    break
                sw()
            if not found_level:
                continue

            # 在 Level 行附近找"去练习"并点击
            for _ in range(3):
                if click_if_exist("去练习", 3):
                    break
                sw()

            # 如果还没进入 → 可能需要点"重新答题"
            if click_if_exist("重新答题", 3):
                print(f"        重新答题 @ Level{level}")

            # 答题循环
            q = answer_loop(10)
            print(f"        Level{level}: {q} 题")

            # 返回 Level 列表
            back(1)
            time.sleep(0.8)

    # 返回 U{unit} 概览
    back(2)
    time.sleep(0.8)

# 返回主页
go_main()
print(f"\n{'='*50}")
print("✅ 全部完成")
print(f"{'='*50}")
