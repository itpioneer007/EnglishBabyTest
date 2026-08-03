"""
英语宝 · 自动化引擎
===================
close_ad / ensure_grade / run_single_module 等核心逻辑
"""
import uiautomator2 as u2
import time, re
from config import MODULE_CONFIG, GLOBAL_POPUPS, APP_PACKAGE, GRADE_LEVEL, BOOK_VERSION

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
    """处理排序题（两种模式，用户约定）：

    模式A（图片排序，练习+测试都有）：
      依次点击所有图片/句子 → 序号自动按点击顺序填充 → 出现"检查"
    模式B（句子排序，测试模块）：
      点第一个方框激活输入框 → 依次点击底部序号按钮(1,2,3...) → 出现"检查"

    之后点"检查"，答对自动进下一题 / 答错点"下一题"。
    """
    print(f"    📋 识别到排序题，处理中...")

    # ── 模式B：检测底部有序号按钮（无文字的图片按钮，两行 8 个位置）──
    has_num_btns = False
    # 检查底部序号按钮是否存在（可点击、无文字、y>1870 且 <2270）
    for e in (d.xpath('//*[@clickable="true"]').all() or []):
        b = e.bounds
        if b[1] > 1870 and b[1] < 2270 and (b[2] - b[0]) > 100:
            has_num_btns = True
            break

    if has_num_btns:
        # 模式B：点第一个方框激活 → 依次点底部序号
        print(f"    🔢 检测到序号按钮（模式B）")
        # 1. 点第一个方框（y 700-1900、宽度100-500的可点击元素，排除序号按钮）
        clicked_box = False
        for e in (d.xpath('//*[@clickable="true"]').all() or []):
            b = e.bounds
            if 700 < b[1] < 1900 and 100 < b[2] - b[0] < 500:
                try:
                    e.click()
                    print(f"      → 点第一个方框激活")
                    time.sleep(1.5)
                    clicked_box = True
                    break
                except Exception:
                    pass
        # 2. 依次点底部序号（句子排序5-7句 → 点 1-5 序号按钮）
        num_btns = [
            (121, 1974), (363, 1974), (605, 1974), (847, 1974),
            (121, 2169), (363, 2169), (605, 2169), (847, 2169),
        ]
        for i in range(5):
            try:
                d.click(num_btns[i][0], num_btns[i][1])
                print(f"      → 点序号{i+1}")
                time.sleep(1)
            except Exception:
                pass
        # 3. 出现检查 → 点它
        for _ in range(8):
            if d(text="检查").exists(timeout=1):
                d(text="检查").click()
                print(f"    ✅ 排序完成，点击检查")
                time.sleep(0.8)
                return True
            if d(text="下一题").exists(timeout=1):
                print(f"    ✅ 排序完成，下一题已出现")
                return True
            time.sleep(0.5)
        return True

    # ── 模式A：依次点击所有图片/句子（序号自动填充）──
    print(f"    🖼 无序号按钮，按图片/句子模式（模式A）")
    clicked = set()
    max_attempts = 15

    for _ in range(max_attempts):
        # 每次循环找新出现的可点击图片/句子
        found_new = False
        for elem in (d.xpath('//*[@clickable="true"]').all() or []):
            b = elem.bounds
            t = (elem.text or "").strip()
            # 排序项特征：y 700-1900、宽度 > 300（大块图片/句子卡片，排除小序号按钮）
            if not (700 < b[1] < 1900 and b[2] - b[0] > 300):
                continue
            key = f"{b[0]}_{b[1]}"
            if key in clicked:
                continue
            try:
                elem.click()
                clicked.add(key)
                print(f"      → 点图片/句子: {(t or '')[:12] or key}")
                time.sleep(1)
                found_new = True
            except Exception:
                pass

        # 点完 → 出现"检查"
        if not found_new and d(text="检查").exists(timeout=1):
            d(text="检查").click()
            print(f"    ✅ 排序题点完，点击检查")
            time.sleep(0.8)
            return True
        # 兼容：直接出"下一题"
        if d(text="下一题").exists(timeout=0.8):
            print(f"    ✅ 排序完成，下一题已出现")
            return True

    # 兜底
    try:
        if d(text="检查").exists(timeout=1):
            d(text="检查").click()
            print(f"    ✅ 兜底点击检查")
            time.sleep(0.8)
            return True
    except Exception:
        pass
    print(f"    ⚠ 排序题处理异常")
    return False


def _handle_match_question(d, config):
    """处理匹配题：点一个方框激活 → 把所有字母选项全部点完

    用户约定（重要，供后续同学接入 API）：
      1. 只需点击一次方框 → 激活底部字母选项输入界面
      2. 之后不用再点方框：点一个字母 → 字母进入当前人物方框
         → 方框自动切换到下一个人物
      3. 因此只需把字母选项（A/B/C/D/E）全部依次点击完即可
    """
    print(f"    📋 识别到匹配题，处理中...")

    # 1. 点第一个可点击方框激活字母选项界面（人物名文字所在区域的方框）
    clicked_box = False
    name_boxes = [e for e in (d.xpath('//*[@clickable="true"]').all() or [])]
    name_texts = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                  if (e.text or "").strip()]
    for ne in name_texts:
        t = ne.text.strip()
        # 人物名特征：英文单词（非 A-E、非标准按钮）
        if len(t) <= 12 and t.isalpha() and t not in ("A","B","C","D","E","T","F","OK"):
            ny = ne.bounds[1]
            for ce in name_boxes:
                cb = ce.bounds
                if cb[1] <= ny <= cb[3]:   # y 与人物名重叠
                    try:
                        ce.click()
                        clicked_box = True
                        print(f"      → 点击方框激活 [{t}]")
                        time.sleep(1)
                        break
                    except Exception:
                        pass
            if clicked_box:
                break
    if not clicked_box:
        print(f"    ⚠ 未找到人物方框，尝试直接处理")
        time.sleep(0.5)

    # 2. 收集字母选项 A-E
    letters = []
    for ch in ("A", "B", "C", "D", "E"):
        try:
            if d(text=ch).exists(timeout=0.5):
                letters.append(ch)
        except Exception:
            pass
    print(f"    字母选项{len(letters)}个: {letters}")
    if not letters:
        print(f"    ⚠ 未找到字母选项"); return False

    # 3. 把字母全部点完（每个点一次；点字母自动配对并切换下一个人物）
    for ch in letters:
        try:
            if d(text=ch).exists(timeout=0.8):
                d(text=ch).click()
                print(f"      → 点字母: {ch}")
                time.sleep(0.5)
        except Exception:
            pass
    print(f"    ✅ 字母选项已全部点完: {letters}")

    # 4. 出现"检查"→ 点它；或直接出"下一题"
    for _ in range(8):
        if d(text="检查").exists(timeout=1):
            d(text="检查").click()
            print(f"    ✅ 匹配题点完，点击检查")
            time.sleep(0.8)
            return True
        if d(text="下一题").exists(timeout=1):
            print(f"    ✅ 匹配完成，下一题已出现")
            return True
        time.sleep(0.5)
    return d(text="下一题").exists(timeout=2)


def _get_qno(d):
    """从页面提取当前题号，如 '3/5' → (3,5)；无则返回 (0,0)"""
    try:
        for e in d.xpath('//*[@text!=""]').all():
            t = (e.text or "").strip()
            import re as _re
            m = _re.match(r'^(\d+)\s*/\s*(\d+)$', t)
            if m:
                return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


def _answer_loop(d, config, module_name):
    """答题循环（内部复用），返回题目数。

    原则：
      1. 有选项就直接点（选择题点A/B/C，判断题点T/F）
      2. 点"检查"
      3. 答对 → App 自动进下一题（无需操作）
      4. 答错 → 出现"下一题"按钮 → 点击进入真正的下一题
      5. 最后一题 → 出现"练习报告" → 处理并返回
    """
    q = 0
    while q < 50:
        # 弹窗检测（"继续练习"+"先走一步"同时出现=中途弹窗）
        if d(text="继续练习").exists(timeout=0.6) and d(text="先走一步").exists(timeout=0.4):
            d(text="继续练习").click()
            print("      → 关弹窗")
            time.sleep(1)
            continue

        # 题型识别：排序/匹配走专用处理
        qtype = _detect_question_type(d, config)
        if qtype == "sort_questions":
            _handle_sort_question(d, config)
            time.sleep(1)
            continue
        elif qtype == "match_questions":
            _handle_match_question(d, config)
            time.sleep(1)
            continue

        # 最后一题完成判定：练习报告
        if d(text="练习报告").exists(timeout=0.5):
            d(text="练习报告").click()
            print(f"      → 练习报告（最后一题）")
            time.sleep(1)
            if not config.get('_is_last_sub', False):
                for _ in range(8):
                    if d(text="继续练习").exists(timeout=0.8):
                        d(text="继续练习").click()
                        print(f"      → 继续练习")
                        time.sleep(1)
                        break
                    time.sleep(0.5)
            print(f"      → 本子模块完成，返回")
            return q

        # 答错后出现"下一题"按钮 → 点击进入真正下一题
        if d(text="下一题").exists(timeout=0.5):
            d(text="下一题").click()
            print(f"      → 下一题（答错）")
            time.sleep(1)
            continue

        # 新题：截图 + 计数
        q += 1
        if q % 3 == 1:
            d.screenshot("test.png")
        print(f"    📸 第{q}题")

        # 等渲染 + 选答案
        time.sleep(0.3)
        answered = False
        for opt in ("A","B","C","T","F"):
            try:
                if d(text=opt).exists(timeout=0.3):
                    d(text=opt).click()
                    print(f"      → 选 {opt}")
                    time.sleep(0.5)
                    answered = True
                    break
            except Exception: pass
        if not answered:
            continue

        # 点检查
        try:
            d(text="检查").click(timeout=1.5)
            print(f"      → 检查")
        except Exception:
            continue
        time.sleep(0.5)
        # 回到循环开头：答对自动跳转/答错出下一题/最后一题出练习报告，都在上面处理

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
            # 子模块切换：左滑直到页面上出现目标子模块名（继续练习后会重置回基础巩固）
            act = sub.get("enter_action")
            if act in ("swipe_left", "swipe_left_sub"):
                target = sub["name"]   # 如"综合进阶"/"难点突破"
                reached = False
                for _ in range(6):    # 最多左滑6次（重置回基础巩固时最多滑2次）
                    # 先看当前页是否已是目标
                    if any(target in (e.text or "") for e in (d.xpath('//*[@text!=""]').all() or [])):
                        reached = True
                        break
                    d.swipe_ext("left", scale=0.5)
                    time.sleep(2)
                print(f"    👈 左滑 → {sub['name']}" + (" ✅" if reached else " ⚠ 未确认"))
            # 答题入口：必须找到"重新答题"或"开始答题"才能开始
            for retry in range(8):
                if d(text="重新答题").exists(timeout=1) or d(text="开始答题").exists(timeout=1):
                    break
                time.sleep(0.5)
            pa = config.get("post_entry_actions", [])
            if pa: execute_actions(d, pa, name)
            # 答题（传入是否最后一个子模块）
            config['_is_last_sub'] = (i == len(sm) - 1)
            q = _answer_loop(d, config, name)
            questions += q
            # 最后子模块：back 回单元列表
            if config['_is_last_sub']:
                for _ in range(4):
                    if d(text="去练习").exists(timeout=1.5):
                        break
                    d.press("back"); time.sleep(1.5)
                print(f"    👋 back → 单元列表")
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
