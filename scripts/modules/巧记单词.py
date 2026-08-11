"""
英语宝 · 巧记单词 模块
=====================
独立可运行：python modules/巧记单词.py

流程（用户约定）：
1. 主页 → 教材精学 → 「巧记单词」卡片（(386,1114)-(694,1269)，中心 540,1192）
2. 「单词同步闯关」→ 关卡地图
3. 关卡地图：每单元 6 关 = 关卡 1~5 + boss关
   - 关卡 1 中心 (681,1593)、2 (767,1312)、3 (583,1096)、4 (346,923)、5 (313,642)
   - boss关 在地图右上角（数字不显示，图标为 boss）
   - 下一单元起始关卡序号 = 前单元最后一关序号 + 1（如 U1 结束 6 → U2 从 7 到 12，12 为 boss）
4. 点关卡数字/文字 → 进入单词浏览页（5 词，点卡片看释义）→ 「马上闯关」
5. 答题界面（15 题）：
   - 听力选释义（A/B/C 选项）等常见题型
   - 答错：点检查 → 正确答案/我的答案 → 「重新答题」（再答一次）
     → 二次答错 → 「跳过」进下一题
   - 答对：点检查 → 直接进下一题
   - 最后一题：点检查 → 「提交」→ 报告页
6. 报告页 → back 两次 → 回到该单元闯关界面 → 点下一关
7. 通过 boss 关 → 点「下一单元」→ 重复操作

批量调用：from modules.巧记单词 import run_module; run_module(d)
"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.logger import should_stop, step_log
from common.evidence import collect_ui_evidence
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

# 每单元关卡数（1~5 + boss = 6 关）
LEVELS_PER_UNIT = 6

# 主页「巧记单词」卡片位置（教材精学第一行第3张，x=876,y=1191；与 MODULE_COORDS 一致）
# ★ 之前 (540,441) 是错误坐标——Y=441 在顶部轮播广告区，点击广告导致异常退出
QIAOJI_CARD = (876, 1191)


UNITS = [1]  # U1 验证；打通后 list(range(1, 10))


def _resolve_units(units, default_units):
    """把外部传入的单元范围解析为列表；None 则用默认全部单元"""
    if units is None:
        return list(default_units)
    if isinstance(units, list):
        return list(units)
    if isinstance(units, int):
        return [units]
    import re as _re
    result = []
    for part in str(units).split(','):
        part = part.strip()
        m = _re.match(r'^(\d+)\s*-\s*(\d+)$', part)
        if m:
            result.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            result.append(int(part))
    return result or list(default_units)


def _enter_qiaoji(d):
    """主页 → 教材精学 → 巧记单词卡片"""
    # 确认主页
    for _ in range(5):
        if d(text="教材精学").exists(timeout=1):
            break
        d.press("back"); time.sleep(0.6)
    # 点巧记单词卡片（卡片是 ImageButton，坐标定位）
    d.click(*S(d, *QIAOJI_CARD))
    print(f"    ✅ 点巧记单词卡片")
    time.sleep(1.6)
    if not d(text="巧记单词").exists(timeout=3):
        print(f"    ❌ 未进入巧记单词页")
        return False
    return True


def _enter_sync_challenge(d):
    """点「单词同步闯关」→ 关卡地图"""
    if d(text="单词同步闯关").exists(timeout=3):
        d(text="单词同步闯关").click()
        print(f"    ✅ 点单词同步闯关")
        time.sleep(1.6)
        return True
    print(f"    ❌ 找不到单词同步闯关")
    return False


def _find_level_positions(d):
    """从地图页获取当前单元关卡数字位置（1~5 + boss）
    返回 {序号: (x, y)}，boss 用 0 键
    boss 关检测：y<500 的 ViewGroup clickable 大卡片（关卡5卡片 y>=495 除外）
    """
    positions = {}
    xml = d.dump_hierarchy()
    for m in re.finditer(
        r'text="(\d+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml
    ):
        num = int(m.group(1))
        x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        # 地图区域（y 400-1800）
        if S_h(d, 400) < y1 < S_h(d, 1800) and num <= 99:
            positions[num] = ((x1+x2)//2, (y1+y2)//2)
    # boss 关：找 y 150-500 的 ViewGroup clickable 大卡片（宽 250-320，高 200-300）
    for m in re.finditer(
        r'<node[^>]*class="android\.widget\.ViewGroup"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml
    ):
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        w, h = x2-x1, y2-y1
        if S_h(d, 150) < y1 < S_h(d, 500) and 250 < w < 320 and 200 < h < 300:
            positions[0] = ((x1+x2)//2, (y1+y2)//2)
            break
    # 兜底：找"boss关"文字，取其上方的卡片中心
    if 0 not in positions:
        for m in re.finditer(
            r'text="boss关"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            bx = (int(m.group(1)) + int(m.group(3))) // 2
            by = int(m.group(2))
            positions[0] = (bx, by - 120)  # 卡片中心在文字上方约120px
            break
    return positions


def _enter_level(d, level_no):
    """在地图页进入指定关卡（level_no: 数字关卡 或 0=boss 关）"""
    pos = None
    for _ in range(3):
        positions = _find_level_positions(d)
        if positions:
            # boss 关（level_no=0）必须用 boss 卡片位置，不能 fallback 到数字关
            if level_no == 0:
                if 0 in positions:
                    pos = positions[0]
                    break
                # 未检测到 boss → 继续重试
                S_swipe(d, 540, 1800, 540, 600, 0.4)
                time.sleep(0.4)
                continue
            # 数字关卡
            if level_no in positions:
                pos = positions[level_no]
                break
            # 目标数字关卡比地图最大关大（如要 7，地图 1-6）→ 用地图最大关兜底
            nums = [n for n in positions if n > 0]
            if nums and level_no > max(nums):
                pos = positions[max(nums)]
                break
        S_swipe(d, 540, 1800, 540, 600, 0.4)
        time.sleep(0.4)
    if not pos:
        print(f"    ❌ 找不到关卡 {level_no}")
        return False
    d.click(*pos)
    print(f"    ✅ 点关卡 {level_no} @{pos}")
    time.sleep(1.2)
    # 单词浏览页 → 先点单词卡片（"点击显示释义"，解锁马上闯关）→ 点马上闯关
    for _ in range(8):
        if d(text="马上闯关").exists(timeout=1):
            # 先点单词卡片（浏览页 5 个单词卡片，点第一个解锁即可）
            try:
                if d(text="点击显示释义").exists(timeout=0.5):
                    el = d(text="点击显示释义")
                    el.click()
                    time.sleep(0.5)
            except Exception:
                pass
            d(text="马上闯关").click()
            print(f"    ✅ 点马上闯关")
            time.sleep(1.2)
            # 确认进入答题（出现 原音/提交/第N关 数字 等答题特征）
            try:
                xml = d.dump_hierarchy()
                if '原音' in xml or '提交' in xml or '马上闯关' in xml:
                    # 马上闯关还在=没进入，继续
                    if '马上闯关' in xml:
                        continue
                    return True
            except Exception:
                pass
            return True
        # 也可能直接进入答题（无浏览页）
        if d(text="提交").exists(timeout=0.5) or d(text="原音").exists(timeout=0.5):
            return True
        time.sleep(0.5)
    print(f"    ⚠ 未出现马上闯关，可能直接进入答题")
    return True


def _answer_loop(d, max_q=20):
    """答题循环（模拟运行填充题型细节）：
    已知流程：
    - 点选项（A/B/C 或 T/F）→ 「检查」按钮出现
    - 答错：检查 → 正确答案/我的答案 + 「重新答题」
      → 再答 → 检查 → 二次答错 → 「跳过」→ 下一题
    - 答对：检查 → 直接下一题
    - 最后一题：检查 → 「提交」
    """
    q = 0
    retry_count = 0  # 当前题答错次数
    idle = 0  # 连续空转计数（防空转死循环）
    _ev_q = -1  # 已发证据卡的题号（每题只发一次）
    while True:
        # ★ 每题界面级完整性检查证据（题型/题干/选项/音频/作答）→ 前端证据卡
        if q != _ev_q:
            try:
                _xml_ev = d.dump_hierarchy()
                step_log(f"  第{q+1}题 完整性检查", "info",
                         collect_ui_evidence(_xml_ev, qtype="巧记单词"))
                _ev_q = q
            except Exception:
                pass
        # ★ 停止检查：web_server 收到停止请求 → 中断
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q
        # 提交（关卡完成）→ 唯一正常退出
        if d(text="提交").exists(timeout=0.15):
            try:
                d(text="提交").click()
            except Exception:
                pass
            print(f"    ✅ 提交！关卡完成")
            time.sleep(0.8)
            return q
        # 弹窗处理：退出确认弹窗（带"温馨提示"标题才是真弹窗；正常答题页的
        # "退出/继续答题"是页面按钮，不能误点！）
        try:
            if d(text="温馨提示").exists(timeout=0.15) or d(textContains="本次闯关尚未完成").exists(timeout=0.15):
                if d(text="继续答题").exists(timeout=0.15):
                    d(text="继续答题").click()
                    print(f"    → 关退出弹窗（继续答题）")
                    time.sleep(0.5)
                    idle = 0
                    continue
            if d(text="确定").exists(timeout=0.15) and d(text="取消").exists(timeout=0.15):
                # 提交确认弹窗 → 点确定
                d(text="确定").click()
                print(f"    ✅ 确定提交")
                time.sleep(0.8)
                continue
        except Exception:
            pass
        # 下一题（答对/录音答完/跳过后的下一步）
        if d(text="下一题").exists(timeout=0.15):
            try:
                d(text="下一题").click()
            except Exception:
                pass
            print(f"    ➡ 下一题")
            time.sleep(0.6)
            retry_count = 0
            idle = 0
            continue
        # 跳过（二次答错）
        if d(text="跳过").exists(timeout=0.15):
            try:
                d(text="跳过").click()
            except Exception:
                pass
            print(f"    ⏭ 跳过（二次答错）")
            time.sleep(0.6)
            retry_count = 0
            q += 1
            idle = 0
            idle = 0
            continue
        # 重新答题（一次答错）
        if d(text="重新答题").exists(timeout=0.15):
            try:
                d(text="重新答题").click()
            except Exception:
                pass
            print(f"    🔄 重新答题")
            time.sleep(0.6)
            retry_count += 1
            continue
        # 检查按钮（答完选项后出现）
        if d(text="检查").exists(timeout=0.15):
            try:
                d(text="检查").click()
            except Exception:
                pass
            print(f"    ✓ 检查")
            time.sleep(0.8)
            continue
        # 填字母题（题目文字含「字母补全」）：
        # 方框 y~430-540 宽 170 + 字母按钮 y 634-991 宽 193（2行5列）
        xml = d.dump_hierarchy()
        is_fill_letters = "字母" in " ".join(
            [e.text or "" for e in (d.xpath('//*[@text!=""]').all() or [])][:6]
        ) and "补全" in " ".join(
            [e.text or "" for e in (d.xpath('//*[@text!=""]').all() or [])][:6]
        )
        if is_fill_letters:
            letter_positions = []
            for m in re.finditer(
                r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml
            ):
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                w, h = x2-x1, y2-y1
                # 字母按钮 193x137 y 600-1000
                if S_h(d, 600) < y1 < S_h(d, 1000) and 180 < w < 210 and 125 < h < 150:
                    letter_positions.append(((x1+x2)//2, (y1+y2)//2))
            letter_positions.sort(key=lambda t: (t[1], t[0]))
            if letter_positions:
                print(f"    🅰 填字母 ({len(letter_positions)}字母)")
                # 点第一个方框（y 400-600 的 LL 170x114）
                first_box = None
                for m in re.finditer(
                    r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                    xml
                ):
                    x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    w, h = x2-x1, y2-y1
                    if S_h(d, 400) < y1 < S_h(d, 600) and 150 < w < 200 and 100 < h < 130:
                        first_box = ((x1+x2)//2, (y1+y2)//2)
                        break
                if first_box:
                    try:
                        d.click(*first_box)
                    except Exception:
                        pass
                    time.sleep(0.4)
                # 依次点字母按钮（填每个方框，检测出现即停）
                for bx, by in letter_positions:
                    try:
                        d.click(bx, by)
                    except Exception:
                        pass
                    time.sleep(0.2)
                    if d(text="检查").exists(timeout=0.1):
                        break
                time.sleep(0.4)
                q += 1
                idle = 0
                idle = 0
                retry_count = 0
                continue
        # 选项（A/B/C 或 T/F）
        clicked = False
        for kw in ("A", "B", "T", "F"):
            if d(text=kw).exists(timeout=0.1):
                try:
                    d(text=kw).click()
                except Exception:
                    pass
                print(f"    → 选 {kw}")
                time.sleep(0.4)
                clicked = True
                break
        if clicked:
            # 答题后可能直接下一题（答对自动跳转）
            continue
        # 录音题（听录音跟读）：原音 → 点击录音 → 点击结束 → 检查
        if d(text="原音").exists(timeout=0.1):
            print(f"    🎤 录音题")
            try:
                # 1. 点原音（听正确发音）
                d(text="原音").click()
                time.sleep(0.8)
                # 2. 点点击录音（开始录音）
                if d(text="点击录音").exists(timeout=1.5):
                    d(text="点击录音").click()
                    print(f"      → 点击录音")
                    time.sleep(0.6)
                    # 3. 点击结束（录音后出现）
                    if d(text="点击结束").exists(timeout=1.5):
                        d(text="点击结束").click()
                        print(f"      → 点击结束")
                        time.sleep(0.8)
            except Exception:
                pass
            # 4. 检查
            try:
                if d(text="检查").exists(timeout=1.5):
                    d(text="检查").click()
                    time.sleep(0.8)
            except Exception:
                pass
            q += 1
            idle = 0
            idle = 0
            retry_count = 0
            continue
        # 未知题型：截图保存，稍等（连续 5 次未知说明页面异常，退出防空转）
        try:
            _shot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
            shot_to_file(d, os.path.join(_shot_dir, f"unknown_qiaoji_{q}.jpg"), width=640)
        except Exception:
            pass
        print(f"    ⚠ 未知: {[e.text for e in (d.xpath('//*[@text!=\"\"]').all() or []) if e.text][:4]}")
        idle += 1
        time.sleep(0.8)
        if idle >= 5:
            print(f"    ⚠ 连续 {idle} 次未知，退出循环")
            return q
    return q


def _run_one_level(d, level_no):
    """跑一个关卡：进入 → 答题（答完自动提交）→ back 回地图"""
    print(f"\n  🎮 关卡 {level_no}")
    if not _enter_level(d, level_no):
        return 0
    q = _answer_loop(d, max_q=40)  # 关卡15+题，max_q 要够大（含重试轮次）
    print(f"  ✅ 关卡 {level_no} 完成: {q} 题")
    # 报告页/答题页 → back 回地图（最多 3 次）
    for _ in range(3):
        texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        # 已在地图（出现关卡数字或boss关）
        if 'boss关' in texts or _find_level_positions(d):
            break
        d.press("back")
        time.sleep(0.6)
    return q


def _run_one_unit(d, unit_no, start_level):
    """跑一个单元的关卡（start_level 到 start_level+4 数字关 + 最后 boss 关）
    unit_no: 单元号（1 开始）
    start_level: 本单元起始关卡序号（U1=1, U2=7, U3=13...）
    """
    total = 0
    # 数字关 start_level ~ start_level+4（5 关）
    for i in range(5):
        level_no = start_level + i
        q = _run_one_level(d, level_no)
        total += q
    # boss 关（level_no=0 表示 boss）
    q = _run_one_level(d, 0)
    total += q
    # 通过 boss 关 → 点「下一单元」
    for _ in range(4):
        if d(text="下一单元").exists(timeout=1.5):
            d(text="下一单元").click()
            print(f"    ✅ 下一单元")
            time.sleep(1.2)
            break
        d.press("back"); time.sleep(0.6)
    return total


def run_module(d, units=None):
    """核心入口：跑完巧记单词指定单元

    units: 单元范围，如 [1,2] 或 '1-2'；None=默认全部
    """
    t0 = time.time()
    total = 0
    _units = _resolve_units(units, UNITS)
    print(f"\n📋 巧记单词 · 单词同步闯关（单元 {_units[0]}-{_units[-1]} · {len(_units)}个）")

    # 1. 进入巧记单词
    if not _enter_qiaoji(d):
        return 0
    # 2. 单词同步闯关
    if not _enter_sync_challenge(d):
        return 0

    # 3. 逐单元闯关（关卡序号连续递增）
    # U1: 关卡 1-6(boss)，U2: 7-12，U3: 13-18 ...
    for unit_no in _units:
        start_level = 1 + (unit_no - 1) * LEVELS_PER_UNIT
        if start_level > 54:
            print(f"  ⚠ Unit {unit_no} 超出范围（仅支持1-9），跳过")
            continue
        print(f"\n🏫 Unit {unit_no}（关卡 {start_level}~{start_level+5}）")
        q = _run_one_unit(d, unit_no, start_level)
        total += q

    print(f"✅ 巧记单词完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
    return total


def main():
    d = u2.connect()
    print("✅ 设备已连接")
    d.press("home"); time.sleep(0.4)
    d.app_stop(APP_PACKAGE); time.sleep(0.8)
    d.app_start(APP_PACKAGE); time.sleep(3)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    # ★ 仅命令行单跑时需要；多模块调度器已在开头统一切换一次，不重复
    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败")
        return 1
    run_module(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
