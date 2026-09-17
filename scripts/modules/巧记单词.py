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
_cur_level = 0

# ★ 2026-09-10 修复（用户反馈"跑完6关审查结果只有15题"）：
#   全局题号分配器。App 页面进度 N/M 每关都从 1 重新开始，而审查结果用它做
#   qid（"auto-Q{题号}"）→ 后一关的同号题覆盖前一关 → 6 关 100+ 题最后只剩
#   max(单关题数) 条。改为给每题分配【跨关卡/跨单元全局递增】题号，qid 唯一。
_GQ_NEXT = 0

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


def _qiaoji_empty_reason(d) -> str:
    """★ 2026-09-10 新增：识别巧记单词「本书籍暂无内容」。

    真机实测（湘少版五年级下册）：点「单词同步闯关」后页面弹出
      「本书籍暂无巧记单词」气泡，进度区显示
      「掌握 0/0 词 / 你已通关 0/0 关 / 你已获星 0/0 颗」——
    说明该「版本 + 年级」组合在 App 后台未配置巧记单词内容。
    ★ 用户约定：智能识别 → 日志报告 → 直接结束本模块（多模块则进下一个）。

    返回：无内容原因字符串（非空 = 无内容）；有内容返回 ""。
    """
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return ""
    try:
        txts = " ".join(t for t in re.findall(r'text="([^"]+)"', xml))
        # ① 显式无内容文案（最可靠）
        for kw in ("本书籍暂无", "暂无巧记单词", "暂无单词", "暂无该内容",
                   "该书籍暂无", "暂未开放", "敬请期待", "正在开发"):
            if kw in txts:
                return f"页面提示「{kw}」"
        # ② 进度全 0/0：掌握 0/0词 + 你已通关 0/0关 + 你已获星 0/0颗
        #   正常有内容的页面这些分母均 > 0（六上实测"掌握 0 /143 词"），不会出现 0/0。
        #   ⚠ 页面文本是分开的节点（'掌握','0','/0','词'），join 后含空格，
        #     故正则用 \s* 容忍 "0 /0" 形态。
        _zeros = len(re.findall(r'0\s*/\s*0', txts))
        if _zeros >= 2:
            return f"进度全为 0/0（掌握/通关/获星，命中 {_zeros} 处）"
        # ③ "掌握 N/M 词" 的分母 M == 0（总词数为 0）→ 无内容可学
        #   用非贪婪避免吃掉斜杠（"掌握 0 /0 词"）
        m_hold = re.search(r'掌握[^\u4e00-\u9fa5]{0,12}?(\d+)\s*/\s*(\d+)', txts)
        if m_hold and int(m_hold.group(2)) == 0:
            return f"掌握词数为 {m_hold.group(1)}/{m_hold.group(2)}（总词数为 0）"
        if re.search(r'掌握\s*0\s*词', txts) or re.search(r'共\s*0\s*词', txts):
            return "掌握词数为 0"
    except Exception:
        pass
    return ""


def _enter_sync_challenge(d):
    """点「单词同步闯关」→ 关卡地图"""
    if d(text="单词同步闯关").exists(timeout=3):
        d(text="单词同步闯关").click()
        print(f"    ✅ 点单词同步闯关")
        time.sleep(1.6)
        return True
    print(f"    ❌ 找不到单词同步闯关")
    return False


# ★ 2026-09-10 新增：闯关地图（Unit 选择页）Unit 卡片锚点
#   真机实测（湘少版六年级上册）：卡片 resource-id = unit{N}_progress_bg_imageview
_UNIT_CARD_RE = re.compile(
    r'resource-id="[^"]*unit(\d+)_progress_bg_imageview"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
)


def _is_unit_map(d, xml=None) -> bool:
    """★ 2026-09-10 新增：判定当前页是否「闯关地图」（Unit 选择页）。

    ★ 用户反馈（六上）：进入巧记单词多了一步——「单词同步闯关」之后不是直接到
      熟悉的单元闯关界面，而是先到「闯关地图」，要滑动找到目标 Unit 再进入。
    判定特征（满足其一即认为是闯关地图）：
      ① 页面出现「闯关地图」标题
      ② 存在 >= 3 张 unitN_progress_bg_imageview 卡片（岛屿式 Unit 卡片）
    """
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return False
    if "闯关地图" in xml:
        return True
    return len(_UNIT_CARD_RE.findall(xml)) >= 3


def _enter_unit_from_map(d, unit_no, max_swipes=8) -> bool:
    """★ 2026-09-10 新增：「闯关地图」→ 滑动/定位找到 Unit N 并进入。

    真机实测（湘少版六年级上册，2026-09-10）：
      - 「单词同步闯关」→「闯关地图」，Unit 1~Unit 10 以岛屿卡片铺开
      - 卡片 resource-id = unit{N}_progress_bg_imageview（199x202）
      - 卡片下方是 "Unit N" 文本，卡片中心比该文字 top 高约 74px
      - 首页进度 "掌握 0 /143 词"；卡片进度 "0/15"（Unit 内关卡数）

    定位策略（按可靠性排序）：
      ① rid 精确匹配 unit{N}_progress_bg_imageview → 点卡片中心（无需滑动）
      ② 目标不在当前视口 → 交替上滑/下滑，每轮重新 dump 后再试
      ③ 兜底：匹配 "Unit N" 文本 → 点其上方 74px（卡片中心）
    返回 True=已点击进入；False=未找到。
    """
    _w, _h = d.window_size()
    for _i in range(max_swipes + 1):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        # ① rid 精确匹配（最优：与卡片归属强绑定，不受文本/布局差异影响）
        for m in _UNIT_CARD_RE.finditer(xml):
            if int(m.group(1)) != unit_no:
                continue
            x1, y1, x2, y2 = (int(m.group(k)) for k in (2, 3, 4, 5))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            if 0 < cy < _h:  # 卡片中心需在可视区内
                d.click(cx, cy)
                step_log(f"🎯 选中 Unit {unit_no}（卡片 rid）@({cx},{cy})", "info")
                time.sleep(1.4)
                return True
        # ② 兜底："Unit N" 文本 → 卡片中心 = 文字上方 74px
        m_txt = re.search(
            rf'text="Unit\s*{unit_no}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m_txt:
            bx = (int(m_txt.group(1)) + int(m_txt.group(3))) // 2
            by = int(m_txt.group(2))
            cx, cy = bx, by - 74
            if 0 < cy < _h:
                d.click(cx, cy)
                step_log(f"🎯 选中 Unit {unit_no}（文本兜底）@({cx},{cy})", "info")
                time.sleep(1.4)
                return True
        # ③ 滑动查找：偶数轮上滑（找下方 Unit），奇数轮下滑（找上方 Unit）
        _mid_x = _w // 2
        if _i % 2 == 0:
            S_swipe(d, _mid_x, 1900, _mid_x, 800, 0.35)
        else:
            S_swipe(d, _mid_x, 800, _mid_x, 1900, 0.35)
        time.sleep(0.5)
    step_log(f"⚠ 闯关地图未找到 Unit {unit_no}", "warning")
    return False


def _current_map_unit(d, xml=None) -> int:
    """★ 2026-09-10 新增：识别「单元关卡地图」当前是哪个 Unit（0 = 不在关卡地图页）。

    ⚠ 必须与「闯关地图」（Unit 选择页）区分，否则会把选择页的卡片文字误当当前 Unit：
      - 闯关地图（选择页）：有「闯关地图」标题 / 多张 unit{N}_progress_bg_imageview 卡片
      - 关卡地图（单元内）：有 boss关 / 上一单元 / 下一单元 + 标题 "Unit N XXX"
    本函数只认后者。
    """
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return 0
    _txts = " ".join(t for t in re.findall(r'text="([^"]+)"', xml))
    if not any(k in _txts for k in ("boss关", "上一单元", "下一单元")):
        return 0
    m = re.search(r'Unit\s*(\d+)\b', _txts)
    return int(m.group(1)) if m else 0


def _switch_unit_by_arrows(d, from_u, to_u, max_steps=12) -> bool:
    """★ 2026-09-10 新增：在关卡地图页用「上一单元」/「下一单元」逐级切换 Unit。

    真机实测（湘少版六上，2026-09-10）：
      - 关卡地图页底部有「上一单元」「下一单元」按钮，**每次点击切换 1 个单元**
      - 到边界（Unit 1 / 最后一个单元）时，对应方向的按钮会消失 → 作为停止条件
      - 双向可逆：Unit 3 →(上一单元)→ 2 → 1；Unit 1 →(下一单元)→ 2
      - 页面标题含 "Unit N XXX" → 用 _current_map_unit 复读实际 Unit，避免盲点

    ⚠ 为什么不 back 回主页重进：App 会记忆"上次进入的 Unit"，
      点「单词同步闯关」每次都回到同一个 Unit（实测反复回到 Unit 3）。
    """
    if from_u == to_u:
        return True
    _btn = "下一单元" if to_u > from_u else "上一单元"
    _steps = min(abs(to_u - from_u), max_steps)
    _cur = from_u
    for _i in range(_steps):
        if not d(text=_btn).exists(timeout=2):
            step_log(f"⚠ 巧记单词：「{_btn}」按钮不存在（可能已到边界），当前 Unit {_cur}", "warning")
            return False
        d(text=_btn).click()
        time.sleep(1.3)
        _new = _current_map_unit(d)
        if _new:
            _cur = _new
        if _cur == to_u:
            return True
    return _cur == to_u


def _ensure_target_unit(d, unit_no, max_try=3) -> bool:
    """★ 2026-09-10 新增：确保当前处在【目标 Unit】的关卡地图。

    真机实测发现（六上，2026-09-10）：App 会**记忆上次进入的 Unit**，
    重启后点「单词同步闯关」会直接落到上次那个 Unit 的关卡地图
    （activity=EWWordLadderActivity），而不是「闯关地图」。此时若只判断
    _is_unit_map 就会**跳过选 Unit 步骤 → 跑错单元**
    （实测：请求 U1，却在跑 Unit 3 的关卡 12~16）。

    策略（按可靠性排序）：
      ① 已在目标 Unit → 直接 True
      ② 在「闯关地图」（Unit 选择页）→ 点目标 Unit 卡片并确认
      ③ 在**其他 Unit 的关卡地图** → 用「上一单元」/「下一单元」逐级切换
         （真机验证可行）；失败才回退到巧记单词主页重进（兜底）
    """
    for _i in range(max_try):
        try:
            _xml = d.dump_hierarchy()
        except Exception:
            _xml = ""
        _cur = _current_map_unit(d, _xml)
        # ① 已在目标 Unit
        if _cur == unit_no:
            step_log(f"🗺 已在 Unit {unit_no} 关卡地图，直接开始", "info")
            return True
        # ② 闯关地图（Unit 选择页）→ 点卡片选 Unit
        if _is_unit_map(d, _xml):
            step_log(f"🗺 检测到闯关地图，定位并进入 Unit {unit_no}", "info")
            if _enter_unit_from_map(d, unit_no):
                time.sleep(1.0)
                if _current_map_unit(d) in (0, unit_no):
                    step_log(f"✅ 已进入 Unit {unit_no} 关卡地图", "success")
                    return True
            step_log(f"⚠ 闯关地图选中 Unit {unit_no} 后未进入，重试（{_i + 1}/{max_try}）", "warning")
        # ③ 在其他 Unit 的关卡地图 → 逐级切换
        elif _cur:
            _dir = "下一单元" if unit_no > _cur else "上一单元"
            step_log(
                f"⚠ 当前在 Unit {_cur} 关卡地图（App 记忆上次单元），"
                f"用「{_dir}」切到 Unit {unit_no}",
                "warning",
            )
            if _switch_unit_by_arrows(d, _cur, unit_no):
                step_log(f"✅ 已切换到 Unit {unit_no} 关卡地图", "success")
                return True
            _left = _current_map_unit(d)
            step_log(f"⚠ 逐级切换未成功（当前 Unit {_left or '未知'}），尝试回主页重进", "warning")
        # 兜底：回退到巧记单词主页后重进「单词同步闯关」
        for _b in range(2):
            try:
                d.press("back")
            except Exception:
                pass
            time.sleep(0.8)
            try:
                if "单词同步闯关" in d.dump_hierarchy():
                    break
            except Exception:
                pass
        if _enter_sync_challenge(d):
            time.sleep(1.2)
    step_log(f"⚠ 巧记单词：多次尝试仍未进入 Unit {unit_no}，跳过本单元", "warning")
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
    # ★ 2026-09-02 浏览页/答题页都可能弹"当前关卡无试题"气泡（关卡未出好题）。
    #   用户约定：识别到就跳过本关继续下一关，不要卡住。
    #   同样要在浏览页早识别（免得干等"点击显示释义"/重复点马上闯关）。
    def _no_question_in(xml: str) -> bool:
        if not xml:
            return False
        _txts = " ".join(t for t in re.findall(r'text="([^"]+)"', xml))
        return any(k in _txts for k in (
            "当前关卡无试题", "没有试题", "暂无题目", "暂无数",
            "无题", "敬请期待", "正在开发",
        ))
    # 单词浏览页 → 先点单词卡片（"点击显示释义"，解锁马上闯关）→ 点马上闯关
    for _retry in range(8):
        if d(text="马上闯关").exists(timeout=1):
            # ★ 浏览页级早识别"当前关卡无试题"：直接跳过，不再强点马上闯关
            #   （无试题关卡点"马上闯关"可能按钮被弹窗遮挡或 selector 失效）
            try:
                _xml_pv = d.dump_hierarchy()
                if _no_question_in(_xml_pv):
                    step_log(
                        f"⚠ 关卡 {level_no} 无试题（浏览页气泡），跳过本关进入下一关",
                        "warning",
                    )
                    return True
            except Exception:
                pass
            # 先点单词卡片（浏览页 5 个单词卡片，点第一个解锁即可）
            try:
                if d(text="点击显示释义").exists(timeout=0.5):
                    d(text="点击显示释义").click()
                    time.sleep(0.5)
                    # 点开后按钮可能重绘，重新等一次"马上闯关"
                    if not d(text="马上闯关").exists(timeout=1):
                        step_log(f"⚠ 关卡 {level_no}：点开释义后未出现马上闯关，尝试直接进入答题", "warning")
                        if d(text="提交").exists(timeout=0.5) or d(text="原音").exists(timeout=0.5):
                            return True
                        continue
            except Exception:
                pass
            # 点击"马上闯关"加保护：若 selector 失效，尝试从 XML 里读坐标兜底
            try:
                d(text="马上闯关").click()
                print(f"    ✅ 点马上闯关")
            except Exception as _e:
                step_log(f"⚠ 关卡 {level_no}：点「马上闯关」失败（{_e}），尝试坐标兜底", "warning")
                try:
                    _xml_btn = d.dump_hierarchy()
                    _m = re.search(r'text="马上闯关"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _xml_btn)
                    if _m:
                        _bx = (int(_m.group(1)) + int(_m.group(3))) // 2
                        _by = (int(_m.group(2)) + int(_m.group(4))) // 2
                        d.click(_bx, _by)
                        print(f"    ✅ 坐标兜底点马上闯关 @({_bx},{_by})")
                    else:
                        # 兜底也找不到：如果已经在答题页，直接继续
                        if d(text="提交").exists(timeout=0.5) or d(text="原音").exists(timeout=0.5):
                            return True
                        continue
                except Exception:
                    continue
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
    # ★ 2026-09-10：本关的全局题号基准（进入本关前已累计的题数）。
    #   本关第 1 题 → 全局第 (_gq_base+1) 题；保证跨关卡 qid 不冲突。
    global _GQ_NEXT
    _gq_base = _GQ_NEXT
    _local_q = 0    # ★ 页面读不到进度时的本地题号兜底
    _local_sig = ""  # ★ 上一题的内容签名（题干+选项），用于判定"换题了"
    _start_progress = 0   # ★ 本关起始题号（App 记忆进度时可能从"第4题"开始）
    _max_progress = 0     # ★ 本关读到过的最大题号

    def _done_count():
        """本次实际完成题数 = 本关最大进度 - 起始进度 + 1。

        ★ 2026-09-10 修复统计口径：旧代码返回 `max(_cur_progress, q)`，而 App 会记住
          关卡内进度（本关可能从"第4题"开始）→ 报出"2关 完成 13 题"却只有 11 条
          审查结果（用户看到自相矛盾）。改后与审查结果条数严格一致。
        """
        if _start_progress and _max_progress >= _start_progress:
            return _max_progress - _start_progress + 1
        return q

    while True:
        # ★ 从 App 页面读取进度 N/M（"第1关 1/15" / "1/15" / "15/15"）
        _cur_progress = 0
        _total_progress = 0
        _xml_prog = ""  # ★ 本轮 dump 的层级（复用做证据卡，省一次 dump；异常时为空串）
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
        #   ★ 2026-09-10：读不到进度时（少数关卡页面结构差异）不再直接退回 q+1
        #     （q 只在部分题型分支自增，会导致整关只算出 1~2 题 → 其余全丢），
        #     改用【题干+选项内容签名变化】判定换题，保证一关能数出全部题。
        if _cur_progress > 0:
            _cur_q = _cur_progress
            # ★ 2026-09-10 题数统计口径修复：App 会记住关卡内进度，本关可能从
            #   "第4题"开始（前面的题上次已做过）→ 旧代码用 max(_cur_progress, q)
            #   报出"2关 完成 13 题"而审查结果只有 11 条（用户看到自相矛盾）。
            #   这里记录本关起始/最大进度，返回【本次实际做的题数】= 最大-起始+1，
            #   与审查结果条数严格一致。
            if _start_progress == 0:
                _start_progress = _cur_progress
            _max_progress = max(_max_progress, _cur_progress)
        else:
            _sig = ""
            try:
                if _xml_prog:
                    from common.gen_script import _extract_ui_question as _euq
                    _qi_s = _euq(_xml_prog)
                    _sig = ((_qi_s.get("stem") or "") + "|" +
                            "|".join(_qi_s.get("options") or [])).strip("|")
            except Exception:
                _sig = ""
            if _sig and _sig != _local_sig:
                _local_sig = _sig
                _local_q += 1
            _cur_q = max(_local_q, 1)
        # ★ 2026-09-10：全局题号 = 本关基准 + 【关内相对题号】（跨关卡唯一 → qid 不覆盖）
        #   用相对号（而不是页面绝对号）保证编号连续：上一关 18 题 → 本关从 19 开始，
        #   不会因为本关页面从"第4题"起算而跳到 22。
        _rel = (_cur_q - _start_progress + 1
                if (_start_progress and _cur_q >= _start_progress) else _cur_q)
        if _rel < 1:
            _rel = 1
        _gq = _gq_base + _rel
        if _gq + 1 > _GQ_NEXT:
            _GQ_NEXT = _gq + 1
        # ★ 每题界面级完整性检查证据（题型/题干/选项/音频/作答）→ 前端证据卡
        #   按 App 实际题号去重（答错重做同一题不再重复发卡）
        #   ★ 2026-09-10 修复（用户反馈"很多题目根本没进审查结果"）：
        #     旧条件要求 _cur_progress > 0（必须读到页面"N/M"进度）才发卡，
        #     一旦某关进度文本读不到（页面结构差异/渲染延迟），【整关题目全部丢失】，
        #     审查结果里只剩读过进度的关卡。改为：读不到进度时，只要页面确实
        #     存在答题元素（检查/提交/原音/重新答题…）也照常发卡。
        _ev_ok = _cur_progress > 0
        _xml_ev = _xml_prog  # 复用本轮已 dump 的 XML，避免重复取层级
        # ★ 2026-09-10：护眼/休息提示页【不是题目】——真机实测它被当成一道"题"记进
        #   审查结果（题干"请眺望一下远方，活动活动身体，休息好了再回来！"），
        #   既虚增题数又会产生假错题。这里显式识别并跳过计题/发卡。
        _is_break_page = False
        try:
            _p_txt = " ".join(re.findall(r'text="([^"]+)"', _xml_ev or ""))
            _is_break_page = any(k in _p_txt for k in (
                "眺望", "活动活动身体", "休息好了再回来", "休息一下", "做眼保健操",
                "保护视力", "让眼睛休息"))
        except Exception:
            _is_break_page = False
        if not _ev_ok and not _is_break_page:
            try:
                _ev_ok = any(k in " ".join(re.findall(r'text="([^"]+)"', _xml_ev))
                             for k in ("检查", "提交", "原音", "点击录音",
                                       "重新答题", "下一题", "跳过"))
            except Exception:
                _ev_ok = False
        if _is_break_page:
            _ev_ok = False
        if _cur_q != _ev_q and _ev_ok:
            try:
                if not _xml_ev:
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
                step_log(f"  第{_gq}题 完整性检查", "info", _ev)
                _ev_q = _cur_q
            except Exception:
                pass
        # ★ 停止检查：web_server 收到停止请求 → 中断
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return _done_count()
        # ★ 2026-09-02 用户约定：识别"当前关卡无试题"立即跳到下一关，不要卡住。
        #   原阈值 6 帧~4.8s 太长（无试题关卡视觉上像死循环）；改为：显式气泡立即跳；
        #   隐式"无答题元素+无进度"连续 2 帧~1.6s 也立即跳，秒过不浪费时间。
        try:
            _xml_st = d.dump_hierarchy()
            _st_txts = " ".join(t for t in re.findall(r'text="([^"]+)"', _xml_st))
            _has_answer_elm = any(k in _st_txts for k in (
                "提交", "检查", "下一题", "跳过", "重新答题", "原音", "点击录音",
                "马上闯关", "字母", "补全"))
            _has_progress = bool(re.search(r'\d+/\d+', _st_txts))
            # 无试题特征：既无答题元素也无进度，且出现"当前关卡无试题/没有试题"类文案
            # ★ 把"当前关卡无试题"放在最前（这是截图真实命中文案）
            _no_q_txt = any(k in _st_txts for k in (
                "当前关卡无试题",        # 真机命中（截图）—— 最常见
                "没有试题", "暂无题目", "暂无数",
                "无题", "敬请期待", "正在开发",
            ))
            if _no_q_txt:
                if not _no_question_logged:
                    step_log(
                        f"⚠ U{_cur_unit} 第{_cur_level}关无试题（页面提示：{_st_txts[:40]}），跳过并进入下一关",
                        "warning",
                    )
                    _no_question_logged = True
                # 返回本次实际完成的题数，跳出关卡
                return _done_count()
            # ★ 2026-09-02 隐式无题（既无答题元素也无 N/M 进度）阈值由 6 → 2，
            #   让"无试题但页面没气泡文案"的关卡也能秒过，单元不被拖慢
            if not _has_answer_elm and not _has_progress and _cur_progress == 0:
                _no_answer_frames = getattr(_answer_loop, "_no_answer_frames", 0) + 1
                _answer_loop._no_answer_frames = _no_answer_frames
                if _no_answer_frames >= 2:
                    step_log(f"⚠ 本关进入后未出现答题元素（可能未出好题），跳过本关（当前页：{_st_txts[:40]}）", "warning")
                    _answer_loop._no_answer_frames = 0
                    return _done_count()
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
            # ★ 2026-09-10：改为"本关进度跨度"（与审查结果条数一致），见 _done_count
            return _done_count()
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
                _m_opt = re.search(r'text="([TFABCDE])"', _xml_q)
                _ans_q = _m_opt.group(1) if _m_opt else ""
                # ★ 2026-09-15 图片题解析：无题干时判断是不是"图片题"（题干/选项是图片），
                #   是则截图存盘，脚本生成阶段用视觉模型识别补全题干/选项/答案。
                _img_path = ""
                if not _stem_q:
                    try:
                        from common.gen_script import is_image_question, save_image_shot
                        if is_image_question(_xml_q):
                            _img_path = save_image_shot(d, "巧记单词", _gq, tag="q")
                    except Exception:
                        _img_path = ""
                if (_stem_q and _ans_q) or _img_path:
                    # ★ 2026-08-26：qno 用 App 实际题号（_cur_q），避免答错重做重复记；
                    #   allow_listen=True 让听音题也进脚本
                    # ★ 2026-09-10：改传全局题号 _gq + 关卡号 level（脚本"位置"行
                    #   显示成"巧记单词 · U1 · 第1关 · 第3题"，跨关卡不再同名混淆）
                    _coll.add(qno=_gq, stem=_stem_q or "", options=_qi["options"],
                              answer=_ans_q, qtype=("巧记单词" if _stem_q else "图片题"),
                              unit=_cur_unit, level=_cur_level,
                              recording=_speaker_word, speaker_word=_speaker_word,
                              allow_listen=True, image_path=_img_path)
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
                        step_log(f"  第{_gq}题 检查（扬声器内容）", "info", _fb_ev)
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
            return _done_count()
    return _done_count()


def _run_one_level(d, level_no):
    """跑一个关卡：进入 → 答题（答完自动提交）→ back 回地图"""
    global _cur_level
    _lv_name = "boss关" if level_no == 0 else f"{level_no}关"
    _cur_level = level_no
    # ★ 2026-09-10 修复（用户要求"题目按单元+关卡分类"）：把关卡写入模块上下文，
    #   审查结果总览即按「巧记单词·U1 第1关」分组统计，不再所有关卡混成一个数字。
    #   （web_server 的 _mod_key = 模块名·stage，stage 即这里的关卡标签）
    _lv_tag = f"U{_cur_unit} boss关" if level_no == 0 else f"U{_cur_unit} 第{level_no}关"
    try:
        from common.logger import set_current_module
        set_current_module("巧记单词", _lv_tag)
    except Exception:
        pass
    step_log(f"🎮 进入{_lv_name}", "info")
    if not _enter_level(d, level_no):
        step_log(f"⚠ 巧记单词：{_lv_name} 进入失败，跳过", "warning")
        return 0
    q = _answer_loop(d, max_q=40)  # 关卡15+题，max_q 要够大（含重试轮次）
    step_log(f"✅ {_lv_name} 完成: {q} 题", "success")
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
    """跑一个单元的所有关卡（数字关 + boss 关）

    unit_no: 单元号（1 开始）
    start_level: 本单元起始关卡序号（仅作读不到页面关卡时的兜底）

    ★ 2026-09-10 重构（随「闯关地图」新步骤一起修复）：
      不再依赖"全局关卡号公式"(1+(unit-1)*6) 推算关卡号，改为**直接读当前
      关卡地图页面上实际存在的关卡数字**，按升序逐个进入。
      真机实测（湘少版六上，2026-09-10）Unit 3 的关卡号是 12~16，
      而旧公式推算为 13~17 → ① 漏掉第 12 关 ② 请求 17 时走
      `level_no > max(nums)` 兜底 → 重复点第 16 关（漏测+重复）。
      动态枚举后与 App 实际编号解耦，任何年级/版本都自适应。
    """
    total = 0
    _done = []           # 本轮已进入过的数字关
    _rounds = 0
    while _rounds < 8:   # 5 个数字关 + 容错余量
        _rounds += 1
        pos = _find_level_positions(d)
        nums = sorted(n for n in pos if n > 0)
        if not nums:
            break
        todo = [n for n in nums if n not in _done]
        if not todo:
            break
        target = todo[0]
        _done.append(target)
        q = _run_one_level(d, target)
        total += q
    # ★ 兜底：页面读不到任何关卡数字（异常/加载中）→ 退回旧的公式顺序
    if not _done:
        step_log("⚠ 巧记单词：未读到页面关卡数字，回退公式顺序", "warning")
        for i in range(5):
            total += _run_one_level(d, start_level + i)
    step_log(
        f"📚 Unit {unit_no} 数字关完成: {sorted(_done) if _done else '(公式兜底)'}",
        "info",
    )
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
    global _coll, _cur_unit, _cur_level, _GQ_NEXT
    _coll = None
    _cur_unit = 0
    _cur_level = 0
    _GQ_NEXT = 0  # ★ 全局题号分配器归零（本次运行内题号连续唯一）
    try:
        from common.gen_script import QuestionCollector
        _g_ver = os.environ.get("YYB_VERSION", BOOK_VERSION)
        _g_grade = os.environ.get("YYB_GRADE", GRADE_LEVEL)
        _coll = QuestionCollector(module="巧记单词", version=_g_ver, grade=_g_grade)
    except Exception:
        _coll = None

    # 1. 进入巧记单词
    if not _enter_qiaoji(d, expected_grade, expected_version):
        step_log("⚠ 巧记单词：未能进入模块页面，跳过本模块", "warning")
        return 0
    # ★ 2026-09-10 无内容检测①：主页即提示「本书籍暂无巧记单词」（如湘少版五下）
    #   用户约定：智能识别 → 日志报告 → 直接结束本模块（多模块则进入下一个）
    _empty = _qiaoji_empty_reason(d)
    if _empty:
        step_log(
            f"⚠ 巧记单词：{_empty} → 本书籍/年级暂无巧记单词内容，"
            f"跳过本模块，直接进入下一个模块",
            "warning",
        )
        print(f"  ⚠ {_empty}，跳过本模块")
        return 0
    # 2. 单词同步闯关
    if not _enter_sync_challenge(d):
        step_log("⚠ 巧记单词：找不到「单词同步闯关」入口，跳过本模块", "warning")
        return 0
    # ★ 2026-09-10 无内容检测②：部分年级点进闯关后才提示无内容（此处补检一次）
    _empty = _qiaoji_empty_reason(d)
    if _empty:
        step_log(
            f"⚠ 巧记单词：{_empty} → 跳过本模块，直接进入下一个模块",
            "warning",
        )
        print(f"  ⚠ {_empty}，跳过本模块")
        return 0

    # 3. 逐单元闯关（关卡序号连续递增）
    # U1: 关卡 1-6(boss)，U2: 7-12，U3: 13-18 ...
    for unit_no in _units:
        start_level = 1 + (unit_no - 1) * LEVELS_PER_UNIT
        if start_level > 54:
            step_log(f"⚠ 巧记单词：Unit {unit_no} 超出范围（仅支持1-9），跳过", "warning")
            continue
        step_log(f"🏫 开始 Unit {unit_no} 闯关", "step")
        # ★ 2026-09-10 新增步骤（用户反馈·六上）：新版流程「单词同步闯关」后可能先到
        #   「闯关地图」（Unit 选择页），需定位到目标 Unit 再进入，才是熟悉的单元闯关界面。
        #   ⚠ 也处理"App 记忆上次 Unit，直接落到别的 Unit 关卡地图"的情况（否则跑错单元）。
        #   旧版无此页且在正确的 Unit → _ensure_target_unit 快速返回 True。
        if not _ensure_target_unit(d, unit_no):
            continue
        _cur_unit = unit_no
        q = _run_one_unit(d, unit_no, start_level)
        total += q
        step_log(f"🏁 Unit {unit_no} 闯关结束: {q} 题", "success")
        # ★ 单元答完：有题干的题汇总生成脚本 docx（无题干/纯听音跳过）
        try:
            if _coll is not None:
                _script_path = _coll.finish_unit(unit=unit_no)
                if _script_path:
                    step_log(f"📄 已生成解析脚本: {os.path.basename(_script_path)}（可在「审查脚本」区下载）", "success")
        except Exception as _e:
            step_log(f"⚠ 巧记单词：生成脚本失败: {_e}", "warning")

    step_log(f"✅ 巧记单词完成: {total} 题, 耗时 {time.time()-t0:.0f}s", "success")
    # ★ 2026-09-10：关卡标签（"U1 第3关"）只用于题目定位/分组统计，模块结束后必须
    #   恢复模块级 stage —— 否则下游（内容补充检查的子模块过滤、下一个模块）会把
    #   关卡标签误当成"脚本子模块名"，导致脚本层审查范围出错。
    try:
        from common.logger import set_current_module
        set_current_module("巧记单词", "")
    except Exception:
        pass
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
