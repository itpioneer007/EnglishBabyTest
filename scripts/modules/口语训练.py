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
import sys
import time
import re
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


def _find_record_btn(d, xml=None):
    """动态查找当前可点击的录音按钮中心坐标。

    口语训练录音按钮结构（2026-08-24 真机 dump）：
      - 容器 record_btn (com.dinoenglish.yyb:id/record_btn) clickable=true
      - 内部包含 record_icon_imageview / speech_textview 文字"点击录音"等
      - 文字节点自身 clickable=false
    查找策略：
      ① 优先按 resource-id "record_btn" 定位可点击容器；
      ② 兜底按"点击录音/点击结束/点击完成"文字，找其所在的 clickable 父容器。
    返回 (x, y) 或 None。
    """
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
    # ① 直接定位 record_btn 容器（最可靠，不依赖文字）
    for m in re.finditer(
        r'resource-id="[^"]*record_btn"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    ):
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return ((x1 + x2) // 2, (y1 + y2) // 2)
    # 兼容：文字节点在 record_btn 内部，文字节点不可点击；找包含文字节点的 clickable 容器
    for kw in ("点击录音", "点击结束", "点击完成"):
        m = re.search(rf'text="{re.escape(kw)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            tx1, ty1, tx2, ty2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            tcx, tcy = (tx1 + tx2) // 2, (ty1 + ty2) // 2
            # 找包含该文字中心的 clickable 容器（通常是 record_btn 或 speech_box）
            best = None
            for m2 in re.finditer(
                r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml,
            ):
                bx1, by1, bx2, by2 = int(m2.group(1)), int(m2.group(2)), int(m2.group(3)), int(m2.group(4))
                if bx1 <= tcx <= bx2 and by1 <= tcy <= by2:
                    # 取最小且包含该文字的 clickable 容器
                    area = (bx2 - bx1) * (by2 - by1)
                    if best is None or area < best[2]:
                        best = ((bx1 + bx2) // 2, (by1 + by2) // 2, area)
            if best:
                return best[:2]
    return None


def _is_transition_state(xml):
    """页面是否处于过渡/上传/倒计时状态（此时不应提取证据/找录音按钮）。"""
    if not xml:
        return False
    for kw in ("请阅读题目", "正在上传", "正在提交", "请稍候", "加载中"):
        if kw in xml:
            return True
    return False


def _wait_ready_for_record(d, timeout=20):
    """等待倒计时/上传结束，且 record_btn 出现。
    返回是否成功。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        xml = d.dump_hierarchy()
        if _is_transition_state(xml):
            time.sleep(0.2)
            continue
        pos = _find_record_btn(d, xml)
        if pos:
            return True
        time.sleep(0.2)
    return False


def _find_active_sub_question(d, xml=None):
    """定位当前正在作答的小题（包含 record_btn 的 speech_box）。
    返回 (sub_no, stem_text, speech_box_bounds) 或 (None, "", None)。
    """
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return None, "", None
    # 找所有 speech_box 及其 bounds、内部 tv_sort 文字
    boxes = []
    for m in re.finditer(
        r'<node[^>]*resource-id="[^"]*speech_box"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    ):
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        boxes.append((y1, x1, y2, x2, (x1, y1, x2, y2)))
    if not boxes:
        return None, "", None
    boxes.sort()  # 按 y 排序
    # 哪个 speech_box 内部包含 record_btn？
    record_m = re.search(
        r'resource-id="[^"]*record_btn"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    )
    if not record_m:
        # 兜底：取最上方的 speech_box
        active_box = boxes[0][4]
    else:
        rx1, ry1, rx2, ry2 = int(record_m.group(1)), int(record_m.group(2)), int(record_m.group(3)), int(record_m.group(4))
        rcx, rcy = (rx1 + rx2) // 2, (ry1 + ry2) // 2
        active_box = None
        for y1, x1, y2, x2, box in boxes:
            if x1 <= rcx <= x2 and y1 <= rcy <= y2:
                active_box = box
                break
        if active_box is None:
            active_box = boxes[0][4]
    # 在该 speech_box 内找 tv_sort（如 "1."）和题干文字
    sub_no = None
    stems = []
    bx1, by1, bx2, by2 = active_box
    # 收集 speech_box 内所有 text 节点
    for m in re.finditer(r'<node[^>]*text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        t = m.group(1).strip()
        x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if x1 < bx1 or y1 < by1 or x2 > bx2 or y2 > by2:
            continue
        # tv_sort: "1." / "2."
        mm = re.match(r"^(\d+)\.$", t)
        if mm:
            sub_no = int(mm.group(1))
            continue
        # 过滤噪音：分值、空白、过长
        if t in ("", " ") or "分" in t or len(t) > 40 or len(t) < 1:
            continue
        stems.append(t)
    stem = " / ".join(stems[:2]) if stems else "图片题"
    return sub_no, stem, active_box


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


def _wait_countdown(d, timeout=20):
    """兼容旧调用：等待倒计时/上传结束且录音按钮出现。"""
    return _wait_ready_for_record(d, timeout)


def _speak_one_sub(d):
    """作答当前可见的录音小题：点录音 → 等状态变 → 点结束。
    返回是否成功。
    """
    pos = _find_record_btn(d)
    if not pos:
        return False
    d.click(*pos)
    print(f"    🎤 点录音 ({pos[0]},{pos[1]})")
    step_log("🎤 点录音", "info")
    # 等 App 切换到"点击结束"/"点击完成"状态
    t0 = time.time()
    while time.time() - t0 < 3.0:
        xml = d.dump_hierarchy()
        if _is_transition_state(xml):
            time.sleep(0.15)
            continue
        if "点击结束" in xml or "点击完成" in xml:
            break
        # 兜底：等一小会儿
        time.sleep(0.15)
    # 再点一次结束录音
    d.click(*pos)
    print(f"    ⏹ 点结束 ({pos[0]},{pos[1]})")
    step_log("⏹ 点结束", "info")
    # 等录音结束状态消失（上传/切换下一题）
    t1 = time.time()
    while time.time() - t1 < 3.0:
        xml = d.dump_hierarchy()
        if _is_transition_state(xml):
            time.sleep(0.15)
            continue
        if not _find_record_btn(d, xml):
            # 当前 record_btn 消失/切换了 → 大概率已完成
            break
        if "点击结束" in xml or "点击完成" in xml:
            time.sleep(0.2)
            continue
        break
    return True


def _scroll_question_area(d):
    """在题目滚动区内向下滑动，露出下方小题。"""
    S_swipe(d, 540, 1700, 540, 900, 0.4)


def _answer_big_question(d, big_idx=0):
    """作答一个大题（含若干小题）。

    口语训练当前结构（2026-08-24 真机）：
      - 一个大题一个长页面，顶部进度 "1/4"、"2/4"... 表示大题序号；
      - 页面内列出所有小题（通常 4~5 道），每道小题包含 tv_sort "1."、pic_iv 图片、分值；
      - 同一时刻只有一道小题出现可点击的 record_btn；
      - 点完当前小题录音后，下一道小题的 record_btn 才会出现；
      - 本大题全部答完后，底部出现"下一题"/"交卷"按钮。

    流程：
      1. 等"请阅读题目"倒计时结束，首个 record_btn 出现；
      2. 逐小题：定位当前 active record_btn → 收集证据 → 点录音 → 点结束；
      3. 当前 record_btn 消失后，若下方出现新的 record_btn 继续；否则下滑；
      4. 无新 record_btn 且出现"下一题/交卷" → 点击进入下一大题。
    """
    q = 0
    _ev_q = -1          # 已发证据卡的题号（每小题只发一次）
    _score_checked = False
    _horn_clicked = False  # 每大题只需点一次顶部说明喇叭

    # 1. 等大题首题 ready
    if not _wait_ready_for_record(d, timeout=22):
        print(f"    ❌ 第{big_idx}大题：等待首题录音按钮超时")
        return 0

    # 2. 逐小题作答
    for _ in range(30):  # 防护上限
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q

        xml = d.dump_hierarchy()

        # 整单元结束标记
        if "练习报告" in xml:
            print(f"    ✅ 练习报告页出现，单元结束")
            step_log("📊 练习报告（单元完成）", "success")
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from src.doc_checks import check_report_page
                check_report_page(d, module_name="口语训练")
            except Exception:
                pass
            return q

        # 大题间过渡按钮（下一题/交卷等）
        _big_done_btn = None
        for _btxt in ("交卷", "下一大题", "开始训练下一题", "再来一组", "提交成绩", "完成本大题", "下一组", "下一题"):
            if d(text=_btxt).exists(timeout=0.05):
                _big_done_btn = _btxt
                break
        if _big_done_btn:
            # 仅当本大题已答至少 1 小题，或按钮是"交卷"（最后一题）时才点
            if q > 0 or _big_done_btn == "交卷":
                d(text=_big_done_btn).click()
                print(f"    ✅ 大题完成 → 点{_big_done_btn}")
                step_log(f"➡ {_big_done_btn}", "success")
                time.sleep(0.8)
                return q

        # 找当前 active 录音按钮
        pos = _find_record_btn(d, xml)
        if not pos:
            # 当前屏没有，下滑继续找
            _scroll_question_area(d)
            time.sleep(0.5)
            pos = _find_record_btn(d)
            if not pos:
                # 下滑后仍无录音按钮，且存在下一题 → 本大题答完
                if _click_next_btn(d):
                    print(f"    ➡ 下一题（大题完成）")
                    step_log("➡ 进入下一大题", "step")
                    time.sleep(0.8)
                    return q
                # 仍无按钮，可能已结束或异常
                if q > 0:
                    print(f"    ✅ 大题完成（已答{q}小题，无新录音按钮）")
                    return q
                print(f"    ⚠ 第{big_idx}大题未找到任何录音按钮")
                return q

        # 确定当前小题编号/题干
        sub_no, stem, _ = _find_active_sub_question(d, xml)
        sub_label = sub_no if sub_no is not None else q + 1

        # 每小题只发一次证据卡（避免重复）
        if q != _ev_q:
            try:
                from common.evidence import collect_ui_evidence
                step_log(f"  第{big_idx}大题·第{sub_label}小题（{stem}）完整性检查", "info",
                         collect_ui_evidence(xml, qtype="口语训练"))
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

        # 每大题首次点击顶部说明小喇叭（iv_caption_play）
        if q == 0 and not _horn_clicked:
            try:
                if d(resourceId="com.dinoenglish.yyb:id/iv_caption_play").exists(timeout=0.2):
                    d(resourceId="com.dinoenglish.yyb:id/iv_caption_play").click()
                    print("    🔊 播放题目说明")
                    time.sleep(0.5)
                    _horn_clicked = True
            except Exception:
                pass

        # 作答
        if _speak_one_sub(d):
            q += 1
            time.sleep(0.3)
            continue
        else:
            print(f"    ⚠ 第{big_idx}大题·第{sub_label}小题录音失败")
            _scroll_question_area(d)
            time.sleep(0.5)

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
