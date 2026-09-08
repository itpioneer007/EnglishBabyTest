"""共享工具函数：广告关闭、弹窗处理、年级切换、滚动查找、通用动作执行"""
import time
from config import GLOBAL_POPUPS

# 基准分辨率（当前手机实测 1080x2400）
BASE_W, BASE_H = 1080, 2400


def S(d, x, y):
    """将基于 1080x2400 的坐标换算到当前屏幕分辨率（动态比例）
    用法：d.click(*S(d, 986, 1823))
    """
    try:
        w, h = d.window_size()
    except Exception:
        w, h = BASE_W, BASE_H
    return (int(x * w / BASE_W), int(y * h / BASE_H))


def S_h(d, y):
    """仅换算 y 坐标（用于范围判断）"""
    try:
        _, h = d.window_size()
    except Exception:
        h = BASE_H
    return int(y * h / BASE_H)


def S_w(d, x):
    """仅换算 x 坐标"""
    try:
        w, _ = d.window_size()
    except Exception:
        w = BASE_W
    return int(x * w / BASE_W)


def S_swipe(d, x1, y1, x2, y2, duration=0.4):
    """按比例换算的滑动"""
    return d.swipe(*S(d, x1, y1), *S(d, x2, y2), duration)


_AD_TEXT_KEYWORDS = (
    "老师伴学", "打卡服务", "点击参与", "广告", "推广", "跳过",
    "专属老师服务", "正在链接", "专属", "老师服务",
    "E英语宝伴学服务", "伴学服务",
)


def _has_ad_text(xml: str) -> bool:
    """XML 中是否仍包含广告弹窗文字特征"""
    return bool(xml) and any(kw in xml for kw in _AD_TEXT_KEYWORDS)


def close_ad(d):
    """关闭广告：多种策略按顺序尝试
    ★ 广告结构（实测）：右下角 fl_ad_container 广告卡片，关闭按钮 resource-id=iv_close（72x72）
      "老师伴学/打卡服务"是广告卡片标题（有时只显示"伴学"），底部导航的"伴学/会员"不是广告！
      关闭优先级：resource-id 精确定位 > description=关闭 > 广告文字 > 小尺寸X > 卡片右上角兜底"""
    try:
        xml = d.dump_hierarchy()
    except Exception:
        xml = ""

    # 广告特征：弹窗广告文字 / 关闭按钮资源 / 广告角标
    # ★ 新增"专属老师服务"等老师伴学类弹窗关键词（该弹窗含二维码，点到即跳微信）
    has_ad_text = _has_ad_text(xml)
    has_close_btn = ('content-desc="关闭' in xml or 'text="关闭"' in xml)
    # ★ 实测：右下角广告卡片 fl_ad_container + 关闭按钮 iv_close（坐标 986,1823）
    # ★ 加固（用户反馈：担心广告关闭位置点错）：必须命中【可见】节点（visible-to-user="true"）
    #   才算真广告，防止页面里隐藏/残留的广告容器 id 误触发坐标点击。
    #   若解析到可见 iv_close 节点，优先用其真实 bounds 中心点击（更稳，不再依赖固定坐标）。
    # ★ 同时记录广告卡片整体 bounds，找不到 iv_close 时点击卡片右上角区域，避免全局固定坐标
    #   落到二维码/广告主体上导致跳微信。
    has_ad_card = False
    _close_xy = None
    _card_bounds = None
    try:
        import re as _re3
        for _m3 in _re3.finditer(r'<node[^>]*>', xml):
            _t3 = _m3.group(0)
            if any(_k in _t3 for _k in ('fl_ad_container', 'iv_ad', 'iv_close')):
                if 'visible-to-user="true"' in _t3:
                    has_ad_card = True
                    _bm3 = _re3.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _t3)
                    if _bm3:
                        _x1, _y1, _x2, _y2 = map(int, _bm3.groups())
                        if 'iv_close' in _t3 or 'iv_ad' in _t3:
                            _close_xy = ((_x1 + _x2) // 2, (_y1 + _y2) // 2)
                        elif 'fl_ad_container' in _t3:
                            _card_bounds = (_x1, _y1, _x2, _y2)
                    break
    except Exception:
        has_ad_card = ('fl_ad_container' in xml or 'iv_ad' in xml or 'iv_close' in xml)  # 解析失败保守处理

    # 方式0（★ 最可靠）：检测到广告卡片 → 点关闭按钮（优先节点真实坐标，其次卡片右上角）
    if has_ad_card:
        try:
            if _close_xy:
                d.click(*S(d, *_close_xy))
                print(f"    🔔 通过广告卡片关闭按钮真实坐标 {_close_xy} 关闭广告")
            elif _card_bounds:
                # 关闭按钮一般在卡片右上角，取卡片右边缘往左约 80px、下约 80px 的安全区
                _cx = max(_card_bounds[0] + 80, _card_bounds[2] - 80)
                _cy = _card_bounds[1] + 80
                d.click(*S(d, _cx, _cy))
                print(f"    🔔 通过广告卡片右上角区域 ({_cx},{_cy}) 关闭广告")
            else:
                # 仅有广告文字/id 但没解析到卡片 bounds 时，不再用固定全局坐标，避免误点广告主体
                print("    ⚠ 检测到广告卡片但无法定位关闭按钮，跳过盲目坐标点击")
                return False
            time.sleep(0.35)
            return True
        except Exception:
            pass

    # 方式0b：按 resource-id 找广告关闭按钮（兜底，部分机型 resourceId 匹配不上时走坐标）
    for close_rid in ("iv_close", "close_iv", "ad_close", "btn_close", "iv_ad_close",
                      "fl_close", "close_btn", "img_close", "ad_del"):
        if close_rid in xml:
            try:
                found = d(resourceId=f".*{close_rid}").exists(timeout=0.5)
                if found:
                    d(resourceId=f".*{close_rid}").click()
                    print(f"    🔔 通过 resource-id [{close_rid}] 关闭广告")
                    time.sleep(0.35)
                    return True
            except Exception:
                pass

    # 方式1：contentDescription 包含"关闭"（广告右上角 X）
    if has_close_btn:
        try:
            if d(description="关闭").exists(timeout=0.5):
                d(description="关闭").click()
                print("    🔔 通过 description='关闭' 关闭广告")
                time.sleep(0.35)
                return True
        except Exception:
            pass

    # 方式2：找广告文字（"老师伴学"/"打卡服务"/"跳过"），点其右上角的 X
    if has_ad_text:
        try:
            for kw in ("老师伴学", "打卡服务", "点击参与"):
                if kw in xml:
                    for elem in (d.xpath('//*[@text!=""]').all() or []):
                        if kw in (elem.text or ""):
                            b = elem.bounds
                            # 使用当前屏幕宽度，避免在 1224 等宽屏上被错误截断
                            _screen_w = d.window_size()[0]
                            close_x = min(b[2] - 10, _screen_w - 10)
                            close_y = b[3] + 15
                            d.click(close_x, close_y)
                            print(f"    🔔 通过 ad 文字 [{kw}] 定位 X 按钮 ({close_x},{close_y})")
                            time.sleep(0.35)
                            return True
        except Exception:
            pass
        # 有"跳过"按钮 → 直接点（开屏广告常用）
        if "跳过" in xml:
            try:
                if d(text="跳过").exists(timeout=0.5):
                    d(text="跳过").click()
                    print("    🔔 通过'跳过'关闭开屏广告")
                    time.sleep(0.35)
                    return True
            except Exception:
                pass

    # 方式3：找内嵌的小尺寸 clickable（X 通常很小、无文字）—— ★ 仅当检测到广告特征才尝试
    #   （避免误点主页正常图标：成长宠物区(950,1787)、右上角功能按钮等）
    if has_ad_text or has_close_btn:
        try:
            for elem in (d.xpath('//*[@clickable="true"]').all() or []):
                b = elem.bounds
                w = b[2] - b[0]
                h = b[3] - b[1]
                # X 按钮特征：尺寸小（< 90x90）、位于右侧、y>600（避开底部导航）
                if w < 90 and h < 90 and b[0] > 800 and b[1] > 600:
                    elem.click()
                    print(f"    🔔 通过小尺寸 clickable (X) 关闭广告 ({sum(b)//4},{h*1000})")
                    time.sleep(0.35)
                    return True
        except Exception:
            pass

    # 方式4/5：右上角 ImageView —— 仅当页面有广告特征文字时才尝试
    # （避免误点主页右上角的正常功能按钮，如二维码/扫码入口）
    # ★ 删除固定坐标 (986,1823) 兜底：该坐标在部分机型/弹窗上会落到广告主体/二维码，
    #   导致误点跳微信。广告卡片的右上角兜底已在方式0中通过 _card_bounds 处理。
    if has_ad_text:
        try:
            for elem in d(className="android.widget.ImageView"):
                info = elem.info
                if not info.get("clickable"):
                    continue
                b = info.get("bounds", {})
                if b.get("right", 0) > d.window_size()[0] * 0.7 and b.get("top", 0) < 200:
                    elem.click()
                    print("    🔔 通过右上角 ImageView 关闭广告（检测到广告特征）")
                    time.sleep(0.35)
                    return True
        except Exception:
            pass

    print("    ⚠ 未找到广告关闭按钮")
    return False

# ==================== ④ 通用动作执行器 ====================
def execute_actions(d, actions, label=""):
    """执行一组动作。动作类型:
    click:         点击文字  
    close_popup:   关闭弹窗（文字可以是 str 或 list）
    close_ad:      关闭广告（description / ImageView / 坐标）
    wait:          等待秒数
    scroll_and_click: 向上滑后点击
    """
    for i, action in enumerate(actions):
        at = action.get("type")
        timeout = action.get("timeout", 3)

        if at == "click":
            text = action["text"]
            if safe_click(d, text, timeout=timeout):
                print(f"    ✅ 点击 '{text}'")
            else:
                print(f"    ⚠ 未找到 '{text}'，跳过")

        elif at == "close_popup":
            texts = action["text"]
            if isinstance(texts, str):
                texts = [texts]
            for t in texts:
                try:
                    if d(text=t).exists(timeout=min(timeout, 2)):
                        d(text=t).click()
                        print(f"    🔔 关闭弹窗: '{t}'")
                        time.sleep(0.35)
                        break
                except Exception:
                    pass

        elif at == "wait":
            seconds = action.get("seconds", 1)
            time.sleep(seconds)

        elif at == "scroll_and_click":
            text = action["text"]
            for _ in range(5):
                if d(text=text).exists(timeout=1.5): break
                S_swipe(d, 500, 1400, 500, 400, 0.3)
                time.sleep(0.4)
            if safe_click(d, text, timeout=min(timeout, 3)):
                print(f"    ✅ 滑动后点击 '{text}'")
            else:
                print(f"    ⚠ 滑动后未找到 '{text}'")

        elif at == "close_ad":
            close_ad(d)

        elif at == "swipe_left":
            # 水平左滑切换子模块
            S_swipe(d, 900, 600, 200, 600, 0.3)
            time.sleep(0.6)
            print(f"    👈 左滑切换子模块")

        elif at == "swipe_left_sub":
            # 子模块区左滑：用 swipe_ext，在基础巩固文字稍上方
            d.swipe_ext("left", scale=0.5)
            time.sleep(0.6)
            print(f"    👈 swipe_ext 左滑")

# ==================== ⑤ 基础工具 ====================
def safe_click(d, text, timeout=3) -> bool:
    try:
        d(text=text).click(timeout=timeout)
        return True
    except Exception:
        return False

def wait_until(d, text, timeout=2.0, interval=0.15):
    """★ 轮询等页面出现指定文本（替代固定 sleep，快则立即返回）。

    用于"点击后等新界面刷新"场景：比固定 sleep 既快又稳——
    页面 0.3s 就绪则 0.3s 返回，慢到 2s 也最多等 2s，避免竞态点空。
    返回: True=已出现 / False=超时
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            xml = d.dump_hierarchy()
            if text in xml:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False

def wait_any(d, texts, timeout=2.0, interval=0.15):
    """★ 轮询等任一目标文本出现；返回命中的文本，超时返回空串。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            xml = d.dump_hierarchy()
            for t in texts:
                if t in xml:
                    return t
        except Exception:
            pass
        time.sleep(interval)
    return ""

def click_then_wait(d, click_text, expect_text, timeout=2.5, click_timeout=2):
    """★ 点击后等新界面刷新（消除"点击快于刷新"竞态）。

    场景: 点"下一题/检查/继续答题"后，新页面可能 0.3s~2s 才渲染完。
    固定 sleep(0.5) 对快页面浪费、对慢页面不够 → 用轮询。
    若 expect_text 未出现则回退固定等待兜底（防止误判）。
    返回: True=等待到目标元素 / False=超时
    """
    try:
        d(text=click_text).click(timeout=click_timeout)
    except Exception:
        return False
    ok = wait_until(d, expect_text, timeout=timeout)
    if not ok:
        time.sleep(0.4)  # 兜底：给慢加载一次额外机会
    return ok

# ★ 主页特征（英语宝主页判定，供模块间回退/保底使用）
HOME_XML_FEATURES = ('switch_textbook_tv', '教材精学', '专项突破',
                     '听课文', '全脑记词', '单词听写')
APP_PACKAGE = "com.dinoenglish.yyb"


def is_home_xml(xml: str) -> bool:
    """判定 XML 是否英语宝主页（特征见 HOME_XML_FEATURES）"""
    return bool(xml) and any(f in xml for f in HOME_XML_FEATURES)


def safe_back_to_home(d, max_backs=6, extra_hit=None):
    """★ 模块间安全回退到主页：back 循环但【检测到主页立即停】。

    解决用户实测"back 过多退到手机桌面"：
      - 模块内部/模块间的 back 循环只认目标特征（如"去答题"），特征变化时
        back 会一路退到桌面 → 这里统一加"主页特征命中即停"保底
      - 非 yyb 前台（退过头到桌面）→ 冷启动回主页
      - 每次 back 前检查主页；命中主页立即返回（不继续 back）
    Args:
        d: 设备
        max_backs: 最多 back 次数（默认6，超过说明回不到主页→冷启动）
        extra_hit: 额外停止条件 callable(xml)->bool（如"去答题"列表页特征）
    Returns:
        True=已回到主页/目标页；False=冷启动兜底
    """
    try:
        _cur = d.app_current()
        _is_yyb = (_cur or {}).get("package") == APP_PACKAGE
    except Exception:
        _is_yyb = False
    if not _is_yyb:
        # 退过头到桌面 → 冷启动
        try:
            d.press("home"); time.sleep(0.4)
            d.app_start(APP_PACKAGE); time.sleep(3)
        except Exception:
            pass
        return False
    for _ in range(max_backs):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        if is_home_xml(xml):
            return True
        if extra_hit and extra_hit(xml):
            return True
        try:
            d.press("back"); time.sleep(0.5)
        except Exception:
            break
    # 兜底：回不到主页 → 冷启动
    try:
        d.press("home"); time.sleep(0.4)
        d.app_start(APP_PACKAGE); time.sleep(3)
    except Exception:
        pass
    return False


def dismiss_global_popups(d):
    """关闭全局弹窗（★ 优化：一次 dump + 字符串匹配，避免逐词 UI 查询）"""
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return False
    # 找出页面上实际出现的弹窗词
    hit = None
    for t in GLOBAL_POPUPS:
        if f'text="{t}"' in xml or f'content-desc="{t}"' in xml:
            hit = t
            break
    if hit:
        try:
            d(text=hit).click(timeout=1)
            print(f"    🔔 全局弹窗: '{hit}'")
            time.sleep(0.35)
            return True
        except Exception:
            pass
    return False

def settle_ads(d, wait_total=10):
    """等待广告加载并关闭，直到连续 2 轮确认无广告（最多 wait_total 秒）。

    ★ 竞态根因（用户实测）：广告是延迟加载的（冷重启后 4-6s 甚至更晚才出现）。
      - 若在广告出现前就点击 → 点空；
      - 若在广告刚弹出的瞬间点击 → 误点广告 → 导航被带歪（找不到 tab/入口等怪异结果）。
      本函数在关键点击前调用：循环「检测→关闭→再检测」，直到连续 2 轮干净才返回，
      消除"点空/点广告"竞态。
    ★ 日志与动作对应：实际关闭了弹窗/广告才打日志（且限前3轮避免刷屏），
      没弹广告时静默快速通过，不再"只打一行关广告日志但动作在后面"。
    返回 True（尽力而为）。
    """
    clean = 0
    t0 = time.time()
    _round = 0
    while time.time() - t0 < wait_total:
        _round += 1
        closed = False
        try:
            if dismiss_global_popups(d):
                closed = True
        except Exception:
            pass
        try:
            if close_ad(d):
                closed = True
        except Exception:
            pass
        if closed:
            clean = 0
            if _round <= 3:
                try:
                    from common.logger import step_log
                    step_log(f"🧹 已关闭弹窗/广告（第{_round}轮）", "info")
                except Exception:
                    pass
            time.sleep(0.5)
        else:
            # ★ 安全加固：即使 close_ad/dismiss 没动作，若页面仍有广告文字，
            #   不视为"干净"，继续等待/重试，避免后续点击落在广告上导致跳微信。
            try:
                xml_now = d.dump_hierarchy()
            except Exception:
                xml_now = ""
            if _has_ad_text(xml_now):
                clean = 0
                time.sleep(0.5)
                continue
            clean += 1
            if clean >= 2:
                return True
            time.sleep(0.4)
    return True

def applock_blocked(d):
    """检测 OPPO 系统「应用锁」验证框（使用面部验证/密码验证，包 com.oplus.safecenter）。

    冷重启 App 后偶发弹出，把整个 App 盖住，入口点击会静默失败 → 产生"找不到测试 tab/
    找不到入口"等怪异结果。自动化无法绕过（需人脸/密码），命中时应明确报错提示用户解锁。
    返回 True = 被应用锁挡住。
    """
    try:
        xml = d.dump_hierarchy()
        if "safecenter" in xml or "面部验证" in xml or "密码验证" in xml:
            return True
    except Exception:
        pass
    return False

def scroll_and_find(d, text, max_swipes=8) -> bool:
    """查找文字：先直接找，然后向上滑（内容下移）找下方，再向下滑（内容上移）找上方
    ★ 支持精确/包含匹配，以及 description 属性（部分入口文字在 content-desc 里）"""
    def _found():
        if d(text=text).exists(timeout=1): return True
        if d(textContains=text).exists(timeout=1): return True
        if d(description=text).exists(timeout=1): return True
        if d(descriptionContains=text).exists(timeout=1): return True
        # 兜底：从 dump 里子串匹配可见节点
        try:
            xml = d.dump_hierarchy()
            return f'text="{text}"' in xml or f'content-desc="{text}"' in xml
        except Exception:
            return False
    if _found(): return True
    # 第一轮：向上滑（内容下移），找下方内容
    for i in range(max_swipes):
        S_swipe(d, 500, 1600, 500, 500, 0.4)
        time.sleep(0.5)
        if _found():
            print(f"    👇 向下滑动 {i+1} 次后找到「{text}」")
            return True
    # 第二轮：向下滑（内容上移，返回顶部区域），找上方内容
    for i in range(max_swipes):
        S_swipe(d, 500, 500, 500, 1600, 0.4)
        time.sleep(0.5)
        if _found():
            print(f"    👆 向上滑动 {i+1} 次后找到「{text}」")
            return True
    print(f"    ❌ 滚动查找「{text}」失败（已滑 {max_swipes*2} 次）")
    return False

# ==================== ⑥ 年级切换 ====================
def ensure_grade(d, grade_level, book_version=""):
    """
    确保当前年级匹配。不匹配则自动切换。
    ★ 统一委托 common.setup.switch_version_grade（走主页顶部版本+年级栏切换，
      用户确认：年级切换必须在英语主页顶部栏，不能在"我的"里切）
    """
    try:
        from common.setup import switch_version_grade
    except Exception:
        switch_version_grade = None
    if switch_version_grade:
        return switch_version_grade(d, book_version or "湘少版", grade_level, skip_if_ok=True)
    # 兜底（无 setup 时）：判断主页版本文字
    if d(textContains=grade_level).exists(timeout=3):
        return True
    return False

def back_to_home(d, grade_level=""):
    """从模块内部回到年级主页：按 back 直到看到年级文字或主页特征"""
    home_keywords = ["我的练习", "专项突破", "教材精学", "学习计划", "成长记录"]
    for _ in range(10):
        dismiss_global_popups(d)
        if grade_level and d(textContains=grade_level).exists(timeout=1):
            return True
        for kw in home_keywords:
            if d(textContains=kw).exists(timeout=1):
                return True
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _is_miniprogram_auth(xml: str) -> bool:
    """判断是否误点主页悬浮广告后跳到了微信小程序授权页"""
    if not xml:
        return False
    return any(k in xml for k in ("E英语宝伴学服务", "申请", "你的昵称、头像", "微信昵称头像"))


def enter_module_by_entry(d, entry, max_tries=5):
    """★ 稳健进入模块：滚动找入口 → 点前清广告 → 若入口落在右下角悬浮广告区则上滑错开 → 点击 → 校验是否进入

    返回 True/False（是否成功进入模块页）。

    ★ 统一给「练习(run_module)」与「测试(run_test_module)」复用，避免测试路径直接 click 误触广告
       （用户实测：仅选测试时手机点到广告、并未进入 听力专项）。

    ★ 点击策略：优先点击「可点击的入口元素」(d(text=entry, clickable=True))，由 uiautomator 点击真实
       UI 元素（必要时自动滚入视野），避免旧逻辑「按 bounds 中心算坐标后 d.click」在入口是非可点击标题、
       或入口在屏幕外时点到错位的节点导致「点了却没进模块」。
    """
    try:
        from common.logger import step_log
    except Exception:
        def step_log(msg, level="info"):
            print(msg)

    def _entered():
        try:
            _xml = d.dump_hierarchy()
        except Exception:
            _xml = ""
        return any(k in _xml for k in ("去练习", "去答题", "练习记录", "重新答题", "开始答题", "测试"))

    def _miniprog(xml):
        return any(k in (xml or "") for k in ("E英语宝伴学服务", "申请", "你的昵称、头像", "微信昵称头像"))

    def _el():
        # 优先可点击的入口卡片；否则退而求其次用 text / textContains
        try:
            if d(text=entry, clickable=True).exists(timeout=0.5):
                return d(text=entry, clickable=True)
        except Exception:
            pass
        try:
            if d(text=entry).exists(timeout=0.5):
                return d(text=entry)
        except Exception:
            pass
        try:
            if d(textContains=entry).exists(timeout=0.5):
                return d(textContains=entry)
        except Exception:
            pass
        return None

    def _center(el):
        try:
            b = el.bounds()  # ★ uiautomator2: bounds() 是方法，返回 (l,t,r,b) 元组
            return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
        except Exception:
            return None

    def _in_ad(cx, cy):
        _w, _h = d.window_size()
        return cx > _w * 0.6 and cy > _h * 0.6

    step_log(f"[入口] 查找并点击「{entry}」...", "info")
    if not scroll_and_find(d, entry):
        step_log(f"❌ 未找到模块入口: {entry}", "error")
        return False
    settle_ads(d, wait_total=8)

    for _ in range(max_tries):
        el = _el()
        if not el:
            if not scroll_and_find(d, entry):
                step_log(f"❌ 未找到模块入口: {entry}", "error")
                return False
            continue
        c = _center(el)
        if not c:
            continue
        cx, cy = c
        if _in_ad(cx, cy):
            step_log(f"⚠ 入口「{entry}」中心({cx},{cy})落在屏幕右下角广告区 → 上滑错开", "warning")
            _h = d.window_size()[1]
            d.swipe(cx, int(_h * 0.78), cx, int(_h * 0.35), 0.4)
            time.sleep(1.3)
            continue
        try:
            el.click()  # uiautomator 点击真实元素（必要时自动滚入视野）
        except Exception:
            d.click(cx, cy)
        step_log(f"✅ 点击入口 {entry} @({cx},{cy})", "info")
        time.sleep(1.6)
        if _entered():
            return True
        _xml = ""
        try:
            _xml = d.dump_hierarchy() or ""
        except Exception:
            pass
        if _miniprog(_xml):
            step_log(f"⚠ 点击 {entry} 误触悬浮广告跳到小程序授权页，返回并重试", "warning")
            for _b in range(3):
                d.press("back"); time.sleep(0.7)
        else:
            step_log(f"⚠ 点击 {entry} 后未进入模块（坐标 {cx},{cy}），上滑重试", "warning")
        _h = d.window_size()[1]
        d.swipe(cx, int(_h * 0.78), cx, int(_h * 0.35), 0.4)
        time.sleep(1.2)
    step_log(f"❌ 点击入口失败: {entry}（多次滑动错开仍未能进入；若仍被广告遮挡，请手动关闭右下角卡片后重试）", "error")
    return False

# ==================== ⑦ 核心：单模块检测 ====================


# ==================== ⑧ 智能单元定位（随机应变按名字找内容） ====================
def smart_find_unit_row(d, target, click_text="去答题", max_pages=8, prefer_restart=False):
    """智能定位目标单元/测试行并点击其按钮 —— 不写死标题，随机应变

    target: 单元引用
      - 数字(1) / 区间("1-3")：按 "Unit N" / "Unit N单元评价" 模式匹配
      - 关键词("期中"/"期末"/"AI检测"/"湘少三上期中评价")：先点筛选 tab（如有），
        再匹配标题包含关键词的行
    click_text: 目标行旁按钮文字（"去答题"/"去练习"）
    prefer_restart: ★ 为 True 时不接受"继续答题"（上次中途退出状态）——只匹配
      "去答题/重新答题"，保证从第 1 题重头测（避免漏测中途退出后的前段题目）
    返回: 是否点击成功
    """
    try:
        from common.logger import step_log
    except Exception:
        def step_log(msg, level="info"):
            print(msg)
    import re as _re
    s = str(target).strip()
    is_keyword = not _re.fullmatch(r"\d+(-\d+)?", s)

    # ① 关键词目标 → 若页面有筛选 tab（全部/单元/期中/期末…），先点匹配 tab
    if is_keyword:
        _clicked_tab = False
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        # tab 名：目标关键词本身或其变体（"期中评价"→"期中"，"期末评价"→"期末"）
        tab_names = [s]
        for _k in ("期中评价", "期末评价", "期中", "期末", "单元"):
            if _k in s:
                tab_names.append(_k)
        for _t in tab_names:
            try:
                if f'text="{_t}"' in xml:
                    d(text=_t).click()
                    time.sleep(1.2)
                    _clicked_tab = True
                    break
            except Exception:
                pass

    # ② 构造标题匹配函数
    def _match(t):
        t = (t or "").strip()
        if not t:
            return False
        if is_keyword:
            return s in t          # 标题包含关键词（如"AI检测 测试题目选题"）
        # 数字/区间：Unit N 或 Unit N单元评价（忽略"湘少X上"前缀）
        #   ★ 容错：Unit3(无空格) / "Unit 3·单元评价" / "Unit 3 单元评价" 都匹配
        #     —— 之前严格 `(?:\s*单元评价|\s|$)` 在"Unit3单元评价"(无空格)时
        #     可能漏匹配 → 误下滑（用户实测：目标在首屏却下滑找不到）
        if _re.search(rf"U\s*n\s*i\s*t\s*{_re.escape(s)}", t, _re.IGNORECASE):
            return True
        if _re.fullmatch(r"\d+", s):
            # U3 / U3单元 / U 3（单元自检新列表可能用 U3 简写）
            if _re.search(rf"U\s*{_re.escape(s)}(?:\s*单元评价|\s*·|\s|$)", t, _re.IGNORECASE):
                return True
        return False

    # ③ 逐屏查找：标题行 → 点同行 click_text 按钮
    #   ★ 修复（用户实测）：目标单元明明在首屏却下滑 → 找不到。
    #     根因：U3 中途退出显示"继续答题"，prefer_restart=True 不接受 →
    #     匹配不到 → 下滑 → U3 滚出屏幕 → 永远找不到。
    #     修复：首屏先"无下滑"完整找一遍（含降级接受"继续答题"），
    #           下滑只在确认首屏没有目标时才发生。
    _fallback_accept = False  # 是否已降级接受"继续答题"
    for _ in range(max_pages):
        try:
            elements = (d.xpath('//*[@text!=""]').all() or [])
        except Exception:
            elements = []
        row = None
        for e in elements:
            if _match(e.text):
                row = e
                break
        if row:
            row_top = row.bounds[1]
            row_bottom = row.bounds[3]
            row_center_y = (row_top + row_bottom) // 2
            # ★ prefer_restart：优先"去答题/重新答题"；首屏找不到时降级接受"继续答题"
            _accept = ("去答题", "重新答题") if (prefer_restart and not _fallback_accept) \
                else ("去答题", "重新答题", "继续答题")
            # ★ 同行判断：不再"第一个 y 差 < 500 就点"，因为上一行按钮可能落在 500 范围内
            #   （如 Unit2 标题在 y=1313，Unit1 的"去答题"在 y=945，差 368 < 500，会误点 Unit1）。
            #   改为：在所有候选按钮里选**垂直中心与标题中心最近**的一个，且距离 < 350。
            #   若找不到，再放宽到按钮与标题行有垂直重叠。
            candidates = []
            for e in elements:
                t = (e.text or "").strip()
                # ★ 按钮文字多状态匹配（用户确认）：
                #   - "去答题"：单元自检首次作答
                #   - "重新答题"：已答过一次（按钮文字变化）
                #   - "继续答题"：中途退出后恢复（此时需从当前题继续，见 _enter_unit）
                #   ★ 注意：不能匹配"已评测/全站平均分/分数"——那是分数展示块，不是按钮！
                _btn_hit = (t == click_text or t in _accept
                            or (click_text in _accept and t in _accept))
                if not _btn_hit:
                    continue
                btn_top = e.bounds[1]
                btn_bottom = e.bounds[3]
                btn_center_y = (btn_top + btn_bottom) // 2
                dy = abs(btn_center_y - row_center_y)
                # 候选 1：中心接近（< 350），基本保证同一行
                if dy < 350:
                    candidates.append((dy, e))
                    continue
                # 候选 2：按钮与标题行有垂直重叠（兜底，适配行高很大的布局）
                if btn_top < row_bottom and btn_bottom > row_top:
                    candidates.append((dy, e))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                best = candidates[0][1]
                bx = (best.bounds[0] + best.bounds[2]) // 2
                by = (best.bounds[1] + best.bounds[3]) // 2
                step_log(f"🎯 定位目标 [{target}]，点击同行按钮「{best.text}」@({bx},{by})（距标题中心 {candidates[0][0]}px）", "info")
                try:
                    best.click()
                except Exception:
                    d.click(bx, by)
                return True
            step_log(f"⚠ 找到目标 [{target}] 标题，但未找到同行按钮（最近候选 > 350px），继续查找...", "warning")
        # 首屏（第 1 轮）未命中且 prefer_restart → 降级接受"继续答题"再找一遍（不下滑！）
        if _ == 0 and prefer_restart and not _fallback_accept:
            _fallback_accept = True
            continue
        # 未找到目标行/同行按钮 → 下滑翻页（只有确认首屏没有目标才下滑）
        try:
            S_swipe(d, 540, 1800, 540, 600, 0.3)
            time.sleep(0.4)
        except Exception:
            break
    return False
