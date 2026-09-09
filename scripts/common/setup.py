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


# ★ 2026-09-08：切课本页里的版本分组标题是 "X版 学段" 格式（如 "湘鲁版 小学"），
#   归一化后 tn = "湘鲁版小学"，与用户传入的 target_n="湘鲁版" 精确不命中。
#   学段后缀仅允许 小学/初中/高中/中学/空，不允许"审定/PEP"等修饰词
#   ——这样既兼容 X版 → X版小学（不区分审定），又保留 X版 ≠ X版(PEP) 的精确区分。
_SCHOOL_LEVELS = ("", "小学", "初中", "高中", "中学", "中")


def _ver_base(s):
    """抽取版本『基础名』：剥掉学段后缀(小学/初中/高中/中学)与审定噪声(2024审定/审定)，
    并去掉由此产生的空括号；保留 PEP（用于区分 人教版 ≠ 人教版(PEP)）。
    例：'湘鲁版（2024审定）小学' → '湘鲁版'；'人教版(PEP)小学' → '人教版(PEP)'。"""
    s = s or ""
    for suf in ("小学", "初中", "高中", "中学", "中"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = s.replace("2024审定", "").replace("审定", "")
    # 去掉因去掉审定而产生的空括号，如 "湘鲁版（）" → "湘鲁版"
    s = _re.sub(r'[（(][）)]', '', s)
    return s


def _ver_is_preferred(tn, target_n):
    """该版本标题是否『优先匹配』：去噪基础名相等，且其 审定/PEP 噪声与目标一致。

    用途：版本/年级归属时优先选与目标噪声一致的那一版，而不是误选另一版。
      - 目标"湘鲁版"(无审定)  → 优先"湘鲁版 小学"(无审定)，不优先"湘鲁版（2024审定）小学"
      - 目标"湘鲁版（2024审定）" → 优先"湘鲁版（2024审定）小学"(有审定)
      - 目标"人教版" → 不优先"人教版(PEP)小学"（PEP 边界保留）
    """
    if not tn or not target_n:
        return False
    tn = _norm(tn); target_n = _norm(target_n)
    if ('PEP' in tn) != ('PEP' in target_n):
        return False
    if ('审定' in tn) != ('审定' in target_n):
        return False
    return _ver_base(tn) == _ver_base(target_n)


def _ver_title_match(tn, target_n):
    """版本分组标题归一化匹配（★ 宽松前缀版，恢复『输入湘鲁版即可自动点中』的行为）。

    规则（target_n 为用户/前端传入版本名，如 '湘鲁版' / '人教版(PEP)'）：
      1) 完全相等：tn == target_n → 命中
      2) 仅接学段/审定噪声：去噪后基础名相等 → 命中
         （'湘鲁版' 命中 '湘鲁版 小学' / '湘鲁版（2024审定）小学' / '湘鲁版（2024审定）'）
      3) PEP 边界：target 含 PEP 而 tn 不含（或反之）→ 不命中
         （保留 '人教版' ≠ '人教版(PEP)' 的精确区分）
      4) 前缀兜底：去噪后基础名互为前缀 → 命中
    """
    if not target_n or not tn:
        return False
    tn = _norm(tn); target_n = _norm(target_n)
    # ★ PEP 边界：跨 PEP 不互认（这是唯一严格保留的区分）
    if ('PEP' in tn) != ('PEP' in target_n):
        return False
    if _ver_base(tn) == _ver_base(target_n):
        return True
    bn, bt = _ver_base(tn), _ver_base(target_n)
    if bn.startswith(bt) or bt.startswith(bn):
        return True
    return False



def _strip_school_level(t):
    """从 'X版 学段' 文本中剥掉学段后缀，返回纯版本名（如 '湘鲁版 小学' → '湘鲁版'）。"""
    t = (t or "").strip()
    for suf in _SCHOOL_LEVELS:
        if not suf:
            continue
        if t.endswith(suf):
            return t[: -len(suf)].strip()
    return t


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


def ensure_app_ready(d, package="com.dinoenglish.yyb", timeout=10):
    """★ 确保手机「亮屏解锁 + 英语宝在前台主页」。

    背景（2026-09-08 真机）：web_server 的 /api/version-grades/current 连上设备后
    直接 dump 当前页面找 switch_textbook_tv，若手机停在桌面/AOD/其他 App
    → 什么也读不到 → 前端一直显示「年级 读取中…」。
    本函数把「亮屏 + 解锁 + 拉起 App + 等主页 + 关开屏弹窗」串起来。

    返回 True/False（False 时上层应回退缓存，不要静默失败）
    """
    if not _ensure_screen_ready(d):
        return False
    # 1) 已在英语宝主页？
    for _ in range(3):
        try:
            xml = d.dump_hierarchy() or ""
        except Exception:
            xml = ""
        if "switch_textbook_tv" in xml:
            return True
        if package in xml:
            break
        time.sleep(0.6)
    # 2) 拉起 App
    try:
        print(f"    → 英语宝未在前台，启动 {package}")
        d.app_start(package)
    except Exception as e:
        print(f"    ⚠ app_start 失败: {e}")
        try:
            d.shell(["monkey", "-p", package,
                     "-c", "android.intent.category.LAUNCHER", "1"])
        except Exception:
            pass
    # 3) 等主页出现（switch_textbook_tv = 主页顶部「版本+年级」栏）
    for _ in range(timeout * 2):
        time.sleep(0.5)
        try:
            xml = d.dump_hierarchy() or ""
        except Exception:
            xml = ""
        if "switch_textbook_tv" in xml:
            print("    ✓ 已进入英语宝主页")
            return True
        # 开屏广告/权限弹窗 → 顺手关掉
        for _txt in ("同意", "允许", "跳过", "关闭", "我知道了", "好的"):
            try:
                if d(text=_txt).exists(timeout=0.3):
                    d(text=_txt).click()
                    print(f"    → 关闭弹窗: {_txt}")
                    time.sleep(0.6)
                    break
            except Exception:
                pass
    print("    ❌ 未能进入英语宝主页（请确认已安装、已登录，且未在锁屏）")
    return False


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
    plain_pick = None   # ★ 纯版本（无审定/PEP 噪声）优先
    any_pick = None     # 兜底：任意匹配版本
    # 版本选项分布在页面上部，先上滑回顶再向下逐屏扫描
    for _ in range(3):
        S_swipe(d, 540, 650, 540, 1850, 0.3); time.sleep(0.4)
    for _scan in range(10):
        for e in d.xpath('//*[@text!=""]').all():
            t = (e.text or "").strip()
            tn = _norm(t)
            # ★ 版本分组标题是 "X版 学段"（如 "湘鲁版 小学"）：用 _ver_title_match 宽松前缀匹配；
            #   同时保留 人教版 ≠ 人教版(PEP) 的区分（PEP 边界）。
            if (('版' in t or '审定' in t) and '年级' not in t and '册' not in t
                    and '切换' not in t and '如何' not in t and len(t) <= 20
                    and _ver_title_match(tn, target_n)):
                if _ver_is_preferred(tn, target_n) and plain_pick is None:
                    plain_pick = (t, e)
                elif any_pick is None:
                    any_pick = (t, e)
        # 找到纯版本即可停止扫描（纯版本优先于审定版）
        if plain_pick:
            break
        S_swipe(d, 540, 1850, 540, 650, 0.45); time.sleep(0.7)  # 下滑继续找
    target_e = plain_pick or any_pick
    if target_e:
        t, e = target_e
        try:
            e.click()
        except Exception:
            try:
                b = e.bounds
                d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
            except Exception:
                pass
        print(f"    → 选中版本: {t}")
        picked = True
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
            # ★ 2026-09-08：版本分组标题是 "X版 学段"（如 "湘鲁版 小学"），
            #   剥掉学段后缀，只留版本名（"湘鲁版"）— 与 versions_grades.json / 前端一致。
            short = _strip_school_level(t)
            if short and short not in seen:
                seen.add(short)
                versions.append(short)
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
    ★ 版本/年级均用精确匹配（_ver_is_preferred）：基础名 + 审定/PEP 噪声都一致才算，
      保证"湘鲁版"与"湘鲁版（2024审定）"是两个独立版本，互不串台。
    """
    if not _is_home(d):
        return False
    cur_ver, cur_gra = _current_texts(d)
    if not cur_ver:
        return False
    ver_ok = bool(cur_ver and _ver_is_preferred(cur_ver, version))
    gra_ok = bool(cur_gra and _norm(cur_gra) == _norm(grade))
    return ver_ok and gra_ok


# ═══════════ 教材分册扫描（新旧分开）═══════════
# ★ 2026-09-08 按用户指定规格实现：
#   ① 进入课本切换页面
#   ② 循环：读取当前页面所有文本控件 → 提取年级分册 → 滑动上翻
#   ③ 判断：滑动前后没有新增课本条目 → 停止滚动
#   ④ 对 book_list 做去重
#   ⑤ 输出 json
#   ⑥ 湘鲁旧版校验：预期 8 套分册，数量不对添加 warning
#
#   重要限制：
#     ❌ 不用多张截图 OCR   ❌ 不读取出版社   ❌ 不图像识别封面
#     ✅ 全部读取 APP 控件文本，滚动遍历列表，只解析文字
#
#   ★ 新旧分开：页面上方是【新教材】区（2024审定），下方是湘鲁版旧教材。
#     归属规则：按 y 坐标顺序扫描，遇到「版本分组标题」（如"湘鲁版 小学"）
#     之前的年级条目 → new_books；之后的 → old_books。两套分开不混。

# 年级分册（如"三年级上册"/"六年级下册"）
_GRADE_RE = _re.compile(r'([一二三四五六七八九]年级\s*(?:上|下)\s*册)')
# 版本分组标题噪音词（说明文字/提示语，不是真正的版本标题）
_VER_NOISE = ("如何", "切换", "教材发行", "：", "|", "｜", "新教材：", "开始新使用")


def _is_ver_title(t):
    """是否版本分组标题（如"湘鲁版 小学"）。排除说明文字（含：/|/教材发行等）。"""
    t = (t or "").strip()
    if not t:
        return False
    if any(n in t for n in _VER_NOISE):
        return False
    if '年级' in t or '册' in t:
        return False
    if not ('版' in t or '审定' in t):
        return False
    return len(t) <= 20


def scan_textbook_list(d, max_rounds=15, expect_old=8):
    """扫描「切换课本」页的教材分册列表（新旧两套分开）。

    返回 dict（可直接 json.dumps）:
      {
        "ok": True/False,
        "new_books":  [{"grade": "六年级上册", "y": 820}, ...],   # 新教材区（页面上方）
        "old_books":  [{"grade": "三年级上册", "y": 1250}, ...],  # 湘鲁旧教材（版本标题下方）
        "new_count": N,
        "old_count": M,
        "version_titles": ["湘鲁版 小学", ...],   # 扫描到的版本分组标题（调试用）
        "rounds": K,                             # 实际滚动轮数
        "warnings": [...],
      }
    """
    result = {
        "ok": False,
        "new_books": [],
        "old_books": [],
        "new_count": 0,
        "old_count": 0,
        "version_titles": [],
        "rounds": 0,
        "warnings": [],
    }

    # ① 进入课本切换页面
    if not ensure_app_ready(d):
        result["warnings"].append("无法进入英语宝主页（屏幕未解锁 / App 未启动）")
        return result
    if not _enter_switchbook(d):
        result["warnings"].append("无法进入「切换课本」页")
        return result
    time.sleep(0.8)
    # 回到页面顶部（版本分组从上方开始）
    for _ in range(3):
        S_swipe(d, 540, 650, 540, 1850, 0.3); time.sleep(0.4)

    seen_new, seen_old = set(), set()
    prev_total = -1

    # ② 循环：读控件文本 → 提取分册 → 滑动上翻
    for _round in range(max_rounds):
        result["rounds"] = _round + 1
        try:
            xml = d.dump_hierarchy() or ""
        except Exception:
            break

        # 收集本屏节点（带 y 坐标），按 y 升序归属新旧
        nodes = []
        for m in _re.finditer(
                r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
            t = (m.group(1) or "").strip()
            if not t:
                continue
            y = int(m.group(3))
            if _is_ver_title(t):
                nodes.append((y, 'ver', t))
            else:
                gm = _GRADE_RE.search(t)
                if gm:
                    nodes.append((y, 'grade', gm.group(1).replace(" ", "")))

        # ★ 归属：版本标题之前的年级 → new_books；之后的 → old_books
        nodes.sort(key=lambda x: x[0])
        in_old = False
        for y, kind, t in nodes:
            if kind == 'ver':
                in_old = True
                if t not in result["version_titles"]:
                    result["version_titles"].append(t)
                continue
            # kind == 'grade'
            if in_old:
                if t not in seen_old:
                    seen_old.add(t)
                    result["old_books"].append({"grade": t, "y": y})
            else:
                if t not in seen_new:
                    seen_new.add(t)
                    result["new_books"].append({"grade": t, "y": y})

        # ③ 终止：本轮滑动后没有新增条目 → 已到底
        total = len(seen_new) + len(seen_old)
        if total == prev_total:
            break
        prev_total = total

        # 滑动上翻（从网格下方空白区起滑，避免起点落在卡片上被识别为点击）
        try:
            S_swipe(d, 540, 1900, 540, 500, 0.5)
            time.sleep(0.7)
        except Exception:
            break

    # ④ 去重（seen set 已保证唯一）→ 按 y 排序输出
    result["new_books"].sort(key=lambda x: x["y"])
    result["old_books"].sort(key=lambda x: x["y"])
    result["new_count"] = len(result["new_books"])
    result["old_count"] = len(result["old_books"])

    # ⑥ 湘鲁旧版校验：预期 8 套分册
    if result["old_count"] != expect_old:
        got = [b["grade"] for b in result["old_books"]]
        result["warnings"].append(
            f"湘鲁旧版分册数量异常：预期 {expect_old} 套，实际采集 {result['old_count']} 套 → {got}"
        )
    if not result["new_books"] and not result["old_books"]:
        result["warnings"].append("未采集到任何分册条目（页面可能未正确加载）")

    # 回主页（不选中任何年级 → back = 取消）
    try:
        d.press('back'); time.sleep(0.8)
    except Exception:
        pass

    result["ok"] = bool(result["new_books"] or result["old_books"])
    return result


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
    """只检查当前版本是否匹配目标版本（精确匹配：基础名 + 审定/PEP 噪声一致）"""
    cur_ver, _ = _current_texts(d)
    if not cur_ver:
        return False
    return _ver_is_preferred(cur_ver, version)


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
    version_seen = False  # ★ 目标版本系列是否在整页扫描中出现过（区分"版本不存在"vs"年级不存在"）
    # ★ 精确匹配：只有『版本名 + 审定/PEP 噪声』都一致时才点。
    #   这样手机里"湘鲁版"与"湘鲁版（2024审定）"是两个独立版本，各点各的，绝不串。
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
                # ★ 宽松系列匹配仅用于"版本系列是否存在"的判断（version_seen）
                current_vn = tn
                if _ver_title_match(tn, target_vn):
                    version_seen = True
            elif typ == 'grade':
                # ★ 精确点选：年级必须落在『精确等于目标版本』的分组里。
                #   _ver_is_preferred 要求基础名相等 + 审定/PEP 噪声一致，
                #   故输入"湘鲁版"只点"湘鲁版"分组，输入"湘鲁版（2024审定）"只点审定版分组。
                if _ver_is_preferred(current_vn or "", target_vn) and tn == target_gn:
                    try:
                        elem.click()
                        print(f"    → 选中 {version} {grade}")
                    except Exception:
                        d.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
                        print(f"    → 选中 {version} {grade}（坐标兜底）")
                    return True
        # 本屏未命中 → 下滑继续（current_vn 跨屏保留）
        S_swipe(d, 540, 1850, 540, 650, 0.45); time.sleep(0.7)
    # ★ 区分失败原因
    if not version_seen:
        print(f"    ✘ 版本不存在: {version}（APP 内未找到该版本系列，请核对版本名）")
        return "VERSION_NOT_FOUND"
    # 系列存在但无精确匹配——多半是输入的版本名与 APP 内不一致（如输入"湘鲁版"但只有审定版有该年级）
    print(f"    ✘ 在切换课本页找到『{version}』系列，但未精确匹配到 {grade}（请确认 APP 内版本/年级名称是否一致）")
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
    ver_ok = bool(cur_ver and _ver_is_preferred(cur_ver, version))
    gra_ok = bool(cur_gra and _norm(cur_gra) == _norm(grade))
    if ver_ok and gra_ok:
        print(f"    ✔ 已是 {version} {grade}（当前 {cur_ver} {cur_gra}），无需切换")
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
    # ★ 精确确认：当前版本必须『基础名 + 审定/PEP 噪声』都一致才算切换成功，
    #   保证"湘鲁版"≠"湘鲁版（2024审定）"，互不串台。
    if not _is_home(d):
        _back_home(d); time.sleep(1.2)
    cur_ver, cur_gra = _current_texts(d)
    ver_ok = bool(cur_ver and _ver_is_preferred(cur_ver, version))
    gra_ok = bool(cur_gra and _norm(cur_gra) == _norm(grade))
    print(f"    最终: {'✔' if ver_ok and gra_ok else '✘'} {cur_ver} {cur_gra}")
    return ver_ok and gra_ok
