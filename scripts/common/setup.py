"""版本/年级切换前提功能

版本切换：主页 → 底部「我」→ 点年级栏 → 「英语所学教材版本」→ 选版本 → 回主页
年级切换：主页顶部「版本+年级」文字栏 → 切换课本页 → 下滑找目标年级 → 点击
（用户确认：年级切换必须走主页顶部栏，"我的"里的年级无效，只切版本）
"""
import time
import re as _re
from common.tools import S, S_swipe

def _is_home(d):
    """判断是否在英语主页：顶部「版本+年级」栏(switch_textbook_tv)是主页独有标志
    （旧版主页有'教材精学/专项突破'，新版主页改版后没有，用 switch_textbook_tv 更可靠）"""
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return False
    if 'switch_textbook_tv' in xml:
        return True
    return d(text='教材精学').exists(timeout=0.3) or d(text='专项突破').exists(timeout=0.3)

def _back_home(d):
    """back 回主页（处理中途退出的确认弹窗）"""
    for _ in range(5):
        # 处理退出确认弹窗（答题中 back 会弹"确定退出/退出/继续答题"）
        try:
            if d(text="确定退出").exists(timeout=0.3):
                d(text="确定退出").click(); time.sleep(0.8)
            elif d(text="退出").exists(timeout=0.3) and d(text="继续答题").exists(timeout=0.3):
                d(text="退出").click(); time.sleep(0.8)
            elif d(text="继续答题").exists(timeout=0.3):
                d(text="继续答题").click(); time.sleep(0.8)
        except Exception:
            pass
        if _is_home(d):
            return True
        d.press('back'); time.sleep(0.6)
    return False


# ============================================================
# 设备无关定位工具（元素优先，坐标只做兜底）
# ★ 2026-10-16 新增。根因：本文件的版本/年级切换此前**全靠写死像素坐标**再经 S() 做
#   比例换算。但 Android 布局按 dp 排布，真机 360x800dp 与 MuMu 600x1067dp 尺寸不同
#   → 布局是"重排"而非等比拉伸 → 像素比例换算原理上不成立；且系统栏是固定 dp，
#   进一步破坏"整屏等比"前提。正解是取节点自报的 bounds 中心（与分辨率/density 无关），
#   与 scripts/modules/语音评测.py 的 _rid_center 同一路子。
# ============================================================

def _screen_wh(d):
    try:
        return d.window_size()
    except Exception:
        return (1080, 2400)


def _dump(d):
    try:
        return d.dump_hierarchy()
    except Exception:
        return ""


def _node_bounds(xml, *, rid=None, text_eq=None, text_contains=None,
                 y_min=None, y_max=None):
    """在 hierarchy xml 里找第一个满足条件的节点，返回 (x1, y1, x2, y2)；找不到返回 None。

    - rid：resource-id 的**短名**精确匹配（uiautomator2 的 resourceId() 需完整包名，
      故这里自行解析 XML）
    - text_eq / text_contains：text 精确 / 包含匹配
    - y_min / y_max：按节点上边 y 过滤（用于"底部 tab""顶部区域"之类约束）
    """
    for m in _re.finditer(r"<node[^>]*>", xml or ""):
        tag = m.group(0)
        if rid is not None:
            r = _re.search(r'resource-id="([^"]*)"', tag)
            if not r or r.group(1).rsplit("/", 1)[-1] != rid:
                continue
        if text_eq is not None or text_contains is not None:
            _tm = _re.search(r'text="([^"]*)"', tag)
            t = _tm.group(1) if _tm else ""
            if text_eq is not None and t != text_eq:
                continue
            if text_contains is not None and text_contains not in t:
                continue
        b = _re.search(r'bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"', tag)
        if not b:
            continue
        x1, y1, x2, y2 = (int(b.group(i)) for i in (1, 2, 3, 4))
        if y_min is not None and y1 < y_min:
            continue
        if y_max is not None and y1 > y_max:
            continue
        return (x1, y1, x2, y2)
    return None


def _tap_bounds(d, bounds):
    """点 bounds 中心。"""
    x1, y1, x2, y2 = bounds
    d.click((x1 + x2) // 2, (y1 + y2) // 2)


def _tap_rid(d, rid):
    """按 resource-id 点节点中心；返回是否点中。"""
    b = _node_bounds(_dump(d), rid=rid)
    if not b:
        return False
    _tap_bounds(d, b)
    return True


def _tap_bottom_tab(d, text):
    """点底部导航 tab（文字精确匹配 + 约束在屏幕下 28%）。找不到返回 False。"""
    _, h = _screen_wh(d)
    b = _node_bounds(_dump(d), text_eq=text, y_min=int(h * 0.72))
    if not b:
        return False
    _tap_bounds(d, b)
    return True


def switch_version(d, target_version):
    """切换教材版本（如'湘少版'）

    流程：主页 → 底部「我」→ 点年级栏 → 设置面板「英语所学教材版本」→
          版本选择页 → 点目标版本 → back → 底部「英语」回主页

    ★ 2026-10-16：入口改为**元素优先**（底部「我」按文字定位；「我的」页年级栏按
      文字/区域定位），写死坐标 S(972,2220) / S(250,300) 仅作兜底。每步带成功校验，
      失败时打印**可读原因** —— 原实现任一步点不中就直接 return False，前端只看到
      一个 HTTP 500，完全不知道卡在哪一步。
    """
    if not _is_home(d):
        _back_home(d)

    # ---- 1) 底部「我」 ----
    entered = False
    for _try_i in range(2):
        if _tap_bottom_tab(d, "我"):
            time.sleep(1.4)
            if "switch_textbook_tv" not in _dump(d):   # 已离开主页 = 进入成功
                entered = True
                break
        else:
            d.click(*S(d, 972, 2220)); time.sleep(1.4)
            if "switch_textbook_tv" not in _dump(d):
                entered = True
                break
        print(f"    ⚠ 未能进入底部「我」页（第 {_try_i + 1} 次尝试）")
    if not entered:
        print("    ✘ 切换版本失败：无法进入底部「我」页")
        return False

    # ---- 2) 「我的」页 → 设置面板 ----
    def _find_textbook_entry():
        for _e in d.xpath('//*[@text!=""]').all():
            if '英语所学教材版本' in (_e.text or ''):
                return _e
        return None

    entry = _find_textbook_entry()
    if entry is None:
        # 面板可能需先点一下年级栏才展开：元素优先（顶部含"年级"的行），坐标兜底
        _, _h = _screen_wh(d)
        _b = _node_bounds(_dump(d), text_contains="年级", y_max=int(_h * 0.45))
        if _b:
            _tap_bounds(d, _b)
        else:
            d.click(*S(d, 250, 300))
        time.sleep(1.5)
        entry = _find_textbook_entry()
    if entry is None:
        print("    ✘ 切换版本失败：找不到「英语所学教材版本」入口")
        return False
    try:
        entry.click()
    except Exception:
        _b = entry.bounds
        d.click((_b[0] + _b[2]) // 2, (_b[1] + _b[3]) // 2)
    time.sleep(1.5)

    # ---- 3) 版本选择页：点目标版本 ----
    # 完全相等优先（避免"人教版"误匹配"人教版(PEP)"），无完全相等时退回前缀匹配
    # （兼容"湘少版"→"湘少版(2024审定)"）；找不到时下滑翻页（版本列表可能不止一屏）
    picked = False
    for _page in range(5):
        exact = None
        prefix = None
        for e in d.xpath('//*[@text!=""]').all():
            t = (e.text or '').strip()
            if t == target_version:
                exact = e
                break
            if prefix is None and t.startswith(target_version) and ('版' in t or '审定' in t):
                prefix = e
        pick = exact or prefix
        if pick is not None:
            try:
                pick.click()
            except Exception:
                b = pick.bounds
                d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
            picked = True
            break
        # 本屏没找到 → 下滑翻页
        try:
            S_swipe(d, 540, 1800, 540, 700, 0.4)
            time.sleep(0.7)
        except Exception:
            break
    time.sleep(1.2)
    if not picked:
        print(f"    ✘ 切换版本失败：版本列表里找不到「{target_version}」"
              f"（已翻 5 屏，请核对版本名与 App 内是否完全一致）")
        return False

    # ---- 4) 关闭设置面板 + 回主页 ----
    # ★ 用户确认：选完版本后只需按一次 back 就能回到"我"主界面（两次会退过头）
    d.press('back'); time.sleep(0.6)
    if d(text='英语').exists(timeout=1.5):
        d(text='英语').click(); time.sleep(1.2)
    ok = _is_home(d)
    if not ok:
        print("    ⚠ 已选中目标版本，但未自动回到主页（后续会再兜底回主页）")
    return ok or picked


def switch_grade(d, target_grade):
    """切换年级（如'五年级上册'）

    流程：主页点顶部「版本+年级」栏 → 「切换课本」页 → 下滑逐屏找目标年级文字 → 点击

    ★ 2026-10-16：打开「切换课本」页改为**元素优先**（resource-id
      switch_textbook_tv —— 主页顶部那条版本+年级栏的稳定标识），写死坐标
      S(321,275) 仅作兜底；并以页面出现「切换课本」为"已打开"的**正向校验**，
      失败重试一次并打印可读原因。
    """
    if not _is_home(d):
        _back_home(d)

    opened = False
    for _try_i in range(2):
        if not _tap_rid(d, "switch_textbook_tv"):
            d.click(*S(d, 321, 275))
        time.sleep(2.2)
        if '切换课本' in _dump(d):
            opened = True
            break
        print(f"    ⚠ 未打开「切换课本」页（第 {_try_i + 1} 次尝试）")
    if not opened:
        print("    ✘ 切换年级失败：无法打开「切换课本」页")
        return False

    # 下滑逐屏找目标年级文字（仅可见区域才点）
    for _ in range(6):
        b = _node_bounds(_dump(d), text_eq=target_grade, y_min=300, y_max=2000)
        if b:
            _tap_bounds(d, b)
            time.sleep(2.5)
            return True
        S_swipe(d, 540, 1700, 540, 700, 0.4); time.sleep(0.6)
    print(f"    ✘ 切换年级失败：「切换课本」页里找不到「{target_grade}」")
    return False


def check_current(d, version, grade):
    """快速判断当前是否已是目标版本+年级（是则返回 True，无需切换）

    主页顶部栏节点 resource-id=switch_textbook_tv，text 形如
    「湘少版（2024审定）   五年级上册」
    """
    if not _is_home(d):
        return False
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return False
    for m in _re.finditer(r'<node[^>]*resource-id="[^"]*switch_textbook_tv"[^>]*>', xml):
        tag = m.group(0)
        tm = _re.search(r'text="([^"]*)"', tag)
        if not tm:
            continue
        t = tm.group(1)
        if version in t and grade in t:
            return True
    # 兜底：xpath 遍历（兼容无 switch_textbook_tv 的版本）
    for e in d.xpath('//*[@text!=""]').all():
        t = (e.text or '').strip()
        if '版' in t and ('上册' in t or '下册' in t):
            if version in t and grade in t:
                return True
    return False


def get_grades_from_app(d, max_pages=5):
    """从 App「切换课本」页实时读取当前版本下的年级列表（与 App 实际内容一致）

    流程：主页点顶部「版本+年级」栏(321,275) → 「切换课本」页 → dump 解析年级
          （X年级上册/下册 网格）→ 下滑翻页收集 → back 关闭（不选中任何年级）→ 返回去重列表
    返回: ["五年级上册", "五年级下册", ...]（空列表表示读取失败）
    ★ 注意：下滑必须从网格下方空白区（y=1900）起滑，避免起点落在年级格子上
            被系统识别为点击 → 误切年级
    """
    if not _is_home(d):
        _back_home(d)
    if not _is_home(d):
        return []
    # 打开切换课本页（验证页面出现"切换课本"标题才继续，最多重试2次）
    opened = False
    for _ in range(2):
        try:
            d.click(*S(d, 321, 275))
            time.sleep(2.2)
            xml = d.dump_hierarchy()
            if '切换课本' in xml:
                opened = True
                break
        except Exception:
            break
    if not opened:
        return []
    grades = []
    prev_n = -1
    for page in range(max_pages):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            break
        # 解析年级：提取文本中"X年级上/下册"子串（兼容"人教版   五年级下册"整行文本）
        for m in _re.finditer(r'([一二三四五六]年级(?:上|下)册)', xml):
            t = m.group(1).strip()
            if t and t not in grades:
                grades.append(t)
        # 页面无新内容且已滑过 → 结束
        if len(grades) == prev_n and page > 0:
            break
        prev_n = len(grades)
        try:
            # 从网格下方空白区起滑，长距离慢速，避免误触选中年级
            S_swipe(d, 540, 1900, 540, 500, 0.5)
            time.sleep(0.7)
        except Exception:
            break
    # 关闭弹窗回主页（不选中任何年级 → back = 取消，保持原年级）
    try:
        d.press('back')
        time.sleep(0.8)
    except Exception:
        pass
    return grades


def _norm_cmp_text(s: str) -> str:
    """★ 2026-09-21：版本/年级"是否一致"比较前的归一化。

    实测根因：App 主页顶部栏显示「教科版（2024审定）」（**全角**括号），
    而前端下拉框/CLI 传过来的目标是「教科版(2024审定)」（**半角**括号）——
    直接做 `version in cur_ver` 永远为 False → 每次运行都误判"版本不对" →
    触发一次**本不需要的版本切换**；切换失败后 App 停在半途（版本弹层/被误触的
    通知栏），紧接着模块就报"当前页无'口语训练'卡片"（诊断 dump 出来的全是
    安卓通知栏文本：无通知 / 飞行模式 / 深色主题）。

    归一化：全角 ASCII → 半角、去掉所有空白、统一小写。
    """
    if not s:
        return ""
    out = []
    for ch in str(s):
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:        # 全角 ！..～ → 半角
            out.append(chr(o - 0xFEE0))
        elif o == 0x3000:                # 全角空格
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out).replace(" ", "").lower()


def _version_match(cur_ver: str, version: str) -> bool:
    """当前版本是否等于目标版本（容忍全/半角括号差异；仍支持前缀/包含匹配）。"""
    a, b = _norm_cmp_text(cur_ver), _norm_cmp_text(version)
    if not a or not b:
        return False
    return a.startswith(b) or b in a


def _grade_match(cur_grade: str, grade: str) -> bool:
    """当前年级是否等于目标年级（同样容错全/半角）。"""
    a, b = _norm_cmp_text(cur_grade), _norm_cmp_text(grade)
    return bool(a and b and a == b)


def _current_texts(d):
    """读取主页顶部栏当前版本+年级文字，返回 (version_text, grade_text) 或 (None, None)
    主页顶部栏节点 resource-id=switch_textbook_tv，text 形如「湘少版（2024审定）   五年级上册」
    """
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return None, None
    for m in _re.finditer(r'<node[^>]*resource-id="[^"]*switch_textbook_tv"[^>]*>', xml):
        tag = m.group(0)
        tm = _re.search(r'text="([^"]*)"', tag)
        if tm and tm.group(1).strip():
            t = tm.group(1).strip()
            # 拆出版本部分（含"版"）与年级部分（含"册"）
            m_ver = _re.search(r'([\u4e00-\u9fa5A-Za-z0-9()（）]+版[^\s]*?)(?:\s|$)', t)
            m_gra = _re.search(r'([一二三四五六]年级[上下]册)', t)
            return (m_ver.group(1) if m_ver else t), (m_gra.group(1) if m_gra else t)
    return None, None


def check_version_ok(d, version):
    """只检查当前版本是否匹配目标版本（前缀匹配 + 全/半角容错）"""
    cur_ver, _ = _current_texts(d)
    return _version_match(cur_ver, version)


def check_grade_ok(d, grade):
    """只检查当前年级是否匹配目标年级（全/半角容错）"""
    _, cur_gra = _current_texts(d)
    return _grade_match(cur_gra, grade)


def switch_version_grade(d, version, grade, skip_if_ok=True):
    """切到目标版本+年级（简单版：选了版本年级，就直接在 App 里切过去）

    流程：
      1. 回主页
      2. 读主页当前版本+年级
      3. 都对 → 不切，直接返回
      4. 版本不对 → 切版本（切完版本年级会重置）
      5. 年级不对 → 切年级
      6. 切完稍等确认，返回结果
    """
    print(f"  检查目标: {version} {grade}")
    # 1. 回主页
    if not _is_home(d):
        _back_home(d)
    if not _is_home(d):
        print("    ✘ 无法回到主页，切换中止")
        return False

    # 2. 读当前版本+年级
    cur_ver, cur_gra = _current_texts(d)
    ver_ok = _version_match(cur_ver, version)
    gra_ok = _grade_match(cur_gra, grade)
    if ver_ok and gra_ok:
        print(f"    ✔ 已是 {version} {grade}，无需切换")
        return True

    # 3. 版本不对 → 切版本
    if not ver_ok:
        print(f"    → 切版本: {cur_ver or '未知'} → {version}")
        if not switch_version(d, version):
            print("    ✘ 版本切换失败")
            return False
        time.sleep(1)

    # 4. 年级不对 → 切年级（版本切换后年级会重置，即使刚才对也需确认）
    cur_ver, cur_gra = _current_texts(d)
    gra_ok = _grade_match(cur_gra, grade)
    if not gra_ok:
        print(f"    → 切年级: {cur_gra or '未知'} → {grade}")
        if not switch_grade(d, grade):
            print("    ✘ 年级切换失败")
            return False
        time.sleep(1)

    # 5. 最终确认
    cur_ver, cur_gra = _current_texts(d)
    ver_ok = _version_match(cur_ver, version)
    gra_ok = _grade_match(cur_gra, grade)
    print(f"    最终: {'✔' if ver_ok and gra_ok else '✘'} {cur_ver} {cur_gra}")
    return ver_ok and gra_ok
