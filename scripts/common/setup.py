"""版本/年级切换前提功能

版本切换：主页 → 底部「我」→ 点年级栏 → 「英语所学教材版本」→ 选版本 → 回主页
年级切换：主页顶部「版本+年级」文字栏 → 切换课本页 → 下滑找目标年级 → 点击
（用户确认：年级切换必须走主页顶部栏，"我的"里的年级无效，只切版本）
"""
import time
import re as _re
from common.tools import S, S_swipe


def _norm_ver(s):
    """版本名归一化：全角括号→半角、去空格（兼容 App 显示的"湘少版（2024审定）"
    与代码里写的"湘少版(2024审定)"）"""
    return (
        (s or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("　", "")
        .replace(" ", "")
        .strip()
    )


def _ver_match(cur, target):
    """当前版本 是否 就是目标版本 —— 归一化后【完全相等】才算匹配。

    ★ 重要：人教版 与 人教版(2024审定) 是两个不同版本，不能用前缀/包含匹配，
      否则会把非2024审定版误判成2024审定版（导致该切的版本没切）。
      全角/半角括号、空格的差异由 _norm_ver 消除。
    """
    if not cur or not target:
        return False
    c, t = _norm_ver(cur), _norm_ver(target)
    return bool(c and t and c == t)


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


def switch_version(d, target_version):
    """切换教材版本（如'湘少版'）

    流程：主页 → 底部「我」→ 点年级栏(250,300) → 设置面板「英语所学教材版本」→
          版本选择页 → 点目标版本 → back → 底部「英语」回主页
    """
    if not _is_home(d): _back_home(d)
    d.click(*S(d, 972, 2220)); time.sleep(1.2)   # 底部「我」
    d.click(*S(d, 250, 300)); time.sleep(1.5)    # 「我的」页年级栏（领五/五年级 那行）→ 设置面板
    # 找「英语所学教材版本」点进入
    clicked = False
    for e in d.xpath('//*[@text!=""]').all():
        if '英语所学教材版本' in (e.text or ''):
            try:
                e.click()
            except Exception:
                b = e.bounds
                d.click((b[0]+b[2])//2, (b[1]+b[3])//2)
            clicked = True
            break
    if not clicked:
        return False
    time.sleep(1.5)
    # 版本选择页：点目标版本。★ 完全相等优先（避免"人教版"误匹配"人教版(PEP)"），
    #   无完全相等时退回前缀匹配（兼容"湘少版"→"湘少版(2024审定)"）
    #   ★ 找不到时下滑翻页再找（版本列表可能不止一屏，如教科版在底部）
    picked = False
    _tv = _norm_ver(target_version)
    exact = None      # 归一化后完全相等（优先，避免 人教版 误配 人教版(2024审定)）
    prefix = None     # 兜底：下拉写简称、App 显示全称时才用
    for _page in range(5):
        for e in d.xpath('//*[@text!=""]').all():
            t = (e.text or '').strip()
            tn = _norm_ver(t)
            if tn == _tv:
                if exact is None:
                    exact = e
            elif prefix is None and tn.startswith(_tv) and ('版' in tn or '审定' in tn):
                prefix = e
        if exact is not None:
            break          # 找到完全相等 → 立即停止翻页
        # 本屏没找到 → 下滑翻页
        try:
            S_swipe(d, 540, 1800, 540, 700, 0.4)
            time.sleep(0.7)
        except Exception:
            break
    pick = exact or prefix
    if pick is not None:
        try:
            pick.click()
        except Exception:
            b = pick.bounds
            d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
        picked = True
    time.sleep(1.2)
    # 关闭设置面板 + 回主页
    # ★ 用户确认：选完版本后只需按一次 back 就能回到"我"主界面（之前按两次
    #   会多退一层，可能退过头）。back 一次回"我"主界面 → 点底部「英语」回主页。
    d.press('back'); time.sleep(0.6)
    if d(text='英语').exists(timeout=1.5):
        d(text='英语').click(); time.sleep(1.2)
    return _is_home(d) or picked


def switch_grade(d, target_grade):
    """切换年级（如'五年级上册'）

    流程：主页点顶部「版本+年级」栏(321,275) → 「切换课本」页 → 下滑逐屏找
          目标年级文字（如"五年级上册"）→ 点击 → 自动回主页
    """
    if not _is_home(d): _back_home(d)
    d.click(*S(d, 321, 275)); time.sleep(2)      # 主页顶部版本+年级栏 → 切换课本页
    # 下滑逐屏找目标年级文字（可见区域才点）
    for _ in range(6):
        xml = d.dump_hierarchy()
        for m in _re.finditer(
            r'text="' + _re.escape(target_grade) + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            if 300 < y1 < 2000:  # 可见区域
                d.click((x1 + x2) // 2, (y1 + y2) // 2)
                time.sleep(2.5)
                return True
        S_swipe(d, 540, 1700, 540, 700, 0.4); time.sleep(0.6)
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
        if _ver_match(t, version) and grade in t:
            return True
    # 兜底：xpath 遍历（兼容无 switch_textbook_tv 的版本）
    for e in d.xpath('//*[@text!=""]').all():
        t = (e.text or '').strip()
        if '版' in t and ('上册' in t or '下册' in t):
            if _ver_match(t, version) and grade in t:
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
    """只检查当前版本是否匹配目标版本（前缀匹配，兼容"湘少版"→"湘少版（2024审定）"）"""
    cur_ver, _ = _current_texts(d)
    if not cur_ver:
        return False
    return _ver_match(cur_ver, version)


def check_grade_ok(d, grade):
    """只检查当前年级是否匹配目标年级"""
    _, cur_gra = _current_texts(d)
    return bool(cur_gra and cur_gra == grade)


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
    ver_ok = _ver_match(cur_ver, version)
    gra_ok = bool(cur_gra and cur_gra == grade)
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
    gra_ok = bool(cur_gra and cur_gra == grade)
    if not gra_ok:
        print(f"    → 切年级: {cur_gra or '未知'} → {grade}")
        if not switch_grade(d, grade):
            print("    ✘ 年级切换失败")
            return False
        time.sleep(1)

    # 5. 最终确认
    cur_ver, cur_gra = _current_texts(d)
    ver_ok = _ver_match(cur_ver, version)
    gra_ok = bool(cur_gra and cur_gra == grade)
    print(f"    最终: {'✔' if ver_ok and gra_ok else '✘'} {cur_ver} {cur_gra}")
    return ver_ok and gra_ok
