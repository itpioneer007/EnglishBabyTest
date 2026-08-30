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
    applock_blocked,
)

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

# ★ 题目解析收集器（run_module 初始化；巧记单词在可生成脚本白名单内）
_coll = None
_cur_unit = 0

# 每单元关卡数（1~5 + boss = 6 关）
LEVELS_PER_UNIT = 6

# 主页「巧记单词」卡片位置（教材精学行中间那张图片卡，无文字标签）
# ★ 真机实测（2026-08-24）：教材精学行三张卡片中心 y≈1357，x 分别为 203 / 540 / 876
#   巧记单词是中间一张 = (540,1357)。旧坐标 (540,1191) 点在了卡片上方空白区，所以进不去。
QIAOJI_CARD = (540, 1357)


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


def _find_qiaoji_card(d, xml=None):
    """★ 2026-08-30 重写（动态定位，不再写死 y 范围）：

    巧记单词 = 「专项突破」标题下方那行 root_layout 图片卡里的【中间一张】。
    ★ 不同年级布局差异实测：
      - 六上：教材精学行 y≈1250-1450（3张卡，巧记单词=中间），专项突破在下方
      - 三上：教材精学行 y 1458-1762（2张卡：课本学习），专项突破行 y 1888-2043
        （3张卡：卡1=知识类目录 / 卡2=巧记单词 / 卡3=语音评测）
    ★ 定位策略：找"专项突破"标题文字 → 取其上方最近的 root_layout 卡片行 →
      该行按 x 排序取中间一张（3张时=第2张；2张时=第1张）。
      找不到"专项突破" → 回退：找所有 root_layout 行里 y 最小且卡片数>=3 的那行。
    """
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return None
    # ① 收集所有 root_layout 卡片（含 y 范围）
    all_cards = []
    for m in re.finditer(
        r'resource-id="[^"]*root_layout"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    ):
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        # 排除全屏大容器（宽>900 且高>300 的行容器是包裹层，非单卡）
        w, h = x2 - x1, y2 - y1
        if w > 900 or h > 350:
            continue
        all_cards.append(((x1 + x2) // 2, (y1 + y2) // 2, y1))

    # ② 找"专项突破"标题，取其上方的卡片行
    m_sec = re.search(r'text="专项突破"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if m_sec:
        sec_y = int(m_sec.group(2))  # 标题 top y
        # 该标题上方 350px 内的卡片（同行的卡片 y 中心应接近）
        row_cards = [c for c in all_cards if sec_y - 400 < c[2] < sec_y - 50]
        if len(row_cards) >= 2:
            row_cards.sort(key=lambda c: c[0])
            # 3张 → 中间；2张 → 第1张（中间偏左）；多张 → 中间
            idx = len(row_cards) // 2 if len(row_cards) >= 3 else 0
            if len(row_cards) == 2:
                # 2张卡时取 x 更接近 540 的那张（中间位置）
                row_cards.sort(key=lambda c: abs(c[0] - 540))
                return (row_cards[0][0], row_cards[0][1])
            return (row_cards[idx][0], row_cards[idx][1])

    # ③ 回退：所有卡片按 y 聚类成行，取 y 最小且 >=3 张的行（教材精学行）
    rows = {}
    for c in sorted(all_cards, key=lambda c: c[2]):
        placed = False
        for ky in rows:
            if abs(ky - c[2]) < 100:
                rows[ky].append(c)
                placed = True
                break
        if not placed:
            rows[c[2]] = [c]
    for ky in sorted(rows):
        if len(rows[ky]) >= 3:
            cards = sorted(rows[ky], key=lambda c: c[0])
            return (cards[len(cards) // 2][0], cards[len(cards) // 2][1])
    # ④ 终极兜底：找 y 1300-2200 中间那张卡
    mid_cards = [c for c in all_cards if 1300 < c[2] < 2200]
    if mid_cards:
        mid_cards.sort(key=lambda c: abs(c[0] - 540))
        return (mid_cards[0][0], mid_cards[0][1])
    return None


def _enter_qiaoji(d, expected_grade="", expected_version=""):
    """首页 → 巧记单词（图片卡，无文字标签，按动态定位/坐标进入）
    ★ 参照语音评测入口逻辑（2026-08-24 重构）：
      ① 检测首页（教材精学 + 专项突破 同屏，无需进入子页）
      ② 优先按文字"巧记单词"定位；找不到则按教材精学行中间卡片坐标 (540,1357) 进入
      ③ 处理 OPPO 应用锁拦截
      ④ 验证进入（单词同步闯关 / 单词分类复习 / 全脑排行榜 / 你已通关），失败重试
    """
    expected_grade = expected_grade or GRADE_LEVEL
    expected_version = expected_version or BOOK_VERSION
    # 1. 确保在首页
    for _ in range(5):
        try:
            xml = d.dump_hierarchy()
            if '教材精学' in xml and '专项突破' in xml:
                break
        except Exception:
            pass
        d.press('back'); time.sleep(0.6)
    # 2. 定位并点击巧记单词卡片
    _clicked = False
    for _ in range(3):
        try:
            xml = d.dump_hierarchy()
            # 优先：文字"巧记单词"直接定位（部分版本/状态卡片带文字）
            m = re.search(r'text="巧记单词"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
            if m:
                x = (int(m.group(1)) + int(m.group(3))) // 2
                y = (int(m.group(2)) + int(m.group(4))) // 2
                print(f"  → 点巧记单词文字 ({x},{y})")
                d.click(x, y)
                _clicked = True
                break
            # 兜底：教材精学行中间卡片（动态定位 root_layout 容器，取 x 中心≈540 的那张）
            pos = _find_qiaoji_card(d, xml)
            if pos:
                print(f"  → 点巧记单词卡片 {pos}")
                d.click(*pos)
                _clicked = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not _clicked:
        # 最后兜底：硬编码坐标（按 1080x2400 基准缩放）
        print(f"  → 未定位到卡片，使用兜底坐标 {QIAOJI_CARD}")
        d.click(*S(d, *QIAOJI_CARD))
        _clicked = True
    time.sleep(2.5)
    # 3. 应用锁拦截（点卡片偶发触发 OPPO 应用锁）
    if applock_blocked(d):
        print("  ⚠ 触发应用锁，等待自动消失...")
        for _ in range(15):
            time.sleep(0.8)
            if not applock_blocked(d):
                print("    ✅ 应用锁已消失")
                break
        else:
            print("    ❌ 应用锁未消失，请手动解锁后重试")
            return False
    # 4. 验证进入巧记单词页
    _entered = False
    for _ in range(6):
        try:
            xml = d.dump_hierarchy()
            if '单词同步闯关' in xml or '单词分类复习' in xml or '全脑排行榜' in xml or '你已通关' in xml:
                _entered = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not _entered:
        print("  ❌ 未进入巧记单词页")
        return False
    print("  ✅ 已进入巧记单词")
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


def _extract_speaker_from_feedback(xml) -> str:
    """★ 2026-08-26 首选方案：从【答错反馈页】提取扬声器播放的单词。

    真机实测（听音选释义题）：答错后反馈页出现「文字解析 / 听力内容：new」——
    App 自己把扬声器播放的单词写出来了！这是最可靠、无需 ASR 的扬声器内容来源。

    格式：<node resource-id=".../analysis_tv" text="听力内容：new&#10;"/>
    提取结果：'new'（句子场景 'My father is a worker.' → 小写整句）
    """
    try:
        # ① 直接匹配 "听力内容：xxx" 文本（含 &#10; 换行实体）
        m = re.search(r'text="听力内容[:：]\s*([A-Za-z0-9\s\'\-]+)', xml)
        if m:
            _w = m.group(1).strip()
            if len(_w) >= 1:
                return _w.lower()
        # ② 兜底：找 analysis_tv 节点内的文本再匹配
        m2 = re.search(r'analysis_tv[^>]*text="([^"]*)"', xml)
        if m2:
            t = m2.group(1)
            mm = re.search(r'听力内容[:：]\s*([A-Za-z0-9\s\'\-]+)', t)
            if mm and len(mm.group(1).strip()) >= 1:
                return mm.group(1).strip().lower()
    except Exception:
        pass
    return ""


def _speaker_word_of(xml) -> str:
    """从答题页 XML 提取扬声器播放的单词（听音题）。

    听音选释义题：扬声器播放一个英文单词（如 new），选项是中文释义。
    ⚠ 纯听音选释义题页面【无英文单词】（选项是中文释义）→ _speaker_word_of 返回空，
      这是正常现象——必须接入 ASR(audio转文本) 才能拿到真正的扬声器单词。
    本函数仅对"页面含英文单词"的题（如跟读题/选项带英文）兜底。
    ★ 接入 ASR 后：asr_transcribe(音频) 优先，_speaker_word_of 只作兜底。
    ★ 2026-08-26：答错反馈页的"听力内容：xxx"是最可靠来源，见 _extract_speaker_from_feedback。
    """
    try:
        _en_words = re.findall(r"[A-Za-z]{2,}", " ".join(
            t for t in re.findall(r'text="([^"]+)"', xml)))
        # ★ 2026-08-26 增加词性标注过滤：跟读题页面显示"new / adj. 新来的；新的"，
        #   adj/n/v/adv 等词性标注会被误提取为单词
        _filter = ("check", "next", "submit", "listen", "original", "play",
                   "skip", "retry", "again", "finish", "complete",
                   "adj", "n", "v", "adv", "prep", "conj", "pron", "num", "art")
        _cands = [w for w in _en_words
                  if w.lower() not in _filter and len(w) >= 2
                  and not w.lower().isdigit()]
        # 纯听音选释义题选项全中文 → 无英文候选，正常返回空（等 ASR）
        return (_cands[-1].lower() if _cands else "")
    except Exception:
        return ""


def _answer_loop(d, max_q=20):
    """答题循环（模拟运行填充题型细节）：
    已知流程：
    - 点选项（A/B/C 或 T/F）→ 「检查」按钮出现
    - 答错：检查 → 正确答案/我的答案 + 「重新答题」
      → 再答 → 检查 → 二次答错 → 「跳过」→ 下一题
    - 答对：检查 → 直接下一题
    - 最后一题：检查 → 「提交」
    ★ 2026-08-26 修复题数记录：以 App 页面 N/M（如"第1关 1/15"）为准记录当前题号，
      答错重做同一题（重新答题）不重复计数；无进度文本时才回退本地计数。
    """
    q = 0
    retry_count = 0  # 当前题答错次数
    idle = 0  # 连续空转计数（防空转死循环）
    _ev_q = -1  # 已发证据卡的题号（每题只发一次，按 App 实际题号）
    _last_progress = 0  # 上一次读取到的 App 进度题号（防重复发卡）
    _no_question_logged = False  # 无试题关卡是否已记过提示（只记一次）
    while True:
        # ★ 从 App 页面读取进度 N/M（"第1关 1/15" / "1/15" / "15/15"）
        _cur_progress = 0
        _total_progress = 0
        try:
            _xml_prog = d.dump_hierarchy()
            m = re.search(r'第?\d+\s*关\s*(\d+)/(\d+)', " ".join(
                t for t in re.findall(r'text="([^"]+)"', _xml_prog)))
            if m:
                _cur_progress = int(m.group(1))
                _total_progress = int(m.group(2))
            else:
                m2 = re.search(r'(\d+)/(\d+)', " ".join(
                    t for t in re.findall(r'text="([^"]+)"', _xml_prog)))
                if m2:
                    _cur_progress = int(m2.group(1))
                    _total_progress = int(m2.group(2))
        except Exception:
            pass
        # ★ 以 App 实际题号为准（答错重做同一题时 _cur_progress 不变 → 不重复计数）
        _cur_q = _cur_progress if _cur_progress > 0 else q + 1
        # ★ 每题界面级完整性检查证据（题型/题干/选项/音频/作答）→ 前端证据卡
        #   按 App 实际题号去重（答错重做同一题不再重复发卡）
        if _cur_q != _ev_q and _cur_progress > 0:
            try:
                _xml_ev = d.dump_hierarchy()
                # ★ 2026-08-26 扬声器播放内容：优先用反馈页提取的（"听力内容：new"，
                #   最可靠），其次页面英文单词兜底；追加到证据卡（题干后展示）
                _ev = collect_ui_evidence(_xml_ev, qtype="巧记单词")
                _fb_spk_cached = getattr(_answer_loop, "_last_fb_spk", "") or ""
                _spk = _fb_spk_cached or _speaker_word_of(_xml_ev)
                if _spk:
                    _ev.append({"field": "扬声器", "type": "info",
                                "expected": "听音题扬声器播放的单词",
                                "actual": _spk, "diff": f"扬声器播放：{_spk}"})
                step_log(f"  第{_cur_q}题 完整性检查", "info", _ev)
                _ev_q = _cur_q
            except Exception:
                pass
        # ★ 停止检查：web_server 收到停止请求 → 中断
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q
        # ★ 2026-08-26 无试题关卡识别：进入关卡后若页面没有任何答题元素
        #   （提交/检查/下一题/选项/录音/填字母），且无 N/M 进度 → 该关未出好题，
        #   只记录一句提示，不走每题证据卡刷屏，直接跳出关卡继续下一关。
        try:
            _xml_st = d.dump_hierarchy()
            _st_txts = " ".join(t for t in re.findall(r'text="([^"]+)"', _xml_st))
            _has_answer_elm = any(k in _st_txts for k in (
                "提交", "检查", "下一题", "跳过", "重新答题", "原音", "点击录音",
                "马上闯关", "字母", "补全"))
            _has_progress = bool(re.search(r'\d+/\d+', _st_txts))
            # 无试题特征：既无答题元素也无进度，且出现"没有试题/暂无/无题"类文案
            _no_q_txt = any(k in _st_txts for k in ("没有试题", "暂无题目", "暂无数", "无题", "敬请期待", "正在开发"))
            if _no_q_txt:
                if not _no_question_logged:
                    step_log(f"⚠ 本关无试题（页面：{_st_txts[:40]}），跳过本关继续下一关", "warning")
                    _no_question_logged = True
                # 返回已完成的题数（0），跳出关卡
                return q
            if not _has_answer_elm and not _has_progress and _cur_progress == 0:
                # 首轮可能仍在 loading/浏览页，给几次机会；连续多次无答题元素才判无试题
                _no_answer_frames = getattr(_answer_loop, "_no_answer_frames", 0) + 1
                _answer_loop._no_answer_frames = _no_answer_frames
                if _no_answer_frames >= 6:
                    step_log(f"⚠ 本关进入后未出现答题元素（可能未出好题），跳过本关（当前页：{_st_txts[:40]}）", "warning")
                    _answer_loop._no_answer_frames = 0
                    return q
            else:
                _answer_loop._no_answer_frames = 0
        except Exception:
            pass
        # 提交（关卡完成）→ 唯一正常退出
        if d(text="提交").exists(timeout=0.15):
            try:
                d(text="提交").click()
            except Exception:
                pass
            print(f"    ✅ 提交！关卡完成")
            time.sleep(0.8)
            # ★ 2026-08-26：以 App 实际题号（_cur_progress）为准返回完成题数，
            #   答错重做不计入（_cur_progress 未变）
            return max(_cur_progress, q) if _cur_progress else q
        # ★ 题目解析收集：有题干的题收集（含听音题——巧记单词 allow_listen=True）
        #   ★ 2026-08-26：听音选释义题（题干含"听"）之前被跳过，现在也收集，
        #     题干 + 选项 + 扬声器识别词(speaker_word) + recording 一并进解析脚本
        try:
            if _coll is not None:
                from common.gen_script import _extract_ui_question
                from common.asr import asr_transcribe
                _xml_q = d.dump_hierarchy()
                _qi = _extract_ui_question(_xml_q)
                _stem_q = (_qi["stem"] or "").strip()
                # ★ 扬声器单词：优先用反馈页提取的（"听力内容：xxx"，最可靠），
                #   其次页面英文单词兜底，最后 ASR（未接入返回空）
                _fb_spk_cached = getattr(_answer_loop, "_last_fb_spk", "") or ""
                _speaker_word = _fb_spk_cached or _speaker_word_of(_xml_q)
                if _stem_q:
                    _m_opt = re.search(r'text="([TFABCDE])"', _xml_q)
                    _ans_q = _m_opt.group(1) if _m_opt else ""
                    if _ans_q:
                        # ★ 2026-08-26：qno 用 App 实际题号（_cur_q），避免答错重做重复记；
                        #   allow_listen=True 让听音题也进脚本
                        _coll.add(qno=_cur_q, stem=_stem_q, options=_qi["options"],
                                  answer=_ans_q, qtype="巧记单词", unit=_cur_unit,
                                  recording=_speaker_word, speaker_word=_speaker_word,
                                  allow_listen=True)
        except Exception:
            pass
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
            # ★ 新题清除上一题的扬声器缓存（防串题）
            try:
                _answer_loop._last_fb_spk = ""
            except Exception:
                pass
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
            # ★ 新题清除上一题的扬声器缓存（防串题）
            try:
                _answer_loop._last_fb_spk = ""
            except Exception:
                pass
            continue
        # 重新答题（一次答错）→ ★ 反馈页有「听力内容：xxx」= 扬声器播放的单词
        if d(text="重新答题").exists(timeout=0.15):
            try:
                # ★ 2026-08-26 从反馈页提取扬声器单词（App 自己显示"听力内容：new"），
                #   补发一条带"扬声器"字段的证据卡 → web_server 与脚本 recording 对比
                _xml_fb = d.dump_hierarchy()
                _fb_spk = _extract_speaker_from_feedback(_xml_fb)
                if _fb_spk:
                    # ★ 缓存供同题重做时证据卡使用
                    _answer_loop._last_fb_spk = _fb_spk
                    try:
                        _fb_ev = collect_ui_evidence(_xml_fb, qtype="巧记单词")
                        _fb_ev.append({"field": "扬声器", "type": "info",
                                       "expected": "听音题扬声器播放的单词",
                                       "actual": _fb_spk, "diff": f"扬声器播放：{_fb_spk}"})
                        step_log(f"  第{_cur_q}题 检查（扬声器内容）", "info", _fb_ev)
                        print(f"    🔊 扬声器内容: {_fb_spk}")
                    except Exception:
                        pass
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


def run_module(d, units=None, expected_grade="", expected_version=""):
    """核心入口：跑完巧记单词指定单元

    units: 单元范围，如 [1,2] 或 '1-2'；None=默认全部
    expected_grade/expected_version: 期望年级/版本（从主页继承，内部校验用）
    """
    t0 = time.time()
    total = 0
    _units = _resolve_units(units, UNITS)
    print(f"\n📋 巧记单词 · 单词同步闯关（单元 {_units[0]}-{_units[-1]} · {len(_units)}个）")

    # ★ 题目解析收集器（有题干的题收集，单元答完生成脚本 docx）
    global _coll, _cur_unit
    _coll = None
    _cur_unit = 0
    try:
        from common.gen_script import QuestionCollector
        _g_ver = os.environ.get("YYB_VERSION", BOOK_VERSION)
        _g_grade = os.environ.get("YYB_GRADE", GRADE_LEVEL)
        _coll = QuestionCollector(module="巧记单词", version=_g_ver, grade=_g_grade)
    except Exception:
        _coll = None

    # 1. 进入巧记单词
    if not _enter_qiaoji(d, expected_grade, expected_version):
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
        # ★ 单元答完：有题干的题汇总生成脚本 docx（无题干/纯听音跳过）
        try:
            if _coll is not None:
                _script_path = _coll.finish_unit(unit=unit_no)
                if _script_path:
                    step_log(f"📄 已生成解析脚本: {os.path.basename(_script_path)}（可在「审查脚本」区下载）", "success")
        except Exception as _e:
            print(f"  ⚠ 生成脚本失败: {_e}")

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
