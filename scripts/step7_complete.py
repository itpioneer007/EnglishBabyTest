"""
步骤8：批量调度（多模块 + 年级切换 + 回主页 + 汇总）
===================================================
通过 MODULE_CONFIG 一表管理所有模块差异。
TARGET_MODULES 列表配置要跑的模块顺序。
"""

import uiautomator2 as u2
import time

# ═══════════ 模块列表（逗号分隔即可） ═══════════
TARGET_MODULES = ["听力专项"]
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
        # 单元遍历：逐个点击"去练习"。有 units 时 entry_actions 里的去练习自动跳过
        "units": [1],  # Unit 1-9, 测试先跑 U1
        "entry_actions": [],  # 由 unit loop 点击去练习
        # 子模块：每个单元内，基础巩固→综合进阶→难点突破，中间左滑
        "sub_modules": [
            {"name": "基础巩固", "enter_action": None},
            {"name": "综合进阶", "enter_action": "swipe_left_sub"},
            {"name": "难点突破",  "enter_action": "swipe_left_sub"},
        ],
        "post_entry_actions": [
            {"type": "click", "text": "开始答题", "timeout": 3},
            {"type": "click", "text": "重新答题", "timeout": 2},
        ],
        # 报告页：前N-1个子模块点"继续练习"，最后子模块点左上角回单元列表
        "report_action": {
            "trigger": {"type": "click", "text": "练习报告"},
            "after_report": [
                {"type": "click", "text": "继续练习", "timeout": 3},
            ],
        },
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
        "question_types": {
            "sort": {
                "detect_text": ["排序", "按顺序", "排序题", "给句子排序"],
                "action": "sort_questions",
            },
            "match": {
                "detect_text": ["匹配", "配对", "为人物选择", "选择正确的描述"],
                "action": "match_questions",
            },
        },
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
    """关闭广告：多种策略按顺序尝试"""
    # 方式1：contentDescription 包含"关闭"
    try:
        if d(description="关闭").exists(timeout=1):
            d(description="关闭").click()
            print("    🔔 通过 description='关闭' 关闭广告")
            time.sleep(0.8)
            return True
    except Exception:
        pass

    # 方式2：找广告文字（"老师伴学"/"打卡服务"），点其右上角的 X
    try:
        for kw in ("老师伴学", "打卡服务", "点击参与"):
            for elem in (d.xpath('//*[@text!=""]').all() or []):
                if kw in (elem.text or ""):
                    # 找父级 clickable 容器的 bounds，再点右上角
                    b = elem.bounds
                    # 容器通常从 [705, 1787] 到 [1022, 2104]
                    # X 按钮在右上角，约 (986, 1823)
                    close_x = min(b[2] + 50, 1080) - 30   # 右边 X 按钮
                    close_y = b[1] - 0  # 卡片顶部
                    d.click(close_x, close_y)
                    print(f"    🔔 通过 ad 文字 [{kw}] 定位 X 按钮 ({close_x},{close_y})")
                    time.sleep(0.8)
                    return True
    except Exception:
        pass

    # 方式3：找内嵌的小尺寸 clickable（X 通常很小）
    try:
        for elem in (d.xpath('//*[@clickable="true"]').all() or []):
            b = elem.bounds
            w = b[2] - b[0]
            h = b[3] - b[1]
            # X 按钮特征：尺寸小（< 80x80）、位于右侧、y>600
            if w < 80 and h < 80 and b[0] > 800 and b[1] > 600:
                elem.click()
                print(f"    🔔 通过小尺寸 clickable (X) 关闭广告 ({sum(b)//4},{h*1000})")
                time.sleep(0.8)
                return True
    except Exception:
        pass

    # 方式4：className=ImageView，右上角
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

    # 方式5：硬编码右上角坐标
    try:
        d.click(986, 1823)
        print("    🔔 通过 ad-X 坐标 (986,1823) 关闭广告")
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

        elif at == "swipe_left":
            # 水平左滑切换子模块
            d.swipe(900, 600, 200, 600, duration=0.3)
            time.sleep(1.5)
            print(f"    👈 左滑切换子模块")

        elif at == "swipe_left_sub":
            # 子模块区左滑：用 swipe_ext，在基础巩固文字稍上方
            d.swipe_ext("left", scale=0.5)
            time.sleep(1.5)
            print(f"    👈 swipe_ext 左滑")

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
    """查找文字：先直接找，然后向上滑（内容下移）找下方，再向下滑（内容上移）找上方"""
    if d(text=text).exists(timeout=2): return True
    # 第一轮：向上滑（内容下移）
    for _ in range(max_swipes):
        d.swipe(500, 1400, 500, 400, duration=0.3)
        time.sleep(0.8)
        if d(text=text).exists(timeout=1.5): return True
    # 第二轮：向下滑（内容上移，返回顶部区域）
    for _ in range(max_swipes):
        d.swipe(500, 400, 500, 1400, duration=0.3)
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

def _detect_question_type(d, config):
    """识别当前题型：扫描题干关键词，返回 action 名或 None"""
    qt = config.get("question_types", {})
    if not qt:
        return None
    # 获取当前页面所有文字
    all_texts = ""
    for e in (d.xpath('//*[@text!=""]').all() or []):
        all_texts += (e.text or "") + " "
    for qtype, qcfg in qt.items():
        for kw in qcfg.get("detect_text", []):
            if kw in all_texts:
                return qcfg["action"]
    return None


def _handle_sort_question(d, config):
    """处理排序题：找所有可点击句子，依次点击，直到下一题出现"""
    print(f"    📋 识别到排序题，处理中...")
    clicked = set()
    max_attempts = 30

    for _ in range(max_attempts):
        # 每次循环找新出现的可点击句子
        found_new = False
        for elem in (d.xpath('//*[@clickable="true"]').all() or []):
            t = (elem.text or "").strip()
            # 跳过已点、空文字、标准按钮
            if not t or t in clicked:
                continue
            if t in ("下一题", "继续", "检查", "提交", "完成", "退出", "A", "B", "C", "T", "F"):
                continue
            try:
                elem.click()
                clicked.add(t)
                print(f"      → 点击: {t}")
                time.sleep(0.5)
                found_new = True
            except Exception:
                pass

        # 检查下一题是否出现
        if d(text="下一题").exists(timeout=1):
            print(f"    ✅ 排序完成，下一题已出现")
            return True

        if not found_new:
            break

    return d(text="下一题").exists(timeout=2)


def _handle_match_question(d, config):
    """处理匹配题：依次点击人物方框 → 选字母配对，直到全部配完"""
    print(f"    📋 识别到匹配题，处理中...")
    # 收集字母选项 A-E（按键序）
    letters = []
    for ch in ("A", "B", "C", "D", "E"):
        try:
            if d(text=ch).exists(timeout=0.5):
                letters.append(ch)
        except Exception:
            pass
    if not letters:
        print(f"    ⚠ 未找到字母选项"); return False

    # 收集人物（可点击、非标准按钮、非字母）
    persons = []
    for elem in (d.xpath('//*[@clickable="true"]').all() or []):
        t = (elem.text or "").strip()
        if not t or t in letters:
            continue
        if t in ("下一题", "继续", "检查", "提交", "完成", "退出", "A", "B", "C", "T", "F"):
            continue
        persons.append(elem)

    print(f"    人物{len(persons)}个, 字母{len(letters)}个")
    used_letters = set()

    for person in persons:
        # 点人物
        try:
            person.click()
            print(f"      → 选中: {(person.text or '').strip()[:10]}")
            time.sleep(0.4)
        except Exception:
            continue

        # 选一个未用字母
        found = False
        for ch in letters:
            if ch in used_letters:
                continue
            try:
                if d(text=ch).exists(timeout=1):
                    d(text=ch).click()
                    used_letters.add(ch)
                    print(f"      → 配对: {ch}")
                    time.sleep(0.4)
                    found = True
                    break
            except Exception:
                pass
        if not found:
            print(f"    ⚠ 无可配字母，跳过")

    # 全部配对后等下一题
    for _ in range(8):
        if d(text="下一题").exists(timeout=1.5):
            print(f"    ✅ 匹配完成，下一题已出现")
            return True
        time.sleep(1)
    return d(text="下一题").exists(timeout=2)


def _answer_loop(d, config, module_name):
    """答题循环（内部复用），返回题目数"""
    q = 0
    while q < 50:
        dismiss_global_popups(d)
        # 中途弹窗"完成X%,要不要继续?"（同时有"继续练习"和"先走一步"）→ 关掉继续答题
        if d(text="继续练习").exists(timeout=0.5) and d(text="先走一步").exists(timeout=0.3):
            d(text="继续练习").click()
            print("      → 关弹窗，继续答题")
            time.sleep(2)
            continue

        # ── 题型识别：如果是排序题/匹配题，走专用处理 ──
        qtype = _detect_question_type(d, config)
        if qtype == "sort_questions":
            _handle_sort_question(d, config)
            found = False
            for kw in config.get("next_button_texts", ["下一题"]):
                try:
                    if d(text=kw).exists(timeout=5):
                        d(text=kw).click(); time.sleep(2)
                        q += 1; found = True; break
                except Exception: pass
            if found: continue
            else:
                print(f"    ⏹ 排序后无下一题")
                return q
        elif qtype == "match_questions":
            _handle_match_question(d, config)
            found = False
            for kw in config.get("next_button_texts", ["下一题"]):
                try:
                    if d(text=kw).exists(timeout=5):
                        d(text=kw).click(); time.sleep(2)
                        q += 1; found = True; break
                except Exception: pass
            if found: continue
            else:
                print(f"    ⏹ 匹配后无下一题")
                return q

        # 完成判定
        for kw in config.get("finish_texts", []):
            try:
                if d(text=kw).exists(timeout=0.5):
                    d(text=kw).click()
                    print(f"    ⏹ {kw}")
                    return q
            except Exception: pass

        # ── 截图当前题目 ──
        d.screenshot("test.png")
        q += 1
        print(f"    📸 第{q}题")

        # ── 等待题目渲染，选答案 ──
        answered = False
        for opt in ("A","B","C","T","F"):
            for _ in range(12):                     # 0.5s x 12 = 最多6秒等渲染
                try:
                    if d(text=opt).exists(timeout=0.5):
                        d(text=opt).click()
                        print(f"      → 选 {opt}")
                        time.sleep(0.5)
                        answered = True
                        break
                except Exception: pass
                time.sleep(0.4)
            if answered:
                break

        # 检查/提交（轮询等出现）
        for kw in ("检查","提交"):
            for _ in range(10):
                try:
                    if d(text=kw).exists(timeout=0.5):
                        d(text=kw).click()
                        print(f"      → {kw}")
                        time.sleep(1.5)             # 等反馈动画
                        break
                except Exception: pass
                time.sleep(0.4)

        # 下一题（wait() 原生方法，等元素出现，最长 6s）
        found = False
        for kw in config.get("next_button_texts", ["下一题"]):
            try:
                if d(text=kw).wait(timeout=6):       # wait 比 exists 更可靠
                    d(text=kw).click()
                    print(f"      → {kw}")
                    time.sleep(2)
                    found = True
                    break
            except Exception: pass

        # 最后一题：找不到下一题 → 找「练习报告」
        if not found:
            for _ in range(10):
                if d(text="练习报告").exists(timeout=0.5):
                    d(text="练习报告").click()
                    print(f"      → 练习报告（最后一题）")
                    time.sleep(2)
                    found = True
                    break
                time.sleep(0.5)

        if not found:
            print(f"    ⏹ 无下一题 (第{q}题)")
            return q
    return q


def _handle_report(d, config, sub_name="", is_last=False):
    """处理报告页按钮：
    - 非最后子模块: 点 after_report（如"继续练习"）→ 回单元内小模块列表
    - 最后子模块:   点"先走一步"/左上角返回 → 回单元列表
    """
    ra = config.get("report_action")
    if not ra:
        return

    # 报告页出现的按钮候选
    if is_last:
        # 最后子模块：退出到单元列表（back 或 先走一步）
        if d(text="先走一步").exists(timeout=2):
            d(text="先走一步").click()
            print(f"    👋 先走一步 → 回单元列表")
            time.sleep(2)
        for _ in range(4):
            if d(text="去练习").exists(timeout=1.5):
                return
            d.press("back"); time.sleep(1.5)
        return
    else:
        # 非最后：报告页 → 点"继续练习" → 回到单元内 → 左滑下一关
        after = ra.get("after_report", [])
        # 等报告页完全加载（成绩动画）
        for _ in range(8):
            if d(text="继续练习").exists(timeout=1.5):
                break
            time.sleep(1)
        # 点继续练习
        execute_actions(d, after, sub_name)
        # 等回到单元内（出现"开始答题"或"重新答题"）
        for _ in range(8):
            if d(text="重新答题").exists(timeout=1) or d(text="开始答题").exists(timeout=1):
                return
            time.sleep(1)
        print(f"    ⚠ 继续练习后未回单元内")


def run_single_module(d, module_name, config):
    print(f"\n{'='*45}")
    print(f"🔍 检测模块：{module_name}")
    print(f"{'='*45}")

    questions = 0
    entry = config["entry_text"]
    sub_modules = config.get("sub_modules")     # 子模块列表（None=无子模块）

    # 1. 找模块入口
    print(f"  [1] 查找「{entry}」...")
    if not scroll_and_find(d, entry):
        print(f"  ❌ 未找到模块: {entry}"); return 0
    d(text=entry).click()
    print(f"  ✅ 已进入 {module_name}")
    time.sleep(2)

    # 2. 空态检测
    for kw in config.get("empty_text", []):
        if d(text=kw).exists(timeout=2):
            print(f"  ⚠ {module_name} [{kw}]，跳过"); return 0

    # 3. 入口操作
    for _ in range(3):
        dismiss_global_popups(d)
    ea = config.get("entry_actions", [])
    if ea:
        print(f"  [2] 入口操作 ({len(ea)}个)")
        execute_actions(d, ea, module_name)
        time.sleep(1)

    # ── 4. 单元遍历 + 子模块 ──
    units = config.get("units")  # 如有单元号列表，逐个遍历
    if units:
        print(f"  [3] 单元遍历({len(units)}个)：U{units[0]}-U{units[-1]}")

    # 子模块内部运行（被单元循环或单独调用）
    def run_sub_modules():
        nonlocal questions
        sm = config.get("sub_modules")
        if not sm: return
        print(f"  [子模块] {[s['name'] for s in sm]}")
        for i, sub in enumerate(sm):
            name = f"{module_name}/{sub['name']}"
            print(f"  --- [{i+1}/{len(sm)}] {sub['name']} ---")
            # 子模块切换
            act = sub.get("enter_action")
            if act in ("swipe_left", "swipe_left_sub"):
                d.swipe_ext("left", scale=0.5)
                time.sleep(1.5)
                print(f"    👈 左滑 → {sub['name']}")
            # 答题入口
            pa = config.get("post_entry_actions", [])
            if pa: execute_actions(d, pa, name)
            # 答题
            q = _answer_loop(d, config, name)
            questions += q
            # 报告：最后子模块退出单元，前面的继续练习回单元内
            is_last = (i == len(sm) - 1)
            _handle_report(d, config, sub["name"], is_last=is_last)
            time.sleep(1.5)

    # 单元遍历
    if units:
        for ui, unit_num in enumerate(units):
            print(f"\n  {'='*40}")
            print(f"  🎯 Unit {unit_num} [{ui+1}/{len(units)}]")
            print(f"  {'='*40}")
            # 在模块列表里找该单元的"去练习"并点击
            clicked = False
            for _ in range(20):  # 滚动+查找
                # 找目标 Unit 按钮
                btns = [(e, e.bounds[1]) for e in (d.xpath('//*[@text="去练习"]').all() or [])]
                unit_rows = [(e, e.text, e.bounds[1]) for e in (d.xpath('//*[@text!=""]').all() or [])
                            if (e.text or "").startswith(f"Unit {unit_num}")]
                if unit_rows:
                    ue, uname, uy = unit_rows[0]
                    # 最近"去练习"匹配该单元行
                    for be, by in btns:
                        if abs(by - uy) < 120:
                            be.click(); time.sleep(4); clicked = True
                            break
                if clicked: break
                d.swipe(500, 1800, 500, 600, 0.3); time.sleep(1)
            if not clicked:
                print(f"  ❌ U{unit_num} 找不到去练习"); continue
            print(f"  ✅ U{unit_num} 去练习")
            # 跑子模块
            run_sub_modules()
            # 回单元列表
            print(f"  ↩ 回单元列表...")
            for _ in range(5):
                if d(text="去练习").exists(timeout=1): break
                d.press("back"); time.sleep(1.5)
            time.sleep(1)
        # 所有单元完成后回主页
        print(f"  ↩ 回主页...")
        back_to_home(d, GRADE_LEVEL)
    else:
        # 无单元列表，直接跑 entry_actions + 子模块（或直接答题）
        run_sub_modules()

    return questions if (units or sub_modules) else 0

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
    # ═══ 立即关广告（app_start 后广告先弹出，不等人） ═══
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    # ═════════════════════════════════════════════════

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
