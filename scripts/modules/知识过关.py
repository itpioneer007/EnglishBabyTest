"""
英语宝 · 知识过关 模块
=====================
独立可运行：python modules/知识过关.py

流程：主页 → 知识过关 → 选单元文本框 → 收到了，马上去过关
  → 重点词汇（第一个去闯关）→ 答题循环（108题）→ 查看报告
  → back 回关卡列表 → 重点句型（第二个去闯关）→ 同流程
  → 答完 back 回主页

题型：
- 选择题（点 A-E → 检测 → 下一题）
- 填空题-系统键盘（点方框 → set_fastinput_ime + send_keys → 检测 → 下一题）
- 填空题-界面字母（点字母按钮填方框 → 检测 → 下一题）
- 录音题（点原音 → 点录音 → 点结束 → 检测 → 下一题）

批量调用：from modules.知识过关 import run_module; run_module(d)
"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
)
from engine import _handle_match_question, _handle_sort_question  # noqa: F401  (预留)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

UNITS = [1]  # U1 验证；打通后 list(range(1, 10))


def _answer_loop(d, max_q=120):
    """知识过关答题循环：所有题型统一处理

    题型检测与处理：
    - 录音题：点原音 → 点录音 → 点结束
    - 填空题-系统键盘：FastInputIME 注入
    - 填空题-界面字母：LinearLayout clickable（193x137）按方框顺序点
    - 选择题：点 A → 检测 → 下一题
    """
    q = 0
    for _ in range(max_q):
        # 中途弹窗
        for kw in ('继续答题（0S）', '继续答题', '确定', '好的'):
            if d(text=kw).exists(timeout=0.3):
                d(text=kw).click()
                time.sleep(1.5)
                break
        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.5):
            try:
                d(text="查看报告").click()
            except Exception:
                pass
            print(f"    ✅ 查看报告！知识关过完成")
            time.sleep(2)
            return q
        # 下一题按钮
        if d(text="下一题").exists(timeout=0.5):
            try:
                d(text="下一题").click()
            except Exception:
                pass
            time.sleep(1.5)
            continue

        # 题型识别（页面文字）
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "

        # 1. 录音题：检测"原音"按钮（跟读单词题）
        if d(text="原音").exists(timeout=0.3):
            print(f"    🎤 录音题")
            try:
                d(text="原音").click()
            except Exception:
                pass
            time.sleep(2)
            # 点录音（多轮重试，点击结束后等待自动跳转）
            try:
                if d(text="点击录音").exists(timeout=1):
                    d(text="点击录音").click()
                    time.sleep(1.5)
            except Exception:
                pass
            try:
                if d(text="点击结束").exists(timeout=1):
                    d(text="点击结束").click()
                    time.sleep(2)
                else:
                    # 点完录音后可能直接出下一题/检测
                    time.sleep(2)
            except Exception:
                pass
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue
        if d(text="点原音").exists(timeout=0.3) or d(text="点读原音").exists(timeout=0.3):
            print(f"    🎤 录音题")
            if d(text="点原音").exists(timeout=0.3):
                d(text="点原音").click()
            elif d(text="点读原音").exists(timeout=0.3):
                d(text="点读原音").click()
            time.sleep(2)
            if d(text="点击录音").exists(timeout=0.8):
                d(text="点击录音").click()
                time.sleep(1.5)
            if d(text="点击结束").exists(timeout=0.8):
                d(text="点击结束").click()
                time.sleep(2)
            # 点检测
            if d(text="检测").exists(timeout=1.5):
                d(text="检测").click()
                time.sleep(1.5)
            q += 1
            continue

        # 找 EditText（填空方框）
        xml = d.dump_hierarchy()
        edit_inputs = []
        for m in re.finditer(
            r'class="android\.widget\.EditText"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            edit_inputs.append(((x1+x2)//2, (y1+y2)//2, y1))
        edit_inputs.sort(key=lambda t: t[2])

        # 找界面字母按钮（LinearLayout clickable 193x137）
        letter_btns = []
        for m in re.finditer(
            r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2-x1; h = y2-y1
            if 500 < y1 < 1700 and 150 < w < 250 and 100 < h < 180:
                letter_btns.append(((x1+x2)//2, (y1+y2)//2))
        letter_btns.sort(key=lambda t: (t[1], t[0]))

        if letter_btns:
            # 填空题-界面字母：方框在题干区（不在 dump），但字母按钮可见
            # 简化策略：点 2 个字母按钮（覆盖大部分 1-2 空题）+ 检测
            n = min(2, len(letter_btns))
            print(f"    🅰 填空-界面字母 (点{n}个字母)")
            for bx, by in letter_btns[:n]:
                try:
                    d.click(bx, by)
                except Exception:
                    pass
                time.sleep(0.4)
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        if edit_inputs and not letter_btns:
            # 填空题-系统键盘：FastInputIME 注入
            print(f"    📝 填空-系统键盘 ({len(edit_inputs)}空)")
            try:
                d.set_fastinput_ime(True)
                time.sleep(0.3)
            except Exception:
                pass
            for cx, cy, y1 in edit_inputs:
                try:
                    d.click(cx, cy)
                    time.sleep(1)
                    d.send_keys("a")
                except Exception:
                    try:
                        d.shell("input text a")
                    except Exception:
                        pass
                time.sleep(0.3)
            try:
                d.press("back")
            except Exception:
                pass
            time.sleep(1)
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        # 2. 选择题（A 选项 + 检测按钮）
        if d(text="A").exists(timeout=0.5):
            try:
                d(text="A").click()
            except Exception:
                pass
            time.sleep(0.3)
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    print(f"    ✓ 选择A → 检测")
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        # 3. 兜底：有点击的字母按钮但没识别 → 选 A
        # (已经在 letter_btns 块处理)

        # 未知
        d.screenshot(f"unknown_kp_{q}.png")
        print(f"    ⚠ 未知: {texts[:5]}")
        time.sleep(2)
    return q



def _enter_unit(d, unit_num):
    """进入知识过关单元（U1-U9 文本框）"""
    # 主页下滑找知识过关入口
    found = False
    for _ in range(5):
        if d(text="知识过关").exists(timeout=1):
            found = True
            break
        d.swipe(540, 1800, 540, 600, 0.4)
        time.sleep(1)
    if not found:
        print(f"    ❌ 找不到知识过关入口")
        return False
    d(text="知识过关").click()
    time.sleep(4)

    # 找单元文本框（按 y 排序，第 unit_num 个）
    for _ in range(3):
        units = []
        for e in (d.xpath('//*[@text!=""]').all() or []):
            t = (e.text or "").strip()
            if t.startswith("Unit ") and "What" in t or (t.startswith("Unit ") and "like" in t) or (t.startswith("Unit ") and "?" in t):
                units.append(e)
        if not units:
            for e in (d.xpath('//*[@text!=""]').all() or []):
                t = (e.text or "").strip()
                if t.startswith("Unit "):
                    units.append(e)
        if units:
            break
        d.swipe(540, 1800, 540, 600, 0.4)
        time.sleep(1)
    units.sort(key=lambda e: e.bounds[1])
    if unit_num - 1 >= len(units):
        print(f"    ❌ 找不到 U{unit_num}")
        return False
    units[unit_num - 1].click()
    print(f"    ✅ 点 U{unit_num}")
    time.sleep(4)

    # 收到了，马上去过关
    if d(text="收到了，马上去过关").exists(timeout=5):
        d(text="收到了，马上去过关").click()
        print(f"    ✅ 收到了，马上去过关")
        time.sleep(4)
    return True


def _enter_submodule(d, name_keyword="重点词汇"):
    """进入子模块（重点词汇/重点句型/小惊喜），找「去闯关」按钮"""
    btns = []
    for e in (d.xpath('//*[@text!=""]').all() or []):
        t = (e.text or "").strip()
        if t == "去闯关":
            btns.append(e)
    btns.sort(key=lambda e: e.bounds[1])
    if not btns:
        print(f"    ❌ 找不到「去闯关」按钮")
        return False
    btns[0].click()
    print(f"    ✅ 进入子模块")
    time.sleep(4)
    return True


def _run_one_unit(d, unit_num):
    """跑一个单元的知识过关"""
    print(f"\n  🎯 知识过关 Unit {unit_num}")
    if not _enter_unit(d, unit_num):
        return 0

    # 两个子模块：重点词汇（先做）+ 重点句型
    total = 0
    sub_names = ["重点词汇", "重点句型"]
    for sub_idx, sub_name in enumerate(sub_names):
        print(f"\n  📚 子模块: {sub_name}")
        if sub_idx == 0:
            # 第一个子模块按钮就在页面上
            if not _enter_submodule(d):
                continue
        else:
            # 第二个子模块：先 back 回关卡列表
            for _ in range(3):
                if d(text="去闯关").exists(timeout=1.5):
                    break
                d.press("back")
                time.sleep(1.5)
            if not _enter_submodule(d):
                continue

        # 答题循环
        q = _answer_loop(d, max_q=120)
        total += q
        print(f"  ✅ {sub_name}完成: {q} 题")

        # 答完 → 查看报告 → back 回关卡列表
        for _ in range(3):
            if d(text="重点词汇").exists(timeout=1.5) or d(text="去闯关").exists(timeout=1.5):
                break
            d.press("back")
            time.sleep(1.5)

    return total


def run_module(d):
    """核心入口：跑完知识过关全部单元"""
    t0 = time.time()
    total = 0
    print(f"\n📋 知识过关 · 单元 {UNITS[0]}-{UNITS[-1]} · {len(UNITS)}个单元")

    # 确认在主页（下滑找知识过关）
    for _ in range(5):
        if d(text="知识过关").exists(timeout=1):
            break
        d.swipe(540, 1800, 540, 600, 0.4)
        time.sleep(1)

    for ui, unit_num in enumerate(UNITS):
        q = _run_one_unit(d, unit_num)
        total += q
        # back 回主页
        for _ in range(5):
            if d(text="知识过关").exists(timeout=1.5):
                break
            d.press("back")
            time.sleep(1.5)

    print(f"✅ 知识过关完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
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
