"""
步骤8：批量调度（多模块 + 年级切换 + 回主页 + 汇总）
===================================================
通过 MODULE_CONFIG 一表管理所有模块差异。
TARGET_MODULES 列表配置要跑的模块顺序。
"""

import uiautomator2 as u2
import time

# ═══════════ 模块列表（逗号分隔即可） ═══════════
TARGET_MODULES = ["听力专项", "单词听写", "单元自检"]
# ═══════════ 切换年级/版本 ══════════════════
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"
# ═══════════════════════════════════════════

APP_PACKAGE = "com.dinoenglish.yyb"

# ==================== ① 模块配置表 ====================
MODULE_CONFIG = {
    "听力训练": {
        "entry_text": "听力训练",
        "entry_actions": [],                            # 直接进入，无需额外操作
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续", "下一步"],
        "finish_texts": ["完成", "提交", "结束"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "单元自检": {
        "entry_text": "单元自检",
        "entry_actions": [
            {"type": "click", "text": "去答题", "timeout": 4},
            {"type": "close_ad"},                         # 广告❌关闭（非文字按钮）
            {"type": "close_popup", "text": ["好的，我知道啦~", "我知道了", "确定", "好的"], "timeout": 3},
        ],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续", "下一页"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "单词学习": {
        "entry_text": "单词听写",                       # 界面真实名
        "entry_actions": [
            {"type": "click", "text": "去学习", "timeout": 4},
            {"type": "close_popup", "text": ["开始学习", "我知道了", "好的"], "timeout": 2},
        ],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "听力专项": {
        "entry_text": "听力专项",
        "entry_actions": [
            {"type": "click", "text": "去练习", "timeout": 4},
        ],
        "post_entry_actions": [
            {"type": "click", "text": "开始答题", "timeout": 3},
            {"type": "click", "text": "重新答题", "timeout": 2},
        ],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "口语训练": {
        "entry_text": "口语训练",
        "entry_actions": [],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "单词听写": {
        "entry_text": "单词听写",
        "entry_actions": [],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    # ====== 新增模块：复制以下模板，改 key 和 content ======
    # "新模块": {
    #     "entry_text": "主页显示文字",
    #     "entry_actions": [
    #         {"type": "click", "text": "入口按钮", "timeout": 4},
    #         {"type": "close_popup", "text": ["弹窗按钮1", "弹窗按钮2"], "timeout": 3},
    #     ],
    #     "post_entry_actions": [],
    #     "next_button_texts": ["下一题", "继续"],
    #     "finish_texts": ["完成", "提交"],
    #     "empty_text": ["暂无数据"],
    #     "has_pagination": True,
    # },
}

# ==================== ② 通用弹窗（全模块生效） ====================
GLOBAL_POPUPS = ["允许", "取消", "关闭", "以后再说", "暂不", "跳过"]

# ==================== ③ 广告关闭（非文字按钮，用 description / ImageView 匹配） ====================
def close_ad(d):
    """关闭广告：先匹配 description='关闭'，再找右上角 ImageView，最后坐标兜底"""
    # 方式1：contentDescription 包含"关闭"
    try:
        if d(description="关闭").exists(timeout=1):
            d(description="关闭").click()
            print("    🔔 通过 description='关闭' 关闭广告")
            time.sleep(0.8)
            return True
    except Exception:
        pass

    # 方式2：className=ImageView，可点击，且在右上角
    try:
        for elem in d(className="android.widget.ImageView"):
            info = elem.info
            if not info.get("clickable"):
                continue
            b = info.get("bounds", {})
            if b.get("right", 0) > d.window_size()[0] * 0.7 and b.get("top", 0) < 200:
                elem.click()
                print("    🔔 通过右上角 ImageView 关闭广告")
                time.sleep(0.8)
                return True
    except Exception:
        pass

    # 方式3：硬编码坐标兜底（常见广告关闭在右上角）
    try:
        d.click(1000, 120)
        print("    🔔 通过坐标 (1000,120) 关闭广告")
        time.sleep(0.8)
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
                        time.sleep(0.8)
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
                d.swipe(500, 1400, 500, 400, duration=0.3)
                time.sleep(1)
            if safe_click(d, text, timeout=min(timeout, 3)):
                print(f"    ✅ 滑动后点击 '{text}'")
            else:
                print(f"    ⚠ 滑动后未找到 '{text}'")

        elif at == "close_ad":
            close_ad(d)

# ==================== ⑤ 基础工具 ====================
def safe_click(d, text, timeout=3) -> bool:
    try:
        d(text=text).click(timeout=timeout)
        return True
    except Exception:
        return False

def dismiss_global_popups(d):
    for t in GLOBAL_POPUPS:
        try:
            if d(text=t).exists(timeout=0.5):
                d(text=t).click()
                print(f"    🔔 全局弹窗: '{t}'")
                time.sleep(0.8)
                return True
        except Exception:
            pass
    return False

def scroll_and_find(d, text, max_swipes=8) -> bool:
    if d(text=text).exists(timeout=2): return True
    for _ in range(max_swipes):
        d.swipe(500, 1400, 500, 400, duration=0.3)
        time.sleep(0.8)
        if d(text=text).exists(timeout=1.5): return True
    return False

# ==================== ⑥ 年级切换 ====================
def ensure_grade(d, grade_level, book_version=""):
    """
    确保当前年级匹配。不匹配则自动切换。
    流程：检测主页版本文字 → 不匹配则点版本号 → 选年级 → 确认
    """
    # 主页版本号如 "湘少版（2024审定）五年级上册"
    if d(textContains=grade_level).exists(timeout=3):
        if d(text="教材精学").exists(timeout=1):
            print(f"✅ 已确认 {book_version} {grade_level}")
            return True

    # 不匹配 → 打开年级切换弹层
    print(f"🔄 切换年级 → {book_version} {grade_level}")
    try:
        d(textContains="审定").click(timeout=3)
    except Exception:
        print("❌ 找不到版本号入口")
        return False
    time.sleep(2)

    # 在弹层中找年级（可能需要向上滑）
    for _ in range(8):
        if d(text=grade_level).exists(timeout=1):
            break
        d.swipe(500, 1400, 500, 400, duration=0.3)
        time.sleep(1)

    try:
        d(text=grade_level).click(timeout=3)
    except Exception:
        print(f"❌ 弹层中找不到 {grade_level}")
        d.press("back")
        return False
    time.sleep(2)

    # 确认按钮
    for btn in ("确定", "确认", "完成", "好的"):
        try:
            if d(text=btn).exists(timeout=1):
                d(text=btn).click()
                break
        except Exception:
            pass
    time.sleep(3)

    ok = d(textContains=grade_level).exists(timeout=3)
    if ok:
        print(f"✅ 已切换至 {book_version} {grade_level}")
    else:
        print("❌ 年级切换失败")
    return ok

def back_to_home(d, grade_level):
    """从模块内部回到年级主页：按 back 直到看到年级文字"""
    for _ in range(8):
        # 处理途中弹窗
        dismiss_global_popups(d)
        if d(textContains=grade_level).exists(timeout=1):
            return True
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(1.2)
    return d(textContains=grade_level).exists(timeout=2)

# ==================== ⑦ 核心：单模块检测 ====================
def run_single_module(d, module_name, config):
    print(f"\n{'='*45}")
    print(f"🔍 检测模块：{module_name}")
    print(f"{'='*45}")

    questions = 0
    entry = config["entry_text"]

    # 1. 找模块入口（支持滑动）
    print(f"  [1] 查找「{entry}」...")
    if not scroll_and_find(d, entry):
        print(f"  ❌ 未找到模块: {entry}")
        return 0
    d(text=entry).click()
    print(f"  ✅ 已进入 {module_name}")
    time.sleep(2)

    # 2. 空态检测
    for kw in config.get("empty_text", []):
        if d(text=kw).exists(timeout=2):
            print(f"  ⚠ {module_name} [{kw}]，跳过")
            return 0

    # 3. 执行入口前操作（entry_actions）
    for _ in range(3):
        dismiss_global_popups(d)
    ea = config.get("entry_actions", [])
    if ea:
        print(f"  [2] 执行 {len(ea)} 个入口操作")
        execute_actions(d, ea, module_name)
        time.sleep(1)

    # 4. 执行入口后操作（post_entry_actions）
    pa = config.get("post_entry_actions", [])
    if pa:
        print(f"  [3] 执行 {len(pa)} 个后置操作")
        execute_actions(d, pa, module_name)
        time.sleep(1)

    # 5. 答题循环
    print(f"  [4] 开始答题...")
    while questions < 50:
        dismiss_global_popups(d)

        # 完成判定
        for kw in config.get("finish_texts", []):
            try:
                if d(text=kw).exists(timeout=0.5):
                    d(text=kw).click()
                    print(f"    ⏹ {kw}")
                    return questions
            except Exception:
                pass

        # 截图
        d.screenshot("test.png")
        questions += 1
        print(f"    📸 第{questions}题")

        # 选答案 + 检查
        for opt in ("A", "B", "C", "T", "F"):
            try:
                if d(text=opt).exists(timeout=0.3):
                    d(text=opt).click(); time.sleep(0.3)
                    break
            except Exception:
                pass
        for kw in ("检查", "提交"):
            try:
                if d(text=kw).exists(timeout=1):
                    d(text=kw).click(); time.sleep(0.8)
                    break
            except Exception:
                pass

        # 下一题
        found = False
        for kw in config.get("next_button_texts", ["下一题"]):
            try:
                if d(text=kw).exists(timeout=2):
                    d(text=kw).click()
                    time.sleep(2)
                    found = True
                    break
            except Exception:
                pass
        if not found:
            print(f"    ⏹ 无下一题")
            return questions

    return questions

# ==================== ⑧ 入口（批量调度） ====================
if __name__ == "__main__":
    d = u2.connect()
    print("✅ 设备已连接")

    modules = TARGET_MODULES
    print(f"📋 待跑模块: {len(modules)} 个 → {modules}")

    # 回到 App 主页 + 确认年级
    for _ in range(5):
        d.press("back"); time.sleep(1)
    d.app_start(APP_PACKAGE); time.sleep(5)

    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败"); exit(1)

    # 逐个模块执行
    total_q = 0
    ok_count = 0
    results = []

    for i, mod_name in enumerate(modules, 1):
        cfg = MODULE_CONFIG.get(mod_name)
        if not cfg:
            print(f"❌ 未知模块: {mod_name}，跳过")
            continue

        print(f"\n  [{i}/{len(modules)}]")
        q = run_single_module(d, mod_name, cfg)
        results.append((mod_name, q))
        total_q += q
        if q > 0:
            ok_count += 1

        # 回到主页（最后一个模块不用回）
        if i < len(modules):
            print(f"  ↩ 返回主页...")
            back_to_home(d, GRADE_LEVEL)
            time.sleep(2)

    # 汇总
    print(f"\n{'='*45}")
    print(f"📊 批量调度汇总")
    print(f"{'='*45}")
    for mod, q in results:
        print(f"  {'✅' if q > 0 else '⚠'} {mod}: {q} 题")
    print(f"  总模块: {len(modules)} | 有题: {ok_count}")
    print(f"  总截图: {total_q} 张")
    print(f"{'='*45}")
