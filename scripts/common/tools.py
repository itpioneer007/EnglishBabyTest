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


def close_ad(d):
    """关闭广告：多种策略按顺序尝试
    ★ 广告结构（实测）：右下角 fl_ad_container 广告卡片，关闭按钮 resource-id=iv_close（72x72）
      "老师伴学/打卡服务"是广告卡片标题（有时只显示"伴学"），底部导航的"伴学/会员"不是广告！
      关闭优先级：resource-id 精确定位 > description=关闭 > 广告文字 > 小尺寸X > 坐标"""
    try:
        xml = d.dump_hierarchy()
    except Exception:
        xml = ""

    # 广告特征：弹窗广告文字 / 关闭按钮资源 / 广告角标
    has_ad_text = any(kw in xml for kw in ("老师伴学", "打卡服务", "点击参与", "广告", "推广", "跳过"))
    has_close_btn = ('content-desc="关闭' in xml or 'text="关闭"' in xml)
    # ★ 实测：右下角广告卡片 fl_ad_container + 关闭按钮 iv_close（坐标 986,1823）
    has_ad_card = ('fl_ad_container' in xml or 'iv_ad' in xml or 'iv_close' in xml)

    # 方式0（★ 最可靠）：检测到广告卡片 → 直接点关闭按钮坐标（实测 iv_close 中心 986,1823）
    if has_ad_card:
        try:
            d.click(*S(d, 986, 1823))
            print("    🔔 通过广告卡片 iv_close 坐标 (986,1823) 关闭广告")
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
                            close_x = min(b[2] - 10, 1080)
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

    # 方式4/5：右上角 ImageView / 硬编码坐标 —— 仅当页面有广告特征文字时才尝试
    # （避免误点主页右上角的正常功能按钮，如二维码/扫码入口）
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
        try:
            d.click(*S(d, 986, 1823))
            print("    🔔 通过 ad-X 坐标 (986,1823) 关闭广告")
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

def scroll_and_find(d, text, max_swipes=5) -> bool:
    """查找文字：先直接找，然后向上滑（内容下移）找下方，再向下滑（内容上移）找上方"""
    if d(text=text).exists(timeout=2): return True
    # 第一轮：向上滑（内容下移）
    for _ in range(max_swipes):
        S_swipe(d, 500, 1400, 500, 400, 0.3)
        time.sleep(0.35)
        if d(text=text).exists(timeout=1.5): return True
    # 第二轮：向下滑（内容上移，返回顶部区域）
    for _ in range(max_swipes):
        S_swipe(d, 500, 400, 500, 1400, 0.3)
        time.sleep(0.35)
        if d(text=text).exists(timeout=1.5): return True
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

def back_to_home(d, grade_level):
    """从模块内部回到年级主页：按 back 直到看到年级文字"""
    for _ in range(8):
        dismiss_global_popups(d)
        if d(textContains=grade_level).exists(timeout=1):
            return True
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(0.5)
    return d(textContains=grade_level).exists(timeout=2)

# ==================== ⑦ 核心：单模块检测 ====================


# ==================== ⑧ 智能单元定位（随机应变按名字找内容） ====================
def smart_find_unit_row(d, target, click_text="去答题", max_pages=8):
    """智能定位目标单元/测试行并点击其按钮 —— 不写死标题，随机应变

    target: 单元引用
      - 数字(1) / 区间("1-3")：按 "Unit N" / "Unit N单元评价" 模式匹配
      - 关键词("期中"/"期末"/"AI检测"/"湘少三上期中评价")：先点筛选 tab（如有），
        再匹配标题包含关键词的行
    click_text: 目标行旁按钮文字（"去答题"/"去练习"）
    返回: 是否点击成功
    """
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
        if _re.search(rf"Unit\s*{s}(?:\s*单元评价|\s|$)", t):
            return True
        if _re.fullmatch(r"\d+", s):
            return _re.search(rf"U{_re.escape(s)}(?:\s|$)", t) is not None
        return False

    # ③ 逐屏查找：标题行 → 点同行 click_text 按钮
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
            row_y = row.bounds[1]
            for e in elements:
                if (e.text or "").strip() == click_text:
                    if abs(e.bounds[1] - row_y) < 300:   # 同行
                        try:
                            e.click()
                        except Exception:
                            d.click((e.bounds[0]+e.bounds[2])//2, (e.bounds[1]+e.bounds[3])//2)
                        return True
        # 未找到 → 下滑翻页
        try:
            S_swipe(d, 540, 1800, 540, 600, 0.3)
            time.sleep(0.4)
        except Exception:
            break
    return False
