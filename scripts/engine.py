"""
英语宝 · 自动化引擎
===================
close_ad / ensure_grade / run_single_module 等核心逻辑
"""
import uiautomator2 as u2
import time, re
from config import MODULE_CONFIG, GLOBAL_POPUPS, APP_PACKAGE, GRADE_LEVEL, BOOK_VERSION
from common.tools import S, S_swipe, S_h, S_w
from common.logger import step_log

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
            if w < 80 and h < 80 and b[0] > S_w(d, 800) and b[1] > S_h(d, 600):
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
        d.click(*S(d, 986, 1823))
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
                S_swipe(d, 500, 1400, 500, 400, 0.3)
                time.sleep(1)
            if safe_click(d, text, timeout=min(timeout, 3)):
                print(f"    ✅ 滑动后点击 '{text}'")
            else:
                print(f"    ⚠ 滑动后未找到 '{text}'")

        elif at == "close_ad":
            close_ad(d)

        elif at == "swipe_left":
            # 水平左滑切换子模块
            S_swipe(d, 900, 600, 200, 600, 0.3)
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
        S_swipe(d, 500, 1400, 500, 400, 0.3)
        time.sleep(0.8)
        if d(text=text).exists(timeout=1.5): return True
    # 第二轮：向下滑（内容上移，返回顶部区域）
    for _ in range(max_swipes):
        S_swipe(d, 500, 400, 500, 1400, 0.3)
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
        S_swipe(d, 500, 1400, 500, 400, 0.3)
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
                    time.sleep(1)
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
                time.sleep(0.8)
                return True
            time.sleep(0.5)
        # 兜底：直接出"下一题"
        if d(text="下一题").exists(timeout=1):
            d(text="下一题").click()
            print(f"    ✅ 图片排序完成，点击下一题")
            time.sleep(0.8)
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
                time.sleep(1.5)
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

    # 点 1-5 序号（每次动态检测按钮位置；填一个后若出现"检查/查看报告"则填完停止）
    for target in range(1, 6):
        # 每次重新检测序号栏（点完序号后检查按钮可能出现、布局上移）
        btns = _find_num_btns()
        if not btns:
            print(f"      ⚠ 找不到序号按钮（第{target}次），等待重试")
            time.sleep(0.5)
            continue
        try:
            d.click(btns[0][0], btns[0][1])
            print(f"      → 点序号{target} @({btns[0][0]},{btns[0][1]})")
            time.sleep(1.2)
        except Exception:
            pass
        # 填完一个后：检查/检测/查看报告出现 → 说明填完了，停止
        if (d(text="检查").exists(timeout=0.8)
                or d(text="检测").exists(timeout=0.8)
                or d(text="查看报告").exists(timeout=0.8)):
            print(f"      → 填完第{target}个后出现按钮，停止填序号")
            break

    # 3. 出现检查 → 点它（兼容"检测"；最后一题检查后出"查看报告"也点）
    for _ in range(10):
        if d(text="检查").exists(timeout=0.8):
            d(text="检查").click()
            print(f"    ✅ 排序完成，点击检查")
            time.sleep(1.2)
            continue  # 检查后可能出查看报告/下一题
        if d(text="检测").exists(timeout=0.8):
            d(text="检测").click()
            print(f"    ✅ 排序完成，点击检测")
            time.sleep(1.2)
            continue
        if d(text="查看报告").exists(timeout=0.8):
            # 最后一题：查看报告已出现，交给外层答题循环统一点击（避免重复处理）
            print(f"    ✅ 排序完成，查看报告已出现")
            return True
        if d(text="下一题").exists(timeout=1):
            print(f"    ✅ 排序完成，下一题已出现")
            return True
        time.sleep(0.5)
    return True


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
        time.sleep(1)
        # 填完后检查/检测/查看报告出现 → 完成
        if (d(text="检查").exists(timeout=0.8)
                or d(text="检测").exists(timeout=0.8)
                or d(text="查看报告").exists(timeout=0.8)):
            print(f"      → 点完第{target}个后出现按钮，停止")
            break

    time.sleep(1)
    # 出现检查/检测 → 点击
    for kw in ("检查", "检测"):
        if d(text=kw).exists(timeout=2):
            try:
                d(text=kw).click()
            except Exception:
                pass
            print(f"    ✅ 句子排序完成，点击{kw}")
            time.sleep(1.5)
            return True
    print(f"    ⚠ 句子点完{clicked}个但未出现检查按钮")
    return True


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
                    time.sleep(0.6)
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
            time.sleep(0.8)
            # 检查后：最后一题可能出现"练习报告"（答完反馈页）
            #   ★ 必须先处理"练习报告"，否则反馈页残留"匹配"文字会被误判成匹配题死循环
            if d(text="练习报告").exists(timeout=1.5):
                d(text="练习报告").click()
                print(f"    ✅ 匹配题完成，点击练习报告")
                time.sleep(1.5)
            return True
        time.sleep(0.5)

    # 5. 若检查后答错出现"下一题"→ 点它进入下一题
    if d(text="下一题").exists(timeout=1):
        d(text="下一题").click()
        print(f"    ✅ 匹配完成，点击下一题")
        time.sleep(0.8)
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

        # ★ 完成判定优先：练习报告 / 下一题 必须先于题型识别！
        #   否则最后一题（如匹配题）答完后的反馈页残留题干文字（"匹配"等），
        #   会被 _detect_question_type 误判成同题型 → 在反馈页死循环
        if d(text="练习报告").exists(timeout=0.5):
            d(text="练习报告").click()
            print(f"      → 练习报告（最后一题）")
            step_log(f"📊 练习报告（子模块完成，共{q}题）", "success")
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
            step_log(f"  第{q}题: 答错 → 下一题", "warning")
            time.sleep(1)
            continue

        # 题型识别：排序/匹配走专用处理
        qtype = _detect_question_type(d, config)
        if qtype == "sort_questions":
            # ★ 排序题分流（与听力专项测试部分 _test_answer_loop 保持统一）：
            #   CheckBox 整行句子（宽>800 带文本，圆圈排序题特征）≥3 → 句子圆圈排序
            #   （直接点句子，序号自动填）；否则 → 方框排序（点方框激活+点序号）
            _has_circle = 0
            try:
                _xml = d.dump_hierarchy()
                for _m in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*/?>', _xml):
                    _tag = _m.group(0)
                    _tm = re.search(r'text="([^"]{6,})"', _tag)
                    _bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _tag)
                    if not (_tm and _bm):
                        continue
                    _x1, _y1, _x2, _y2 = int(_bm.group(1)), int(_bm.group(2)), int(_bm.group(3)), int(_bm.group(4))
                    if (_x2 - _x1) > 800 and 700 < _y1 < 1900:
                        _has_circle += 1
            except Exception:
                pass
            if _has_circle >= 3:
                _handle_sentence_sort(d, config)
            else:
                _handle_sort_question(d, config)
            time.sleep(1)
            continue
        elif qtype == "match_questions":
            _handle_match_question(d, config)
            time.sleep(1)
            continue

        # 新题：计数
        q += 1
        print(f"    📸 第{q}题")
        step_log(f"📸 第{q}题", "step")

        # 等渲染 + 选答案
        time.sleep(0.3)
        answered = False
        for opt in ("A","B","C","T","F"):
            try:
                if d(text=opt).exists(timeout=0.3):
                    d(text=opt).click()
                    print(f"      → 选 {opt}")
                    step_log(f"  第{q}题: 选 {opt} → 检查", "info")
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
                S_swipe(d, 500, 1800, 500, 600, 0.3); time.sleep(1)
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
    for _ in range(3):
        try:
            _xml_probe = d.dump_hierarchy()
            if 'class="android.widget.EditText"' in _xml_probe:
                break  # EditText 可见，可开始填方框
        except Exception:
            pass
        d.press("back")
        time.sleep(1.5)

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
            time.sleep(1.5)
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
            time.sleep(1.5)
            print(f"    填一空 ({cx},{cy}) 字={word}")
            step_log(f"  ✏ 输入: {word}", "info")
            no_new_swipes = 0
            continue

        # 当前屏幕没有空框 → 下滑找新的（短文长，空框分布多屏）
        if no_new_swipes >= 3:
            break
        S_swipe(d, 540, 1800, 540, 800, 0.4)
        time.sleep(1.5)
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
            time.sleep(2)
            break
        S_swipe(d, 540, 1800, 540, 600, 0.4)
        time.sleep(1.5)

    # 阶段3：点"下一题"（答对自动跳转，答错出现"下一题"按钮）
    if d(text="下一题").exists(timeout=2):
        d(text="下一题").click()
        print(f"    点击下一题")
        step_log("➡ 填空答完，进入下一题", "info")
        time.sleep(2)
    return True




# ==================== ⑧ 入口（批量调度） ====================
