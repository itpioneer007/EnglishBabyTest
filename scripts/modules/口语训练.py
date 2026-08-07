"""
英语宝 · 口语训练 模块
=====================
独立可运行：python modules/口语训练.py

流程：进口语训练 → 关底部广告(❌) → 开始答题/重新答题
  → 好的，我知道啦~ → 开始答题
  → 每个大题：等"请阅读题目"倒计时结束(12s) → 点击"点击录音"上方麦克风
     → 点击"点击结束" → 自动跳下一小题 → 重复
  → 需要下滑才能看到录音图标（每道口语题说的内容不同，滑动时机需现场判断）
  → 题型2：先点每个小题左上角"小喇叭"播放 → 再录音/结束
  → 答完该大题所有小题 → "下一题" → 下一大题
  → 最后一道 → "交卷" → "确定交卷" → 练习报告 → back → 下一单元

批量调用：from modules.口语训练 import run_module; run_module(d)
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.logger import step_log, should_stop
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade,
)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

UNITS = [1]  # U1 验证；打通后 list(range(1, 5))

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



def _close_bottom_ad(d):
    """关闭界面底部广告：找 ❌ 按钮点击"""
    # 方式1：contentDescription 含"关闭"
    try:
        if d(description="关闭").exists(timeout=1):
            d(description="关闭").click()
            print("    🔔 关闭底部广告 (description=关闭)")
            time.sleep(0.35)
            return True
    except Exception:
        pass
    # 方式2：找小尺寸 clickable X（底部区域 y>1800）
    try:
        for elem in (d.xpath('//*[@clickable="true"]').all() or []):
            b = elem.bounds
            w = b[2] - b[0]
            h = b[3] - b[1]
            if w < 80 and h < 80 and b[1] > S_h(d, 1700):
                elem.click()
                print(f"    🔔 关闭底部广告 (小X按钮)")
                time.sleep(0.35)
                return True
    except Exception:
        pass
    print("    ⚠ 未发现底部广告")
    return False


def _find_record_btn(d):
    """动态查找麦克风按钮：找"点击录音"文字位置，其上方圆形 clickable。
    关键：录音按钮坐标会随页面滚动/换题变化，必须动态获取。
    """
    rec = None
    for e in (d.xpath('//*[@text!=""]').all() or []):
        t = (e.text or "").strip()
        if "点击录音" in t or "点击录制" in t:
            rec = e
            break
    if not rec:
        return None
    rb = rec.bounds
    rx, ry = (rb[0] + rb[2]) // 2, (rb[1] + rb[3]) // 2
    # 找"点击录音"文字正上方的圆形 clickable（麦克风）
    for ce in (d.xpath('//*[@clickable="true"]').all() or []):
        b = ce.bounds
        cx = (b[0] + b[2]) // 2
        cy = (b[1] + b[3]) // 2
        # 麦克风特征：在文字上方，x 接近，宽 200-300、高 250-300
        if abs(cx - rx) < 100 and cy < ry and (ry - cy) < 200 and (b[2]-b[0]) > 150:
            return (cx, cy)
    return None


def _click_horn(d, min_y=400):
    """点击当前可见的小喇叭（宽70-100高60-80的小图标）。
    小喇叭特征：宽70-100、高60-80 的小 clickable。
    """
    # 优先点录音按钮上方附近的小喇叭
    rec = _find_record_btn(d)
    candidates = []
    for e in (d.xpath('//*[@clickable="true"]').all() or []):
        b = e.bounds
        w = b[2] - b[0]
        h = b[3] - b[1]
        if 70 < w < 100 and 60 < h < 80 and b[1] > min_y:
            candidates.append((e, (b[0]+w//2, b[1]+h//2)))
    if not candidates:
        return None
    # 若有录音按钮参考，选 x 最接近的（小喇叭和麦克风在同一小题）
    if rec:
        candidates.sort(key=lambda c: abs(c[1][0] - rec[0]))
    e, pos = candidates[0]
    e.click()
    return pos


def _wait_countdown(d, timeout=15):
    """等待'请阅读题目'倒计时结束（出现'点击录音'文字）。
    速度优化：轮询间隔 0.25s，出现录音按钮立即返回。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _find_record_btn(d):
            return True
        time.sleep(0.12)
    return False


def _speak_question(d, wait_countdown=True):
    """作答一个小题（动态坐标）：等倒计时 → 点录音 → 点结束。
    关键：录音麦克风位置是动态的，必须每次用 _find_record_btn 获取。
    速度优化：录音后等待缩短（App 切换状态约 0.8s）
    """
    # 1. 等倒计时结束
    if wait_countdown:
        _wait_countdown(d)

    # 2. 动态找录音按钮
    pos = _find_record_btn(d)
    if not pos:
        # 可能页面没渲染完或需下滑
        time.sleep(0.3)
        pos = _find_record_btn(d)
    if not pos:
        print("    ⚠ 未找到录音按钮")
        return False

    # 3. 点录音图标（麦克风圆形按钮）
    d.click(pos[0], pos[1])
    print(f"    🎤 点录音 ({pos[0]},{pos[1]})")
    step_log(f"🎤 点录音", "info")
    time.sleep(0.35)

    # 4. 点结束（同一位置，文字从"点击录音"变成"点击结束"）
    d.click(pos[0], pos[1])
    print(f"    ⏹ 点结束 ({pos[0]},{pos[1]})")
    step_log(f"⏹ 点结束", "info")
    time.sleep(0.6)
    return True


def _answer_big_question(d, big_idx=0):
    """作答一个大题（含多个小题）：
    - 大题首题需等"请阅读题目"倒计时结束（仅首次大题需要）
    - 每小题前可能要点小喇叭播放问题
    - 然后点录音+点结束
    - 下滑查看下一小题（4/5, 5/5等）
    - 答完所有小题 → 出现「下一题」或「交卷」
    """
    q = 0
    for _ in range(15):  # 最多15小题（包含若干道口语题）
        # ★ 停止检查：web_server 收到停止请求 → 中断
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q
        # 完成判断：练习报告页（交卷后出现，整单元结束）
        if d(text="练习报告").exists(timeout=0.1):
            print(f"    ✅ 练习报告页出现，单元结束")
            step_log("📊 练习报告（单元完成）", "success")
            time.sleep(0.8)
            return q

        # 完成判断：交卷（最后一题）
        if d(text="交卷").exists(timeout=0.1):
            d(text="交卷").click()
            print(f"    ✅ 交卷按钮出现，点击交卷")
            step_log("✅ 交卷", "success")
            time.sleep(0.6)
            if d(text="确定交卷").exists(timeout=2):
                d(text="确定交卷").click()
                print(f"    ✅ 确定交卷")
                time.sleep(1.2)
            return q

        # 完成判断：下一题（大题答完）——仅当本大题已答过题 或 页面有录音按钮时才允许
        # 防止大题刚切换时误点"下一题"（此时页面还在加载/倒计时）
        if q > 0 and d(text="下一题").exists(timeout=0.1):
            d(text="下一题").click()
            print(f"    ➡ 下一题（进入下一大题）")
            step_log(f"➡ 进入下一大题", "step")
            time.sleep(0.8)
            return q

        # 检查是否小喇叭题型（页面有"小喇叭"提示或喇叭图标）
        # 方式1：找"小喇叭"文字
        has_horn = False
        for e in (d.xpath('//*[@text!=""]').all() or []):
            t = (e.text or "").strip()
            if "小喇叭" in t or "播放问题" in t:
                has_horn = True
                break
        if has_horn:
            pos = _click_horn(d)
            if pos:
                print(f"    🔊 点小喇叭 ({pos[0]},{pos[1]})")
                step_log(f"🔊 点小喇叭", "info")
                time.sleep(0.6)

        # 作答小题（用户约定流程：每道小题点"点击录音"→点"点击结束"，找不到就下滑）
        if _speak_question(d):
            q += 1
        else:
            # 没找到录音按钮：可能大题刚切换（倒计时中）或需下滑
            # 先等倒计时结束再判断
            _wait_countdown(d)
            if _speak_question(d, wait_countdown=False):
                q += 1
                continue
            # 仍没有：下滑查看下一小题
            S_swipe(d, 540, 1600, 540, 800, 0.4)
            time.sleep(0.5)
            # 再尝试一次
            if _speak_question(d, wait_countdown=False):
                q += 1
            else:
                time.sleep(0.4)
    return q


def _run_one_unit(d, unit_num, is_retry):
    """跑一个单元的口语训练"""
    print(f"\n  🎯 口语训练 Unit {unit_num}")
    # 找该单元的答题按钮：3 种状态
    #   - 未训练过："开始答题"
    #   - 已训练过（完成）："重新答题"
    #   - 答题中退出（未完成）："继续答题"
    # 优先"重新答题"（从头开始，每道题都有麦克风），其次"继续答题"，最后"开始答题"
    btn_candidates = ["重新答题", "继续答题", "开始答题"]

    # 方式1：按 "口语训练湘少五上U{unit_num}" 标题文字匹配，定位该行按钮
    import re as _re
    title_pat = _re.compile(rf"[Uu]nits?\s*{unit_num}\b|U{unit_num}\b|{unit_num}")
    for _ in range(8):
        elements = (d.xpath('//*[@text!=""]').all() or [])
        row = None
        for e in elements:
            t = (e.text or "").strip()
            # 单元标题特征：包含"湘少五上"和单元号
            if "口语训练" in t or "U" in t or "Unit" in t:
                if title_pat.search(t):
                    row = e
                    break
        if row:
            row_y = row.bounds[1]
            for e in elements:
                t = (e.text or "").strip()
                if t in btn_candidates:
                    if abs(e.bounds[1] - row_y) < 300:
                        try:
                            e.click()
                        except Exception:
                            d.click((e.bounds[0]+e.bounds[2])//2, (e.bounds[1]+e.bounds[3])//2)
                        print(f"    ✅ 点击 {t} (U{unit_num})")
                        time.sleep(1.2)
                        _after_unit_enter(d)
                        return _run_unit_questions(d, unit_num)
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)

    # 方式2（兜底）：按第 unit_num 个答题按钮（原逻辑）
    btns = []
    idx = unit_num - 1
    chosen_btn = None
    for attempt in range(5):
        for txt in btn_candidates:
            btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                    if (e.text or "").strip() == txt]
            btns.sort(key=lambda e: e.bounds[1])
            if idx < len(btns):
                chosen_btn = txt
                break
        if chosen_btn:
            break
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)
    if not chosen_btn:
        print(f"    ❌ 找不到 U{unit_num} 的答题按钮（已找：{'/'.join(btn_candidates)}）")
        return 0
    btns[idx].click()
    print(f"    ✅ 点击 {chosen_btn} (U{unit_num})")
    time.sleep(1.2)
    _after_unit_enter(d)
    return _run_unit_questions(d, unit_num)


def _after_unit_enter(d):
    """进入单元后的公共处理：弹窗 + 开始答题"""
    if d(text="好的，我知道啦~").exists(timeout=3):
        d(text="好的，我知道啦~").click()
        print(f"    ✅ 好的，我知道啦~")
        time.sleep(0.8)
    if d(text="开始答题").exists(timeout=3):
        d(text="开始答题").click()
        print(f"    ✅ 开始答题")
        time.sleep(1.6)
    return True


def _run_unit_questions(d, unit_num):
    """进入单元后的答题循环（多个大题）"""
    total = 0
    for big in range(1, 10):
        # 大题切换后等待页面稳定（倒计时结束/录音按钮出现），最多15s
        t_st = time.time()
        while time.time() - t_st < 15:
            if _find_record_btn(d):
                break
            time.sleep(0.12)
        # 判断是否最后一题：出现"交卷"
        if d(text="交卷").exists(timeout=0.15):
            print(f"  📝 第{big}大题（最后一题）")
        else:
            print(f"  📝 第{big}大题")
            step_log(f"📝 开始第{big}大题", "step")
        q = _answer_big_question(d, big_idx=big)
        total += q
        # 若交卷/练习报告了则退出（交卷后出现练习报告页）
        if d(text="确定交卷").exists(timeout=0.8) or d(text="练习报告").exists(timeout=0.8):
            break
        time.sleep(0.4)
    return total


def run_module(d, units=None):
    """核心入口：跑完口语训练指定单元，返回题数

    units: 单元范围，如 [1,2] 或 '1-2'；None=默认全部
    """
    t0 = time.time()
    total = 0
    _units = _resolve_units(units, UNITS)
    print(f"\n📋 口语训练 · 单元 {_units[0]}-{_units[-1]} · {len(_units)}个单元")

    # ① 先确保在主页（口语训练入口在主页专项突破区，直接可见，不需要滑动）
    for _ in range(4):
        if d(text="教材精学").exists(timeout=1) or d(text="专项突破").exists(timeout=1):
            break
        d.press("back"); time.sleep(0.6)

    # ② 主页直接找口语训练入口（可见，无需滑动；找不到直接失败）
    if d(text="口语训练").exists(timeout=3):
        d(text="口语训练").click(); time.sleep(1.6)
        print("  ✅ 主页点口语训练入口")
    else:
        print("  ❌ 主页找不到口语训练入口"); return 0

    # 关底部广告
    _close_bottom_ad(d)

    # 逐单元执行
    for ui, unit_num in enumerate(_units):
        # U1 已训练过（重新答题），U2+ 开始答题
        is_retry = (unit_num == 1)
        q = _run_one_unit(d, unit_num, is_retry)
        total += q
        # 答完退出到口语训练列表
        for _ in range(3):
            if d(text="口语训练").exists(timeout=1) or d(text="开始答题").exists(timeout=1):
                break
            d.press("back"); time.sleep(0.6)
        if d(text="口语训练").exists(timeout=2):
            d(text="口语训练").click(); time.sleep(1.2)
        _close_bottom_ad(d)

    print(f"✅ 口语训练完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
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
