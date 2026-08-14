"""
英语宝 · 自动化引擎
===================
close_ad / ensure_grade / run_single_module 等核心逻辑
"""
import uiautomator2 as u2
import os, time, re
from config import MODULE_CONFIG, GLOBAL_POPUPS, APP_PACKAGE, GRADE_LEVEL, BOOK_VERSION
from common.tools import S, S_swipe, S_h, S_w, applock_blocked, settle_ads
from common.logger import step_log, should_stop
from question_types import detect_question_type


def _find_control(xml: str, keywords: tuple) -> tuple:
    """在 XML 中查找含关键词的控件节点，返回 (found, clickable)
    - 逐节点匹配 text/content-desc 含任一关键词
    - ★ 也匹配 resource-id 中的 play/sound/audio/speaker 模式
      （真实 App 扬声器按钮常是 rid=id/play_box，text/content-desc 为空）
    - clickable 取该节点是否 clickable="true"
    """
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        for kw in keywords:
            if kw in tag:
                clickable = 'clickable="true"' in tag
                return True, clickable
        if re.search(r'resource-id="[^"]*(play|sound|audio|speaker)[^"]*"', tag):
            clickable = 'clickable="true"' in tag
            return True, clickable
    return False, False


def close_ad(d):
    """关闭广告：多种策略按顺序尝试"""
    # 方式1：contentDescription 包含"关闭"
    try:
        if d(description="关闭").exists(timeout=1):
            d(description="关闭").click()
            print("    🔔 通过 description='关闭' 关闭广告")
            time.sleep(0.35)
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
                    time.sleep(0.35)
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
            if w < 80 and h < 80 and b[0] > S_w(d, 800) and b[1] > S_h(d, 600):
                elem.click()
                print(f"    🔔 通过小尺寸 clickable (X) 关闭广告 ({sum(b)//4},{h*1000})")
                time.sleep(0.35)
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
                time.sleep(0.35)
                return True
    except Exception:
        pass

    # 方式5：硬编码右上角坐标
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
    for t in GLOBAL_POPUPS:
        try:
            if d(text=t).exists(timeout=0.15):
                d(text=t).click()
                print(f"    🔔 全局弹窗: '{t}'")
                time.sleep(0.35)
                return True
        except Exception:
            pass
    return False

def scroll_and_find(d, text, max_swipes=8) -> bool:
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
    time.sleep(0.8)

    # 在弹层中找年级（可能需要向上滑）
    for _ in range(8):
        if d(text=grade_level).exists(timeout=1):
            break
        S_swipe(d, 500, 1400, 500, 400, 0.3)
        time.sleep(0.4)

    try:
        d(text=grade_level).click(timeout=3)
    except Exception:
        print(f"❌ 弹层中找不到 {grade_level}")
        d.press("back")
        return False
    time.sleep(0.8)

    # 确认按钮
    for btn in ("确定", "确认", "完成", "好的"):
        try:
            if d(text=btn).exists(timeout=1):
                d(text=btn).click()
                break
        except Exception:
            pass
    time.sleep(1.2)

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
        time.sleep(0.5)
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
    """处理排序题（两种子题型，用户约定）：
    
    模式A（图片排序：图片大卡片，宽>300）：
      ★ 直接依次点击图片 → 序号自动按点击顺序填充 → 出现"检查"
      ★ 不需要激活输入框！也不要点底部序号按钮
    模式B（人物/句子排序：句子方框宽~228）：
      点第一个方框激活输入框 → 依次点击底部序号按钮(1,2,3...) → 出现"检查"

    之后点"检查"，答对自动进下一题 / 答错点"下一题"。
    """
    print(f"    📋 识别到排序题，处理中...")
    step_log("🔢 检测到排序题，开始处理…", "step")

    # ── 先区分两种子题型 ──
    # 图片排序特征：y 700-1900 有宽度 300-700 的图片卡片
    # （排除全屏大容器 宽>800，那是句子排序的整块布局）
    has_big_image = False
    big_images = []
    for e in (d.xpath('//*[@clickable="true"]').all() or []):
        b = e.bounds
        w = b[2] - b[0]
        if S_h(d, 700) < b[1] < S_h(d, 1900) and 300 < w < 700:
            has_big_image = True
            big_images.append(e)

    if has_big_image:
        # ── 模式A：图片排序 ── 直接点图片，序号自动填充
        print(f"    🖼 图片排序（模式A）：直接点图片，序号自动填充")
        step_log("🖼 图片排序：直接点图片，序号自动填", "step")
        clicked_keys = set()
        # 依次点击所有大图片（每张点一次）
        for _ in range(len(big_images) + 2):
            progress = False
            for elem in big_images:
                b = elem.bounds
                key = f"{b[0]}_{b[1]}"
                if key in clicked_keys:
                    continue
                try:
                    elem.click()
                    clicked_keys.add(key)
                    print(f"      → 点图片 ({b[0]},{b[1]})")
                    time.sleep(0.4)
                    progress = True
                except Exception:
                    pass
            if not progress:
                break
        # 点完所有图片 → 出现"检查" → 点它
        for _ in range(8):
            if d(text="检查").exists(timeout=1):
                d(text="检查").click()
                print(f"    ✅ 图片排序完成，点击检查")
                time.sleep(0.35)
                return True
            time.sleep(0.5)
        # 兜底：直接出"下一题"
        if d(text="下一题").exists(timeout=1):
            d(text="下一题").click()
            print(f"    ✅ 图片排序完成，点击下一题")
            time.sleep(0.35)
            return True
        return False

    # ── 模式B：人物/句子排序 ── 点方框激活 + 点底部序号
    print(f"    🔢 人物/句子排序（模式B）：点方框激活 → 点序号")
    step_log("🔢 方框排序：点方框激活 → 点序号", "step")
    # 1. 点第一个方框（y 700-1900、宽度100-300的可点击元素，即句子方框）
    clicked_box = False
    for e in (d.xpath('//*[@clickable="true"]').all() or []):
        b = e.bounds
        if S_h(d, 700) < b[1] < S_h(d, 1900) and 100 < b[2] - b[0] < 300:
            try:
                e.click()
                print(f"      → 点第一个方框激活")
                time.sleep(0.6)
                clicked_box = True
                break
            except Exception:
                pass
    if not clicked_box:
        print(f"    ⚠ 未找到方框，仍尝试点序号")

    # 2. 动态检测底部序号按钮，依次点 1,2,3,4,5
    #    ★ 关键：点序号1后"检查"按钮会出现导致坐标变化！
    #    ★ 点完序号1后序号栏会整体上移（y~1877 → y~1786）
    #    ★ 必须每次点完序号后重新检测序号栏位置
    #    ★ 检查按钮在更底部 y~2334（不参与检测）
    def _find_num_btns():
        """检测底部序号按钮位置。
        序号按钮特征：y 1680-2200、宽 200-300、x 起点为 0 或 242 的倍数（不是 58）
        ★ 关键：x 起点 58 是句子方框，必须排除！
        ★ dump 找不到时（图片绘制的序号按钮）→ 坐标兜底：
          在底部大区域（y>1700 宽>800）5 等分估算序号按钮位置
        """
        btns = []
        for e in (d.xpath('//*[@clickable="true"]').all() or []):
            b = e.bounds
            w = b[2] - b[0]
            # x 起点 58 是句子方框，跳过
            # y 上限放宽到 2200（兼容知识过关连词成句的单词按钮 y~2044-2141）
            if S_h(d, 1680) < b[1] < S_h(d, 2200) and 200 < w < 300 and b[0] != 58:
                cx = (b[0] + b[2]) // 2
                cy = (b[1] + b[3]) // 2
                btns.append((cx, cy, b[0], b[1]))
        # 按 y 然后 x 排序（左上优先）
        btns.sort(key=lambda t: (t[1], t[0]))

        # ★ 坐标兜底：dump 找不到 → 图片绘制序号按钮
        if not btns:
            try:
                for e in (d.xpath('//*[@clickable="true"]').all() or []):
                    b = e.bounds
                    w = b[2] - b[0]
                    if b[1] > S_h(d, 1650) and w > 800 and (b[3] - b[1]) < 350:
                        # 底部大区域（听力内容区/按钮区）5 等分
                        area_x1, area_x2 = b[0], b[2]
                        area_y = (b[1] + b[3]) // 2 + 30
                        step = (area_x2 - area_x1) // 10
                        for i in range(5):
                            btns.append((area_x1 + step * (2 * i + 1), area_y, 0, 0))
                        break
            except Exception:
                pass
            if not btns:
                # 终极兜底：屏幕底部 5 等分
                h = d.window_size()[1]
                w = d.window_size()[0]
                step = w // 10
                for i in range(5):
                    btns.append((step * (2 * i + 1), int(h * 0.85), 0, 0))
        return btns

    # 点 1-5 序号：每次动态检测序号栏，序号栏空了（全部填完）才停止。
    # ★ 关键修复：之前"点一个序号发现检查出现就 break"是错的——点第一个序号后
    #   "检查"就已出现，但必须填满所有序号才能提交，否则会漏答（只填1个就检查）。
    for target in range(1, 6):
        # 每次重新检测序号栏（点完序号后该序号被消耗、栏位变化）
        btns = _find_num_btns()
        if not btns:
            print(f"      → 序号栏已空，第{target-1}个序号填完")
            break
        try:
            d.click(btns[0][0], btns[0][1])
            print(f"      → 点序号{target} @({btns[0][0]},{btns[0][1]})")
            time.sleep(0.5)
        except Exception:
            pass

    # 3. 出现检查 → 点它（兼容"检测"；最后一题检查后出"查看报告"也点）
    for _ in range(10):
        if d(text="检查").exists(timeout=0.8):
            d(text="检查").click()
            print(f"    ✅ 排序完成，点击检查")
            time.sleep(0.5)
            continue  # 检查后可能出查看报告/下一题
        if d(text="检测").exists(timeout=0.8):
            d(text="检测").click()
            print(f"    ✅ 排序完成，点击检测")
            time.sleep(0.5)
            continue
        if d(text="查看报告").exists(timeout=0.8):
            # 最后一题：查看报告已出现，交给外层答题循环统一点击（避免重复处理）
            print(f"    ✅ 排序完成，查看报告已出现")
            return True
        if d(text="下一题").exists(timeout=1):
            print(f"    ✅ 排序完成，下一题已出现")
            return True
        time.sleep(0.5)
    # ★★ 关键修复：循环结束仍无"检查/检测/查看报告/下一题" = 排序未完成
    #   （可能序号没点中/页面还在加载）→ 必须返回 False 让主循环等待重试！
    #   ❌ 之前无条件 return True → 失败也被主循环 q+=1 计一次 → 17题被计两次
    #      → q 与真实题号错位 → 下一题"题号未推进超时"卡死（本次 18/36 卡死根因）
    return False


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


def _handle_sentence_sort(d, config):
    """处理「句子圆圈排序题」（听录音，给句子排序）

    ★ 与空方框排序题的区别（防混淆）：
      - 句子圆圈排序题：句子前面是「圆圈」（待填序号），**没有底部序号按钮**，
        **不需要激活**——直接按顺序把句子全部点击掉，序号自动按 1,2,3... 依次填入
        （点击句子 → 自动分配当前最小序号；全部句子点完 → 出现「检查」）
      - 空方框排序题：句子是空方框，需要「点方框激活输入框 → 底部序号按钮才出现 →
        点序号填入」——那个用 _handle_sort_question

    识别特征：有 ≥3 个整行句子 LinearLayout（宽 > 800，y 700-1900）。
    注意：**没有底部序号按钮**（点击句子自动填），这是与空方框题的最大区别。
    """
    import time
    print(f"    📝 句子圆圈排序题：直接按顺序点击句子（序号自动填入）")
    step_log("📝 圆圈排序题：直接点句子", "step")

    def _find_sentences():
        """找未填的整行句子（宽 > 800，y 700-1900）。
        两种控件形态都要支持：
        - LinearLayout clickable=true（旧版句子）
        - CheckBox / option_cb（圆圈排序题：checkable=true 但 clickable=false，
          只能通过 dump 正则匹配 class="android.widget.CheckBox"，text 是句子内容）
        ★ 圆圈排序题判断"已填"的关键：句子旁的小圆圈 CheckBox（86x86，text 空）
          点击句子后小圆圈 checked=true 且 text 变成序号数字；未填则 checked=false,text=''
          句子本身的 checked 永远 false，不能用于判断！
        """
        import re
        xml = d.dump_hierarchy()
        # 收集两类 CheckBox：句子（宽>800 带文本）和小圆圈（宽60-120 text 空）
        sentences = []   # (cx, cy, y1)
        circles = []     # (cx, cy, y1, checked)
        for m in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*/?>', xml):
            tag = m.group(0)
            tm = re.search(r'text="([^"]*)"', tag)
            cm = re.search(r'checked="(true|false)"', tag)
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not (tm and cm and bm):
                continue
            txt = tm.group(1)
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            w = x2 - x1
            cy = (y1 + y2) // 2
            cx = (x1 + x2) // 2
            if len(txt) >= 6 and w > 800 and 700 < y1 < 1900:
                sentences.append((cx, cy, y1))
            elif w <= 130 and 700 < y1 < 1900:  # 小圆圈
                circles.append((cx, cy, y1, cm.group(1)))
        # LinearLayout 形态（旧版，无小圆圈，直接算未填）
        sents_ll = []
        for m in re.finditer(
            r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml
        ):
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            w = x2 - x1
            if w > 800 and 700 < y1 < 1900:
                sents_ll.append(((x1 + x2) // 2, (y1 + y2) // 2, y1))
        if not sentences and sents_ll:
            return sorted(sents_ll, key=lambda t: t[2])

        # 圆圈排序题：句子按 y 匹配最近的小圆圈，小圆圈 checked=false 才算未填
        result = []
        for cx, cy, y1 in sentences:
            # 找 y 最接近的小圆圈
            best = None
            for ccx, ccy, cy1, cchk in circles:
                if abs(ccy - cy) < 100:
                    if best is None or abs(ccy - cy) < abs(best[1] - cy):
                        best = (ccx, ccy, cy1, cchk)
            if best and best[3] == "true":
                continue  # 小圆圈已填序号 → 跳过
            result.append((cx, cy, y1))
        result.sort(key=lambda t: t[2])
        return result

    # 依次点击句子（每次重检位置，防布局变化）；填到「检查」出现为止
    clicked = 0
    for target in range(1, 6):
        # 每次重新检测句子位置（点完一个后布局可能微调）
        sentences = _find_sentences()
        if not sentences:
            print(f"      ⚠ 找不到句子（第{target}次）")
            break
        # 取第一个未填的句子点击（序号自动分配）
        cx, cy, y1 = sentences[0]
        try:
            d.click(cx, cy)
        except Exception:
            pass
        clicked += 1
        print(f"      {target}. 点句子 @({cx},{cy})")
        time.sleep(0.4)
        # 填完后检查/检测/查看报告出现 → 完成
        if (d(text="检查").exists(timeout=0.8)
                or d(text="检测").exists(timeout=0.8)
                or d(text="查看报告").exists(timeout=0.8)):
            print(f"      → 点完第{target}个后出现按钮，停止")
            break

    time.sleep(0.4)
    # 出现检查/检测 → 点击
    for kw in ("检查", "检测"):
        if d(text=kw).exists(timeout=2):
            try:
                d(text=kw).click()
            except Exception:
                pass
            print(f"    ✅ 句子排序完成，点击{kw}")
            time.sleep(0.6)
            return True
    print(f"    ⚠ 句子点完{clicked}个但未出现检查按钮")
    # ★★ 与 _handle_sort_question 同样修复：未完成必须返回 False，
    #   否则失败也被主循环 q+=1 计数 → q 错位 → 后续"题号未推进"卡死
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
    step_log("📋 检测到匹配题，开始配对…", "step")

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
                        time.sleep(0.4)
                        break
                    except Exception:
                        pass
            if clicked_box:
                break
    if not clicked_box:
        print(f"    ⚠ 未找到人物方框，尝试直接处理")
        time.sleep(0.5)

    # 2. 收集字母选项 A-E
    #   ★ 修复：图片/人物匹配题（听力专项）点方框后字母选项才延迟渲染出现，
    #     只查一次会漏 → 轮询等待字母出现（最多5轮，每轮重试点方框一次兜底）
    letters = []
    for _try in range(5):
        letters = []
        for ch in ("A", "B", "C", "D", "E"):
            try:
                if d(text=ch).exists(timeout=0.2):
                    letters.append(ch)
            except Exception:
                pass
        if letters:
            break
        # 字母还没出现 → 再点一次方框（首轮已点过，这里是重试兜底）
        time.sleep(0.5)
    print(f"    字母选项{len(letters)}个: {letters}")
    if not letters:
        print(f"    ⚠ 未找到字母选项"); return False

    # 3. 把字母全部点完（每个点一次；点字母自动配对并切换下一个人物）
    #    关键：即使"检查"提前出现，也要把 A-E 全部点完再检查！
    clicked_letters = set()
    for _ in range(len(letters) + 2):   # 最多轮转 letters数+2 次
        # 每轮尝试点所有未点过的字母
        for ch in letters:
            if ch in clicked_letters:
                continue
            try:
                if d(text=ch).exists(timeout=0.6):
                    d(text=ch).click()
                    clicked_letters.add(ch)
                    print(f"      → 点字母: {ch}")
                    time.sleep(0.3)
            except Exception:
                pass
        if len(clicked_letters) >= len(letters):
            break
    print(f"    ✅ 字母选项已全部点完: {sorted(clicked_letters)}")

    # 4. 全部点完后，出现"检查"→ 点它
    for _ in range(8):
        if d(text="检查").exists(timeout=1):
            d(text="检查").click()
            print(f"    ✅ 匹配题点完，点击检查")
            time.sleep(0.35)
            # 检查后：最后一题可能出现"练习报告"（答完反馈页）
            #   ★ 必须先处理"练习报告"，否则反馈页残留"匹配"文字会被误判成匹配题死循环
            if d(text="练习报告").exists(timeout=1.5):
                d(text="练习报告").click()
                print(f"    ✅ 匹配题完成，点击练习报告")
                time.sleep(0.6)
            return True
        time.sleep(0.5)

    # 5. 若检查后答错出现"下一题"→ 点它进入下一题
    if d(text="下一题").exists(timeout=1):
        d(text="下一题").click()
        print(f"    ✅ 匹配完成，点击下一题")
        time.sleep(0.35)
        return True
    return False


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


def _handle_select_fill(d, config):
    """★ 选词填空（听力专项新题型）：
    句子中嵌 N 个空格框（CheckBox, resource-id=.../select_tv），底部是词库
    （TextView, resource-id=.../select_btn）。
    交互（实测确认）：点空格框 → 该空格被激活（checked=true）→ 点底部词库词
    → 词填入该空格，词库词仍保留可选。
    处理流程：
      1. 收集所有空格框（select_tv，含 text 为空的和已填词的），按 y 排序
      2. 收集词库词（select_btn，text 非空），按 y/x 排序
      3. 对每个空格：点它（激活）→ 点词库词 → 循环（每个空格一个词）
      4. 全部填完 → 找"检查/检测"按钮点击 → 点"下一题"
    返回 True=已处理；False=非选词填空页
    """
    import re as _re
    print(f"    🔤 选词填空，处理中...")
    step_log("🔤 选词填空：点空格→点词填入", "step")

    # 1. 解析空格框与词库词
    def _parse():
        """返回 (blanks, word_btns)：
        blanks: [(cx, cy, filled_text, y)] 按 y 排序；filled_text 非空=已填
        word_btns: [(cx, cy, word, y, x)] 词库词
        """
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return [], []
        blanks = []
        word_btns = []
        for m in _re.finditer(r'<node[^>]*>', xml):
            tag = m.group(0)
            rid = _re.search(r'resource-id="([^"]*)"', tag)
            if not rid:
                continue
            ridv = rid.group(1)
            tm = _re.search(r'text="([^"]*)"', tag)
            bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            tv = (tm.group(1) if tm else "").strip()
            if ridv.endswith("/select_tv"):
                # 空格框：可能含已填词文本（text 非空=已填）
                blanks.append((cx, cy, tv, y1))
            elif ridv.endswith("/select_btn"):
                # 词库词
                if tv:
                    word_btns.append((cx, cy, tv, y1, x1))
        blanks.sort(key=lambda t: t[3])
        word_btns.sort(key=lambda t: (t[3], t[4]))
        return blanks, word_btns

    blanks, word_btns = _parse()
    if not blanks or not word_btns:
        print("    ⚠ 未识别到空格框/词库词，跳过选词填空")
        return False
    print(f"      空格框 {len(blanks)} 个, 词库 {len(word_btns)} 个: {[w[2] for w in word_btns]}")

    # 2. 逐空格填词：点空格(激活) → 点词库词
    #   ★ 每填一个词后布局会重排（空格框位置/大小变化），重新解析
    filled_cnt = 0
    for _ in range(len(blanks) + 3):
        blanks_now, word_btns_now = _parse()
        if not blanks_now or not word_btns_now:
            break
        # 找第一个未填的空格（text 为空）
        empty = [b for b in blanks_now if not b[2]]
        if not empty:
            break
        bx, by = empty[0][0], empty[0][1]
        # 点空格激活
        try:
            d.click(bx, by)
        except Exception:
            continue
        time.sleep(0.5)
        # 点词库第一个未用词（简单策略：按序填入；听力题无法听音选词，
        #   程序只保证不卡流程，答对与否由人工/后续改进）
        w = word_btns_now[filled_cnt % len(word_btns_now)]
        try:
            d.click(w[0], w[1])
        except Exception:
            continue
        print(f"      空格({bx},{by}) ← {w[2]}")
        step_log(f"  🔤 填词: {w[2]}", "info")
        filled_cnt += 1
        time.sleep(0.6)

    # 3. 全部填完 → 找"检查/检测" → 点击
    for _ in range(6):
        btn = None
        if d(text="检查").exists(timeout=1.2):
            btn = "检查"
        elif d(text="检测").exists(timeout=0.8):
            btn = "检测"
        if btn:
            d(text=btn).click()
            print(f"    ✅ 选词填空完成，点击{btn}")
            step_log("✅ 选词填空全部完成", "success")
            time.sleep(0.8)
            break
        S_swipe(d, 540, 1800, 540, 600, 0.4)
        time.sleep(0.6)

    # 4. 点"下一题"（答对自动跳，答错出按钮）
    if d(text="下一题").exists(timeout=2):
        d(text="下一题").click()
        print(f"      → 下一题（选词填空答完）")
        time.sleep(0.8)
    return True


def _answer_loop(d, config, module_name):
    """答题循环（内部复用），返回题目数。
    
    ★ 性能优化：每轮循环只 dump 一次 XML（≈200ms），后续所有文本判断/坐标获取
      都在内存做字符串匹配，消灭每次循环 ~20 次设备 HTTP 交互（exists/xpath）。
      只在执行 click 改变页面后重新 dump。
    """
    q = 0
    _idle = 0  # 连续空转计数（无选项且无题型匹配），防倒计时被误计/死循环
    _xml = ""  # 当前 UI 缓存
    _need_dump = True  # 需要在下一轮重新 dump

    def _collect_ui_evidence(qtype):
        """每题界面级检查证据（题型/题干/选项/音频/作答）→ 前端证据卡展示"""
        import re as _re
        ev = []
        try:
            # ① 题型识别
            ev.append({"field": "题型", "type": "text_ok",
                       "expected": qtype or "选择题",
                       "actual": qtype or "选择题", "diff": f"识别为[{qtype or '选择题'}]"})
            # ② 题干文字：★ 优先 question_title_tv，再兼容普通 text（过滤提示词）
            stems = []
            seen = set()
            _noise = ("下一题", "上一题", "检查", "检测", "提交", "开始答题", "重新答题",
                      "继续练习", "查看报告", "练习报告", "完成", "点击录音", "点击结束",
                      "原音", "小喇叭", "跳过", "温馨提示", "继续答题", "恭喜",
                      "回答正确", "回答错误", "很遗憾", "答对了", "答错了",
                      "练习结束还剩", "还剩", "得分", "用时", "获得", "本题得分")
            # ★ 时间/得分/进度等非题干文本（状态栏时间 21:12、得分 77.0、进度 3/40）
            _timer_pat = _re.compile(r"^\d{1,2}:\d{2}$|^还剩[：:]\s*\d{1,2}:\d{2}$|^\d+(\.\d+)?%?$|^\d+\s*/\s*\d+$|^\d+分$")
            for m in _re.finditer(r'resource-id="[^"]*question_title_tv[^"]*"[^>]*text="([^"]+)"', _xml):
                t = m.group(1).strip()
                if t and t not in seen:
                    seen.add(t); stems.append(t)
                if len(stems) >= 3: break
            for m in _re.finditer(r'text="([^"]{4,})"', _xml):
                t = m.group(1).strip()
                if not t or t in seen: continue
                # ★ 过滤非题干文本（图片提示、按钮文字、反馈、时间/得分等）
                if t in ("点击图片查看高清大图", "查看高清大图", "点击查看高清大图"): continue
                if "点击图片" in t or "高清大图" in t: continue
                if any(n in t for n in _noise): continue
                if _timer_pat.match(t): continue          # ★ 时间/得分/进度
                if len(t) >= 60: continue
                seen.add(t); stems.append(t)
                if len(stems) >= 3: break
            stem_txt = " / ".join(stems[:2]) if stems else "(无题干文字)"
            ev.append({"field": "题干", "type": "text_ok" if stems else "text_mismatch",
                       "expected": "文字完整可见", "actual": stem_txt,
                       "diff": f"提取到{len(stems)}条文字" if stems else "⚠ 未提取到题干文字"})
            # ③ 选项存在性
            opts_found = [o for o in ("A", "B", "C", "D", "T", "F")
                          if f'text="{o}"' in _xml]
            ev.append({"field": "选项", "type": "text_ok" if opts_found else "text_mismatch",
                       "expected": "存在可选项", "actual": ",".join(opts_found) or "(无)",
                       "diff": f"检测到 {len(opts_found)} 个选项"})
            # ④ 音频/语音控件检查（★ 结合题型：听力题查扬声器、口语题查小喇叭+麦克风，均查可点击）
            # ★ 关键词判断直接基于整段 XML（短题干如"跟读句子"也能命中）
            LISTEN_KWS = ("听录音", "听音", "听一听", "听对话", "听短文", "听句子",
                          "听单词", "listen", "听下面", "听材料", "听问题")
            # ★ 扩展口语/跟读关键词：知识过关模块常用"跟读单词""读一读""朗读句子""大声朗读"
            SPEAK_KWS = ("朗读", "读一读", "跟读", "读单词", "读句子", "大声读",
                         "repeat", "口语", "跟录音读", "大声朗读", "读下面",
                         "跟读单词", "跟读句子", "跟读短文", "read", "speak")
            is_listening = any(kw in _xml for kw in LISTEN_KWS)
            is_speaking = any(kw in _xml for kw in SPEAK_KWS)
            PLAY_KWS = ("播放", "喇叭", "扬声器", "ic_play", "btn_play",
                        "play_btn", "audio", "sound", "▶", "play_box")
            MIC_KWS = ("麦克风", "录音", "record", "mic", "开始作答",
                       "mic_box", "start_record")
            play_found, play_clickable = _find_control(_xml, PLAY_KWS)
            mic_found, mic_clickable = _find_control(_xml, MIC_KWS)
            if is_listening:
                if play_found:
                    ev.append({"field": "音频", "type": "text_ok" if play_clickable else "text_mismatch",
                               "expected": "听力题须有可点击的扬声器",
                               "actual": "播放控件" + ("(可点击)" if play_clickable else "(存在但不可点击)"),
                               "diff": ("扬声器/播放标识可见且可点击（题干含'听录音'）" if play_clickable
                                        else "⚠ 扬声器存在但不可点击（无法播放音频）")})
                else:
                    ev.append({"field": "音频", "type": "text_mismatch",
                               "expected": "听力题须有扬声器/播放标识",
                               "actual": "未检测到播放控件",
                               "diff": "⚠ 题干含'听录音'但页面未检测到扬声器/播放标识"})
            elif is_speaking:
                # ★ 口语题/跟读题：同时检查播放键（听原音）+麦克风（录音作答）
                ev.append({"field": "音频", "type": "text_ok" if play_clickable else "text_mismatch",
                           "expected": "口语题须有可点击的播放控件(小喇叭/导读音频)",
                           "actual": "播放控件" + ("(可点击)" if play_clickable else "(存在但不可点击)") if play_found else "未检测到播放控件",
                           "diff": ("小喇叭/播放标识可见且可点击" if play_clickable
                                    else ("⚠ 小喇叭存在但不可点击（无法播放音频）" if play_found
                                          else "⚠ 口语题未检测到小喇叭/播放控件"))})
                ev.append({"field": "作答", "type": "text_ok" if mic_clickable else "text_mismatch",
                           "expected": "口语题须有可点击的麦克风(录音作答)",
                           "actual": "麦克风/录音控件" + ("(可点击)" if mic_clickable else "(存在但不可点击)") if mic_found else "未检测到麦克风",
                           "diff": ("麦克风/录音控件可见且可点击" if mic_clickable
                                    else ("⚠ 麦克风存在但不可点击（无法录音）" if mic_found
                                          else "⚠ 口语题未检测到麦克风/录音控件"))})
            else:
                ev.append({"field": "音频", "type": "skip",
                           "expected": "非听力/口语题",
                           "actual": "—",
                           "diff": "题干无'听录音/朗读'等关键词，本题非听力/口语题，无需音频"})
            # ⑤ 作答元素（★ 多信号检测：检查/检测/录音/输入/选项/可点击大图，特殊题型不再误判）
            _act = (
                "检查" in _xml or "检测" in _xml or "完成" in _xml or "提交" in _xml
                or "录音" in _xml or "点击结束" in _xml or "点击录音" in _xml or "回放" in _xml
                or "EditText" in _xml or "麦克风" in _xml or "record" in _xml.lower()
                or bool(_re.search(r'text="[TFABCDE]"', _xml))
                or "CheckBox" in _xml
            )
            if not _act:
                _bc = _re.search(r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _xml)
                if _bc:
                    _bx1, _by1, _bx2, _by2 = (int(_bc.group(1)), int(_bc.group(2)),
                                              int(_bc.group(3)), int(_bc.group(4)))
                    if (_bx2 - _bx1) > 300 and (_by2 - _by1) > 150:
                        _act = True
            ev.append({"field": "作答", "type": "text_ok" if _act else "text_mismatch",
                       "expected": "可作答（检查/录音/输入/选项）", "actual": "可作答" if _act else "⚠ 未见作答元素",
                       "diff": "作答元素存在" if _act else "⚠ 检查/录音/输入元素未识别"})
        except Exception:
            pass
        return ev

    # ── 缓存辅助函数 ──
    def _dump():
        return d.dump_hierarchy()
    def _has(text):
        return f'text="{text}"' in _xml
    def _click_text(text, allow_miss=False):
        """从缓存 XML 拿坐标点击，找不到就返回 False"""
        m = re.search(r'text="'+re.escape(text)+r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _xml)
        if m:
            d.click((int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2)
            return True
        return False
    def _multi_has(*texts):
        """多文本中任一存在"""
        for t in texts:
            if _has(t): return True
        return False
    def _find_opt():
        """找第一个选项 A/B/C/T/F"""
        for opt in ("A","B","C","T","F"):
            if _has(opt):
                return opt
        return None
    # 题型关键词扫描（基于缓存 XML）
    def _has_keywords(*kws):
        for kw in kws:
            if kw in _xml: return True
        return False

    while q < 50:
        # ★ 停止检查：web_server 收到停止请求 → 立即中断当前模块
        if should_stop():
            step_log("⏹ 收到停止请求，中断当前模块", "warning")
            return q
        if _need_dump:
            _xml = _dump()
            _need_dump = False

        # 弹窗检测
        if _has("继续练习") and _has("先走一步"):
            _click_text("继续练习")
            print("      → 关弹窗")
            _idle = 0
            time.sleep(0.4)
            _need_dump = True; continue

        # ★ 完成判定优先于题型识别
        if _has("练习报告"):
            _click_text("练习报告")
            print(f"      → 练习报告（最后一题）")
            step_log(f"📊 练习报告（子模块完成，共{q}题）", "success")
            time.sleep(0.4); _xml = _dump()
            if not config.get('_is_last_sub', False):
                # ★ 非最后子模块：点"继续练习"回单元列表页（下一个子模块由
                #   外层循环左滑切换）。H5 报告页按钮 click 可能无效 → 坐标点击。
                _clicked_cont = False
                for _ in range(8):
                    if _has("继续练习"):
                        _m_cont = re.search(
                            r'text="继续练习"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                            _xml)
                        if _m_cont:
                            d.click((int(_m_cont.group(1)) + int(_m_cont.group(3))) // 2,
                                    (int(_m_cont.group(2)) + int(_m_cont.group(4))) // 2)
                        else:
                            _click_text("继续练习")
                        print(f"      → 继续练习（回列表）")
                        time.sleep(0.6); _xml = _dump()
                        _clicked_cont = True
                        # 验证回到列表（出现"重新答题/去练习/练习记录"任一）
                        if any(k in _xml for k in ("重新答题", "去练习", "练习记录")):
                            break
                    else:
                        time.sleep(0.5); _xml = _dump()
            print(f"      → 本子模块完成，返回")
            return q
        if _has("下一题"):
            # ★ 答错题目截图：捕获当前答错画面，供人工核验错题并同步到前端「最近截图」
            #   （文件名带模块标识，避免多模块练习互相覆盖；web_server 识别 evidence 写入面板）
            _wrong_shot = ""
            try:
                _shot_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "screenshots")
                os.makedirs(_shot_dir, exist_ok=True)
                # ★ 文件名彻底 ASCII 化：中文模块名（如"听力专项/难点突破"）转成
                #   ascii 编码的十六进制后缀，避免 Windows 写盘偶发 Errno 22
                #   （Invalid argument）。之前 re.sub(r"[^\w]","_") 保留中文，
                #   中文字符在部分 Windows/设备组合下截图写盘偶发失败。
                _mod_tag = re.sub(r"[^\w]", "_", module_name)[:12] or "mod"
                try:
                    _mod_tag = _mod_tag.encode("ascii", "ignore").decode("ascii") or "mod"
                except Exception:
                    _mod_tag = "mod"
                _wrong_shot = f"wrong_{_mod_tag}_q{q:02d}.png"
                # ★ 截图重试3次（uiautomator2 设备端截图偶发 Errno 22，重试可自愈）
                for _r in range(3):
                    try:
                        d.screenshot(os.path.join(_shot_dir, _wrong_shot))
                        break
                    except OSError:
                        if _r >= 2:
                            raise
                        time.sleep(0.5)
                print(f"      → 答错截图: {_wrong_shot}")
            except Exception as _e:
                print(f"      ⚠ 答错截图失败: {_e}")
            _click_text("下一题")
            print(f"      → 下一题（答错）")
            _idle = 0
            step_log(f"  第{q}题 答错截图", "warning",
                     evidence=[{"field": "错题截图", "type": "wrong_shot",
                                "screenshot": _wrong_shot}] if _wrong_shot else None)
            time.sleep(0.4); _need_dump = True; continue

        # 题型识别：基于缓存的字符串匹配（不再调 xpath）
        qtype = _detect_question_type_cached(_xml, config)
        if qtype == "sort_questions":
            q += 1  # ★ 排序题计数（之前遗漏，导致总题数少）
            step_log(f"📸 第{q}题（排序题）", "step")
            step_log(f"  第{q}题 检查", "info", _collect_ui_evidence("排序题"))
            _has_circle = 0
            for _m in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*/?>', _xml):
                _tag = _m.group(0)
                _tm = re.search(r'text="([^"]{6,})"', _tag)
                _bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _tag)
                if not (_tm and _bm): continue
                _x1, _y1 = int(_bm.group(1)), int(_bm.group(2))
                if (int(_bm.group(3)) - _x1) > 800 and 700 < _y1 < 1900:
                    _has_circle += 1
            if _has_circle >= 3:
                _handle_sentence_sort(d, config)
            else:
                _handle_sort_question(d, config)
            _idle = 0
            time.sleep(0.4); _need_dump = True; continue
        elif qtype == "match_questions":
            q += 1  # ★ 匹配题计数（之前遗漏，导致总题数少）
            step_log(f"📸 第{q}题（匹配题）", "step")
            step_log(f"  第{q}题 检查", "info", _collect_ui_evidence("匹配题"))
            _handle_match_question(d, config)
            _idle = 0
            time.sleep(0.4); _need_dump = True; continue
        elif qtype == "select_fill_questions":
            # ★ 选词填空（听力专项）：点空格→点词库词，全部填完→检查
            q += 1
            step_log(f"📸 第{q}题（选词填空）", "step")
            step_log(f"  第{q}题 检查", "info", _collect_ui_evidence("选词填空"))
            _handle_select_fill(d, config)
            _idle = 0
            time.sleep(0.4); _need_dump = True; continue
        elif qtype == "fill_blank_questions":
            # ★ 表格/短文补全（键盘注入）：复用 _handle_fill_blank
            q += 1
            step_log(f"📸 第{q}题（表格/短文补全）", "step")
            step_log(f"  第{q}题 检查", "info", _collect_ui_evidence("补全题"))
            _handle_fill_blank(d, config)
            _idle = 0
            time.sleep(0.4); _need_dump = True; continue
        elif qtype == "reading_multi_questions":
            # ★ 阅读多小题：多组字母选项，每题点一个选项，全点完才出检查
            q += 1
            step_log(f"📸 第{q}题（阅读多小题）", "step")
            step_log(f"  第{q}题 检查", "info", _collect_ui_evidence("阅读多小题"))
            _handle_reading_multi(d, _xml)
            _idle = 0
            time.sleep(0.4); _need_dump = True; continue

        # ── 单选/判断（兜底：有字母选项但无特殊题型关键词）──
        #   ★ 优化：直接从缓存的 _xml 找选项坐标，零设备交互
        opt = _find_opt()
        if not opt:
            # 无选项 → 倒计时/加载中/异常页：不计数，空转保护防死循环
            _idle += 1
            if _idle >= 15:
                step_log(f"⚠ 连续 {_idle} 轮无有效题目（可能停在非答题页/倒计时异常），退出答题循环", "warning")
                return q
            time.sleep(0.3); _need_dump = True
            continue
        _idle = 0
        q += 1
        print(f"    📸 第{q}题")
        step_log(f"📸 第{q}题", "step")
        # ★ 每题界面级检查证据 → 前端证据卡（题型/题干/选项/音频/作答）
        qtype_now = _detect_question_type_cached(_xml, config)
        step_log(f"  第{q}题 检查", "info", _collect_ui_evidence(qtype_now))
        time.sleep(0.3); _xml = _dump()

        _click_text(opt)
        print(f"      → 选 {opt}")
        step_log(f"  第{q}题: 选 {opt} → 检查", "info")
        # ★ 提速+防竞态：轮询等"检查"出现（替代固定 sleep(0.5)），页面快则立即继续
        _t_check = time.time()
        _check_found = False
        while time.time() - _t_check < 1.8:
            _xml = _dump()
            if "检查" in _xml or "检测" in _xml:
                _check_found = True
                break
            time.sleep(0.1)
        if not _check_found:
            time.sleep(0.3)  # 兜底：慢加载再等一次
        if _has("检查") or _has("检测"):
            _click_text("检查" if _has("检查") else "检测")
            print(f"      → 检查")
            time.sleep(0.4); _need_dump = True
        continue

    return q


def _detect_question_type_cached(_xml, config):
    """★ 统一题型检测入口：遍历 question_types.py 汇总的题型表，
       按优先级匹配关键词 + DOM特征，返回题型标识名。
    """
    return detect_question_type(_xml)


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
            time.sleep(0.8)
        for _ in range(4):
            if d(text="去练习").exists(timeout=1.5):
                return
            d.press("back"); time.sleep(0.6)
        return
    else:
        # 非最后：报告页 → 点"继续练习" → 回到单元内 → 左滑下一关
        after = ra.get("after_report", [])
        # 等报告页完全加载（成绩动画）
        for _ in range(8):
            if d(text="继续练习").exists(timeout=1.5):
                break
            time.sleep(0.4)
        # 点继续练习
        execute_actions(d, after, sub_name)
        # 等回到单元内（出现"开始答题"或"重新答题"）
        for _ in range(8):
            if d(text="重新答题").exists(timeout=1) or d(text="开始答题").exists(timeout=1):
                return
            time.sleep(0.4)
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
    # ★ 点击入口【前】必须先清广告：广告延迟加载并覆盖入口卡片，直接点文字坐标会
    #   点到广告上 → 打开外链触发 OPPO 系统验证弹窗（使用面部验证/密码验证）→ 全流程卡死。
    #   （用户定位：只有点到广告才会弹这个验证框）
    settle_ads(d, wait_total=8)
    # ★ 修复：不能用 d(text=entry).click()——页面可能多处含该文字（顶栏tab+入口卡片），
    #   exists() 命中后 click() 可能点到不可见节点 → UiObjectNotFoundError。
    #   改用 dump 找可点击容器坐标点击，并验证进入（出现"去练习/去答题/练习记录"等）。
    _entered = False
    for _try in range(5):
        try:
            _xml_entry = d.dump_hierarchy()
        except Exception:
            _xml_entry = ""
        _m_entry = re.search(
            rf'text="{re.escape(entry)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            _xml_entry)
        if _m_entry:
            _ex = (int(_m_entry.group(1)) + int(_m_entry.group(3))) // 2
            _ey = (int(_m_entry.group(2)) + int(_m_entry.group(4))) // 2
            d.click(_ex, _ey)
            print(f"  ✅ 点击入口 {entry} @({_ex},{_ey})")
            time.sleep(1.2)
            # 验证进入模块（出现模块内特征文字）
            try:
                _xml_after = d.dump_hierarchy()
                if any(k in _xml_after for k in ("去练习", "去答题", "练习记录", "重新答题", "开始答题")):
                    _entered = True
                    break
            except Exception:
                pass
        else:
            time.sleep(0.8)
    if not _entered:
        # 兜底：直接用 text 点击
        try:
            d(text=entry).click()
            print(f"  ✅ 已进入 {module_name}（text点击兜底）")
            _entered = True
            time.sleep(0.8)
        except Exception as _e:
            print(f"  ❌ 点击入口失败: {_e}")
            return 0
    print(f"  ✅ 已进入 {module_name}")
    time.sleep(0.8)

    # ★ 系统验证弹窗（点到广告触发）→ 先等它自动消失；持续不退 → back 关闭 + 清广告重试一次
    if applock_blocked(d):
        _cleared = False
        for _lk in range(10):
            time.sleep(0.5)
            if not applock_blocked(d):
                _cleared = True
                break
        if _cleared:
            print(f"  ⏳ 系统验证弹窗已自动消失，继续…")
        else:
            d.press("back"); time.sleep(0.8)
            settle_ads(d, wait_total=6)
            if not applock_blocked(d):
                print(f"  ⏳ 系统验证弹窗已关闭（疑似点到广告），已清广告，继续…")
            else:
                print(f"  ❌ 被系统验证（使用面部验证/密码验证）挡住，请先解锁「{entry}」，再重新运行")
                return 0

    # ★ 广告延迟加载：进入模块页后广告可能刚好弹出，先关干净再继续（避免后续点击误触广告）
    settle_ads(d, wait_total=6)

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
        time.sleep(0.4)

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
            # ★ 停止检查：前端停止 → 中断子模块循环
            if should_stop():
                step_log("⏹ 收到停止请求，中断子模块循环", "warning")
                return
            name = f"{module_name}/{sub['name']}"
            print(f"  --- [{i+1}/{len(sm)}] {sub['name']} ---")
            # ★ 更新模块上下文中的子模块（stage）：让错题记录的 module_qno
            #   按"模块·子模块"重置计数（否则跨子模块累加，难点突破会显示第28题）
            try:
                from common.logger import set_current_module
                set_current_module(module_name, sub["name"])
            except Exception:
                pass
            # 子模块切换：固定规则（3个子模块固定顺序）
            #   第1个（基础巩固）：不滑；第2个（综合进阶）：左滑1次；第3个（难点突破）：左滑2次
            #   ★ 切换后读取页面当前子模块文字，展示"当前子模块: X"（用户要求知道测到哪了）
            act = sub.get("enter_action")
            # 读取页面上所有子模块相关文字（横排可能同时显示多个）
            def _sub_texts():
                out = []
                for e in (d.xpath('//*[@text!=""]').all() or []):
                    t = (e.text or "").strip()
                    if "Level" in t or "基础巩固" in t or "综合进阶" in t or "难点突破" in t or t.startswith("-"):
                        out.append(t)
                return out
            if act in ("swipe_left", "swipe_left_sub"):
                # 按固定次数左滑（i=1滑1次、i=2滑2次），每次滑完等页面稳定
                swiped = 0
                for _ in range(i):
                    d.swipe_ext("left", scale=0.5)
                    time.sleep(0.9)
                    swiped += 1
                # 如果目标名未出现在任一子模块文字中（上次遗留位置不同），补滑1次（最多补2次）
                for _ in range(2):
                    cur_texts = _sub_texts()
                    if any(sub["name"] in t for t in cur_texts):
                        break
                    d.swipe_ext("left", scale=0.5)
                    time.sleep(0.9)
                    swiped += 1
                cur_texts = _sub_texts()
                shown = next((t for t in cur_texts if sub["name"] in t), cur_texts[0] if cur_texts else "")
                step_log(f"📌 当前子模块: {shown or sub['name']}（第{i+1}/{len(sm)}个，左滑{swiped}次）", "step")
                print(f"    👈 切到 {sub['name']}（左滑{swiped}次）→ 当前显示: {shown or '?'}")
            else:
                # 第1个子模块：先右滑回最左（基础巩固），处理上次遗留位置（可能停在 Level 3）
                for _ in range(4):
                    cur_texts = _sub_texts()
                    if any("基础巩固" in t for t in cur_texts):
                        break
                    d.swipe_ext("right", scale=0.5)
                    time.sleep(0.9)
                # 读取展示
                cur_texts = _sub_texts()
                shown = next((t for t in cur_texts if sub["name"] in t), cur_texts[0] if cur_texts else "")
                step_log(f"📌 当前子模块: {shown or sub['name']}（第{i+1}/{len(sm)}个，无需滑动）", "step")
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
            # ★ 非最后子模块：确保已回到列表页（若仍停在"练习报告"页，
            #   说明"继续练习"点击失败 → 再点一次/back 兜底，否则下个子模块左滑起点错乱）
            if not config['_is_last_sub']:
                for _ in range(4):
                    try:
                        _xml_back = d.dump_hierarchy()
                        if ("重新答题" in _xml_back or "去练习" in _xml_back
                                or "练习记录" in _xml_back):
                            break
                        if "继续练习" in _xml_back:
                            _m_cont = re.search(
                                r'text="继续练习"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                                _xml_back)
                            if _m_cont:
                                d.click((int(_m_cont.group(1)) + int(_m_cont.group(3))) // 2,
                                        (int(_m_cont.group(2)) + int(_m_cont.group(4))) // 2)
                            else:
                                d(textContains="继续练习").click()
                            time.sleep(0.6)
                        else:
                            d.press("back"); time.sleep(0.5)
                    except Exception:
                        break
            # 最后子模块：back 回单元列表
            if config['_is_last_sub']:
                for _ in range(4):
                    if d(text="去练习").exists(timeout=1.5):
                        break
                    d.press("back"); time.sleep(0.6)
                print(f"    👋 back → 单元列表")
            time.sleep(0.6)

    # 单元遍历
    if units:
        for ui, unit_num in enumerate(units):
            # ★ 停止检查：前端停止 → 中断单元循环
            if should_stop():
                step_log("⏹ 收到停止请求，中断单元循环", "warning")
                return
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
                            be.click(); time.sleep(1.6); clicked = True
                            break
                if clicked: break
                S_swipe(d, 500, 1800, 500, 600, 0.3); time.sleep(0.4)
            if not clicked:
                print(f"  ❌ U{unit_num} 找不到去练习"); continue
            print(f"  ✅ U{unit_num} 去练习")
            # 跑子模块
            run_sub_modules()
            # 回单元列表
            print(f"  ↩ 回单元列表...")
            for _ in range(5):
                if d(text="去练习").exists(timeout=1): break
                d.press("back"); time.sleep(0.6)
            time.sleep(0.4)
        # 所有单元完成后回主页
        print(f"  ↩ 回主页...")
        back_to_home(d, GRADE_LEVEL)
    else:
        # 无单元列表，直接跑 entry_actions + 子模块（或直接答题）
        run_sub_modules()

    return questions if (units or sub_modules) else 0


def _handle_reading_multi(d, xml=None):
    """阅读理解多小题：一屏含多道小题（每道小题有 T/F 或 A-E 选项组），
    ★ 必须把所有小题都选完（每组选1个选项，checked=true），"检查"按钮才会出现！
    返回 True=已处理完成；False=非多小题页面（单小题，走原逻辑）
    xml: 外部传入的 dump_hierarchy() 结果（速度优化：避免函数内重复 dump）
    """
    import re as _re
    time.sleep(0.2)

    # ★ 排除匹配题
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return False
    if any(kw in xml for kw in ('匹配', '配对', '为人物选择', '选择正确的描述')):
        return False

    def _groups(_xml):
        """解析页面 XML 中所有字母选项，按 y 聚类分组"""
        opts = []
        for m in _re.finditer(r'<node[^>]*text="([TFABCDE])"[^>]*>', _xml):
            tag = m.group(0)
            lm = _re.search(r'checked="(\w+)"', tag)
            bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            opts.append((m.group(1), (x1 + x2) // 2, (y1 + y2) // 2, y1,
                         bool(lm and lm.group(1) == "true")))
        groups = []
        for o in sorted(opts, key=lambda t: t[3]):
            if groups and abs(o[3] - groups[-1][0][3]) < 150:
                groups[-1].append(o)
            else:
                groups.append([o])
        return [g for g in groups if len(g) >= 2]

    groups = _groups(xml)
    if len(groups) < 2:
        return False

    print(f"    📖 阅读理解多小题: {len(groups)} 道小题待选")
    step_log(f"📖 阅读多小题 {len(groups)} 道，逐题选选项", "step")

    no_new = 0
    for _ in range(len(groups) + 12):
        xml = d.dump_hierarchy()
        groups = _groups(xml)
        pending = [g for g in groups if not any(o[4] for o in g)]
        if pending:
            g = sorted(pending[0], key=lambda o: o[1])
            o = g[0]
            d.click(o[1], o[2])
            print(f"      → 小题: 选 {o[0]}")
            time.sleep(0.6)
            no_new = 0
            continue
        if d(text="检查").exists(timeout=1.0):
            d(text="检查").click()
            print("    ✅ 多小题全部选完，点击检查")
            step_log("✅ 阅读多小题全部选完，已检查", "success")
            time.sleep(0.8)
            return True
        S_swipe(d, 540, 1800, 540, 800, 0.4)
        time.sleep(0.4)
        no_new += 1
        if no_new >= 4:
            break
    for _ in range(4):
        if d(text="检查").exists(timeout=1):
            d(text="检查").click()
            print("    ✅ 多小题兜底点击检查")
            time.sleep(0.8)
            return True
        S_swipe(d, 540, 1800, 540, 800, 0.4)
        time.sleep(0.4)
    return True


# ==================== ⑨ 填空题处理（新题型） ====================

# 键盘字母固定坐标（基于 1080×2400 屏幕截图实测）
# 键盘布局（4行）：
#   qwertyuiop (y=875)
#   asdfghjkl  (y=990)
#   小写/ zxcvbnm /删除 (y=1110)
#   123 / \' / 空格 / - / 英文 (y=1215)
_KEYBOARD_LETTERS = {
    'q': (60, 875), 'w': (170, 875), 'e': (280, 875), 'r': (390, 875),
    't': (500, 875), 'y': (610, 875), 'u': (720, 875), 'i': (830, 875),
    'o': (940, 875), 'p': (1020, 875),
    'a': (115, 990), 's': (225, 990), 'd': (335, 990), 'f': (445, 990),
    'g': (555, 990), 'h': (665, 990), 'j': (775, 990), 'k': (885, 990),
    'l': (995, 990),
    'z': (150, 1110), 'x': (265, 1110), 'c': (380, 1110), 'v': (495, 1110),
    'b': (610, 1110), 'n': (725, 1110), 'm': (840, 1110),
    ' ': (450, 1215),
}


def _handle_fill_blank(d, config):
    """处理填空题（方案一：FastInputIME 输入法注入，用户确认最稳定）：
    1. 循环找空 EditText（text='' 即未填；不能用坐标去重——填一个框后布局会变化）
    2. 每个方框：点方框获得焦点 → d.set_fastinput_ime(True) 切专用输入法
       → d.send_keys(word) 直接注入文本 → back 收起 → 重新 dump 找下一个空框
    3. 当前屏幕没有空框 → 下滑找新方框（补全短文题文字多，空框分布多屏）
    4. 全部填完 → 下滑找"检查"按钮 → 点击 → 点"下一题"
    关键：不点击系统键盘（uiautomator2 无法定位键盘），用 IME 注入绕过搜狗输入法
    """
    import random
    print(f"    填空题，处理中...")
    step_log("📝 补全短文/填空题：开始逐框输入", "step")

    # 开场：确保 EditText 可见（首次进入"补全短文"题时 App 会自动激活系统键盘
    #   把方框挡住，dump 里看不到 EditText 节点；先按 back 收起键盘）
    #   ★ 用户确认的正确时序（H5 填空页）：
    #     1) 进入填空页后页面加载 + 键盘弹出约需 4~5 秒
    #     2) 等页面加载完成（题干关键词出现）→ 等键盘弹出 → back 收键盘 → EditText 可见
    #   ★ 关键安全点：绝不能"没等页面加载完就 back"——back 会退出答题页弹"中途退出"！
    #     所以开场严格按序：先等题干出现（页面加载完）→ 等键盘弹出（mInputShown 或等待）
    #     → 再 back → 探测 EditText
    _FILL_KWS = ('填空', '补全', '每空', '填写', '填词', '完成小短文')
    _et_ok = False

    # ① 等页面加载完成（题干关键词出现 或 EditText 已可见）
    _page_loaded = False
    for _ in range(6):
        try:
            _xml_probe = d.dump_hierarchy()
            if 'class="android.widget.EditText"' in _xml_probe:
                _et_ok = True
                _page_loaded = True
                break
            if any(kw in _xml_probe for kw in _FILL_KWS):
                _page_loaded = True
                break
        except Exception:
            pass
        time.sleep(1.0)
    if not _page_loaded:
        print("    ⚠ 页面加载超时（未见填空题干），跳过填空处理")
        return False

    # ② 若 EditText 尚不可见（键盘挡住）→ 等键盘弹出 → back 收键盘（只一次！）
    #   ★ 关键：back 只执行一次。若收键盘后布局恢复慢、EditText 仍不可见，
    #     绝不能再次 back（键盘已收，再 back 会触发"中途退出"弹窗）！
    #     只继续等待探测，直到 EditText 出现或超时。
    if not _et_ok:
        time.sleep(4.0)   # 等键盘完全弹出
        try:
            _xml_probe = d.dump_hierarchy()
            if 'class="android.widget.EditText"' in _xml_probe:
                _et_ok = True
        except Exception:
            pass
        if not _et_ok:
            d.press("back")   # 收键盘（只一次！）
            # 等布局恢复 + 探测（最多等 10 秒，绝不重复 back）
            for _ in range(5):
                time.sleep(2.0)
                try:
                    _xml_probe = d.dump_hierarchy()
                    if 'class="android.widget.EditText"' in _xml_probe:
                        _et_ok = True
                        break
                except Exception:
                    pass
    if not _et_ok:
        # ★ 没有 EditText → 不是填空题（可能是阅读/图片选择题被误路由到这里），
        #   直接返回 False，避免 40 轮空转下滑+误点"检查"，把非填空题消费掉
        print("    ⚠ 未检测到 EditText，跳过填空处理")
        return False

    def _find_empty_inputs():
        """找所有 text='' 的 EditText（未填的空框），按 y 排序。
        关键：dump 节点属性顺序是 text 在 class 之前（NAF=true 节点），
        不能用 'class=...[^>]*text=...' 顺序正则，要整节点匹配后分别提取。
        """
        xml = d.dump_hierarchy()
        inputs = []
        for m in re.finditer(r'<node[^>]*class="android\.widget\.EditText"[^>]*>', xml):
            tag = m.group(0)
            tm = re.search(r'text="([^"]*)"', tag)
            val = tm.group(1) if tm else ''
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            cx, cy = (x1+x2)//2, (y1+y2)//2
            inputs.append((cx, cy, val, y1))
        inputs.sort(key=lambda t: t[3])
        return inputs

    words = ['apple', 'book', 'cat', 'dog', 'sun', 'tree', 'fish', 'bird', 'nice', 'good']
    no_new_swipes = 0  # 连续下滑无新空框次数

    # 阶段1：填所有空框（当前可见的填完 → 下滑找新的）
    for round_i in range(40):
        inputs = _find_empty_inputs()
        empty = [i for i in inputs if i[2] == '']  # text='' 即未填
        if empty:
            cx, cy = empty[0][0], empty[0][1]
            d.click(cx, cy)
            time.sleep(0.6)
            word = random.choice(words)
            try:
                # 方案一：切换 FastInputIME 输入法注入文本（绕过搜狗键盘）
                d.set_fastinput_ime(True)
                time.sleep(0.5)
                d.send_keys(word)
                time.sleep(0.5)
            except Exception:
                # 兜底：ADB input text（之前验证过第1个方框有效）
                try:
                    d.shell(f"input text {word}")
                    time.sleep(0.5)
                except Exception:
                    pass
            # 收起键盘
            d.press("back")
            time.sleep(0.6)
            print(f"    填一空 ({cx},{cy}) 字={word}")
            step_log(f"  ✏ 输入: {word}", "info")
            no_new_swipes = 0
            continue

        # 当前屏幕没有空框 → 下滑找新的（短文长，空框分布多屏）
        if no_new_swipes >= 3:
            break
        S_swipe(d, 540, 1800, 540, 800, 0.4)
        time.sleep(0.6)
        no_new_swipes += 1

    # 阶段2：下滑找"检查"按钮并点击（检查按钮在短文最底部，需下滑才能看到）
    #   兼容两种按钮文字：单元自检用"检查"，知识过关用"检测"
    for _ in range(6):
        btn = None
        if d(text="检查").exists(timeout=1.2):
            btn = "检查"
        elif d(text="检测").exists(timeout=0.8):
            btn = "检测"
        if btn:
            d(text=btn).click()
            print(f"    填空完成，点击{btn}")
            step_log("✅ 填空全部完成", "success")
            time.sleep(0.8)
            break
        S_swipe(d, 540, 1800, 540, 600, 0.4)
        time.sleep(0.6)

    # 阶段3：点"下一题"（答对自动跳转，答错出现"下一题"按钮）
    if d(text="下一题").exists(timeout=2):
        d(text="下一题").click()
        print(f"    点击下一题")
        step_log("➡ 填空答完，进入下一题", "info")
        time.sleep(0.8)
    return True




# ==================== ⑧ 入口（批量调度） ====================
