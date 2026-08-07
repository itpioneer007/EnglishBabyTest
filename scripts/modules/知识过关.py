"""
英语宝 · 知识过关 模块
=====================
独立可运行：python modules/知识过关.py

流程：主页 → 知识过关 → 选单元文本框 → 收到了，马上去过关
  → 重点词汇（第一个去闯关）→ 答题循环（108题）→ 查看报告
  → back 回关卡列表 → 重点句型（第二个去闯关）→ 同流程
  → 答完 back 回主页

题型（按题目文字严格区分，避免逻辑冲突）：
- 选择题（题目：A-E 文字选项）：点 A → 检测 → 下一题
- 判断题（题目：T/F 文字）：点 T → 检测 → 下一题
- 录音题（题目：「听录音，跟读...」+「原音」按钮）：点原音 → 点录音 → 点结束 → 检测
- 填字母题（题目：「根据中文提示，选择正确的字母补全单词」）：
    * 方框：2-3 个 LL clickable 170x114，y ~478（题目正文下方）
    * 字母按钮：10 个 LL clickable 193x137，y 680/837（2 行 5 列），文字是图片（uiautomator 读不到 text）
    * 机制：点第一个方框激活 → 自动跳方框并填字母 → 检测按钮出现
    * 字母按钮位置固定（x: 132/337/542/747/952, y: 748/905），但字母随机——按位置依次点（不关心是哪个字母）
- 填单词题-连词成句（题目：「连词成句」）：
    * 方框：3-5 个 LL clickable 228x114，y 815-1043
    * 单词按钮：底部 LL clickable 242x195，y 2044-2141，无 text
    * 机制：每个方框都点激活 → 单词按钮弹出 → 填一个上方移（每次重新 dump 定位）
    * 直接调用 _handle_sort_question 处理（与序号排序同机制）
- 填空题-系统键盘（题目：「补全情景图」无字母按钮）：FastInputIME 注入

批量调用：from modules.知识过关 import run_module; run_module(d)
"""
import os
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
)
from engine import _handle_match_question, _handle_sort_question  # noqa: F401  (预留)

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

UNITS = _env_units()  # U1 验证；打通后 list(range(1, 10))


def _answer_loop(d, max_q=120):
    """知识过关答题循环：所有题型统一处理

    题型检测与处理：
    - 录音题：点原音 → 点录音 → 点结束
    - 填空题-系统键盘：FastInputIME 注入
    - 填空题-界面字母：LinearLayout clickable（193x137）按方框顺序点
    - 选择题：点 A → 检测 → 下一题
    """
    import re as _re
    q = 0
    for _ in range(max_q):
        # 中途弹窗
        for kw in ('继续答题（0S）', '继续答题', '确定', '好的'):
            if d(text=kw).exists(timeout=0.3):
                d(text=kw).click()
                time.sleep(1.5)
                break
        # 最后一题 → 提交（知识过关答完最后一题是"提交"而非"查看报告"）
        if d(text="提交").exists(timeout=0.5):
            try:
                d(text="提交").click()
            except Exception:
                pass
            print(f"    ✅ 提交！知识过关完成")
            time.sleep(2)
            return q
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

        # 题目文字（用于判断题型）
        title_text = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            t = (e.text or "").strip()
            if "字母" in t and "补全" in t:
                title_text = "fill_letters"
                break
            if "连词成句" in t:
                title_text = "sentence_sort"
                break

        # === 填字母题：根据题目文字判断 ===
        # 特征：题目文字含「字母补全」+ 字母按钮有 text（a-z 单字母）
        if title_text == "fill_letters":
            # 字母按钮：10 个 LL clickable（193x137）排成 2 行 5 列，y ~680 / 837
            # 字母文字是图片绘制（uiautomator 读不到），用坐标定位
            xml = d.dump_hierarchy()
            letter_positions = []
            for m in _re.finditer(
                r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml
            ):
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                w, h = x2-x1, y2-y1
                # 字母按钮特征：宽 180-210 高 130-145，y 在 600-900 之间
                if 180 < w < 210 and 125 < h < 150 and S_h(d, 600) < y1 < S_h(d, 950):
                    letter_positions.append(((x1+x2)//2, (y1+y2)//2))
            letter_positions.sort(key=lambda t: (t[1], t[0]))  # 按 y 再 x 排序（左到右、上到下）
            # 找第一个方框（y < 700 的 LL clickable 170x114）
            first_box = None
            for m in _re.finditer(
                r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml
            ):
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                w, h = x2-x1, y2-y1
                if S_h(d, 400) < y1 < S_h(d, 700) and 150 < w < 200 and 100 < h < 130:
                    first_box = ((x1+x2)//2, (y1+y2)//2)
                    break
            if first_box and letter_positions:
                print(f"    🅰 填字母 (方框+{len(letter_positions)}字母按钮)")
                # 点第一个方框激活（自动填第一个字母后光标跳到下一方框）
                try:
                    d.click(*first_box)
                except Exception:
                    pass
                time.sleep(1)
                # 依次点每个字母按钮（填到所有方框）
                # 简化：按顺序点 5-10 个字母按钮（覆盖任意方框数）
                # 关键：每点一个后检测是否出现，出现就停
                for i, (bx, by) in enumerate(letter_positions):
                    try:
                        d.click(bx, by)
                    except Exception:
                        pass
                    time.sleep(0.4)
                    if d(text="检测").exists(timeout=0.3):
                        break
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

        # === 填单词题（连词成句）：调用排序处理 ===
        if title_text == "sentence_sort":
            print(f"    🧩 连词成句 → 调用排序处理")
            try:
                _handle_sort_question(d, {})
            except Exception:
                pass
            q += 1
            continue

        # 找 EditText（填空方框）+ 字母按钮（旧的字母填空，可能没题目文字触发）
        xml = d.dump_hierarchy()
        edit_inputs = []
        for m in _re.finditer(
            r'class="android\.widget\.EditText"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            edit_inputs.append(((x1+x2)//2, (y1+y2)//2, y1))
        edit_inputs.sort(key=lambda t: t[2])

        # 找界面字母按钮（LinearLayout clickable 193x137）
        letter_btns = []
        for m in _re.finditer(
            r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2-x1; h = y2-y1
            # 字母按钮：y 1100-1700（排除上方句子方框 y 815-1043）
            if S_h(d, 1100) < y1 < S_h(d, 1700) and 150 < w < 250 and 100 < h < 180:
                letter_btns.append(((x1+x2)//2, (y1+y2)//2))
        letter_btns.sort(key=lambda t: (t[1], t[0]))

        if letter_btns:
            # 兜底：填空题-界面字母（无题目文字触发）
            n = min(2, len(letter_btns))
            print(f"    🅰 填空-界面字母 (点{n}个字母，兜底)")
            for bx, by in letter_btns[:n]:
                try:
                    d.click(bx, by)
                except Exception:
                    pass
                time.sleep(0.4)
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        if edit_inputs:
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

        # 2.5 判断题（T/F 选项）
        if d(text="T").exists(timeout=0.5) and d(text="F").exists(timeout=0.3):
            try:
                d(text="T").click()
            except Exception:
                pass
            time.sleep(0.3)
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    print(f"    ✓ 判断T → 检测")
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue

        # 2.7 连词成句题：和序号排序题机制一样（点方框激活 → 点底部单词按钮）
        # 检测：≥2 个句子方框（LL 200-250宽 100-130高，y 600-1100）→ 调用排序处理
        xml = d.dump_hierarchy()
        sentence_boxes = []
        for m in re.finditer(
            r'class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2-x1; h = y2-y1
            cx = (x1+x2)//2; cy = (y1+y2)//2
            if 200 < w < 250 and 100 < h < 130 and S_h(d, 600) < y1 < S_h(d, 1100):
                sentence_boxes.append((cx, cy, y1))
        if len(sentence_boxes) >= 2:
            print(f"    🧩 连词成句 ({len(sentence_boxes)}句) → 调用排序处理")
            try:
                _handle_sort_question(d, {})
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
    # 已在单元列表（有 "Unit N" 文本框）则跳过主页入口
    in_unit_list = False
    for e in (d.xpath('//*[@text!=""]').all() or []):
        t = (e.text or "").strip()
        if t.startswith("Unit ") and "What" in t or (t.startswith("Unit ") and "like" in t):
            in_unit_list = True
            break
    if not in_unit_list:
        # 主页下滑找知识过关入口
        found = False
        for _ in range(5):
            if d(text="知识过关").exists(timeout=1):
                found = True
                break
            S_swipe(d, 540, 1800, 540, 600, 0.4)
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
        S_swipe(d, 540, 1800, 540, 600, 0.4)
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
    """进入子模块（重点词汇/重点句型），找「去闯关」或「重新闯关」按钮"""
    # 支持两种按钮文字：未答过=去闯关，答过=重新闯关
    for btn_text in ("去闯关", "重新闯关"):
        btns = []
        for e in (d.xpath('//*[@text!=""]').all() or []):
            t = (e.text or "").strip()
            if t == btn_text:
                btns.append(e)
        btns.sort(key=lambda e: e.bounds[1])
        if btns:
            btns[0].click()
            print(f"    ✅ 进入子模块（{btn_text}）")
            time.sleep(4)
            return True
    print(f"    ❌ 找不到「去闯关/重新闯关」按钮")
    return False


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
            # 第一个子模块按钮就在知识闯关界面
            if not _enter_submodule(d):
                continue
        else:
            # 第二个子模块：先 back 回知识闯关界面（重点词汇报告页 → 1 下 back）
            for _ in range(3):
                if d(text="重点词汇").exists(timeout=1.5) or d(text="去闯关").exists(timeout=1.5) or d(text="重新闯关").exists(timeout=1.5):
                    break
                d.press("back")
                time.sleep(1.5)
            if not _enter_submodule(d):
                continue

        # 答题循环（最后一题答完自动点"提交"）
        q = _answer_loop(d, max_q=120)
        total += q
        print(f"  ✅ {sub_name}完成: {q} 题")

        # 答完 → 提交 → 报告页 → back 退出
        # 重点词汇：back 1 次回知识闯关界面（继续重点句型）
        # 重点句型：back 2 次回单元列表（下一单元）
        if sub_idx == 0:
            # back 1 次回知识闯关界面（重点词汇/重点句型按钮页面）
            for _ in range(2):
                if d(text="重点词汇").exists(timeout=1.5) or d(text="去闯关").exists(timeout=1.5) or d(text="重新闯关").exists(timeout=1.5):
                    break
                d.press("back")
                time.sleep(1.5)
        else:
            # back 2 次回单元列表
            for _ in range(3):
                if d(text="Unit 1").exists(timeout=1.5):
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
        S_swipe(d, 540, 1800, 540, 600, 0.4)
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
