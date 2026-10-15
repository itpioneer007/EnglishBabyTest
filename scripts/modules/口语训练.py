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
import html
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.logger import (
    step_log, should_stop,
    set_current_unit, get_current_unit, get_module_script,
)
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade,
    scroll_and_find,
)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

# ★ 2026-09-15 解析脚本收集器（run_module 初始化，单元答完尝试写 docx）
#   ⚠ 规则已收紧（用户明确）：**只有"有明确答案"的题目才做解析**。
#     口语训练全是跟读 / 看图说句题，App 里没有标准答案 → 收集器的准入规则会
#     全部拦下，本模块通常**不产出**解析脚本（finish_unit 会在日志说明原因）。
#     保留调用是为了把"收不收"的判定集中在 gen_script（单一规则来源），
#     而不是在这里写死模块白名单——将来规则若放宽也无需改本文件。
_oral_coll = None
_oral_unit = 0


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


def _diag_no_record_ctrl(d, big_idx):
    """超时未等到录音按钮时，区分「页面还没就绪」和「本大题压根没有可作答控件」。

    ★ 2026-10-08（湘少四下 U1 大题3）：该大题为纯图片题，整页唯一可点击节点是
      tv_exit（退出训练）——无 record_btn、无喇叭、无「下一题/交卷」。
      工具只能超时退出 → 单元提前结束（U1 只采到 大题1 + 大题2 共 10 题）。
      不写这条日志的话，报告里只表现为"题变少了"，原因不可见。
    """
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return
    if _is_transition_state(xml):
        try:
            step_log(f"⚠ 第{big_idx}大题等待录音按钮超时（页面仍在倒计时/上传状态）", "warning")
        except Exception:
            pass
        return
    if _find_record_btn(d, xml):
        return
    # 只要还有"下一题/交卷/答题卡"这类过渡控件，就说明只是没等到，不是页面坏
    if any(b in xml for b in ("下一题", "下一大题", "交卷", "答题卡")):
        return
    labels = []
    for tag in re.findall(r'<node[^>]*clickable="true"[^>]*>', xml):
        m = re.search(r'text="([^"]*)"', tag)
        rid = re.search(r'resource-id="([^"]*)"', tag)
        t = (m.group(1) if m else "").strip()
        if not t and rid:
            t = rid.group(1).split("/")[-1]
        if t and t not in labels:
            labels.append(t)
    try:
        step_log(f"⚠ 第{big_idx}大题无可作答控件：整页无录音按钮/喇叭/「下一题」，"
                 f"可点击元素仅 {labels[:6] or ['无']} → 本单元在此中断，"
                 f"该大题及其后大题未检测（App 侧页面问题）", "warning")
    except Exception:
        pass


# ★ 2026-09-15 最近一次小题题干的来源：
#   "vision" = 由视觉模型识别配图得到（概率性结论，脚本需标注人工复核）
#   "text"   = 页面文字直接给出（句型题 / 朗读题，确定）
#   "audio"  = 容器内无图无字（纯听音跟读，无文字内容）
#   供脚本收集时决定是否打"内容由视觉识别·需人工复核"标记。
_LAST_STEM_SRC = ""


def _find_active_sub_question(d, xml=None, big=None):
    """定位当前正在作答的小题（含 record_btn 的 ll_container）。

    big: 当前大题号（图片题取脚本题面时用于定位脚本小题；None 则跳过脚本优先）。

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

    # ★ 2026-09-14 "结合句型"图片题：先定位本小题配图（pic_iv 与 speech_box 同级）
    #   真机 big3.xml：
    #     ll_container [0,885][1080,1598]
    #       speech_box / speech_content '1.例句：I travelled to ...&#10;(2分)'
    #       pic_iv [203,1152][877,1512]
    #   有配图时 "例句：xxx" 是**句型模板**而非普通题干 —— 旧逻辑被 '分' in t 丢弃，
    #   结果图片只被"看图描述"，句型信息完全没用上（用户实测反馈）。
    _pic_box = None
    for pm in re.finditer(
            r'<node[^>]*resource-id="[^"]*pic_iv"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        px1, py1, px2, py2 = map(int, pm.groups())
        if px1 >= ax1 and py1 >= ay1 and px2 <= ax2 and py2 <= ay2:
            _pic_box = (px1, py1, px2, py2)
            break
    _pattern = ""          # 句型模板（仅"结合句型 + 配图"场景非空）
    _seq = []              # ★ 2026-09-21 容器内文本节点（文档顺序）→ 拼回被拆散的「例句：」

    for m in re.finditer(r'<node[^>]*text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        t = m.group(1).strip()
        x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        if x1 < ax1 or y1 < ay1 or x2 > ax2 or y2 > ay2:
            continue
        _seq.append((x1, y1, t))
        # tv_sort: "1/5" / "2/5"（n/本大题小题总数） 或 "1." / "2."
        mm = re.match(r"^(\d+)\s*/\s*(\d+)$", t)
        if mm:
            sub_no, total_sub = int(mm.group(1)), int(mm.group(2))
            continue
        mm = re.match(r"^(\d+)[\.、]\s*$", t)
        if mm:
            sub_no = int(mm.group(1))
            continue
        # ★ 2026-09-14 句型模板："1.例句：I travelled to ...&#10;(2分)"
        #   ① 本小题有配图 → 只记下句型，题干交给视觉模型按句型补全
        #   ② 无配图（图片加载失败 / 纯句型提示题）→ 句型本身即题干，
        #      必须保留；否则会因含"(2分)"被下方 '分' in t 丢弃 → 退化成"听录音作答"
        _pt = _extract_sentence_pattern(t)
        if _pt:
            _pattern = _pt
            _no = re.match(r"^\s*(\d+)\s*[\.、]", t)
            if _no and sub_no is None:
                sub_no = int(_no.group(1))
            if _pic_box is None:
                stems.append(_pt)
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
    # ★ 2026-09-21：例句被 App 拆成多个 TextView 时，单节点提取拿不到正文 →
    #   按文档顺序把「例句：」标签后的英文节点拼回完整例句；并把用掉的碎词
    #   从 stems 剔除（否则 stem 会变成 "例句： / I / will" 这类噪音）。
    if not _pattern:
        _jp, _jused = _join_split_pattern(_seq)
        if _jp:
            _pattern = _jp
            if _jused:
                stems = [s for s in stems if s not in _jused]
    global _LAST_STEM_SRC
    if _pic_box and (_pattern or not stems):
        # ★ 2026-09-23 图片题「脚本优先」（用户要求：脚本有内容就用脚本，不让 LLM 猜）
        #   为什么必须改：视觉模型对"结合句型"图片题的补全结果**往往就是参考答案**
        #   —— 实测教科五上 U5 第3大题第3小题：句型提示 "Hello, this is ..."，
        #   视觉把它补成 "Hello, this is Lucas."，而 Lucas 正是脚本里的参考答案。
        #   把参考答案当成 App 题面展示，既违反用户明确的"App 里不能出现参考答案"，
        #   又会被后端拿去跟脚本 stem（句型模板）比对 → 判"内容不符"的假错。
        _ref = _script_ref_stem(big, sub_no)
        if _ref:
            if _pattern:
                # App 页面上确实渲染了句型提示（DOM 文字，确定）→ 属于真实界面文字，
                # 后续照常与脚本逐字比对（这才是真检查）。
                stem = f"句型提示：{_pattern}"
                _LAST_STEM_SRC = "text"
            else:
                # App 该小题是纯图、无任何文字题面 → 以脚本内容为准展示，
                # 标 src=script：后端只登记"应显示内容"，不做一致性判定。
                stem = f"句型提示：{_ref}"
                _LAST_STEM_SRC = "script"
        else:
            # 脚本未挂载 / 找不到该小题 → 保留原视觉识别兜底
            #   ① 无句型（普通看图说句）→ 用简短英文句子描述图片大意
            #   ② 有句型（"结合句型"变种，2026-09-14 新增）→ 严格沿用给定句型，
            #      把省略号处按图片内容补全成完整句子
            stem = _oral_vision_stem(d, _pic_box, sub_no, pattern=_pattern)
            _LAST_STEM_SRC = "vision" if stem else ""
            # ★ 2026-09-21：例句是学生实际看到的作答指引，必须出现在 App 侧文本里，
            #   供后端与脚本 sentence_pattern 逐字比对。不带例句 → 报告只会写
            #   "App 只有「例句：」标签"，其实 App 显示了、只是被拆成多个节点。
            if _pattern:
                if not stem:
                    stem = f"例句：{_pattern}"
                elif _pattern not in stem:
                    stem = f"例句：{_pattern} / {stem}"
    elif stems or _pattern:
        _parts = list(stems[:2])
        if _pattern and not any(_pattern in p for p in _parts):
            _parts.insert(0, f"例句：{_pattern}")
        stem = " / ".join(_parts[:2])
        _LAST_STEM_SRC = "text"
    else:
        # 容器内既无配图也无文字 → 听录音作答（点小喇叭听题目内容 → 点录音口语作答），
        #   不误标"图片题"。
        # ★ 2026-09-23 用户实测：口语训练五上 U6 第4大题就是这一类——整页只有
        #   一张**表格素材**，每个小题里并没有图片，只有小喇叭 + 录音按钮。
        #   旧标签"听音频跟读"把题型说成了"跟读"，也不准确（学生是听问题后作答，
        #   不是复述）。改为"听录音作答"，与 App 的真实作答方式一致。
        stem = "听录音作答"
        _LAST_STEM_SRC = "audio"
    return sub_no, total_sub, stem, active


# ★ 2026-08-30 口语训练图片题：视觉识别题干缓存（同一小题不重复识别）
_ORAL_VISION_CACHE = {}

# ★ 2026-09-14 "结合句型"图片题：例句/句型标签与英文内容判据
_SENT_PATTERN_KW = re.compile(r"(例句|句型提示|参考句型|句型|sentence\s*pattern)", re.I)
_SENT_PATTERN_EN = re.compile(r"[A-Za-z]")


def _extract_sentence_pattern(t):
    """从容器文本中提取"例句/句型"模板（口语训练 · 结合句型图片题）。

    真机样例（screenshots/oral_probe/big3.xml，ll_container 内 speech_content）：
        '1.例句：I travelled to ...&#10;(2分)'  →  'I travelled to ...'
        '2.例句：I did ...&#10;(2分)'            →  'I did ...'

    返回 "" 表示该文本不是句型模板（保持原有题干逻辑）。
    ★ 仅当小题容器内确有配图（pic_iv）时调用 —— 否则纯文字题的
      "句型提示：Which one do you want, ...?" 会被误吞。
    """
    if not t:
        return ""
    # 正则直接取自 xml 字符串（未反转义）→ 需解开 &#10; / &quot; 等实体
    raw = html.unescape(t).replace("\u200e", "").replace("\u200f", "")
    if not _SENT_PATTERN_KW.search(raw):
        return ""
    s = raw
    s = re.sub(r"^\s*\d+\s*[\.、]\s*", "", s)          # 去小题序号 "1."
    s = _SENT_PATTERN_KW.sub("", s)                     # 去 "例句/句型提示" 标签
    s = re.sub(r"[\r\n]?\s*[（(]\s*\d+\s*分\s*[)）]", " ", s)   # 去 "(2分)"
    s = re.sub(r"[\r\n]?\s*\d+\s*分\s*$", " ", s)               # 去尾部裸 "2分"
    # 从第一个英文字母起截取（清掉"参考句型："/残余冒号等中文前缀）
    _m = _SENT_PATTERN_EN.search(s)
    if _m:
        s = s[_m.start():]
    s = re.sub(r"\s+", " ", s).strip(" \t:：-—")
    if not _SENT_PATTERN_EN.search(s):     # 无英文 → 不是句型（防误吞中文说明）
        return ""
    if len(s) > 120:
        return ""
    return s


_PT_TAG_ONLY = re.compile(r"^[\s\d\.、]*(?:例句|句型提示|参考句型|句型)[:：]?\s*$")
_PT_EN_WORD = re.compile(r"^[A-Za-z0-9'’\-\.\,\!\?…]+$")


def _join_split_pattern(seq):
    """把 App **拆成多个 TextView** 的「例句：…」拼回完整例句。

    ★ 2026-09-21 新增。真机（教科五上 U4 第3大题）实测节点序列为：
        '例句：' │ 'I' │ 'will' │ 'bring' │ 'everything' │ 'inside' │ '.'
    —— 每个词是**独立节点**，而 `_extract_sentence_pattern()` 只吃单个节点的
    text：拿到 '例句：' 时标签后的正文为空 → 返回 "" → **整句例句丢失**，
    stem 退化成 "例句： / I / will"。后果：
      ① App 侧没有例句正文，脚本侧 `sentence_pattern` 比对必然失败，
         报告写"App 只有「例句：」标签"（其实 App 显示了，只是被拆开）；
      ② 视觉补全拿不到句型模板，只能按图片自由描述。

    seq: [(x, y, text), ...]，按 XML **文档顺序**（= 阅读顺序）。
    返回 (例句正文, 已消费的节点文本集合)；拼不出返回 ("", set())。
    """
    if not seq:
        return "", set()
    for i, (_x, _y, t) in enumerate(seq):
        if not _PT_TAG_ONLY.match(t or ""):
            continue
        buf, used = [], set()
        for _x2, _y2, t2 in seq[i + 1:]:
            t2 = (t2 or "").strip()
            if not t2:
                continue
            if _PT_EN_WORD.match(t2):
                buf.append(t2)
                used.add(t2)
                if len(buf) >= 16:          # 正常例句 ≤ 10 词，16 足够且防越界
                    break
                continue
            break                            # 中文/分值/下一个标签 → 例句结束
        if not buf:
            return "", set()
        s = " ".join(buf)
        s = re.sub(r"\s+([\.\,\!\?…])", r"\1", s)   # 标点前不留空格
        return s.strip(), used
    return "", set()


# ★ 2026-09-23 图片题「脚本优先」缓存：{docx 文件名: script_questions}
#   用户要求（原话）:"展示图片对应的题目内容时，如果脚本里面有对应题目的内容，
#   就把那个当做题目展示，就不用让 LLM 自己去猜是什么了"。
#   同时强调:"在 App 里面不能出现参考答案" —— 图片题学生在 App 上只看到
#   「句型提示」（脚本例：句型提示：Hello, this is ... ／ 参考答案：Hello, this is Lucas.），
#   所以这里**只允许**返回 stem（句型模板）或 sentence_pattern，
#   **绝不返回 answer（参考答案）/ keywords（关键词）**。
_ORAL_SCRIPT_CACHE = {}


def _script_ref_stem(big, sub_no):
    """取脚本该小题在 App 上**应显示的题面**（句型提示 / 题目内容）。

    返回 "" 表示脚本没挂载 / 找不到该小题 / 该小题无文字题面 → 调用方回退视觉识别。
    """
    if not big or not sub_no:
        return ""
    try:
        _fn = get_module_script("口语训练")
        if not _fn:
            return ""
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _p = os.path.join(_root, "uploads", _fn)
        if not os.path.exists(_p):
            return ""
        _u = int(get_current_unit() or 0)
        if _fn not in _ORAL_SCRIPT_CACHE:
            from src.review_agent import ReviewAgent, ReviewConfig
            _ag = ReviewAgent(ReviewConfig(docx_path=_p, unit=0,
                                           screenshot_dir="", verbose=False))
            _ORAL_SCRIPT_CACHE[_fn] = _ag.script_questions
        for _q in _ORAL_SCRIPT_CACHE[_fn]:
            try:
                if _u and int(getattr(_q, "unit", 0) or 0) != _u:
                    continue
                if int(getattr(_q, "big", 0) or 0) != int(big):
                    continue
                if int(getattr(_q, "stage_idx", 0) or 0) != int(sub_no):
                    continue
            except Exception:
                continue
            _s = (getattr(_q, "stem", "") or "").strip()
            if _s and not _s.startswith("[") and _s.lower() not in ("none", "-", "/"):
                return _s
            _sp = (getattr(_q, "sentence_pattern", "") or "").strip()
            if _sp:
                return _sp
            return ""
    except Exception as _e:
        print(f"      ⚠ 脚本题面读取失败（回退视觉识别）: {_e}")
    return ""


def _oral_vision_stem(d, pic_box, sub_no, pattern=""):
    """图片题：截取当前小题 pic_iv 区域 → 视觉模型识别 → 题干。

    两种模式：
      ① 无句型（普通看图说句）：用符合年级水平的简短英文句子描述图片大意；
      ② 有句型（"结合句型"变种，2026-09-14 新增）：严格沿用给定句型，
         只把省略号处按图片内容补全成完整句子：
             'I travelled to ...' + 图片(北京/长城) → 'I travelled to Beijing.'

    识别失败/无法调用时回退"图片题"。结果按 (小题号, 句型, 图片指纹) 缓存，避免重复调用。
      缓存用**图片内容指纹**而非 pic_box：页面滚动会改变 pic_box（真机实测小题2
      滚动前后坐标不同）→ 旧键必然 miss → 同一道题被反复送给 LLM 重复计费。
    """
    pattern = (pattern or "").strip()
    _key = (sub_no, pic_box, pattern)          # 兜底键（无法截图时使用）
    _ckey = _key
    if _key in _ORAL_VISION_CACHE:
        return _ORAL_VISION_CACHE[_key]
    stem = ""
    try:
        if d is None:
            raise RuntimeError("无设备连接（离线解析），跳过视觉识别")
        img = d.screenshot()
        im = img.crop(pic_box)
        # ★ 图片内容指纹：同一张图无论出现在屏幕哪个位置，都命中同一条缓存
        try:
            import hashlib
            _fp = hashlib.md5(im.tobytes()).hexdigest()[:12]
            _ckey = (sub_no, pattern, _fp)
            if _ckey in _ORAL_VISION_CACHE:
                _ORAL_VISION_CACHE[_key] = _ORAL_VISION_CACHE[_ckey]
                return _ORAL_VISION_CACHE[_ckey]
        except Exception:
            _ckey = _key
        # ★ 图片被屏幕裁断告警：pic_iv 下边界顶到可滚动区底部（真机 scrollView 底 = 2079）
        #   时，crop 只能拿到图上半部分 → 视觉结论可能不准（不静默）
        try:
            _vis_bottom = min(d.window_size()[1], 2400)
            if pic_box[3] >= _vis_bottom - 12:
                print(f"      ⚠ 小题{sub_no}配图被屏幕裁断（pic_iv 下边界 {pic_box[3]} ≈ 可视底），"
                      f"识别可能不准")
        except Exception:
            pass
        _dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "screenshots", "script_imgs")
        os.makedirs(_dir, exist_ok=True)
        _p = os.path.join(_dir, f"oral_pic_{sub_no or 0}_{pic_box[1]}.png")
        im.save(_p)
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from src.reviewer_common import LLMClient
        llm = LLMClient.from_config()
        # 实际年级优先读环境变量（web_server 调度时设置 YYB_GRADE）
        _grade = os.environ.get("YYB_GRADE", "") or GRADE_LEVEL
        # ★ 2026-09-20 词汇难度约束（用户反馈：视觉生成的句子出现超纲词 cereal）：
        #   只允许小学本年级及以下教材词汇，且生成的句子必须语法正确。
        _vocab_rule = (
            f"词汇难度：只使用中国小学{_grade}及以下教材范围内的常见单词，"
            "禁止超纲词（如 cereal、champion、survey 这类明显超出小学范围的词）；"
            "句子必须语法正确、简短自然"
        )
        # ★ 2026-09-20 优先级规则（用户反馈：教科六上U6"大声说出你看到的单词"，
        #   图里本来就印着 home-stone / boat-coat 这样的词卡，视觉却去"描述图片大意"
        #   编了一句别的话）：
        #   ① 图上有英文文字 → 题干就是那些文字本身，必须**原样照抄**；
        #   ② 图上没有英文 → 才允许按图片内容生成/补全句子。
        if pattern:
            prompt = (
                f"这是中国小学{_grade}英语口语题的配图。"
                f"题目要求「结合句型和图片说句子」，给出的句型是：{pattern}\n"
                "请按以下优先级输出题干：\n"
                "① 若图片中印有英文单词/短语/句子（词卡、标签），必须原样照抄图中英文"
                "（多个词用空格分隔），不要翻译、不要改写、不要补充图中没有的内容；\n"
                "② 若图中没有英文文字，才把句型中省略的部分（... / …）按图片内容补全，"
                "组成一句完整英文句子：严格沿用给定句型结构，只补齐省略部分；"
                f"补入的单词同样受约束（{_vocab_rule}）。\n"
                "单词之间用空格分隔；句首字母大写；句末加英文句号。"
                "只输出最终题干本身，不要引号、不要中文、不要任何解释。"
            )
        else:
            prompt = (
                f"这是中国小学{_grade}英语口语题的配图。请按以下优先级输出题干：\n"
                "① 若图片中印有英文单词/短语/句子（词卡、标签），题干就是这些文字本身——"
                "必须原样照抄图中全部英文（多个词用空格分隔），不要翻译、不要改写、"
                "不要补充图中没有的内容（这类题考察的就是「说出你看到的单词/短语」）；\n"
                "② 若图中没有任何英文文字，才根据图片大意生成一句英文："
                f"不超过8个单词；{_vocab_rule}。\n"
                "只输出最终题干本身，不要引号、不要中文、不要任何解释。"
            )
        ans = (llm.ask(prompt, image_path=_p, temperature=0) or "").strip()
        if ans and "LLM 调用失败" not in ans and len(ans) <= 80:
            # 清理常见的格式残留：引号 / 多行 / "答案：" 前缀 / 中文尾注
            ans = ans.split("\n")[0].strip()
            ans = re.sub(r"^\s*(答案|句子|Answer)\s*[:：]\s*", "", ans, flags=re.I)
            ans = ans.strip(" \t\"'“”‘’")
            if ans:
                stem = ans
    except Exception as e:
        print(f"      ⚠ 图片题视觉识别失败: {e}")
    stem = stem or "图片题"
    _ORAL_VISION_CACHE[_key] = stem
    if _ckey != _key:
        _ORAL_VISION_CACHE[_ckey] = stem
    return stem


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


# ★ 2026-09-21：App 云端语音评分不可用时置位，用于终止本单元（避免死循环空转）
_SCORING_DOWN = False
# 点"结束"之后等待评测收敛的上限（秒）。实测正常 5~6s，给足余量。
_EVAL_SETTLE_TIMEOUT = 15.0


def _wait_eval_settle(d, timeout=_EVAL_SETTLE_TIMEOUT):
    """等一次"结束录音"之后的**评测收敛**：按钮回到可录音态，或页面翻页。

    ⚠ 期间**绝不点击**。这是死循环的根因修复：
      实测（2026-09-21 MuMu 900x1600）点"结束"后 record_btn 仍保持"点击结束"
      **约 5~6 秒**（上传 16k 单声道 WAV + 等驰声服务端返回评分），之后
      - 成功：翻页（record_btn 消失 / 切到下一小题 / 出现练习报告），或
      - 失败：回到"点击录音"（允许重录，但页面不翻页）。
      旧实现这里只等 3.0s，而一次 dump_hierarchy 就要 ~1.5s，
      于是**评测还没结束就返回**，外层循环立刻重新 dump 到同一个 record_btn
      → 再点录音 → **打断上一次评测** → 评分永远拿不到 → 整单元空转
      （实测 U4：20:44:25~20:48:14 连点 30 次，然后重开第1大题）。
    返回 True 表示已回到稳定态。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            time.sleep(0.3)
            continue
        if _is_transition_state(xml):        # "请阅读题目 Ns"/上传中
            time.sleep(0.3)
            continue
        if not _find_record_btn(d, xml):     # 翻页 / 报告页 → 收敛
            return True
        if "点击结束" in xml or "点击完成" in xml:
            time.sleep(0.3)                  # 仍在录音/评测中 → 继续等，不点
            continue
        return True                          # 已回到"点击录音"（评测结束）
    return False


def _speak_one_sub(d):
    """作答当前可见的录音小题：点录音 → 等状态变 → 点结束 → **等评测收敛**。
    返回是否成功（True = 完成了一次"录音+结束"动作）。
    """
    pos = _find_record_btn(d)
    if not pos:
        return False
    # 0) 兜底：若正处于"请阅读题目 Ns"准备倒计时，点击会被 App 吞掉（按钮可见但禁用），
    #    先等它结束再点（_answer_big_question 入口已等过一次，这里防"切小题后重入倒计时"）
    try:
        if _is_transition_state(d.dump_hierarchy()):
            if not _wait_ready_for_record(d, timeout=15):
                return False
            pos = _find_record_btn(d) or pos
    except Exception:
        pass
    d.click(*pos)
    print(f"    🎤 点录音 ({pos[0]},{pos[1]})")
    step_log("🎤 点录音", "info")
    # 等 App 切换到"点击结束"/"点击完成"状态
    t0 = time.time()
    while time.time() - t0 < 4.0:
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
    # ★ 关键：等评测收敛后再交还控制权（旧实现只等 3s → 打断评测 → 死循环）
    _wait_eval_settle(d)
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
    _seen_subs = set()      # ★ 2026-09-20：本大题已计过分的 sub_no（去重，防题数虚高）
    _dup_streak = 0         # ★ 2026-09-21：连续"同一小题重复录音"次数（识别 App 评分未返回）
    global _SCORING_DOWN

    # 1. 等大题首题 ready
    if not _wait_ready_for_record(d, timeout=22):
        print(f"    ❌ 第{big_idx}大题：等待首题录音按钮超时")
        _diag_no_record_ctrl(d, big_idx)   # ★ 区分"还没就绪"与"压根没有可作答控件"
        return 0

    # 2. 逐小题作答
    for _ in range(30):  # 防护上限
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q
        if _SCORING_DOWN:
            # 本单元判定为"App 云端评分不可用" → 不再继续下一大题
            return 0

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
        # ★ 2026-09-23：把大题号传下去，图片题才能按 (单元, 大题, 小题) 取脚本题面
        sub_no, total_sub, stem, _ = _find_active_sub_question(d, xml, big=big_idx)
        sub_label = sub_no if sub_no is not None else q + 1
        # ★ 2026-09-20 修复（题数虚高）：App 偶发"录音成功但页面不翻页"——
        #   `_speak_one_sub` 返回 True 已让 q+1，下一轮 dump 到的仍是同一个 sub_no，
        #   于是同一小题被再记一次（实测第2大题第4小题出现 2 行日志、
        #   5 小题的大题被统计成 6 题）。按 sub_no 去重：重复的那轮照旧重录，
        #   但不再计数、不再刷证据卡日志。
        _dup_sub = (sub_no is not None and sub_no in _seen_subs)
        if sub_no is not None:
            _seen_subs.add(sub_no)

        # 每小题只发一次证据卡（避免重复；重复小题 _dup_sub 也不重复发卡）
        if q != _ev_q and not _dup_sub:
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
                    # ★ 2026-09-20：带上来路 src（dom=界面文字 / vision=视觉识别）。
                    #   web_server 侧只有 dom 文字才允许与脚本 stem 做一致性判定——
                    #   视觉识别的画面描述是**概率性**结论，拿去判"内容不符"会整片误报。
                    _ev.insert(1, {"field": "小题题干", "type": "info",
                                   "expected": "当前作答小题的题干",
                                   "actual": stem,
                                   "src": _LAST_STEM_SRC,
                                   "diff": f"{_sub_label}题干：{stem}"})
                # ★ 2026-08-25 修复"日志刷屏"：同大题第2-N小题 skip_stem=True 时，
                #   evidence 只剩固定的 题型/选项/音频/作答，每题一模一样 → 前端日志
                #   反复追加相同证据卡。压缩策略：
                #   - 保留有差异的（小题题干已插入，若有异常项保留）
                #   - 过滤"通用通过"项（选项=口语题无需选项、音频=无需小喇叭、
                #     作答元素存在），它们每道口语小题都相同，无信息量
                if not _is_first_of_big:
                    _ok_diff_kw = ("无需选项", "无需检查小喇叭", "作答元素存在")
                    _ev = [e for e in _ev if e.get("field") == "小题题干"
                           or e.get("type") in ("text_mismatch", "error", "warning")
                           or not any(k in (e.get("diff") or "") for k in _ok_diff_kw)]
                    # ★★ 2026-09-20 根因修复（口语训练 20 题只剩 4 题）：
                    #   这里原本还有一句 `if len(_ev)==1 and 是小题题干: _ev = []`
                    #   ——"后续小题只剩小题题干 → 不附证据卡，只发一行日志"。
                    #   但 step_log 的 evidence 是**唯一**能把这道题登记进审查结果的
                    #   通道（web_server.log_msg 靠 "第N大题·第M小题（…）检查" + evidence
                    #   建 questions["auto-Q…"]）。证据一清空，第 2~5 小题就永远进不了
                    #   审查结果：实测只剩 Q01-01/Q02-01/Q03-01/Q04-01，即每个大题的
                    #   第 1 小题（_is_first_of_big=True 那批），且审查条数(4) 与
                    #   App 实际作答数(20) 对不上。
                    #   而"小题题干"正是**必须与脚本 stem 逐题比对**的对象
                    #   （用户要的"题目内容一致性"）。题干逐题不同，
                    #   保留它不会造成"每题一模一样的证据卡"刷屏。→ 删掉清空逻辑。
                    # ★ 2026-09-20：显式告知后端"本小题的大题说明是按设计不再重复上报"。
                    #   否则后端只看到 evidence 里没有"题干"→ 判定"App 未渲染大题说明"
                    #   → 每张大题第2~5小题的卡片都刷一条
                    #   "⚠ App 未取到大题说明文字…需连手机人工确认"的**假告警**，
                    #   并把"题干"维度一直压成"未检"（即使小题内容已比对通过）：
                    #   20 题里 16 题显示不出结论，检查人员还要为不存在的问题去翻手机。
                    #   ★ 2026-09-20（用户反馈"实际:1 没有任何意思"）：
                    #     actual 从占位 "1" 改为可读表达，expected 也补上语义，
                    #     让检查人员一眼看懂这是设计行为、不是缺陷。
                    _ev = list(_ev) + [{
                        "field": "大题说明已省略", "type": "info",
                        "expected": "按设计本小题不重复上报大题说明",
                        "actual": "已省略（同大题第2小题起不再重复上报）",
                        "diff": "设计如此，非缺陷：避免同一大题的证据卡重复相同的大题说明"}]
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
            if _dup_sub:
                # ★ 2026-09-20：页面没翻页导致的重复作答 → 不计数（防题数虚高）
                _dup_streak += 1
                print(f"    ↺ 第{big_idx}大题·第{sub_label}小题重复（页面未翻页），不重复计数")
                # ★ 2026-09-21 根因诊断：连续 3 次"录了音但页面不翻页"= App 云端语音评分
                #   没有返回（客户端日志 BaseSingEngine errorCode:16385 "connect to server
                #   failed" / HttpDns2 httpDNSDataFail）。此时再点多少次都没用，
                #   旧实现会一直点到 range(30) 上限（实测空转 ~2.5 分钟）→ 现在明确报错并终止本单元。
                if _dup_streak >= 3:
                    msg = (f"❌ 第{big_idx}大题·第{sub_label}小题连续 {_dup_streak} 次录音后页面均未翻页："
                           f"App 云端语音评分未返回（App 侧 BaseSingEngine 报 16385/connect to server failed）"
                           f"→ 口语训练无法继续，已终止本单元；其余题目**未作答**，不计入通过/不通过结论")
                    print("    " + msg)
                    step_log(msg, "error")
                    _SCORING_DOWN = True
                    return 0
                time.sleep(0.3)
                continue
            _dup_streak = 0
            q += 1
            # ★ 2026-09-15 口语题尝试进脚本（options/answer 均为空）。
            #   ⚠ 按收紧后的准入规则（只收"有明确答案"的题），这里会被收集器
            #     拦下并计入 skipped_no_answer —— 属**预期行为**：
            #     视觉识别出的画面描述只用于让学生跟读，不作为解析脚本内容。
            try:
                if _oral_coll is not None and stem:
                    # 看图题题干由视觉模型识别（概率性结论），qtype 带"看图"，
                    # 便于日志与后续规则区分来源
                    _qt = "口语题·看图" if _LAST_STEM_SRC == "vision" else "口语题"
                    _oral_coll.add(qno=q, stem=stem, options=[], answer="",
                                   qtype=_qt, unit=_oral_unit, big=big_idx,
                                   allow_listen=True)
            except Exception:
                pass
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
    # ★ 2026-08-25：先切到"单元"tab（三年级上册默认在"全部"tab，只有期末/模拟卷，
    #   没有 U 单元列表；五年级上册无 tab 栏 → _switch_tab 幂等直接返回）
    _switch_tab(d, "单元")
    # 找该单元的答题按钮：3 种状态
    #   - 未训练过："开始答题"
    #   - 已训练过（完成）："重新答题"
    #   - 答题中退出（未完成）："继续答题"
    # 优先"重新答题"（从头开始，每道题都有麦克风），其次"继续答题"，最后"开始答题"
    btn_candidates = ["重新答题", "继续答题", "开始答题"]

    # 方式1：按 "口语训练湘少五上U{unit_num}" 标题文字匹配，定位该行按钮
    import re as _re
    # ★ 2026-09-20 修复（选错单元）：原第三分支是**裸数字** `|{unit_num}`，
    #   再配合下一行 `if "口语训练" in t or "U" in t or "Unit" in t` 这种很宽的准入条件，
    #   任何「含 U/Unit/口语训练」且「含该数字」的文本都会命中
    #   （带进度 "3/4" 的行、含年份 "2024" 的行等），于是可能点到别的单元。
    #   实测：请求 U4，App 实际打开的是「口语训练教科五上U3」。
    #   改为只按 U{num} / Unit {num} / 第{num}单元 精确匹配，并用 (?!\d) 挡住 U4→U40 这类前缀误配。
    title_pat = _re.compile(
        rf"[Uu]nits?\s*0*{unit_num}(?!\d)|U0*{unit_num}(?!\d)|第\s*{unit_num}\s*单元")
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
            # ★ 2026-09-20 修复（选错单元的**真正根因**）：
            #   旧实现 `abs(e.bounds[1] - row_y) < 300` 且取 DOM 顺序**第一个**命中的按钮。
            #   实测「单元」tab 真实布局（tools/probe_oral_unit_tab.py dump，MuMu 900x1600）：
            #     卡片节距 ≈330px，卡片内「标题 → 答题按钮」偏移 ≈135px
            #       U1 标题 y= 345 → 开始答题 y= 420
            #       U2 标题 y= 609 → 开始答题 y= 687
            #       U3 标题 y= 874 → 重新答题 y=1011
            #       U4 标题 y=1200 → 重新答题 y=1335   ← 请求 U4 时命中的 row
            #   对 row_y=1200 来说，U3 的按钮 Δy=189 同样 < 300，且 DOM 顺序在 U4 的按钮之前
            #   → 每轮都点到**上一张卡片**的按钮 → 请求 U4、实际打开 U3 试卷。
            #   改为两条约束：① 按钮必须在标题**下方**（同一张卡片，Δy≥0）；
            #                ② 取 Δy 最小者；上限收到 300（< 卡片节距，不会跨卡）。
            _best_btn, _best_dy = None, None
            for e in elements:
                t = (e.text or "").strip()
                if t not in btn_candidates:
                    continue
                _dy = e.bounds[1] - row_y
                if _dy < 0 or _dy > 300:
                    continue
                if _best_dy is None or _dy < _best_dy:
                    _best_btn, _best_dy = e, _dy
            if _best_btn is not None:
                t = (_best_btn.text or "").strip()
                try:
                    _best_btn.click()
                except Exception:
                    d.click((_best_btn.bounds[0] + _best_btn.bounds[2]) // 2,
                            (_best_btn.bounds[1] + _best_btn.bounds[3]) // 2)
                print(f"    ✅ 点击 {t} (U{unit_num}) Δy={_best_dy}")
                time.sleep(1.2)
                # ★ 2026-09-20：进单元后必须回验"实际打开的单元号"，
                #   不一致 → 直接中止（否则拿错单元脚本比对 → 全量误报）
                if not _after_unit_enter(d, unit_num):
                    return 0
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

    # 方式2（兜底）：把「单元标题 → 其正下方答题按钮」配对后取目标单元
    #   ★ 2026-09-20 修复：旧逻辑是"按 y 排序按钮，取第 unit_num-1 个"，隐含
    #   「每个单元都出现同名按钮、且顺序与单元号一致」的假设。
    #   实测「单元」tab：U1/U2/U5 是「开始答题」、U3/U4 是「重新答题」
    #   → 按钮列表长度与单元号完全不对齐，请求 U4 时 idx=3 直接越界 →
    #   方式2 也找不到按钮（这解释了兜底路径从来没救回来过）。
    #   改为按几何配对：卡片标题 y 与其按钮 y 相差 0~300px（下方）。
    _card_pat = _re.compile(r"[Uu]nits?\s*0*(\d+)(?!\d)|[Uu]0*(\d+)(?!\d)")
    chosen_btn = None
    _btn_el = None
    for attempt in range(5):
        _els = d.xpath('//*[@text!=""]').all() or []
        _cards = []
        for e in _els:
            t = (e.text or "").strip()
            if len(t) > 60:
                continue
            _m = _card_pat.search(t)
            if _m:
                _n = int(_m.group(1) or _m.group(2))
                _cards.append((_n, e.bounds[1]))
        _map = {}
        for _un, _uy in _cards:
            _b, _bd = None, None
            for e in _els:
                t = (e.text or "").strip()
                if t not in btn_candidates:
                    continue
                _d2 = e.bounds[1] - _uy
                if 0 <= _d2 <= 300 and (_bd is None or _d2 < _bd):
                    _b, _bd = e, _d2
            if _b is not None:
                _map.setdefault(_un, _b)
        if unit_num in _map:
            _btn_el = _map[unit_num]
            chosen_btn = (_btn_el.text or "").strip()
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
    try:
        _btn_el.click()
    except Exception:
        d.click((_btn_el.bounds[0] + _btn_el.bounds[2]) // 2,
                (_btn_el.bounds[1] + _btn_el.bounds[3]) // 2)
    print(f"    ✅ 点击 {chosen_btn} (U{unit_num})[方式2]")
    time.sleep(1.2)
    if not _after_unit_enter(d, unit_num):
        return 0
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


def _switch_tab(d, tab_name, timeout=3):
    """★ 2026-08-25：口语训练模块页顶部有 tab 栏（全部/单元/期末/模拟）。

    不同年级布局不同：
      - 三年级上册：默认在"全部"tab（显示期末+模拟统测卷，无 U 单元）→
        必须先点"单元"tab 才有 U1-U10 单元列表（用户实测根因）
      - 五年级上册：可能无 tab 栏（单元列表直接平铺）
    此函数幂等：目标 tab 已选中（或页面无 tab 栏）→ 直接返回 True。
    返回是否成功（或无需切换）。
    """
    try:
        xml = d.dump_hierarchy()
    except Exception:
        xml = ""
    # ① 页面没有 tab 栏（五年级上册平铺布局）→ 无需切换
    tabs = []
    for t in ("全部", "单元", "期末", "模拟"):
        if re.search(rf'text="{t}"', xml):
            tabs.append(t)
    if not tabs:
        return True
    # ② 目标 tab 已存在且当前选中（selected="true" 或首位）→ 无需点击
    m = re.search(rf'<node[^>]*text="{tab_name}"[^>]*>', xml)
    if m and ('selected="true"' in m.group(0) or 'checked="true"' in m.group(0)):
        return True
    # ③ 目标 tab 存在但未选中 → 点击
    el = d(text=tab_name)
    if el.exists(timeout=timeout):
        el.click()
        time.sleep(1.0)
        print(f"    📑 已切换到 tab: {tab_name}")
        return True
    print(f"    ⚠ 页面无 '{tab_name}' tab（当前 tabs: {tabs}）")
    return False


def _after_unit_enter(d, unit_num=None):
    """进入单元后的公共处理：弹窗 + 试卷首页 rule-based 检查 + 开始答题

    ★ 2026-09-20 新增参数 unit_num：请求的单元号。试卷首页标题里带着实际打开的
      单元号（"口语训练教科五上U3"），必须与请求单元核对——
      旧逻辑只判 `bool(_title) and bool(_btn)`（"标题存在就算通过"），
      实测请求 U4、标题却是 U3，日志照样打「试卷首页检查: 通过」，
      之后每一道题的「App 内容 ↔ 脚本」比对都拿错单元的脚本，结论全部失真。
    """
    # ★ 2026-08-25 修复：去掉 LLM 调用 check_paper_header（每次进入单元等10-30秒太慢）
    #   按 txt 流程第 2 点"试卷首页检查"用规则匹配即可（标题+总分+时量+按钮），
    #   不需要 LLM 语义判断，毫秒级完成。
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
        # ★ 2026-09-20 新增：单元一致性校验（见函数 docstring）
        _title_unit = None
        if _title:
            _m_u = re.search(r"[Uu]nits?\s*0*(\d+)(?!\d)|[Uu]0*(\d+)(?!\d)", _title)
            if _m_u:
                _title_unit = int(_m_u.group(1) or _m_u.group(2))
        _unit_bad = (unit_num is not None and _title_unit is not None
                     and int(_title_unit) != int(unit_num))
        if _unit_bad:
            _ok = False
            _msg += f" ⚠ 单元不一致：请求 U{unit_num}，实际打开 U{_title_unit}"
            print(f"    ⚠ 试卷首页单元不一致: 请求 U{unit_num} → 实际 U{_title_unit}")
        print(f"    📋 试卷首页: {'✅' if _ok else '⚠'} {_msg}")
        try:
            step_log(f"📋 试卷首页检查: {'通过' if _ok else '异常'} | {_msg}",
                     "info" if _ok else ("error" if _unit_bad else "warning"))
        except Exception:
            pass
        if _unit_bad:
            # 拿错单元的脚本去比对 = 全单元结论失真 → 直接中止本单元，交给上层报错
            try:
                step_log(f"❌ 口语训练 U{unit_num} 中止：App 打开的试卷是 U{_title_unit}，"
                         f"脚本与该单元不对应，继续检测会产出全量误报", "error")
            except Exception:
                pass
            return False
    except Exception as e:
        print(f"    📋 试卷首页检查异常: {e}")
    if d(text="开始答题").exists(timeout=3):
        d(text="开始答题").click()
        print(f"    ✅ 开始答题")
        time.sleep(1.2)
    return True


def _run_unit_questions(d, unit_num):
    """进入单元后的答题循环（多个大题）"""
    # ★ 2026-09-23：上报"当前正在作答的单元"，供 web_server 做脚本层比对时定位
    #   脚本里对应的单元段落。绝不能让后端去猜 state["unit"]（那是本轮**范围**，
    #   形如 "5-6"）——旧实现取首段 5，导致连跑时第 2 个单元全部拿第 1 个单元的
    #   脚本比对，整单元假错（用户实测 U5-6 连跑时 U6 的题全被判"内容不符"）。
    try:
        set_current_unit(unit_num)
        print(f"  📍 当前作答单元 = U{unit_num}（已上报，供脚本比对定位）")
    except Exception:
        pass
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


# ── 口语训练试卷页「退出训练」确认框（真机 dump 2026-10-08，MuMu 900x1600）──
#   点顶栏 tv_exit（"退出训练"）后弹出：
#     confirm_title   = "温馨提示"
#     confirm_context = "你完成了N道题，练习未做完，中途退出别错过练习时间哦~"
#     confirm_left_btn  = "确定退出"   ← 必须点这个；点完落到 口语训练单元列表
#     confirm_right_btn = "继续答题"   ← 点了回到试卷继续答，绝不能误点
_EXIT_CONFIRM_RID = "confirm_left_btn"
#   ⚠ text= 是**精确匹配**。白名单里只写 "确定" 匹配不到 "确定退出" ——
#     这正是 2026-10-08 复跑卡死 6 轮的直接原因。长词必须排在前面。
_EXIT_CONFIRM_TEXTS = ("确定退出", "确认退出", "退出确认", "确认退出练习",
                       "确定", "确认", "继续退出")


def _in_exit_confirm(xml):
    """当前页是否弹着「确定退出 / 继续答题」确认框。

    ★ 必须单独识别：该弹窗出现时 XML 里【既没有「退出训练」也没有 U+数字】，
      若沿用"不在试卷页就当已退出"的判据 → 会误判成功，或去按 back（= 取消弹窗）。
    """
    if not xml:
        return False
    return ("温馨提示" in xml and "继续答题" in xml
            and ("确定退出" in xml or "退出" in xml))


def _click_exit_confirm(d, xml=""):
    """点确认框左侧的「确定退出」，返回是否点到。

    ⚠ 右侧是「继续答题」，点错就前功尽弃 —— 优先用 resource-id 精确定位，
      退而用精确文本；白名单里【不含】"继续答题"。
    """
    if xml and not _in_exit_confirm(xml):
        return False
    try:
        el = d(resourceId=f"{APP_PACKAGE}:id/{_EXIT_CONFIRM_RID}")
        if el.exists(timeout=0.8):
            el.click()
            print("    ✅ 点『确定退出』(confirm_left_btn)")
            return True
    except Exception:
        pass
    for _t in _EXIT_CONFIRM_TEXTS:
        try:
            if d(text=_t).exists(timeout=0.4):
                d(text=_t).click()
                print(f"    ✅ 点『{_t}』(文本兜底)")
                return True
        except Exception:
            pass
    return False


def _is_oral_list_page(xml):
    """是否已回到「口语训练」单元列表（= 下一个单元可以正常进入）。

    用**正向特征**判定，不看"有没有离开试卷页"（那正是第一版踩的坑）：
      ① 排除试卷页/确认框（退出训练 / 答题卡 / 确定退出）
      ② 有单元答题按钮 → 是列表
      ③ 否则看单元卡片标题行（"口语训练新湘少版四下U3"）—— 单元多到需要滚动时按钮
         可能不在首屏，但标题行一定在；练习报告页两者都没有。
    """
    if not xml or "口语训练" not in xml:
        return False
    if "退出训练" in xml or "答题卡" in xml or "确定退出" in xml:
        return False
    if any(b in xml for b in ("开始答题", "重新答题", "继续答题")):
        return True
    return bool(re.search(r'口语训练[^"<]{0,20}[Uu]\s*0*\d', xml))


def _restart_to_oral_module(d):
    """兜底：重启 App 并重新导航到「口语训练」模块页（返回是否成功）。

    只在所有 UI 退出尝试都失败时调用 —— 宁可慢 ~25s，也不能让"停在试卷页"
    把下一个单元误报成"App 无此单元"（2026-10-08 实测的误报源头）。
    """
    try:
        d.press("home")
        time.sleep(0.6)
        d.app_stop(APP_PACKAGE)
        time.sleep(1.0)
        d.app_start(APP_PACKAGE)
    except Exception:
        return False
    for _ in range(20):
        time.sleep(1)
        try:
            xml = d.dump_hierarchy()
        except Exception:
            continue
        if "教材精学" in xml or "专项突破" in xml or "听课文" in xml:
            break
        try:
            d.press("back")
        except Exception:
            pass
    try:
        if not scroll_and_find(d, "口语训练", max_swipes=4):
            return False
        d(text="口语训练").click()
        time.sleep(1.6)
        _close_bottom_ad(d)
        return True
    except Exception:
        return False


def _exit_paper_to_list(d, tries=6, allow_restart=True):
    r"""从口语训练「试卷页(SpokeTestActivity)」退回单元列表；已在列表则立即 True。

    ★ 2026-10-08 新增，同日二次修复。原实现（run_module 里）只有：
          for _ in range(3): ... d.press("back")
          if d(text="口语训练").exists(): d(text="口语训练").click()
    第一版按"点『退出训练』+ 点确认框"重写，但三处误判叠加，真机仍然卡死 6 轮：

      ① 确认框按钮实测是 **"确定退出"**，而白名单只有 ("确定","确认",...)；
         uiautomator2 的 text= 是**精确匹配** → "确定" 匹配不到 "确定退出"
         → 一个按钮都没点中。
      ② 确认框弹出时 XML 里【既无「退出训练」也无 U+数字】，
         旧判据 `"退出训练" not in xml and U\d in xml` 为假 →
         再落到 else 分支去按 back —— 而 back 语义是**取消弹窗**，
         于是「弹窗 → back 取消 → 回试卷 → 再点退出训练 → 再弹窗」死循环。
      ③ 原判据把"不在试卷页"当"已回列表"，缺乏正向证据。

    修法：把"识别确认框"提到判据之前，用 resource-id `confirm_left_btn`
    精确点左键（绝不含"继续答题"），并用**正向特征** `_is_oral_list_page`
    判定成功；全部失败则重启 App 重新导航（`_restart_to_oral_module`）。

    真机验证（2026-10-08 探针 probe_oral_exit_dialog.py，湘少四下 U1）：
      tv_exit → 确认框 → confirm_left_btn → 落到单元列表
      （可见 U1 继续答题 / U2~U5 开始答题，其中 U3 入口存在）。

    语义：本函数返回 False 只代表"工具没退出去"，**不等于 App 没有下一个单元**，
    run_module 的告警文案已按此措辞。
    """
    for _ in range(tries):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        # ① 退出确认框 → 点左键「确定退出」（必须先于其他判据）
        if _in_exit_confirm(xml):
            _click_exit_confirm(d, xml)
            time.sleep(1.2)
            continue
        # ② 正向判定：已回到单元列表
        if _is_oral_list_page(xml):
            return True
        # ③ 还在试卷页 → 点顶栏「退出训练」
        if "退出训练" in xml:
            try:
                el = d(resourceId=f"{APP_PACKAGE}:id/tv_exit")
                if el.exists(timeout=1):
                    el.click()
                elif d(text="退出训练").exists(timeout=1):
                    d(text="退出训练").click()
                time.sleep(1.2)
                continue
            except Exception:
                pass
        # ④ 其他中间页（练习报告等）→ back 一层
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(0.8)

    if allow_restart:
        print("    ⚠ UI 退出失败 → 兜底重启 App 并重新进入口语训练")
        if _restart_to_oral_module(d):
            return True
    return False


def run_module(d, units=None):
    """核心入口：跑完口语训练指定单元，返回题数

    units: 单元范围，如 [1,2] 或 '1-2'；None=默认全部
    """
    t0 = time.time()
    total = 0
    _units = _resolve_units(units, UNITS)
    print(f"\n📋 口语训练 · 单元 {_units[0]}-{_units[-1]} · {len(_units)}个单元")

    # ★ 2026-09-21：每次跑模块都复位"评分不可用"标记（模块级变量在 web_server 进程里常驻，
    #   不复位的话上一次判定过线后，之后每一次跑都会在第一道题就直接终止）
    global _SCORING_DOWN
    _SCORING_DOWN = False

    # ★ 2026-09-15 口语题解析脚本收集器（单元答完写 docx）
    global _oral_coll, _oral_unit
    _oral_coll = None
    _oral_unit = 0
    try:
        from common.gen_script import QuestionCollector
        _g_ver = os.environ.get("YYB_VERSION", "") or BOOK_VERSION
        _g_grade = os.environ.get("YYB_GRADE", "") or GRADE_LEVEL
        _oral_coll = QuestionCollector(module="口语训练", version=_g_ver, grade=_g_grade)
    except Exception as _e:
        print(f"  ⚠ 脚本收集器初始化失败（不影响答题）: {_e}")

    # ① 先确保在主页（口语训练入口在主页专项突破区，直接可见，不需要滑动）
    #   ★ 修复：不能用 back 硬退（练习报告/子页面 back 会退出 App 到桌面）
    #   → 先检查是否 yyb 前台，非 yyb 冷启动；yyb 内 back 循环回主页
    # ★ 2026-09-21：先确认英语宝在前台（关掉通知栏/快捷设置面板并重新拉起）。
    #   实测：版本切换失败后 App 已不在前台，模块继续滑动 → 把安卓通知栏拉了下来 →
    #   报"当前页无'口语训练'卡片（可能该年级无此模块/主页改版）"，结论完全跑偏。
    _fg_ok = True
    try:
        from common.tools import ensure_app_foreground as _ensure_fg
        _fg_ok = _ensure_fg(d)
        if not _fg_ok:
            step_log("⚠ 未能把英语宝切到前台（可能有系统弹窗/通知栏遮挡），仍尝试继续", "warning")
    except Exception:
        pass
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
        _oral_unit = unit_num   # ★ 当前单元号（脚本收集器标注 unit 用）
        # U1 已训练过（重新答题），U2+ 开始答题
        is_retry = (unit_num == 1)
        q = _run_one_unit(d, unit_num, is_retry)
        total += q
        # ★ 单元答完 → 尝试生成解析脚本（受 gen_script 准入规则约束：
        #   口语题无明确答案 → 会被全部跳过，通常不产出脚本文件）
        try:
            if _oral_coll is not None:
                _p = _oral_coll.finish_unit(unit=unit_num)
                if _p:
                    step_log(f"📄 已生成解析脚本: {os.path.basename(_p)}（可在「审查脚本」区下载）",
                             "success")
        except Exception as _e:
            print(f"  ⚠ 生成脚本失败: {_e}")
        # 答完退出到口语训练列表
        # ★ 2026-10-08 改用 _exit_paper_to_list：原实现最多 back 3 次且只认
        #   "口语训练/开始答题"两个文本，遇"确定退出?"确认框会卡死在试卷页 →
        #   下一个单元报"入口缺失"（详见 _exit_paper_to_list 文档字符串）。
        if not _exit_paper_to_list(d):
            step_log(f"⚠ 未能退出口语训练试卷页（U{unit_num} 之后）：UI 退出与「重启 App」"
                     f"兜底均失败，后续单元可能报“入口缺失”——那是【工具侧未退出】，"
                     f"不是 App 缺单元", "warning")
        _close_bottom_ad(d)

    # ★ 模块完成信号（web_server log_msg 靠"完成"关键词触发脚本内容审查）
    #   练习报告页可能因渲染延迟没检测到 → 这里兜底必发
    step_log(f"✅ 口语训练完成，共{total}题", "success")
    print(f"✅ 口语训练完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
    return total


def run_paper(d, paper_kw="期末", grade="三年级上册"):
    """★ 2026-08-25 新增：跑口语训练的"期末/模拟"统测卷（考前突破类内容）。

    背景：口语训练模块页有 tab 栏（全部/单元/期末/模拟），期末/模拟 tab 下是
    统测卷/模考卷（如"期末听说统测卷英语三年级上册（新湘少版）"），每卷一个
    "开始答题"。这些不是单元训练，单元循环 _run_one_unit 不覆盖 → 单独入口。

    paper_kw: 匹配关键词（"期末" 或 "模拟"），对应 tab 名
    grade:    目标年级（用于匹配"英语X年级上册"标题）
    返回答题数（成功进入并作答返回实际题数；失败返回 0）。
    """
    t0 = time.time()
    total = 0
    print(f"\n📋 口语训练 · {paper_kw}统测卷（{grade}）")
    # ① 切到对应 tab（期末/模拟）
    _switch_tab(d, paper_kw)
    # ② 找该年级的卷子标题行 + 其"开始答题"按钮
    import re as _re
    _grade_key = grade.replace("年级", "").replace("上册", "").replace("下册", "")  # "三"
    _found = False
    for _ in range(6):
        elements = (d.xpath('//*[@text!=""]').all() or [])
        row = None
        for e in elements:
            t = (e.text or "").strip()
            # 卷子标题特征：含"听说统测" + 年级关键词
            if paper_kw in t and "听说" in t and "英语" in t:
                if _grade_key in t.replace("年级", ""):
                    row = e
                    break
        if row:
            row_y = row.bounds[1]
            for e in elements:
                t = (e.text or "").strip()
                if t in ("开始答题", "重新答题", "继续答题"):
                    if abs(e.bounds[1] - row_y) < 300:
                        try:
                            e.click()
                        except Exception:
                            d.click((e.bounds[0]+e.bounds[2])//2, (e.bounds[1]+e.bounds[3])//2)
                        print(f"    ✅ 点击 {t}（{paper_kw}卷: {row.text[:40]}）")
                        time.sleep(1.2)
                        _after_unit_enter(d)
                        _found = True
                        break
        if _found:
            break
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)
    if not _found:
        _diag = _snapshot_page(d, want_kw=(paper_kw, "听说", "统测", "模考"), limit=12)
        print(f"    ❌ 找不到 {grade} 的 {paper_kw} 卷（当前页: {_diag['texts'][:6]}）")
        try:
            step_log(f"❌ 口语训练 {paper_kw}卷入口缺失：当前页无「{grade}·{paper_kw}听说统测」标题（可见: {_diag['texts'][:4] or '无'}）", "error")
        except Exception:
            pass
        return 0
    # ③ 答题（统测卷也是多题循环，复用 _run_unit_questions）
    total = _run_unit_questions(d, unit_num=0)
    step_log(f"✅ 口语训练{paper_kw}卷完成，共{total}题", "success")
    print(f"✅ 口语训练{paper_kw}卷完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
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
