"""
导航模块（engine_navigator.py）
===============================
所有页面导航操作，基于 uiautomator2 纯文字定位。
已验证通过（2026-07-31，湘少版六年级上册）。
"""

import time
from engine_config import POPUP_BUTTONS


def is_on_home(d) -> bool:
    """主页检测：教材精学 + 专项突破 同时存在"""
    return (d(text="教材精学").exists(timeout=1) and
            d(text="专项突破").exists(timeout=1))


def handle_popup(d) -> bool:
    """关闭常见弹窗，返回是否处理了弹窗"""
    for kw in POPUP_BUTTONS:
        try:
            if d(text=kw).exists(timeout=0.5):
                d(text=kw).click()
                time.sleep(0.8)
                return True
        except Exception:
            pass
    return False


def back_until_home(d, max_back=8) -> bool:
    """按back直到回到主页"""
    for _ in range(max_back):
        if is_on_home(d):
            return True
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(1.2)
    return is_on_home(d)


def scroll_to_find(d, text: str, max_swipes=8) -> bool:
    """
    向上滑（内容往下走）逐屏查找文字。
    滑动方向: swipe(500, 1400, 500, 400) = 手指从下往上 = 内容向下滚动
    """
    # 先直接找
    if d(text=text).exists(timeout=2):
        return True

    # 逐屏向上滑查找
    for _ in range(max_swipes):
        d.swipe(500, 1400, 500, 400, duration=0.3)
        time.sleep(0.8)
        if d(text=text).exists(timeout=1.5):
            return True
    return False


def ensure_grade(d, target_grade: str = "六年级上册",
                 target_version: str = "湘少版(2024审定)") -> bool:
    """
    确保目标版本+年级匹配。不匹配则自动切换。
    
    已验证切换路径（2026-07-31 真机）：
      主页 → 我 → 设置齿轮 → 学生资料 → 英语所学教材版本
      → 选版本 → back×3回主页 → 点版本号 → 选年级
    """
    # 1. 先尽量回主页
    back_until_home(d)

    # 2. 检查当前版本+年级是否已匹配
    current = ""
    for el in (d.xpath('//*[@text!=""]').all() or []):
        t = el.text or ""
        if ("审定" in t and "版" in t):
            current = t
            break
    if current:
        match_version = target_version[:2] in current  # "湘少" in current
        match_grade = target_grade in current
        if match_version and match_grade:
            print(f"    ✅ 版本/年级已匹配: {target_version} {target_grade}")
            return True

    # 3. 不匹配 → 切换（路径已验证）
    print(f"    🔄 切换版本: → {target_version} {target_grade}")

    # 我 → 设置
    try: d(text="我").click(timeout=3)
    except Exception: pass
    time.sleep(1.5)

    for kw in ("设", "置"):
        try:
            d(textContains=kw).click(timeout=2)
            break
        except Exception:
            continue
    time.sleep(2)

    # 学生资料
    try: d(text="学生资料").click(timeout=3)
    except Exception: pass
    time.sleep(2)

    # 英语所学教材版本
    try: d(text="英语所学教材版本").click(timeout=3)
    except Exception: pass
    time.sleep(2)

    # 选版本
    try: d(text=target_version).click(timeout=3)
    except Exception: pass
    time.sleep(2)

    # 返回主页
    back_until_home(d)

    # 点版本号 ��� 选年级
    try: d(textContains="审定").click(timeout=3)
    except Exception: pass
    time.sleep(2)

    scroll_to_find(d, target_grade)
    try: d(text=target_grade).click(timeout=3)
    except Exception: pass
    time.sleep(2)

    # 确认按钮
    for btn in ("确定", "确认", "完成", "好的"):
        try:
            if d(text=btn).exists(timeout=1):
                d(text=btn).click()
                break
        except Exception:
            pass
    time.sleep(2)

    # 验证
    ok = is_on_home(d)
    if ok:
        print(f"    ✅ 已切换至 {target_version} {target_grade}")
    else:
        print(f"    ❌ 版本切换失败")
    return ok


def wait_home_loaded(d, max_wait=15):
    """等待主页模块列表加载完成"""
    for _ in range(max_wait):
        if is_on_home(d):
            return True
        time.sleep(1.5)
    return False


def navigate_to_module(d, module_name: str) -> bool:
    """
    从主页进入指定模块。
    先直接找，找不到就向上滑滚动查找。
    """
    # 确保在主页
    if not is_on_home(d):
        back_until_home(d)
    wait_home_loaded(d)

    # 查找模块
    if not scroll_to_find(d, module_name):
        print(f"    ❌ 未找到模块: {module_name}")
        return False

    # 点击进入
    try:
        d(text=module_name).click(timeout=3)
        time.sleep(2)
        handle_popup(d)
        return True
    except Exception:
        print(f"    ❌ 进入模块失败: {module_name}")
        return False


def enter_unit_and_start(d, config: dict) -> bool:
    """
    进入单元并点击开始按钮（如"去练习"/"我要听写"等）。
    支持两种入口：
      need_unit=True  → 点击 Unit N 标题 → 再点开始按钮
      need_unit=False → 直接找"去练习/开始答题/进入"
    """
    if config.get("need_unit"):
        # 点第一个 Unit 标题
        for u in range(1, 7):
            try:
                if d(textContains=f"Unit {u} ").exists(timeout=1.5):
                    d(textContains=f"Unit {u} ").click()
                    time.sleep(2)
                    break
            except Exception:
                continue
        else:
            try:
                d(textContains="Unit").click(timeout=2)
                time.sleep(2)
            except Exception:
                pass

        # 轮询等开始按钮出现
        for btn in config.get("start_button", []):
            for _ in range(5):
                try:
                    if d(text=btn).exists(timeout=1):
                        d(text=btn).click()
                        print(f"    ✅ 点击 {btn}")
                        time.sleep(2)
                        break
                except Exception:
                    pass
                time.sleep(1.2)
    else:
        # 直接找通用入口按钮
        for btn in ("去练习", "开始答题", "进入", "重新答题"):
            try:
                if d(text=btn).exists(timeout=2):
                    d(text=btn).click()
                    print(f"    ✅ 点击 {btn}")
                    time.sleep(2)
                    return True
            except Exception:
                continue
    return True


def back_to_home(d, max_back=6) -> bool:
    """从模块页返回主页"""
    return back_until_home(d, max_back)
