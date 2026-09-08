"""版本/年级切换前提功能

版本切换：主页 → 底部「我」→ 点年级栏 → 「英语所学教材版本」→ 选版本 → 回主页
年级切换：主页顶部「版本+年级」文字栏 → 切换课本页 → 下滑找目标年级 → 点击
（用户确认：年级切换必须走主页顶部栏，"我的"里的年级无效，只切版本）
"""
import time
import re as _re
from common.tools import S, S_swipe


def _norm(s):
    """版本/年级字符串归一化：去空格、全角括号转半角，便于精确比对。

    典型问题：前端发 '湘少版(2024审定)'（半角括号），App 内显示
    '湘少版（2024审定）'（全角括号）。不归一化会导致精确/前缀匹配双双失败。
    归一化后两者都变成 '湘少版(2024审定)'，可精确区分与 '湘少版'。
    """
    if not s:
        return ""
    s = str(s).strip()
    s = s.replace('（', '(').replace('）', ')')
    s = s.replace(' ', '')
    return s

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


def _ensure_screen_ready(d):
    """★ 前置检查：确保屏幕亮着且已解锁（息屏/AOD 状态下点击一律无效）。

    真机问题（2026-09-08）：手机自动息屏后跑任务，`_enter_switchbook` 点顶部栏
    完全点不动 → 版本/年级切换失败 → 任务以「同版本/年级无法切换」终止，
    用户还以为是「版本不存在」，实际是屏幕根本没亮。

    流程：screenOn? → 否 → screen_on() → 尝试 unlock() → 再确认一次
    返回 True/False（False = 仍不可用，上层应明确提示用户手动解锁）
    """
    try:
        info = d.info or {}
    except Exception:
        info = {}
    # 1) 亮屏
    try:
        if not info.get("screenOn", True):
            print("    ⚠ 屏幕处于息屏状态 → 尝试点亮")
            try:
                d.screen_on()
            except Exception:
                try:
                    d.shell("input keyevent 26")  # 电源键兜底
                except Exception:
                    pass
            time.sleep(1.2)
    except Exception:
        pass
    # 2) 解锁（无密码/图案时可直接滑开；有人脸/密码/指纹时无法绕过 → 提示用户）
    try:
        d.unlock()
        time.sleep(0.8)
    except Exception:
        pass
    # 3) 再确认一次：能 dump 到非空页面才算就绪
    try:
        _xml = d.dump_hierarchy() or ""
    except Exception:
        _xml = ""
    if len(_xml) < 2000:
        print("    ❌ 屏幕仍不可用（可能锁屏需人脸/密码解锁）→ 请手动解锁手机后重试")
        return False
    # 锁屏页特征（AOD/锁屏时钟）：包名不是英语宝且节点极少
    if ("com.hihonor.aod" in _xml or "keyguard" in _xml.lower()
            or "com.android.systemui" in _xml and "status_bar" not in _xml):
        print("    ❌ 当前停在锁屏/息屏界面 → 请手动解锁并回到英语宝主页后重试")
        return False
    return True


def _enter_switchbook(d, max_retry=3):
    """主页 → 点顶部栏「switch_textbook_tv」进入'切换课本'页。
    返回是否成功进入（页面出现'切换课本'标题）。
    """
    # ★ 前置：息屏状态下点击无效，先确保亮屏+解锁
    if not _ensure_screen_ready(d):
        return False
    if not _is_home(d):
        _back_home(d); time.sleep(1.2)
    for _ in range(max_retry):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        m = _re.search(r'<node[^>]*resource-id="[^"]*switch_textbook_tv"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            d.click((x1 + x2) // 2, (y1 + y2) // 2)
            print(f"    → 点击顶部栏进入切换课本页 ({(x1+x2)//2},{(y1+y2)//2})")
        else:
            d.click(*S(d, 321, 275))
            print("    → 点击顶部栏(缩放坐标兜底)")
        time.sleep(2.5)
        try:
            if '切换课本' in (d.dump_hierarchy() or ""):
                return True
        except Exception:
            pass
        _back_home(d); time.sleep(1.0)
    return False


def switch_version(d, target_version):
    """切换教材版本（如'湘少版' / '湘少版（2024审定）'）

    ★ 正确路径（用户确认）：主页点顶部栏进入「切换课本」页 → 该页为长滚动页，
      版本选项与年级网格同页，向下滑才显示全 → 在页内滚动扫描版本选项并点击。
      （旧代码走「我的页→英语所学教材版本」路径，该入口在现版 App 已失效。）
    """
    target_n = _norm(target_version)
    if not _enter_switchbook(d):
        print("    ✘ 无法进入切换课本页（切版本失败）")
        return False
    time.sleep(0.5)
    picked = False
    # 版本选项分布在页面上部，先上滑回顶再向下逐屏扫描
    for _ in range(3):
        S_swipe(d, 540, 650, 540, 1850, 0.3); time.sleep(0.4)
    for _scan in range(10):
        for e in d.xpath('//*[@text!=""]').all():
            t = (e.text or "").strip()
            tn = _norm(t)
            # 精确匹配目标版本；并用'版'/'审定'过滤，避免误点年级格子（含'年级'）
            if tn == target_n and ('版' in t or '审定' in t):
                try:
                    e.click()
                except Exception:
                    b = e.bounds
                    d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
                print(f"    → 选中版本: {t}")
                picked = True
                break
        if picked:
            break
        S_swipe(d, 540, 1850, 540, 650, 0.45); time.sleep(0.7)  # 下滑继续找
    time.sleep(1.5)
    # 版本切换后年级会被重置；回到主页以便后续统一确认/切年级
    if not _is_home(d):
        _back_home(d); time.sleep(1.0)
    return picked


def list_versions_from_app(d, max_pages=12):
    """进入「切换课本」页，扫描并返回当前 APP 所有教材版本标题（去重列表）。

    ★ 用途：运行前校验目标版本是否存在。例如网站输入「人教版」，但 APP 已无人教版，
      本函数返回 ['湘鲁版（2024审定）','湘鲁版', ...]，供调度器判断并提示『版本不存在』。
    返回: ['湘鲁版（2024审定）','湘鲁版', ...]；读取失败（进不去切换课本页等）返回 []。
    """
    if not _is_home(d):
        _back_home(d)
    if not _is_home(d):
        return []
    if not _enter_switchbook(d):
        return []
    # 先回到页面顶部（版本分组从上方开始）
    for _ in range(3):
        S_swipe(d, 540, 650, 540, 1850, 0.3); time.sleep(0.4)
    versions = []
    seen = set()
    for _ in range(max_pages):
        try:
            elems = d.xpath('//*[@text!=""]').all()
        except Exception:
            elems = []
        for e in elems:
            t = (e.text or "").strip()
            if not t:
                continue
            # 版本标题：含'版'/'审定'，不含年级/册/切换/如何，且长度<=20
            if (('版' in t or '审定' in t) and '年级' not in t and '册' not in t
                    and '切换' not in t and '如何' not in t and len(t) <= 20):
                if t not in seen:
                    seen.add(t)
                    versions.append(t)
        S_swipe(d, 540, 1850, 540, 650, 0.45); time.sleep(0.7)
    if not _is_home(d):
        _back_home(d)
    return versions


def switch_grade(d, target_grade):
    """切换年级（如'五年级上册'）

    流程：主页点顶部「版本+年级」栏 → 「切换课本」页 → 下滑逐屏找
          目标年级文字（如"五年级上册"）→ 点击 → 自动回主页
    """
    if not _is_home(d): _back_home(d)
    # 打开年级选择器：进入「切换课本」页（版本/年级同页，向下滑显示全）
    if not _enter_switchbook(d):
        print("    ✘ 无法打开年级选择器（切年级失败）")
        return False

    # 下滑逐屏找目标年级文字（可见区域才点）
    # ★ 改为子串匹配（兼容「一年级上册」可能带前后空格/版本后缀），并放宽到 8 屏，
    #   起点从网格下方空白区(1900)起滑，避免起点落在年级格子上被系统识别为点击→误切年级
    for _ in range(8):
        xml = d.dump_hierarchy()
        for m in _re.finditer(
            r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml
        ):
            txt = _norm(m.group(1))
            if _norm(target_grade) in txt and _re.search(r'[一二三四五六七八九]年级[上下]册', txt):
                x1, y1, x2, y2 = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                if 200 < y1 < 2100:  # 可见区域
                    d.click((x1 + x2) // 2, (y1 + y2) // 2)
                    time.sleep(2.5)
                    return True
        S_swipe(d, 540, 1900, 540, 700, 0.4); time.sleep(0.6)
    return False


def check_current(d, version, grade):
    """快速判断当前是否已是目标版本+年级（是则返回 True，无需切换）

    主页顶部栏节点 resource-id=switch_textbook_tv，text 形如
    「湘少版（2024审定）   五年级上册」
    ★ 版本/年级均用归一化【精确】匹配，避免"湘少版"误判为"湘少版（2024审定）"
    """
    if not _is_home(d):
        return False
    cur_ver, cur_gra = _current_texts(d)
    if not cur_ver:
        return False
    return _norm(cur_ver) == _norm(version) and _norm(cur_gra) == _norm(grade)


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
    """只检查当前版本是否匹配目标版本（归一化精确匹配，区分'湘少版'与'湘少版（2024审定）'）"""
    cur_ver, _ = _current_texts(d)
    if not cur_ver:
        return False
    return _norm(cur_ver) == _norm(version)


def check_grade_ok(d, grade):
    """只检查当前年级是否匹配目标年级（归一化精确匹配）"""
    _, cur_gra = _current_texts(d)
    return bool(cur_gra and _norm(cur_gra) == _norm(grade))


def _pick_version_grade(d, version, grade):
    """在'切换课本'页内，找到目标版本分组中的目标年级封面并点击。
    该页按教材系列垂直分组（如'湘少版（2024审定） 小学'、'湘少版 小学'），
    每个分组下面是该系列的年级封面网格。直接点击目标分组里的目标年级封面，
    即可同时完成版本+年级切换。

    ★ 采用顺序扫描法：从上往下滑动时，每看到一个版本标题就把它设为"当前版本"，
      之后出现的年级节点都归属该版本，直到遇到下一个版本标题。这样即使目标
      年级滚动到其版本标题已不可见的位置（如 2024审定版的六年级在普通湘少版
      标题上方），仍能正确归属并点击。
    """
    target_vn = _norm(version)
    target_gn = _norm(grade)
    current_vn = None
    version_seen = False  # ★ 目标版本标题是否在整页扫描中出现过（区分"版本不存在"vs"年级不存在"）
    # 先回到页面顶部（版本分组从上方开始）
    for _ in range(3):
        S_swipe(d, 540, 650, 540, 1850, 0.3); time.sleep(0.4)
    for _scan in range(12):
        try:
            elems = d.xpath('//*[@text!=""]').all()
        except Exception:
            elems = []
        nodes = []  # 按 y 排序扫描：版本标题与年级节点混在一起
        for e in elems:
            t = (e.text or "").strip()
            if not t:
                continue
            tn = _norm(t)
            try:
                b = e.bounds
            except Exception:
                continue
            if not b:
                continue
            # 版本标题：含'版'/'审定'，不含年级/册/切换/如何
            if (('版' in t or '审定' in t) and '年级' not in t and '册' not in t
                    and '切换' not in t and '如何' not in t and len(t) <= 20):
                nodes.append((b[3], 'ver', t, tn, None, b))
            # 年级封面：含'年级'且含'册'
            if '年级' in t and '册' in t:
                nodes.append((b[1], 'grade', t, tn, e, b))
        # 按 y 坐标排序后顺序处理：遇到版本标题更新 current_vn，遇到年级判断归属
        nodes.sort(key=lambda x: x[0])
        for y, typ, t, tn, elem, b in nodes:
            if typ == 'ver':
                current_vn = tn
                if tn == target_vn:
                    version_seen = True
            elif typ == 'grade':
                if current_vn == target_vn and tn == target_gn:
                    try:
                        elem.click()
                        print(f"    → 选中 {version} {grade}")
                    except Exception:
                        d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
                        print(f"    → 选中 {version} {grade}（坐标兜底）")
                    return True
        # 本屏未命中 → 下滑继续（current_vn 跨屏保留）
        S_swipe(d, 540, 1850, 540, 650, 0.45); time.sleep(0.7)
    # ★ 区分失败原因：目标版本标题从未出现 → 版本不存在；否则是年级不存在/未找到
    if not version_seen:
        print(f"    ✘ 版本不存在: {version}")
        return "VERSION_NOT_FOUND"
    print(f"    ✘ 在切换课本页未找到 {version} {grade}")
    return "GRADE_NOT_FOUND"


def switch_version_grade(d, version, grade, skip_if_ok=True):
    """切到目标版本+年级。
    ★ 正确路径（用户确认+截图证实）：主页点顶部栏进入「切换课本」长滚动页 →
      该页按教材系列垂直分组，每个分组下方是该版本的年级封面网格 →
      直接点击目标版本分组里的目标年级封面，同时完成版本+年级切换。
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
    ver_ok = bool(cur_ver and _norm(cur_ver) == _norm(version))
    gra_ok = bool(cur_gra and _norm(cur_gra) == _norm(grade))
    if ver_ok and gra_ok:
        print(f"    ✔ 已是 {version} {grade}，无需切换")
        return True

    # 3. 进入切换课本页，直接点目标版本+年级组合
    print(f"    → 进入切换课本页选择: {version} {grade}")
    if not _enter_switchbook(d):
        print("    ✘ 无法进入切换课本页")
        return False
    res = _pick_version_grade(d, version, grade)
    if res is not True:
        # res 可能是 'VERSION_NOT_FOUND' / 'GRADE_NOT_FOUND' / False，原样透传给调用方
        return res
    time.sleep(2)

    # 4. 最终确认（点年级封面后 App 会自动回主页）
    if not _is_home(d):
        _back_home(d); time.sleep(1.2)
    cur_ver, cur_gra = _current_texts(d)
    ver_ok = bool(cur_ver and _norm(cur_ver) == _norm(version))
    gra_ok = bool(cur_gra and _norm(cur_gra) == _norm(grade))
    print(f"    最终: {'✔' if ver_ok and gra_ok else '✘'} {cur_ver} {cur_gra}")
    return ver_ok and gra_ok
