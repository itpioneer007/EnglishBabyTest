"""
英语宝 · 语音评测 模块（半自动混合方案）
================================================
流程：
  主页 → 教材精学 → 「语音评测」图片卡（876,1357）
  进入 → 顶部版本栏 → 左栏选版本 → 右栏选年级 → 目录
  目录 → 单元栏 → 展开 → 部分卡片（从上到下）
  部分页 → 逐条：
    滚到当前题 →（切题自动播原音，等2s）→ 点"录音"（record_layout @ 540,975）
    → 【等用户对麦克风朗读】→ 按钮变"点击完成" → 点"点击完成" → 下一题
  全部完成 → 点"完成并获取报告" → 点"练习下一节" → 下一节
  全部节完成 → back 一次 → 单元列表（可选下一单元）
  全部单元完成 → back 两次 → 下一模块

⚠️ 核心限制（用户已确认）：
  - adb 无法注入真实音频到麦克风
  - TTS 扬声器外放被 AEC 滤掉，不可靠
  - App 做了语音识别比对，必须读出与题目相关的内容（如 jumping rope）才算完成
  - 解决方案：脚本驱动所有点击/滚动/切换，用户对麦克风朗读

用法：
  from modules.语音评测 import run_module
  run_module(d, units=[1, 2])  # 跑 Unit 1-2（默认全部）
  run_module(d)  # 跑所有 Unit
"""
import os
import re
import sys
import time
import uiautomator2 as u2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
    smart_find_unit_row, applock_blocked,
)
from common.logger import step_log

APP_PACKAGE = "com.dinoenglish.yyb"

# 默认参数（具体版本/年级在 _enter_voice_eval 内部切换，不依赖 ensure_grade）
GRADE_LEVEL = "二年级上册"
BOOK_VERSION = "湘少版（2024审定）"

# 主页语音评测图片卡（教材精学 y=1220 下、专项突破 y=1501 上，第三张卡）
VOICE_CARD = (876, 1357)

# 答题页关键坐标（已真机验证，screen 1080×2400）
BTN_PLAY_SYSVOICE = (266, 975)   # 原音 iv_play_sysvoice
BTN_RECORD_LAYOUT = (540, 975)   # 录音 record_layout（点完变"点击完成"）
BTN_MY_RECORD     = (812, 975)   # 回放 iv_my_record
BTN_CONFIRM_REPORT = (540, 2145) # 完成并获取报告 speech_btn_confirm
TOP_VERSION_BAR  = (526, 165)    # 顶部版本/年级栏
# 左侧版本栏（需下滑找湘少版，y~1485）
LEFT_BAR_X = 294
# 右侧年级栏（点完版本后出现，y~1548 找二年级上册）
RIGHT_BAR_X = 834

# 滑屏节奏：每条录音用户朗读时长（秒），超时自动点完成避免挂起
USER_READ_TIMEOUT = 15


# ============================================================
# 入口：主页 → 语音评测（继承主页版本，必要时内部切版本/年级）
# ============================================================
def _enter_voice_eval(d, expected_grade="", expected_version=""):
    """主页 → 语音评测（文字+图片标签，点击文字/图片均可进入）
    ★ 新版（2026-08-23）：语音评测从主页继承当前版本/年级——
      主页是二年级上册，进入语音评测直接就是二年级上册目录，无需内部切换。
      内部切换（_switch_version_grade）保留为兜底：仅当进入后发现版本不匹配时调用。
    """
    expected_grade = expected_grade or GRADE_LEVEL
    expected_version = expected_version or BOOK_VERSION
    # 1. 确保在主页
    for _ in range(5):
        try:
            xml = d.dump_hierarchy()
            if '教材精学' in xml and '专项突破' in xml:
                break
        except Exception:
            pass
        d.press('back'); time.sleep(0.6)
    # 2. 点语音评测（优先按文字 name_tv 定位；找不到再按卡片坐标）
    _clicked = False
    for _ in range(3):
        try:
            xml = d.dump_hierarchy()
            m = re.search(r'text="语音评测"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
            if m:
                x = (int(m.group(1)) + int(m.group(3))) // 2
                y = (int(m.group(2)) + int(m.group(4))) // 2
                print(f"  → 点语音评测文字 ({x},{y})")
                d.click(x, y)
                _clicked = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not _clicked:
        # 兜底：老版本图片卡坐标
        print("  → 未找到语音评测文字，尝试图片卡坐标")
        d.click(*VOICE_CARD)
        _clicked = True
    time.sleep(2.5)
    # 应用锁拦截（点语音评测偶发触发 OPPO 应用锁）
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
    # 3. 验证进入语音评测（顶部有版本栏 + 简介/目录 tab）
    _entered = False
    for _ in range(6):
        try:
            xml = d.dump_hierarchy()
            if '学习进度' in xml and ('简介' in xml or '目录' in xml):
                _entered = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not _entered:
        print("  ❌ 未进入语音评测页")
        return False
    # 4. 版本匹配检查：进入后若版本/年级不符 → 内部切换（兜底）
    try:
        xml = d.dump_hierarchy()
        _ver_ok = expected_version in xml
        _grade_ok = expected_grade in xml
        if _ver_ok and _grade_ok:
            print(f"  → 版本已匹配（{expected_version} {expected_grade}），无需切换")
            return True
        print(f"  → 版本不匹配（期望 {expected_version} {expected_grade}），内部切换")
        return _switch_version_grade(d, expected_version, expected_grade)
    except Exception:
        return True


def _switch_version_grade(d, target_version, target_grade):
    """语音评测内切换版本/年级（左栏版本 + 右栏年级，两栏联动）"""
    # 1. 点顶部版本栏（湘少版（2024审定）五年级上册）展开选择面板
    for _ in range(3):
        try:
            xml = d.dump_hierarchy()
            # 顶部版本栏可能有空格或无空格
            m = re.search(r'text="(湘少版（2024审定）\s*\S+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
            if not m:
                m = re.search(r'text="湘少版（2024审定）"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
            if m:
                # 第一组捕获 = 完整文本，找其中版本部分
                full_text = m.group(1) if m.lastindex >= 1 else ''
                bm_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', m.group(0))
                if bm_match:
                    x = (int(bm_match.group(1)) + int(bm_match.group(3))) // 2
                    y = (int(bm_match.group(2)) + int(bm_match.group(4))) // 2
                    d.click(x, y); time.sleep(1.5)
                    break
        except Exception:
            pass
        time.sleep(0.5)
    # 2. 左栏找目标版本（可能需要下滑）
    _target_ver = target_version  # 如 "湘少版（2024审定）"
    for _ in range(8):
        try:
            xml = d.dump_hierarchy()
            m = re.search(rf'text="{re.escape(_target_ver)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
            if m:
                x = (int(m.group(1)) + int(m.group(3))) // 2
                y = (int(m.group(2)) + int(m.group(4))) // 2
                print(f"  → 左栏选版本 [{_target_ver}]: ({x},{y})")
                d.click(x, y); time.sleep(1.2)
                break
        except Exception:
            pass
        S_swipe(d, LEFT_BAR_X, 1600, LEFT_BAR_X, 700, 0.35)
        time.sleep(0.6)
    else:
        print(f"  ⚠ 未找到版本 [{_target_ver}]")
        return False
    # 3. 右栏找目标年级（点完版本后右栏联动显示该版本年级）
    for _ in range(8):
        try:
            xml = d.dump_hierarchy()
            m = re.search(rf'text="{re.escape(target_grade)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
            if m:
                x = (int(m.group(1)) + int(m.group(3))) // 2
                y = (int(m.group(2)) + int(m.group(4))) // 2
                print(f"  → 右栏选年级 [{target_grade}]: ({x},{y})")
                d.click(x, y); time.sleep(2.0)
                return True
        except Exception:
            pass
        S_swipe(d, RIGHT_BAR_X, 1600, RIGHT_BAR_X, 700, 0.35)
        time.sleep(0.6)
    print(f"  ⚠ 未找到年级 [{target_grade}]")
    return False


# ============================================================
# 单元列表 → 部分卡片 → 答题循环
# ============================================================
def _list_units(d):
    """在目录页列出所有 Unit（如 Unit 1 Hobbies / Unit 2 ...）"""
    units = []
    # 切到目录 tab
    for _ in range(3):
        try:
            xml = d.dump_hierarchy()
            if '目录' in xml and '学习进度' in xml:
                # 已显示目录
                break
        except Exception:
            pass
        d(text='目录').click(); time.sleep(0.8)
    # 列出 Unit（Unit N 文字 + 副标题），按 y 排序
    time.sleep(0.5)
    xml = d.dump_hierarchy()
    for m in re.finditer(r'text="(Unit\s+\d+\s+[^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        full = m.group(1)
        n = re.search(r'Unit\s+(\d+)', full)
        if n:
            units.append((int(n.group(1)), full, m.group(2), m.group(3), m.group(4)))
    units.sort(key=lambda x: x[0])
    return units


def _open_unit(d, unit_no, unit_text):
    """点单元栏展开，返回 part 卡片列表 [(text, y_top, y_bot), ...]
    ★ Unit 栏是 LinearLayout 可点击容器 [37,778][1043,908]（非标题文字）
      点击后必须验证展开（出现部分卡片），否则重试
    """
    # 找到 Unit 栏（可点击容器），点容器中心 (540, y_center)
    # ★ 先等目录页稳定（切完年级后列表可能还在加载）
    time.sleep(1.5)
    for _ in range(3):
        xml = d.dump_hierarchy()
        # 找 Unit 标题文字坐标，取其 y 中心（栏覆盖 37-1043 宽）
        m = re.search(rf'text="{re.escape(unit_text)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            y1, y2 = int(m.group(2)), int(m.group(4))
            # 若已展开（可见部分卡片）→ 不用点；否则点击栏中心
            if 'Look, Listen' in xml or 'Chant' in xml or 'Word List' in xml:
                break  # 已展开
            # 点栏中心 (540, y_center) —— 栏可点击容器横跨全宽
            d.click(540, (y1 + y2) // 2)
            # ★ 等展开动画完成：循环等待（最长 6s），出现部分卡片才 break
            _expanded = False
            for _w in range(6):
                time.sleep(1.0)
                xml2 = d.dump_hierarchy()
                if 'Look, Listen' in xml2 or 'Chant' in xml2 or 'Word List' in xml2:
                    _expanded = True
                    break
            if _expanded:
                break
            # 展开失败：可能页面不在目录（切完年级慢加载）→ 等 1s 重试
            time.sleep(1.0)
        else:
            # 不在目录页 → 直接返回（绝不 back，防止退过头到主页/桌面）
            print(f"  ⚠ 目录页无 [{unit_text}]")
            return []
    # 收集展开后的"部分"卡片（不带 Unit 标题/跟读报告/状态栏/顶部版本栏）
    # ★ 使用更宽松匹配：兼容 text 在 bounds 前/后 两种属性顺序
    parts = []
    time.sleep(0.5)  # ★ 再次等渲染稳定
    xml = d.dump_hierarchy()
    # 收集所有 (text, y_top, y_bot) 兼容两种属性顺序
    text_bounds = []
    for m in re.finditer(r'text="([^"]+)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        text_bounds.append((m.group(1), int(m.group(3)), int(m.group(5))))
    for m in re.finditer(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*?text="([^"]+)"', xml):
        text_bounds.append((m.group(4), int(m.group(2)), int(m.group(4))))
    # 应用过滤
    for t, y_top, y_bot in text_bounds:
        # y 过滤：状态栏/标题栏/学习进度/简介/目录 都在 y<800；部分卡片 y>800
        if y_top < 800:
            continue
        if t.startswith('Unit ') or t in ('跟读报告', '继续答题', '去答题', '已评测'):
            continue
        if any(k in t for k in ('完成并获取', '练习下一节', '开始', '规则', '学习进度', '简介', '目录')):
            continue
        if len(t) > 1 and not t.isdigit():
            parts.append((t, y_top, y_bot))
    return parts


def _enter_part(d, part_text):
    """点部分卡片进入答题页（点后验证出现 原音/点击录音 才算成功）
    ★ back 最多 1 次（防止退过头到主页/桌面）
    """
    for _ in range(2):
        xml = d.dump_hierarchy()
        m = re.search(rf'text="{re.escape(part_text)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            x = (int(m.group(1)) + int(m.group(3))) // 2
            y = (int(m.group(2)) + int(m.group(4))) // 2
            d.click(x, y); time.sleep(2.0)
            # 验证进入答题页（出现 原音/点击录音/录音 之一）
            try:
                xml2 = d.dump_hierarchy()
                if '点击录音' in xml2 or '原音' in xml2 or 'speech_btn_confirm' in xml2:
                    return True
                # 可能弹"训练规则"→ 点掉再试
                if '开始' in xml2 and '我知道了' in xml2:
                    m2 = re.search(r'text="我知道了[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml2)
                    if m2:
                        d.click((int(m2.group(1))+int(m2.group(3)))//2,
                                (int(m2.group(2))+int(m2.group(4)))//2)
                        time.sleep(1.0)
                        continue
            except Exception:
                pass
        d.press('back'); time.sleep(0.6)
    return False


# ============================================================
# 答题循环（混合半自动：脚本点原音/录音/完成，你朗读）
# ============================================================
def _wait_record_done(d, timeout=USER_READ_TIMEOUT):
    """点录音后等用户朗读，按钮变'点击完成'→点击它
    超时也强制点完成（避免挂起）
    """
    # 1. 立即点录音（按钮变"点击完成"）
    d.click(*BTN_RECORD_LAYOUT)
    time.sleep(0.8)
    # 2. 轮询：等用户读完（按钮文字变"点击完成"或"已完成"）
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            xml = d.dump_hierarchy()
            if '点击完成' in xml:
                # 找到点击完成按钮坐标
                m = re.search(r'text="点击完成"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
                if m:
                    x = (int(m.group(1)) + int(m.group(3))) // 2
                    y = (int(m.group(2)) + int(m.group(4))) // 2
                    d.click(x, y)
                    time.sleep(2.0)
                    return 'completed'
        except Exception:
            pass
        time.sleep(0.6)
    # 超时兜底：再点一次"点击完成"位置（按钮可能已变回原状）
    print(f"    ⚠ 录音等待超时（{timeout}s），强制点完成")
    d.click(*BTN_RECORD_LAYOUT)
    time.sleep(2.0)
    return 'timeout'


def _answer_one_part(d, part_text):
    """一个部分（卡片）答题循环：滚到每条 → 录音 → 等用户朗读 → 完成"""
    print(f"\n  📖 进入部分: {part_text}")
    # 解析总题数：页面上找 N/M 找最大 M
    xml = d.dump_hierarchy()
    total = 0
    for m in re.finditer(r'text="(\d+)/(\d+)"', xml):
        try:
            total = max(total, int(m.group(2)))
        except Exception:
            pass
    if total == 0:
        # 兜底：根据"完成并获取报告"位置推断（已验证 7 条 = 1/7 ~ 7/7）
        total = 7
    print(f"    共 {total} 条")
    done = 0
    for i in range(1, total + 1):
        # 1. 滚到当前 N/M 题可见（每条约 y=1300-1900 在按钮完成报告之上）
        # 简单策略：滚到使"完成并获取报告"按钮在屏幕下方，让 N/M 标题可见
        _scroll_to_current(d, i, total)
        # 2. 确认当前是 N/M 题（页面上 "i/total"）
        time.sleep(0.4)
        # ★ 每题界面级完整性检查（六维：题型/题干/选项/音频/作答，前端证据卡）
        #   复用 collect_ui_evidence（口语题识别：跟读/原音/点击录音 关键词命中）
        try:
            _xml_ev = d.dump_hierarchy()
            from common.evidence import collect_ui_evidence
            step_log(f"  第{i}题 完整性检查", "info",
                     collect_ui_evidence(_xml_ev, qtype="语音评测"))
        except Exception:
            pass
        # 3. 流程（★ 用户确认：切题时 App 会自动播放原音，无需点"原音"按钮）
        #   切题后等自动原音播放完（约 2s），再点录音（学生听完才好跟读）
        time.sleep(2.0)   # 等自动原音播放
        # 点录音 + 等完成
        result = _wait_record_done(d)
        done += 1
        marker = '✅' if result == 'completed' else '⚠'
        print(f"    {marker} 第{i}/{total}条 [{result}]")
    # 全部完成 → 点"完成并获取报告"
    _scroll_to_confirm(d)
    time.sleep(0.5)
    d.click(*BTN_CONFIRM_REPORT)
    time.sleep(2.5)
    return _check_in_report(d)


def _scroll_to_current(d, idx, total):
    """滚到第 idx 条可见（向上滑让下方内容上移）"""
    # 简单粗暴：滚到让 N/M 文字出现在屏幕上半部分
    for _ in range(3):
        xml = d.dump_hierarchy()
        m = re.search(rf'text="{idx}/{total}"', xml)
        if m:
            return
        S_swipe(d, 540, 1600, 540, 800, 0.3)
        time.sleep(0.4)


def _scroll_to_confirm(d):
    """滚到底部让"完成并获取报告"可见"""
    for _ in range(5):
        xml = d.dump_hierarchy()
        if '完成并获取报告' in xml:
            return
        S_swipe(d, 540, 1800, 540, 500, 0.35)
        time.sleep(0.4)


def _check_in_report(d):
    """检测是否进入报告页（含"报告"/"得分"/"练习下一节"任一）"""
    for _ in range(3):
        xml = d.dump_hierarchy()
        if '练习下一节' in xml:
            return 'next_section'
        if any(k in xml for k in ('评测报告', '测评报告', '本次成绩', '练习报告', '开始学习', '查看报告')):
            return 'report'
        if '请完成所有条目' in xml:
            return 'incomplete'
        time.sleep(0.8)
    return 'unknown'


def _next_section(d):
    """点"练习下一节"进入下一个部分卡片"""
    for _ in range(3):
        xml = d.dump_hierarchy()
        m = re.search(r'text="练习下一节"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            x = (int(m.group(1)) + int(m.group(3))) // 2
            y = (int(m.group(2)) + int(m.group(4))) // 2
            d.click(x, y); time.sleep(2.0)
            return True
        time.sleep(0.6)
    return False


# ============================================================
# 总入口
# ============================================================
def run_module(d, units=None, expected_grade="", expected_version=""):
    """语音评测自动化入口（半自动：每条题目需用户对麦克风朗读）
    units: list[int]，如 [1, 2] 跑 Unit 1-2；None = 全部 Unit
    expected_grade/expected_version: 期望的年级/版本（从主页继承，内部切换兜底用）
    """
    t0 = time.time()
    print(f"\n📋 语音评测 · 半自动混合模式")
    if not _enter_voice_eval(d, expected_grade, expected_version):
        return 0
    time.sleep(1.0)
    # 列出所有 Unit
    all_units = _list_units(d)
    if not all_units:
        print("  ❌ 未找到任何 Unit")
        return 0
    print(f"  📚 找到 {len(all_units)} 个 Unit")
    # 选要跑的 Unit
    # ★ 兼容 units 格式：list[int] / "1-3"区间 / "1,3,5"枚举 / None全部
    _u_targets = None
    if units is not None:
        if isinstance(units, str):
            units = str(units).strip()
            if '-' in units:
                a, b = units.split('-', 1)
                _u_targets = list(range(int(a), int(b) + 1))
            elif ',' in units:
                _u_targets = [int(x) for x in units.split(',') if x.strip().isdigit()]
            elif units.isdigit():
                _u_targets = [int(units)]
            else:
                _u_targets = None
        else:
            try:
                _u_targets = [int(x) for x in units]
            except Exception:
                _u_targets = None
    targets = all_units if _u_targets is None else [u for u in all_units if u[0] in _u_targets]
    if not targets:
        print(f"  ❌ 没有匹配的 Unit: {units}")
        return 0
    total_q = 0
    for unit_no, unit_text, _, _, _ in targets:
        print(f"\n  🎯 Unit {unit_no}: {unit_text}")
        # 1. 打开单元
        parts = _open_unit(d, unit_no, unit_text)
        if not parts:
            print(f"    ⚠ Unit {unit_no} 展开后无部分，跳过")
            continue
        print(f"    找到 {len(parts)} 个部分")
        # 2. 逐个部分作答
        for part_text, _, _ in parts:
            if not _enter_part(d, part_text):
                print(f"    ⚠ 进入 [{part_text}] 失败，跳过")
                continue
            r = _answer_one_part(d, part_text)
            if r == 'incomplete':
                print(f"    ⚠ [{part_text}] 有条目未测评（用户未朗读相关）")
            elif r == 'next_section':
                print(f"    ✅ [{part_text}] 完成 → 下一节")
            else:
                print(f"    ✅ [{part_text}] 完成（状态: {r}）")
            # 尝试进入下一节（如果不是最后一节）
            if r == 'next_section':
                _next_section(d)
        # 3. 答完单元所有部分 → back 一次回单元列表
        d.press('back'); time.sleep(1.0)
    print(f"\n✅ 语音评测完成: {len(targets)} 个单元, 耗时 {time.time()-t0:.0f}s")
    return len(targets)


def main():
    d = u2.connect()
    print("✅ 设备已连接")
    d.press("home"); time.sleep(0.4)
    d.app_stop(APP_PACKAGE); time.sleep(0.8)
    d.app_start(APP_PACKAGE); time.sleep(3)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    run_module(d)


if __name__ == "__main__":
    sys.exit(main())
