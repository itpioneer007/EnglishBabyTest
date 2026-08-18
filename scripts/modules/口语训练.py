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
import os
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


def _env_units():
    """从环境变量读取单元范围 (scheduler 设置); 未设置时默认 Unit 1"""
    f = os.environ.get("YYB_UNIT_FROM", "")
    t = os.environ.get("YYB_UNIT_TO", "")
    if f.isdigit():
        f = int(f)
        t = int(t) if t.isdigit() else f
        return list(range(f, t + 1))
    return [1]

UNITS = _env_units()  # U1 验证；打通后 list(range(1, 5))

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


def _click_next_btn(d):
    """点击"下一题"按钮（大题答完时出现）
    ★ 口语训练是原生 SpokeTestActivity：按钮可能无 text（图片/rid），
      d(text="下一题") 找不到。三重检测：
      ① 文本"下一题/下一题按钮/next"
      ② resource-id 含 next/next_btn/btn_next
      ③ 兜底：右下角固定区域（next 按钮通常在右下角 (900-1050, y1900-2150)）
    """
    import re as _re
    try:
        xml = d.dump_hierarchy()
    except Exception:
        xml = ""
    # ① 文本
    for t in ("下一题", "下一题", "next", "Next"):
        try:
            if d(textContains=t).exists(timeout=0.1):
                d(textContains=t).click()
                return True
        except Exception:
            pass
    # ② rid 含 next
    m = _re.search(r'resource-id="[^"]*next[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if m:
        x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
        d.click((x1 + x2) // 2, (y1 + y2) // 2)
        return True
    # ③ 兜底：右下角区域找可点击节点（next 按钮位置）
    for m2 in _re.finditer(r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        x1, y1, x2, y2 = (int(m2.group(i)) for i in range(1, 5))
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if cx > 600 and cy > 1700 and (x2 - x1) < 400:  # 右下角小按钮
            d.click(cx, cy)
            return True
    return False


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
    # ★ 竞态修复：等 App 把"点击录音"切换成"点击结束"状态再点（轮询替代固定0.35s）。
    #   否则点快于刷新 → 第二次点击点空/误点，录音没结束就进入下一小题。
    _t0 = time.time()
    _ended = False
    while time.time() - _t0 < 2.0:
        try:
            _x = d.dump_hierarchy()
            if "点击结束" in _x or "点击完成" in _x:
                _ended = True
                break
            # 状态已变（录音按钮消失）也算就绪
            if "点击录音" not in _x and "点击录制" not in _x:
                _ended = True
                break
        except Exception:
            pass
        time.sleep(0.1)
    if not _ended:
        time.sleep(0.3)  # 兜底：状态未切换也等一次再点（防点空）
    # 4. 点结束（同一位置，文字从"点击录音"变成"点击结束"）
    d.click(pos[0], pos[1])
    print(f"    ⏹ 点结束 ({pos[0]},{pos[1]})")
    step_log(f"⏹ 点结束", "info")
    # ★ 等"点击结束"消失（本轮小题完成，App 进入下一小题或出"下一题"）
    _t1 = time.time()
    while time.time() - _t1 < 1.5:
        try:
            _x2 = d.dump_hierarchy()
            if "点击结束" not in _x2 and "点击完成" not in _x2:
                break
        except Exception:
            pass
        time.sleep(0.1)
    return True


def _answer_big_question(d, big_idx=0):
    """作答一个大题（含多个小题）：
    - 大题首题需等"请阅读题目"倒计时结束（仅首次大题需要）
    - 每小题前可能要点小喇叭播放问题
    - 然后点录音+点结束
    - 下滑查看下一小题（4/5, 5/5等）
    - 答完所有小题 → 出现「下一大题」或「交卷」

    ★ 用户实测根因（2026-08-18）：
      - 口语训练是"同页连续"模式：5 个喇叭图标都在同一页，进度条 1/5~5/5
      - 大题间**没有"下一题"按钮**（找"下一题"永远找不到 → _answer_big_question 跑完 15 次循环
        → 第 6 次发"第6题·完整性检查"证据卡 → 重复计题 + 误判"作答未识别"）
      - 退出条件应改为：进度条到 5/5 + 找"交卷/下一大题/开始训练下一题/再来一组"等大题间过渡按钮
    """
    q = 0
    _ev_q = -1  # 已发证据卡的题号（每题只发一次）
    _score_checked = False  # ★ 每大题只做一次分值检查（避免拖慢流程）
    # ★ 大题最多 5 小题（口语训练每大题固定 5 题，进度条 N/5），不再盲目跑 15 次
    for _ in range(5):
        # ★ 每题界面级完整性检查证据（题型/题干/选项/音频/作答）→ 前端证据卡
        #   口语题为录音作答：证据卡会显示"录音/麦克风"作答元素 + 题干文字
        #   ★ 精确定位：标注"第big_idx大题·第M小题"（用户要求错题能定位到题）
        if q != _ev_q:
            try:
                _xml_ev = d.dump_hierarchy()
                from common.evidence import collect_ui_evidence
                step_log(f"  第{big_idx}大题·第{q+1}小题 完整性检查", "info",
                         collect_ui_evidence(_xml_ev, qtype="口语训练"))
                # ★ 文档检查点：大题首题做一次分值核对（页面显示的分值是否正常）
                if not _score_checked:
                    _score_checked = True
                    try:
                        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        from src.doc_checks import check_score_display
                        check_score_display(d)
                    except Exception:
                        pass
                _ev_q = q
            except Exception:
                pass
        # ★ 停止检查：web_server 收到停止请求 → 中断
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q
        # 完成判断：练习报告页（交卷后出现，整单元结束）
        if d(text="练习报告").exists(timeout=0.1):
            print(f"    ✅ 练习报告页出现，单元结束")
            step_log("📊 练习报告（单元完成）", "success")
            # ★ 文档检查点：报告页核对（总分=得分之和、结果图标、题干文字）
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from src.doc_checks import check_report_page
                check_report_page(d, module_name="口语训练")
            except Exception:
                pass
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
                # ★ 等练习报告渲染（1-2s 延迟）：确保上层 _run_unit_questions
                #   能检测到"练习报告"→ 不会误进下一大题记假错题
                for _r in range(5):
                    if d(text="练习报告").exists(timeout=0.5):
                        break
                    time.sleep(0.5)
            return q

        # ★★★ 完成判断：口语训练同页模式（进度条 1/5~5/5），大题结束靠【进度满 5/5】+ 大题间按钮
        #   找"交卷"/"确定交卷"/"下一大题"/"开始训练下一题"/"再来一组"/"提交成绩"等大题间过渡按钮
        _big_done_btn = None
        for _btxt in ("交卷", "下一大题", "开始训练下一题", "再来一组", "提交成绩", "完成本大题", "下一组", "下一题"):
            try:
                if d(text=_btxt).exists(timeout=0.06):
                    _big_done_btn = _btxt
                    break
            except Exception:
                pass
        if _big_done_btn:
            d(text=_big_done_btn).click()
            print(f"    ✅ 大题完成 → 点{_big_done_btn}")
            step_log(f"➡ {_big_done_btn}", "success")
            time.sleep(0.6)
            return q
        # 旧逻辑兜底：找"下一题"按钮（兼容旧 App 布局）
        if q > 0 and d(text="下一题").exists(timeout=0.1):
            d(text="下一题").click()
            print(f"    ➡ 下一题（进入下一大题）")
            step_log(f"➡ 进入下一大题", "step")
            time.sleep(0.8)
            return q

        # ★ 用户优化：麦克风全部点击完出现下一题后快速点下一题（不等倒计时）
        #   下滑策略改为：只要当前页没有"点击录音"按钮（无论大题刚切换/录音结束/需要下一小题）
        #   就立即下滑（最多 2 屏），不再等 _wait_countdown 慢轮询
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

        # ★ 大题首题（q==0）：必须等"请阅读题目"倒计时结束、第一个麦克风出现！
        #   ★★ 用户实测根因：首题还在倒计时时找麦克风必然找不到 → 立即下滑 →
        #   下滑2次找不到 → 误判"大题结束"退出 → 0题。必须等倒计时结束再作答。
        if q == 0 and not _find_record_btn(d):
            print(f"    ⏳ 首题等待倒计时结束（等第一个麦克风出现）…")
            step_log(f"⏳ 首题等待麦克风", "info")
            _wait_countdown(d, timeout=18)  # 等"点击录音"出现（倒计时通常12s）
            if not _find_record_btn(d):
                # 倒计时结束仍无麦克风 → 才下滑找（长页面首题可能在下方）
                S_swipe(d, 540, 1600, 540, 800, 0.4)
                time.sleep(0.4)
        # ★ 用户要求：先快速试一次(不等倒计时)；若没找到"点击录音"则立即下滑（不等15s）
        #   之前路径：_speak_question 默认 wait_countdown=True → _wait_countdown 等15s
        #   → 每题白白等 15s，即使录音按钮马上就有
        #   优化：第一次尝试不预等；若 _speak_question 失败 → 立刻下滑（不等倒计时）
        if _speak_question(d, wait_countdown=False):
            q += 1
            continue
        # 没找到录音按钮：用户要求"页面没有麦克风图标就往下滑"——直接下滑，不等
        # ★★★ 优化：下滑前不再 _wait_countdown（用户实测白白等 15s+）
        S_swipe(d, 540, 1600, 540, 800, 0.4)
        time.sleep(0.4)
        # 再试一次（同样不等倒计时）
        if _speak_question(d, wait_countdown=False):
            q += 1
            continue
        # 仍没有：再滑一次（覆盖长页面）
        S_swipe(d, 540, 1600, 540, 800, 0.4)
        time.sleep(0.4)
        if _speak_question(d, wait_countdown=False):
            q += 1
            continue
        # ★ 用户要求：麦克风全部点完 → 出现"下一题"就点（大题结束）
        #   下滑 2 次仍无录音按钮 = 本大题已答完，找"下一题"按钮（支持文本/rid/右下角坐标）
        if _click_next_btn(d):
            print(f"    ➡ 下一题（大题完成）")
            step_log(f"➡ 进入下一大题", "step")
            time.sleep(0.6)
            return q  # ★ 修复：之前 continue → 循环继续 → 重复计题；现在 return 退出大题循环
        # ★★★ 兜底：下滑 2 次仍无录音按钮 = 大题已答完（口语训练同页模式，每大题固定 5 小题）
        #   之前错误：继续循环 + 发"第6题"证据卡 + 误判"作答未识别"
        #   修复：直接退出大题循环（q 即为已答小題数）
        if q >= 3:  # 至少答了 3 小题 + 下滑 2 次无录音 = 大题完成
            print(f"    ✅ 大题完成（已答{q}小題，下滑无新录音按钮）")
            return q
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
    # ★ 文档检查点：试卷首页/单元目录核对（标题、总分/时量、按钮文字）
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.doc_checks import check_paper_header
        check_paper_header(d, module_name="口语训练")
    except Exception:
        pass
    if d(text="开始答题").exists(timeout=3):
        d(text="开始答题").click()
        print(f"    ✅ 开始答题")
        time.sleep(1.6)
    return True


def _run_unit_questions(d, unit_num):
    """进入单元后的答题循环（多个大题）"""
    total = 0
    for big in range(1, 10):
        # ★ 前置检查：交卷后练习报告页渲染有 1-2s 延迟，上一轮可能没检测到。
        #   若已在练习报告/交卷确认页 → 直接结束（防止误进"第5大题"记假错题）
        try:
            if d(text="练习报告").exists(timeout=0.3) or d(text="确定交卷").exists(timeout=0.3):
                print(f"  ✅ 已交卷/练习报告，结束（不进入第{big}大题）")
                return total
        except Exception:
            pass
        # ★ 大题切换后等待页面稳定：
        #   第一大题 → 等 18s（"请阅读题目"倒计时结束+第一个麦克风出现，用户实测根因）
        #   后续大题 → 3s 快速（页面已加载过，切换快）
        _wait_max = 18 if big == 1 else 3
        t_st = time.time()
        while time.time() - t_st < _wait_max:
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
        # ★ 若本大题 0 小题（q==0）→ 说明已交卷/结束/页面已到报告页，不再进入下一大题
        #   （交卷后练习报告渲染延迟，上一轮检测可能失败，q==0 是可靠信号）
        if q == 0:
            return total
        # 若交卷/练习报告了则退出（交卷后出现练习报告页；timeout 提高到 3s 等渲染）
        if d(text="确定交卷").exists(timeout=3) or d(text="练习报告").exists(timeout=3):
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
    #   ★ 修复：不能用 back 硬退（练习报告/子页面 back 会退出 App 到桌面）
    #   → 先检查是否 yyb 前台，非 yyb 冷启动；yyb 内 back 循环回主页
    try:
        _pkg = (d.app_current() or {}).get("package", "")
        if _pkg != "com.dinoenglish.yyb":
            d.press("home"); time.sleep(0.4)
            d.app_start("com.dinoenglish.yyb"); time.sleep(3)
    except Exception:
        pass
    for _ in range(6):
        try:
            xml = d.dump_hierarchy()
            if ("教材精学" in xml or "专项突破" in xml or "听课文" in xml):
                break
        except Exception:
            pass
        d.press("back"); time.sleep(0.5)

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
