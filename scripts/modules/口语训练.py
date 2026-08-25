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
    scroll_and_find,
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
    """定位当前正在作答的小题（含 record_btn 的 ll_container）。

    口语训练真机结构（2026-08-24 实测 oral_q3 / cur_home dump）：
      - option_flexbox 内多个 ll_container，每个 = 一个小题：
          tv_sort（内容 "1/5" / "2/5"，或 "1."/"2."）
          speech_box
            ├ speech_content（朗读句子题：小题题干 = 句子文本，如 "I see a bee..."）
            └ speech_translation（翻译，可能为空）
          或（看图回答题）tv_title_score "(2分)" + tv_answer_status "已作答" + pic_iv
      - record_btn 只在当前作答小题出现（倒计时中/已作答状态无 record_btn）
      - tv_question_sort（顶部 "N/M"）是大题进度，tv_sort 是小题进度（M = 本大题小题总数）
    返回 (sub_no, total_sub, stem_text, ll_container_bounds)；
    找不到时返回 (None, None, "", None)。
    """
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return None, None, "", None

    # 1) record_btn 中心（当前作答小题的麦克风）
    rec_m = re.search(
        r'resource-id="[^"]*record_btn"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    )
    rcx = rcy = None
    if rec_m:
        rcx = (int(rec_m.group(1)) + int(rec_m.group(3))) // 2
        rcy = (int(rec_m.group(2)) + int(rec_m.group(4))) // 2

    # 2) 所有 ll_container（小题容器，tv_sort 与 speech_box 都在其内）
    containers = []
    for m in re.finditer(
        r'<node[^>]*resource-id="[^"]*ll_container"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    ):
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        containers.append((x1, y1, x2, y2))
    if not containers:
        return None, None, "", None
    containers.sort()  # 按 y 排序

    # 3) 选包含 record_btn 的容器；无 record_btn（倒计时/已答完）→ 取第一个
    active = None
    if rcx is not None:
        for box in containers:
            if box[0] <= rcx <= box[2] and box[1] <= rcy <= box[3]:
                active = box
                break
    if active is None:
        active = containers[0]

    # 4) 容器内提取：tv_sort（"N/M" 或 "N."）+ 题干文本
    sub_no, total_sub = None, None
    stems = []
    ax1, ay1, ax2, ay2 = active
    for m in re.finditer(r'<node[^>]*text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        t = m.group(1).strip()
        x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if x1 < ax1 or y1 < ay1 or x2 > ax2 or y2 > ay2:
            continue
        # tv_sort: "1/5" / "2/5"（n/本大题小题总数） 或 "1." / "2."
        mm = re.match(r"^(\d+)\s*/\s*(\d+)$", t)
        if mm:
            sub_no, total_sub = int(mm.group(1)), int(mm.group(2))
            continue
        mm = re.match(r"^(\d+)[\.、]\s*$", t)
        if mm:
            sub_no = int(mm.group(1))
            continue
        # ★ 2026-08-25 噪音过滤（按真实页面补充）：
        #   ① 动作文本（麦克风区按钮文字，不是题干）："点击录音"/"点击结束"/"点击完成"/"继续作答"
        #   ② 分值 "(2分)" / 计时 "0.0" / "25S"（原逻辑）
        #   ③ 作答状态 "已作答"/"未作答"（原逻辑）
        if t in ("点击录音", "点击结束", "点击完成", "继续作答", "结束录音", "录音中"):
            continue
        if t in ("", " ") or "分" in t or "作答" in t or len(t) > 60:
            continue
        if re.match(r"^\d+(\.\d+)?\s*S?$", t) or re.match(r"^S\s*\d+$", t):
            continue
        # ★ 2026-08-25 优先：小题题干通常是"句型提示：xxx"/"听力材料：xxx"/"单词"等
        #   保留原始前缀（不剥除"句型提示："），学生在 App 看到的就是这个
        #   短中文/无内容（如"句型提示"被 split 后）→ 跳过
        if not t or len(t) < 1:
            continue
        stems.append(t)
    stem = " / ".join(stems[:2]) if stems else "图片题"
    return sub_no, total_sub, stem, active


def _get_big_progress(xml):
    """读取页面顶部大题进度（tv_question_sort，内容如 "2/4" = 第2大题/共4大题）。
    返回 (current_big, total_big) 或 (None, None)。
    """
    if not xml:
        return None, None
    # ★ 真机 dump 属性顺序 text 在 resource-id 之前，先定位节点再取 text
    for m in re.finditer(r'<node[^>]*tv_question_sort[^>]*>', xml):
        tm = re.search(r'text="(\d+)\s*/\s*(\d+)"', m.group(0))
        if tm:
            return int(tm.group(1)), int(tm.group(2))
        break
    return None, None


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
    _last_ev_big = -1       # 上次发证据卡时的大题号（变化时=新大题首小题，发"大题题干"）

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

        # 找当前 active 录音按钮（★ 优先答小题；过渡按钮检测移到下方"无录音按钮"分支，
        #   因为真机 btn_box 的"下一题/交卷"按钮常驻——第4大题从答题开始就有"交卷"，
        #   若在循环顶部检测 → 答完1小题就点交卷 → 被 App Toast 拒绝（还有题未答）
        #   → 交卷不生效、界面停住、脚本却误报"点交卷"成功）
        pos = _find_record_btn(d, xml)
        if not pos:
            # 当前屏没有，下滑继续找
            _scroll_question_area(d)
            time.sleep(0.5)
            try:
                xml = d.dump_hierarchy()   # ★ 滚动后必须刷新 XML：证据卡/小题题干都用它，
            except Exception:              #   否则拿滚动前的旧 XML → 麦克风/题干都检测不到
                pass
            pos = _find_record_btn(d, xml)
            if not pos:
                # ---- 下滑后仍无录音按钮 → 本大题已答满，处理过渡按钮 ----
                # 1) 交卷（最后一大题）：点击后必须等"确定交卷"确认框！
                #    确认框不出现 = 交卷被 App 拒绝（还有小题未答/页面未就绪）
                #    → continue 重新循环，不误报成功
                if d(text="交卷").exists(timeout=0.2):
                    d(text="交卷").click()
                    print(f"    ✅ 大题完成 → 点交卷")
                    step_log("➡ 交卷", "success")
                    if d(text="确定交卷").exists(timeout=2):
                        d(text="确定交卷").click()
                        print("    ✅ 点确定交卷")
                        step_log("➡ 确定交卷", "success")
                        time.sleep(1.0)
                        if not d(text="练习报告").exists(timeout=3):
                            print("    ⚠ 确定交卷后练习报告未出现（可能仍在渲染）")
                        else:
                            print("    ✅ 练习报告页出现")
                        return q
                    else:
                        print("    ⚠ 点交卷后未出现确认框（可能还有小题未答），继续作答")
                        time.sleep(0.5)
                        continue
                # 2) 其他大题过渡按钮（下一大题/再来一组/提交成绩…）
                _done_btn = None
                for _btxt in ("下一大题", "开始训练下一题", "再来一组", "提交成绩", "完成本大题", "下一组"):
                    if d(text=_btxt).exists(timeout=0.05):
                        _done_btn = _btxt
                        break
                if _done_btn:
                    d(text=_done_btn).click()
                    print(f"    ➡ {_done_btn}（大题完成）")
                    step_log(f"➡ {_done_btn}", "step")
                    time.sleep(0.8)
                    return q
                # 3) 下一题按钮（此时 record_btn 已消失 = 本大题答满，点击安全）
                if _click_next_btn(d):
                    print(f"    ➡ 下一题（大题完成）")
                    step_log("➡ 进入下一大题", "step")
                    time.sleep(0.8)
                    return q
                # 4) 无任何过渡按钮 → 大题完成/结束
                if q > 0:
                    print(f"    ✅ 大题完成（已答{q}小题，无新录音按钮）")
                    return q
                print(f"    ⚠ 第{big_idx}大题未找到任何录音按钮")
                return q

        # 确定当前小题编号/题干
        sub_no, total_sub, stem, _ = _find_active_sub_question(d, xml)
        sub_label = sub_no if sub_no is not None else q + 1

        # 每小题只发一次证据卡（避免重复）
        if q != _ev_q:
            try:
                from common.evidence import collect_ui_evidence
                # ★ 2026-08-25：每大题只在第一小题下显示大题题干（来自 tv_caption），
                #   后续小题 skip_stem=True 不显示大题题干——避免下滑后大题题干错位显示
                #   成上面大题的内容（用户实测"听/答→listen/answer"残留）
                _is_first_of_big = (big_idx != _last_ev_big)
                _ev = collect_ui_evidence(xml, qtype="口语训练", skip_stem=not _is_first_of_big)
                # ★ 小题题干：每小题都加（口语训练学生看的就是"句型提示：xxx"/"听力材料：xxx"/"单词"等）
                if stem:
                    _sub_label = f"小题{sub_label}" + (f"/{total_sub}" if total_sub else "")
                    _ev.insert(1, {"field": "小题题干", "type": "info",
                                   "expected": "当前作答小题的题干",
                                   "actual": stem,
                                   "diff": f"{_sub_label}题干：{stem}"})
                step_log(f"  第{big_idx}大题·第{sub_label}小题（{stem}）完整性检查", "info", _ev)
                _ev_q = q
                _last_ev_big = big_idx
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

    # ★ 方式1 失败诊断：滑动 8 次未找到目标 U 入口，dump 当前页可见 U 标题
    #   （用户实测：二年级下册跑口语训练 U1 返回 0 不知原因 → 现在直接告知）
    _diag = _snapshot_page(d, want_kw=("U1", "U2", "U3", "Unit"), limit=12)
    _visible_u = [t for t in _diag["texts"] if re.search(r"[Uu]\s*\d|Unit", t)][:8]
    # ★ 占位页识别：模块页显示"正在开发 敬请期待~" → 该年级该模块在 App 未上线
    #   （2026-08-25 真机：湘少版(2024审定)二年级下册口语训练模块页 = WebView 占位页，
    #    无任何单元入口。旧逻辑报"找不到 U1 入口"，误导成代码 bug）
    try:
        _xml_now = d.dump_hierarchy()
        if "正在开发" in _xml_now or "敬请期待" in _xml_now:
            print(f"    ❌ 口语训练 U{unit_num}：模块页为占位页（'正在开发 敬请期待~'）→ 该年级口语训练未上线，跳过")
            try:
                step_log(f"❌ 口语训练 U{unit_num}：该年级口语训练未上线（App 显示'正在开发 敬请期待~'），无法作答", "error")
            except Exception:
                pass
            return 0
    except Exception:
        pass
    print(f"    ❌ 方式1 失败：滑动 8 次未找到 U{unit_num} 标题")
    print(f"    当前页可见 U 标题: {_visible_u}")
    try:
        step_log(f"❌ 口语训练 U{unit_num} 入口缺失：当前页无该单元标题行（可见 U: {','.join(_visible_u[:5]) or '无'}，可能该年级无此单元）", "error")
    except Exception:
        pass

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
        _diag2 = _snapshot_page(d, want_kw=("开始", "重新", "继续", "U1", "U2"), limit=12)
        _visible_btns = [t for t in _diag2["texts"] if t in ("开始答题", "重新答题", "继续答题")]
        print(f"    ❌ 找不到 U{unit_num} 的答题按钮（已找：{'/'.join(btn_candidates)}）")
        print(f"    当前页可见答题按钮: {_visible_btns}")
        try:
            step_log(f"❌ 口语训练 U{unit_num} 无答题按钮：当前页答题按钮={_visible_btns or '无'}", "error")
        except Exception:
            pass
        return 0
    btns[idx].click()
    print(f"    ✅ 点击 {chosen_btn} (U{unit_num})")
    time.sleep(1.2)
    _after_unit_enter(d)
    return _run_unit_questions(d, unit_num)


def _snapshot_page(d, want_kw=("U1", "U2", "口语", "训练", "开始", "重新", "继续"), limit=15):
    """诊断：找不到期望元素时快照当前页关键文本 + resource-id 前缀（仅 read-only）。
    返回 {texts: [...], rids: [...]} 方便日志/stdout 排查。"""
    out = {"texts": [], "rids": []}
    try:
        xml = d.dump_hierarchy()
    except Exception as e:
        out["texts"] = [f"<dump失败: {e}>"]
        return out
    texts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
    # 优先输出含 want_kw 的；其它再补足到 limit
    prio = [t for t in texts if any(k in t for k in want_kw)]
    others = [t for t in texts if t not in prio]
    out["texts"] = (prio + others)[:limit]
    rids = sorted({r for r in re.findall(r'resource-id="com\.dinoenglish\.yyb:id/([a-z_0-9]+)"', xml)})
    out["rids"] = rids[:8]
    return out


def _after_unit_enter(d):
    """进入单元后的公共处理：弹窗 + 试卷首页 rule-based 检查 + 开始答题

    ★ 2026-08-25 修复：去掉 LLM 调用 check_paper_header（每次进入单元等10-30秒太慢）
      按 txt 流程第 2 点"试卷首页检查"用规则匹配即可（标题+总分+时量+按钮），
      不需要 LLM 语义判断，毫秒级完成。
    """
    if d(text="好的，我知道啦~").exists(timeout=3):
        d(text="好的，我知道啦~").click()
        print(f"    ✅ 好的，我知道啦~")
        time.sleep(0.5)
    # ★ Rule-based 试卷首页检查（替代 LLM 调用的 check_paper_header）
    #   解析 XML 文本节点提取：标题/总分/时长/按钮，毫秒级
    try:
        _xml = d.dump_hierarchy()
        _texts = [t for t in re.findall(r'text="([^"]+)"', _xml) if t.strip()]
        _title = next((t for t in _texts if "口语训练" in t and ("U" in t or "Unit" in t or "湘少" in t or "新湘" in t)), None)
        _total = next((re.search(r"总分\s*(\d+\s*分)", t).group(0) for t in _texts if re.search(r"总分\s*\d+\s*分", t)), None)
        _time = next((re.search(r"(?:时间|时长).{0,5}?(\d+\s*分钟)", t).group(0) for t in _texts if re.search(r"(?:时间|时长).{0,5}?\d+\s*分钟", t)), None)
        _btn = next((t for t in _texts if t in ("开始答题", "重新答题", "继续答题")), None)
        _ok = bool(_title) and bool(_btn)
        _msg = f"标题={_title or '无'} · 总分={_total or '无'} · 时长={_time or '无'} · 按钮={_btn or '无'}"
        print(f"    📋 试卷首页: {'✅' if _ok else '⚠'} {_msg}")
        try:
            step_log(f"📋 试卷首页检查: {'通过' if _ok else '异常'} | {_msg}", "info" if _ok else "warning")
        except Exception:
            pass
    except Exception as e:
        print(f"    📋 试卷首页检查异常: {e}")
    if d(text="开始答题").exists(timeout=3):
        d(text="开始答题").click()
        print(f"    ✅ 开始答题")
        time.sleep(1.2)
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
        # ★ 日志大题号以页面 tv_question_sort（"N/M"）为准：
        #   防止"还没切到第2大题就记'开始第2大题'"（页面进度为准，不盲信循环计数）
        try:
            _cur_big, _tot_big = _get_big_progress(d.dump_hierarchy())
        except Exception:
            _cur_big, _tot_big = None, None
        _log_big = _cur_big if _cur_big else big
        if d(text="交卷").exists(timeout=0.15):
            print(f"  📝 第{_log_big}大题（最后一题）")
        else:
            print(f"  📝 第{_log_big}大题")
            step_log(f"📝 开始第{_log_big}大题", "step")
        q = _answer_big_question(d, big_idx=_log_big)
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

    # ② 主页找口语训练入口（★ 不同年级主页布局不同！）
    #   ★ 2026-08-25 修复：二年级下册主页"专项突破"区在首屏下方（首屏只有 教材精学/语音评测 等），
    #   五年级上册"口语训练"卡片首屏可见。旧逻辑 d(text="口语训练").exists 只看首屏 →
    #   二年级下册必然找不到 → 静默 return 0（"完成0题4s"）。
    #   → 改用 scroll_and_find：先首屏 → 上滑翻找（内容下移）→ 下滑回顶部，最多各4次。
    # ★ 诊断信息用设备实际年级（不写死 GRADE_LEVEL——多模块调度器已把设备切到目标年级，
    #   写死"五年级上册"会误导排查）
    _dev_v, _dev_g = None, None
    try:
        from common.setup import _current_texts
        _dev_v, _dev_g = _current_texts(d)
    except Exception:
        pass
    _grade_label = _dev_g or GRADE_LEVEL
    if scroll_and_find(d, "口语训练", max_swipes=4):
        d(text="口语训练").click(); time.sleep(1.6)
        print("  ✅ 主页点口语训练入口")
    else:
        _diag = _snapshot_page(d, want_kw=("口语", "U1", "U2", "训练", "单元"), limit=15)
        print(f"  ❌ 主页找不到'口语训练'入口（设备当前: {_dev_v or '?'} {_grade_label}）")
        print(f"  下滑翻找后当前页关键文本: {_diag['texts']}")
        print(f"  当前页 resource-id 前缀: {_diag['rids']}")
        try:
            step_log(f"❌ 口语训练 入口缺失（设备年级={_grade_label}）：下滑翻找后当前页仍无'口语训练'卡片（可能该年级无此模块，或主页布局变化）", "error")
        except Exception:
            pass
        return 0

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

    # ★ 模块完成信号（web_server log_msg 靠"完成"关键词触发脚本内容审查）
    #   练习报告页可能因渲染延迟没检测到 → 这里兜底必发
    step_log(f"✅ 口语训练完成，共{total}题", "success")
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
