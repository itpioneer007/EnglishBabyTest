"""版本/年级切换前提功能"""
import time

def _is_home(d):
    return d(text='教材精学').exists(timeout=0.8) or d(text='专项突破').exists(timeout=0.8)

def _back_home(d):
    for _ in range(3):
        d.press('back'); time.sleep(1.5)
        if _is_home(d): return True
    return False

def switch_version(d, target_version):
    """切换教材版本（如'湘少版'）

    流程：主页 → 我（底栏）→ 右上> → 英语所学教材版本 → 选版本 → back×2 → 英语（底栏）→ 主页
    """
    if not _is_home(d): _back_home(d)
    d.click(972, 2220); time.sleep(3)  # 底部「我」
    d.click(999, 285); time.sleep(3)   # 右上「>」
    # 找「英语所学教材版本」点进入
    clicked = False
    for e in d.xpath('//*[@text!=""]').all():
        if '英语所学教材版本' in (e.text or ''):
            e.click(); clicked = True; break
    if not clicked: return False
    time.sleep(3)
    # 选版本（匹配目标版本前缀，如"湘少版"匹配"湘少版(2024审定)"）
    for e in d.xpath('//*[@text!=""]').all():
        t = (e.text or '').strip()
        if t.startswith(target_version) and ('版' in t):
            e.click(); break
    time.sleep(3)
    # back×2 回「我」+ 点「英语」回主页
    d.press('back'); time.sleep(1.5)
    d.press('back'); time.sleep(1.5)
    d.click(108, 2233); time.sleep(3)  # 底部「英语」
    return _is_home(d)

def switch_grade(d, target_grade):
    """切换年级（如'五年级上册'）

    流程：主页点版本+年级栏 → 选年级 → 自动退回主页
    """
    if not _is_home(d): _back_home(d)
    d.click(321, 275); time.sleep(3)  # 主页年级栏
    # 找目标年级点（按文字匹配）
    for e in d.xpath('//*[@text!=""]').all():
        if (e.text or '').strip() == target_grade:
            e.click(); time.sleep(3); return True
    # 可能需要下滑（年级靠后）
    d.swipe(540, 1500, 540, 800, 0.4); time.sleep(1)
    for e in d.xpath('//*[@text!=""]').all():
        if (e.text or '').strip() == target_grade:
            e.click(); time.sleep(3); return True
    return False

def check_current(d, version, grade):
    """快速判断当前是否已是目标版本+年级（是则返回 True，无需切换）"""
    if not _is_home(d):
        return False
    # 主页顶部版本+年级文本栏（如「湘少版（2024审定）   五年级上册」）
    for e in d.xpath('//*[@text!=""]').all():
        t = (e.text or '').strip()
        if '版' in t and ('年级' in t) and ('上册' in t or '下册' in t):
            if version in t and grade in t:
                return True
    return False

def switch_version_grade(d, version, grade, skip_if_ok=True):
    """一站式切换版本+年级（skip_if_ok: 已是目标则跳过）"""
    print(f"  切换前提: {version} {grade}")
    if skip_if_ok and check_current(d, version, grade):
        print(f"    已是 {version} {grade}，跳过切换")
        return True
    if not switch_version(d, version):
        print("    版本切换失败")
        return False
    if not switch_grade(d, grade):
        print("    年级切换失败")
        return False
    print(f"    当前: {version} {grade}")
    return True