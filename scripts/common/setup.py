"""版本/年级切换前提功能

版本切换：主页 → 底部「我」→ 点年级栏 → 「英语所学教材版本」→ 选版本 → 回主页
年级切换：主页顶部「版本+年级」文字栏 → 切换课本页 → 下滑找目标年级 → 点击
（用户确认：年级切换必须走主页顶部栏，"我的"里的年级无效，只切版本）
"""
import time
import re as _re

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
    d.click(972, 2220); time.sleep(1.2)   # 底部「我」
    d.click(250, 300); time.sleep(1.5)    # 「我的」页年级栏（领五/五年级 那行）→ 设置面板
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
    # 版本选择页：点目标版本（匹配前缀，如"湘少版"匹配"湘少版(2024审定)"或"湘少版（2024审定）"）
    picked = False
    for e in d.xpath('//*[@text!=""]').all():
        t = (e.text or '').strip()
        if t.startswith(target_version) and ('版' in t or '审定' in t):
            try:
                e.click()
            except Exception:
                b = e.bounds
                d.click((b[0]+b[2])//2, (b[1]+b[3])//2)
            picked = True
            break
    time.sleep(1.2)
    # 关闭设置面板 + 回主页
    d.press('back'); time.sleep(0.6)
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
    d.click(321, 275); time.sleep(2)      # 主页顶部版本+年级栏 → 切换课本页
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
        d.swipe(540, 1700, 540, 700, 0.4); time.sleep(0.6)
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
    # 打开切换课本页（验证页面出现年级格子才继续，最多重试2次）
    opened = False
    for _ in range(2):
        try:
            d.click(321, 275)
            time.sleep(2.2)
            xml = d.dump_hierarchy()
            if '年级' in xml and ('上册' in xml or '下册' in xml):
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
        # 解析年级格子：形如「五年级上册」「三年级下册」（排除标题/说明等长文本）
        for m in _re.finditer(r'text="([^"]*年级(?:上|下)册[^"]*)"', xml):
            t = m.group(1).strip()
            if t and t not in grades:
                grades.append(t)
        # 页面无新内容且已滑过 → 结束
        if len(grades) == prev_n and page > 0:
            break
        prev_n = len(grades)
        try:
            # 从网格下方空白区起滑，长距离慢速，避免误触选中年级
            d.swipe(540, 1900, 540, 500, duration=0.5)
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


def switch_version_grade(d, version, grade, skip_if_ok=True):
    """一站式切换版本+年级（skip_if_ok: 已是目标则跳过）

    顺序：先切版本（"我的"页），再切年级（主页顶部栏）
    """
    print(f"  切换前提: {version} {grade}")
    if skip_if_ok and check_current(d, version, grade):
        print(f"    已是 {version} {grade}，跳过切换")
        return True
    if not switch_version(d, version):
        print("    版本切换失败")
    else:
        print(f"    版本: {version} OK")
    if not switch_grade(d, grade):
        print("    年级切换失败")
        return False
    print(f"    当前: {version} {grade}")
    return True
