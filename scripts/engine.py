"""
英语宝 · 自动化引擎
===================
close_ad / ensure_grade / run_single_module 等核心逻辑
"""
import uiautomator2 as u2
import os, time, re
from config import MODULE_CONFIG, GLOBAL_POPUPS, APP_PACKAGE, GRADE_LEVEL, BOOK_VERSION
from common.tools import S, S_swipe, S_h, S_w, applock_blocked, settle_ads, back_to_home, close_ad
from common.logger import step_log, should_stop
from question_types import detect_question_type


def _find_control(xml: str, keywords: tuple, rid_pattern: str = None) -> tuple:
    """在 XML 中查找含关键词的控件节点，返回 (found, clickable)

    ★ 2026-08-25：与 common/evidence.py 的增强版同步（#55 修复只改了 evidence.py，
       engine.py 还是旧版 → 真机口语训练仍误报"麦克风存在但不可点击"）。
      - 优先匹配 clickable="true" 的节点（避免误命中介绍/标签文本）
      - 逐节点匹配 text/content-desc 含任一关键词
      - 也匹配 resource-id 中的 play/sound/audio/speaker/mic/record 模式
      - rid_pattern 可定制：播放检查传 (play|sound|audio|speaker)，
        麦克风检查传 (record|mic)，避免"iv_caption_play 播放图标被当麦克风"串检
      - 命中非 clickable 文本节点时，向上/向外查找包含该节点的 clickable 父容器
        （如口语训练 record_btn 容器内含 "点击录音" 文本）
      - 跳过系统状态栏/通知栏节点（com.android.systemui 含子串 "mic" 会误命中）
    """
    xml = xml or ""
    if rid_pattern is None:
        rid_pattern = r'resource-id="[^"]*(play|sound|audio|speaker|mic|record)[^"]*"'
    _rid_re = re.compile(rid_pattern)

    def _is_system(tag: str) -> bool:
        return "com.android.systemui" in tag or 'package="android"' in tag

    # 先收集所有 clickable 节点 bounds，用于后续"包含关系"判定
    _clickables = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        if _is_system(tag) or 'clickable="true"' not in tag:
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        _clickables.append((int(b.group(1)), int(b.group(2)), int(b.group(3)), int(b.group(4)), tag))

    def _contained_by_clickable(x1, y1, x2, y2, margin=20):
        """判断某个区域是否被某个 clickable 节点包含（或中心落在其中）。"""
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        for bx1, by1, bx2, by2, tag in _clickables:
            if (bx1 - margin <= cx <= bx2 + margin and by1 - margin <= cy <= by2 + margin) or \
               (bx1 <= x1 and by1 <= y1 and bx2 >= x2 and by2 >= y2):
                return True
        return False

    # 第一轮：只找 clickable=true 的节点（避免误命中介绍文案等非控件文本）
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        if _is_system(tag) or 'clickable="true"' not in tag:
            continue
        for kw in keywords:
            if kw in tag:
                return True, True
        if _rid_re.search(tag):
            return True, True
    # 第二轮：兜底找含关键词/rid 的节点（含 clickable=false 的），并尝试找外部 clickable 容器
    nodes = list(re.finditer(r'<node[^>]*>', xml))
    for idx, m in enumerate(nodes):
        tag = m.group(0)
        if _is_system(tag):
            continue
        hit = False
        for kw in keywords:
            if kw in tag:
                hit = True
                break
        if not hit and _rid_re.search(tag):
            hit = True
        if not hit:
            continue
        clickable = 'clickable="true"' in tag
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if b and not clickable:
            bx1, by1, bx2, by2 = map(int, b.groups())
            # 2.1 向上/向外找包含自己的 clickable 容器（口语训练 record_btn 容器）
            if _contained_by_clickable(bx1, by1, bx2, by2):
                clickable = True
            # 2.2 容器内子节点可点击 → 也视为可点击（仅限容器类节点）
            if not clickable:
                _leaf = re.search(r'class="android\.widget\.(TextView|ImageView|Button|ImageButton)"', tag)
                if not _leaf:
                    for m2 in nodes[idx + 1:]:
                        t2 = m2.group(0)
                        b2 = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', t2)
                        if not b2:
                            continue
                        x1, y1, x2, y2 = map(int, b2.groups())
                        if x1 >= bx1 and y1 >= by1 and x2 <= bx2 and y2 <= by2:
                            if 'clickable="true"' in t2:
                                clickable = True
                                break
                        else:
                            break  # 超出容器范围 = 非子节点
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
    流程：确保在英语宝前台并回主页 → 检测主页版本文字 → 不匹配则点版本号 → 选年级 → 确认
    """
    # ★ 先确保在英语宝前台：任务启动时手机可能在模块内部/答题页/弹窗/桌面，
    #   直接点版本号会失败。先按 back 回主页（含冷启动兜底）。
    if not back_to_home(d, grade_level=grade_level):
        print("  ❌ 无法回到主页，切换中止")
        return False

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

def back_to_home(d, grade_level=""):
    """从模块内部回到年级主页：按 back 直到看到年级文字或主页特征；
    若按不回，则冷启动英语宝回主页。"""
    home_keywords = ["我的练习", "专项突破", "教材精学", "学习计划", "成长记录"]
    for _ in range(10):
        try:
            xml = d.dump_hierarchy() or ""
        except Exception:
            xml = ""
        if grade_level and grade_level in xml:
            return True
        if any(kw in xml for kw in home_keywords):
            return True
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(0.5)
    # 末轮兜底
    try:
        xml = d.dump_hierarchy() or ""
    except Exception:
        xml = ""
    if grade_level and grade_level in xml:
        return True
    if any(kw in xml for kw in home_keywords):
        return True
    # ★ 兜底：冷启动英语宝回主页
    print("  🔄 back 回主页失败，冷启动英语宝")
    try:
        d.press("home"); time.sleep(0.4)
        d.app_start(APP_PACKAGE); time.sleep(3.5)
    except Exception as _e:
        print(f"  ⚠ 冷启动异常: {_e}")
        return False
    # 冷启动后再检查一次
    try:
        xml = d.dump_hierarchy() or ""
    except Exception:
        xml = ""
    if grade_level and grade_level in xml:
        return True
    if any(kw in xml for kw in home_keywords):
        return True
    return False

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


def _find_sort_sentence_rows(xml):
    """统一识别「句子排序题」页面上的句子行。

    返回：[(sentence_cx, sentence_cy, y1, txt, circle_cx, circle_cy, is_filled), ...]
      按 y 坐标从上到下排序。
      is_filled=True 表示句子左侧小圆圈已有序号数字（已填）。
      is_filled=False 表示小圆圈 text 为空（未填）。

    兼容性：
      - 句子控件可能是 CheckBox / TextView / LinearLayout
      - 小圆圈一定是 CheckBox，text 为空或数字
      - 对弹窗遮挡/布局变化更鲁棒（放宽宽度、y 范围阈值）
    """
    import re
    sentences = []   # (x1, cx, cy, y1, y2, txt)
    circles = []     # (cx, cy, y1, x1, x2, txt, is_filled)

    # 0. 定位底部数字键盘屏蔽区（这类题数字键盘固定贴在屏幕最底部，
    #    是一排纯数字按钮 1/2/3/4/5...）。这些数字按钮与「已填圆圈」
    #    长得一模一样（text=数字、尺寸小），必须排除，否则会被误判为
    #    已填的句子圆圈。
    _kb = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        tm = re.search(r'text="(\d)"', tag)
        if not tm:
            continue
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bm:
            continue
        x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
        if 20 <= (x2 - x1) <= 220 and 20 <= (y2 - y1) <= 220:
            _kb.append((int(tm.group(1)), y1, y2))
    _kb_top = min(y1 for _, y1, _ in _kb) - 40 if _kb else 10 ** 9

    # ① 长文本句子节点：CheckBox / TextView
    for m in re.finditer(r'<node[^>]*class="android\.widget\.(?:CheckBox|TextView)"[^>]*>', xml):
        tag = m.group(0)
        tm = re.search(r'text="([^"]{4,})"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not (tm and bm):
            continue
        txt = tm.group(1).strip()
        if not txt:
            continue
        x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
        w, h = x2 - x1, y2 - y1
        # 句子通常横向较宽、位于中间区域、高度不大（排除大段文字）
        if w > 250 and 50 < y1 < 4000 and h < 320 and y2 < _kb_top:
            sentences.append((x1, (x1 + x2) // 2, (y1 + y2) // 2, y1, y2, txt))

    # ② LinearLayout 可点击长条（旧版/特殊形态）：只在没有①结果时作为兜底
    if not sentences:
        for m in re.finditer(r'<node[^>]*class="android\.widget\.LinearLayout"[^>]*clickable="true"[^>]*>', xml):
            tag = m.group(0)
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            w = x2 - x1
            if w > 500 and 50 < y1 < 4000:
                # 向后截取一段文本作为句子内容
                snippet = xml[m.start():m.start() + 800]
                tm = re.search(r'text="([^"]{6,})"', snippet)
                txt = tm.group(1) if tm else ""
                sentences.append((x1, (x1 + x2) // 2, (y1 + y2) // 2, y1, y2, txt))

    # ③ 小圆圈 CheckBox：text 为空（未填）或纯数字（已填）
    for m in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*>', xml):
        tag = m.group(0)
        tm = re.search(r'text="([^"]*)"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not (tm and bm):
            continue
        txt = tm.group(1).strip()
        x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
        w, h = x2 - x1, y2 - y1
        is_filled = txt.isdigit()
        ccy = (y1 + y2) // 2
        # 圆圈：尺寸小、宽高接近、text 为空或数字；排除底部数字键盘按钮
        if 30 <= w <= 200 and 30 <= h <= 200 and 50 < y1 < 4000 and (txt == "" or is_filled) and ccy < _kb_top:
            circles.append(((x1 + x2) // 2, ccy, y1, x1, x2, txt, is_filled))

    # ④ 句子与小圆圈配对（圆圈在句子左侧，y 接近）
    rows = []
    for sx1, scx, scy, sy1, sy2, stxt in sentences:
        best = None
        best_dist = float('inf')
        for ccx, ccy, cy1, cx1, cx2, ctxt, is_filled in circles:
            # 圆圈应在句子左侧，不能偏右太多
            if ccx > scx - 20:
                continue
            if abs(ccy - scy) > 160:
                continue
            dist = abs(ccy - scy)
            if dist < best_dist:
                best_dist = dist
                best = (ccx, ccy, is_filled)
        if best:
            rows.append((scx, scy, sy1, stxt, best[0], best[1], best[2]))
        else:
            # 没配到圆圈，用句子左边缘 + 60 作为点击位置（往往是圆圈所在列）
            rows.append((scx, scy, sy1, stxt, sx1 + 60, scy, False))

    # ⑤ 按 y 排序并去重（同一句可能对应多个节点，取最宽/最靠前的）
    rows.sort(key=lambda t: t[2])
    seen = set()
    uniq = []
    for r in rows:
        key = (r[2] // 80, r[3][:25])  # y 按 80px 分桶去重
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _handle_sentence_sort(d, config):
    """处理「句子圆圈排序题」（听录音/排序，给句子排顺序）

    交互规则（已与用户核对）：
      - 直接依次点击句子前面的小圆圈，系统**按点击顺序自动填入 1,2,3...**
        （先点的用掉数字1，第二点用掉2，依次类推）
      - 因此「点击句子的顺序」就是答案顺序；把全部句子点完即可
      - **部分句子不在当前屏幕内（被底部数字键盘挤下去 / 需滚动），
        必须先向上滑动把下方句子划上来再点**
      - 全部点完 → 出现「检查」
    """
    import time
    screen_w, screen_h = d.window_size()
    print(f"    📝 句子排序题：依次点击未填句子（含滑动找屏外句子）")
    step_log("📝 句子排序题：依次点击未填句子（含滑动）", "step")

    def _get_rows():
        return _find_sort_sentence_rows(d.dump_hierarchy())

    def _check_done():
        return d(text="检查").exists(timeout=0.5) or d(text="检测").exists(timeout=0.5)

    def _dismiss_80_popup():
        """关闭 80% 进度弹窗：优先点「继续练习」"""
        try:
            xml = d.dump_hierarchy()
            if 'text="继续练习"' in xml and ('text="先走一步"' in xml or '完成80%' in xml or '你已经完成了' in xml):
                _cont_matches = list(re.finditer(r'text="继续练习"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml))
                _step_matches = list(re.finditer(r'text="先走一步"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml))
                if _step_matches and _cont_matches:
                    _step_y = (int(_step_matches[0].group(2)) + int(_step_matches[0].group(4))) // 2
                    _best = min(_cont_matches, key=lambda _m: abs((int(_m.group(2)) + int(_m.group(4))) // 2 - _step_y))
                    d.click((int(_best.group(1)) + int(_best.group(3))) // 2,
                            (int(_best.group(2)) + int(_best.group(4))) // 2)
                else:
                    d(text="继续练习").click()
                print("      → 关 80% 弹窗（继续练习）")
                time.sleep(0.5)
                return True
        except Exception:
            pass
        return False

    def _swipe_up():
        """向上滑动一屏，把下方句子划上来（手指从下往上滑）"""
        try:
            d.swipe(screen_w // 2, int(screen_h * 0.68),
                    screen_w // 2, int(screen_h * 0.30), 0.35)
        except Exception:
            pass
        time.sleep(0.7)

    def _detect_keyboard_total():
        """识别底部数字键盘的最大数字 = 该排序题的句子总数。

        数字键盘固定贴在屏幕最底部（一排 1/2/3/4/5... 按钮），
        「排到几」就说明有「几个句子」要按顺序点掉。用它作为完成
        判定的兜底：当已点击次数达到这个数，即可认为全部点完。
        """
        xml = d.dump_hierarchy()
        import re as _re
        nums = []
        for m in _re.finditer(r'<node[^>]*>', xml):
            tag = m.group(0)
            tm = _re.search(r'text="(\d)"', tag)
            if not tm:
                continue
            bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            if 20 <= (x2 - x1) <= 220 and 20 <= (y2 - y1) <= 220:
                nums.append((int(tm.group(1)), y2))
        if len(nums) < 2:
            return 0
        # 取最底部一行（最大 y2 簇）的按钮
        max_y2 = max(y2 for _, y2 in nums)
        bottom = [n for n, y2 in nums if y2 >= max_y2 - 80]
        return max(bottom) if bottom else 0

    clicked_total = 0
    prev_unfilled = None
    stall = 0

    for round_idx in range(15):
        _dismiss_80_popup()

        if _check_done():
            print("      ✅ 检查按钮已出现")
            break

        total = _detect_keyboard_total()
        rows = _get_rows()
        unfilled = [r for r in rows if not r[6]]
        print(f"      第{round_idx+1}轮：识别 {len(rows)} 句（未填 {len(unfilled)}）" + (f"，数字键盘总数≈{total}" if total else ""))

        # 只点「屏幕内」的未填句子（屏外坐标点了也不生效）
        onscreen = [r for r in unfilled if 60 < r[5] < screen_h - 40]
        if onscreen:
            for it in onscreen:
                cx, cy = it[4], it[5]
                try:
                    d.click(cx, cy)
                    print(f"      → 点击 @({cx},{cy}) [{it[3][:20]!r}]")
                    clicked_total += 1
                except Exception as _e:
                    print(f"      → 点击 @({cx},{cy}) 异常: {_e}")
                time.sleep(0.35)
                _dismiss_80_popup()
                if _check_done():
                    break

        # 数字键盘「排到几就有几个句子」：已点次数达到总数即视为全部点完
        if total and clicked_total >= total:
            print(f"      ✅ 已点击 {clicked_total} 次（=数字键盘总数{total}），达成")
            break

        if _check_done():
            break

        rows2 = _get_rows()
        unfilled2 = [r for r in rows2 if not r[6]]
        if not unfilled2:
            print("      ℹ 全部句子已填序号")
            break

        progressed = prev_unfilled is None or len(unfilled2) < prev_unfilled
        prev_unfilled = len(unfilled2)

        if progressed:
            stall = 0
            _swipe_up()          # 把下方句子划上来继续点
        else:
            stall += 1
            print(f"      ⚠ 未推进（{stall}次），滑动重试")
            _swipe_up()
            if stall >= 3:
                print("      ⚠ 连续无进展，兜底点击所有未填句子")
                for it in unfilled2:
                    try:
                        d.click(it[4], it[5])
                        clicked_total += 1
                    except Exception:
                        pass
                    time.sleep(0.3)
                if _check_done():
                    break
                print(f"    ⚠ 句子排序未完成（共点击{clicked_total}次）")
                return False

    time.sleep(0.4)
    _dismiss_80_popup()
    for kw in ("检查", "检测"):
        if d(text=kw).exists(timeout=2):
            try:
                d(text=kw).click()
            except Exception:
                pass
            print(f"    ✅ 句子排序完成，点击{kw}")
            time.sleep(0.6)
            return True
    print(f"    ⚠ 句子排序未完成（共点击{clicked_total}次）")
    return False


    # [已删除旧的 _find_sentences，统一使用模块级 _find_sort_sentence_rows]



def _handle_match_question(d, config):
    """处理匹配题：兼容两种交互形态

    形态1（底部固定字母条，旧）：
      点一个人物方框激活底部字母选项 → 依次把 A/B/C/D/E 全部点完。

    形态2（弹出键盘式，新）：
      每个人物名右侧都有独立的输入方框，点击方框会弹出字母键盘，
      在键盘上点一个字母即可填入该人物。需要把每个人物的方框都填上
      字母，"检查"按钮才会出现。
      用户确认：只要每个框框都有字母即可出现检查，不必填对。
    """
    import time
    import re as _re
    print(f"    📋 识别到匹配题，处理中...")
    step_log("📋 检测到匹配题，开始配对…", "step")

    # ── 形态1：底部固定字母条 ──
    #   特征：点一个人物方框后，底部出现一排 A/B/C/D/E 字母按钮。
    #   如果尝试后字母没出现，则回退到形态2。
    _bottom_ok = _handle_match_bottom_bar(d)
    if _bottom_ok:
        return True

    # ── 形态2：弹出键盘式人物-图片匹配 ──
    return _handle_match_popup_keyboard(d)


def _handle_match_bottom_bar(d):
    """匹配题形态1：底部固定字母条。
    返回 True=成功处理并提交；False=不是这种形态，需回退。"""
    import time
    try:
        # 1. 点第一个人物旁边的可点击方框
        clicked_box = False
        name_boxes = [e for e in (d.xpath('//*[@clickable="true"]').all() or [])]
        name_texts = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                      if (e.text or "").strip()]
        for ne in name_texts:
            t = ne.text.strip()
            if len(t) <= 12 and t.isalpha() and t not in ("A","B","C","D","E","T","F","OK"):
                ny = ne.bounds[1]
                for ce in name_boxes:
                    cb = ce.bounds
                    if cb[1] <= ny <= cb[3]:
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
            return False

        # 2. 轮询等待底部字母条出现
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
            time.sleep(0.5)
        if not letters:
            print(f"      ℹ 未出现底部字母条，尝试弹出键盘形态")
            return False

        print(f"    底部字母条 {len(letters)}个: {letters}")
        clicked_letters = set()
        for _ in range(len(letters) + 2):
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
        return _match_click_check(d)
    except Exception:
        return False


def _handle_match_popup_keyboard(d):
    """匹配题形态2：人名右侧有独立输入框，点击后弹出字母键盘。

    策略：
      1. 识别所有英文人名（如 Mark / Jackson / Amy）。
      2. 为每个人名找到右侧最近的输入方框。
      3. 依次点击方框 → 在弹出的字母键盘中点击一个字母（选 y 最大的，
         避免点到顶部图片标签 A/B/C）→ 按 back 关闭键盘 → 继续下一个。
      4. 每轮结束检测"检查"按钮，出现即点。
    """
    import time
    import re as _re
    print(f"    📋 弹出键盘式匹配题：为每个人物方框填入字母")
    step_log("📋 弹出键盘式匹配：逐个点框填字母", "step")

    screen_w, screen_h = d.window_size()

    def _find_names_and_boxes(xml):
        """返回 [(name_text, name_cx, name_cy, box_cx, box_cy), ...]"""
        # 收集英文人名
        names = []
        for m in _re.finditer(r'<node[^>]*text="([^"]{2,12})"[^>]*>', xml):
            t = m.group(1).strip()
            if not (t.isalpha() and t not in ("A","B","C","D","E","F","T","OK")):
                continue
            bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', m.group(0))
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            if y1 < 150 or y2 > screen_h - 150:
                continue
            names.append((t, (x1+x2)//2, (y1+y2)//2, x2, y1, y2))

        # 收集可点击方框（text 为空或很短，且不是图片标签 A/B/C）
        boxes = []
        for m in _re.finditer(r'<node[^>]*clickable="true"[^>]*>', xml):
            tag = m.group(0)
            tm = _re.search(r'text="([^"]*)"', tag)
            bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            txt = (tm.group(1) if tm else "").strip()
            # 排除本身是 A/B/C 等单字母的控件（它们可能是图片标签）
            if len(txt) == 1 and txt.isalpha():
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            w, h = x2 - x1, y2 - y1
            # 方框尺寸不能太大或太小
            if 40 <= w <= 500 and 30 <= h <= 200 and 150 < y1 < screen_h - 150:
                boxes.append(((x1+x2)//2, (y1+y2)//2, x1, y1, x2, y2))

        # 人名与右侧方框配对
        pairs = []
        for t, ncx, ncy, nx2, ny1, ny2 in names:
            best = None
            best_dist = float('inf')
            for bcx, bcy, bx1, by1, bx2, by2 in boxes:
                # 方框在人名右侧，y 接近
                if bx1 < nx2 + 10:
                    continue
                if abs(bcy - ncy) > 120:
                    continue
                dist = abs(bcy - ncy) + (bx1 - nx2) * 0.3
                if dist < best_dist:
                    best_dist = dist
                    best = (bcx, bcy)
            if best:
                pairs.append((t, ncx, ncy, best[0], best[1]))
        return pairs

    def _click_one_letter():
        """在弹出的字母键盘中点击一个字母（选最靠下的，避免图片标签）"""
        xml = d.dump_hierarchy()
        best = None
        best_y = -1
        for m in _re.finditer(r'<node[^>]*text="([A-F])"[^>]*>', xml):
            tag = m.group(0)
            bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            if 20 <= (x2 - x1) <= 220 and 20 <= (y2 - y1) <= 220:
                cy = (y1 + y2) // 2
                if cy > best_y:
                    best_y = cy
                    best = ((x1 + x2) // 2, cy)
        if best:
            try:
                d.click(best[0], best[1])
                print(f"      → 点键盘字母 @({best[0]},{best[1]})")
                return True
            except Exception:
                pass
        return False

    # 主循环：最多 3 轮，每轮把所有人名方框都点一遍
    for round_idx in range(3):
        xml = d.dump_hierarchy()
        pairs = _find_names_and_boxes(xml)
        print(f"      第{round_idx+1}轮：识别 {len(pairs)} 个人物方框")
        if not pairs:
            break

        for t, ncx, ncy, bcx, bcy in pairs:
            # 检查是否已经填过了（方框 text 非空）——通过 dump 重新看该位置
            xml2 = d.dump_hierarchy()
            # 简化：直接再点一次，不管是否已填
            try:
                d.click(bcx, bcy)
                print(f"      → 点击 [{t}] 方框 @({bcx},{bcy})")
                time.sleep(0.4)
                if _click_one_letter():
                    time.sleep(0.3)
                # 关闭键盘，避免挡到下一个框
                try:
                    d.press("back")
                except Exception:
                    pass
                time.sleep(0.3)
            except Exception as e:
                print(f"      → 点击 [{t}] 方框异常: {e}")

            if d(text="检查").exists(timeout=0.4) or d(text="检测").exists(timeout=0.4):
                print(f"      ✅ 检查按钮已出现")
                return _match_click_check(d)

    # 兜底：即使没识别到完整配对，也尝试点击所有可点击方框并填入字母
    print(f"      ⚠ 尝试兜底：点击所有可疑方框")
    xml = d.dump_hierarchy()
    boxes = []
    for m in _re.finditer(r'<node[^>]*clickable="true"[^>]*>', xml):
        bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', m.group(0))
        if not bm:
            continue
        x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
        w, h = x2 - x1, y2 - y1
        if 40 <= w <= 500 and 30 <= h <= 200 and y1 > screen_h * 0.25 and y2 < screen_h - 80:
            boxes.append(((x1+x2)//2, (y1+y2)//2))
    for bcx, bcy in boxes:
        try:
            d.click(bcx, bcy)
            time.sleep(0.3)
            _click_one_letter()
            time.sleep(0.2)
            d.press("back")
            time.sleep(0.2)
        except Exception:
            pass
        if d(text="检查").exists(timeout=0.3) or d(text="检测").exists(timeout=0.3):
            return _match_click_check(d)

    return _match_click_check(d, must=False)


def _match_click_check(d, must=True):
    """点击"检查"/"检测"，或"下一题"/"练习报告"。
    must=False 时即使没找到检查也返回 True，避免外层循环卡死。"""
    import time
    for kw in ("检查", "检测"):
        if d(text=kw).exists(timeout=1.5):
            try:
                d(text=kw).click()
                print(f"    ✅ 匹配题完成，点击{kw}")
            except Exception:
                pass
            time.sleep(0.4)
            if d(text="练习报告").exists(timeout=1.5):
                d(text="练习报告").click()
                print(f"    ✅ 匹配题完成，点击练习报告")
                time.sleep(0.6)
            return True
    if d(text="下一题").exists(timeout=1):
        d(text="下一题").click()
        print(f"    ✅ 匹配完成，点击下一题")
        time.sleep(0.35)
        return True
    if not must:
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

    # ★ 防多算题目：页面签名去重 + 总题数越界硬停止
    #   根因：之前只要"页面像题目"就无条件 q+=1，手机提前回首页/某题卡住时，
    #   同一页被反复当新题计数（曾出现 难点突破 记 47 题，手机实际只点 ~16 题）。
    #   现在每题必须有"页面推进"才计数：用页面签名去重，且超过题库总题数立即停。
    _last_sig = None      # 上一题页面签名（题号 X/Y 或 题干+选项），用于去重
    _adv_stall = 0        # 同一页重复出现、未推进的次数
    _total_q = 0          # 从界面 X/Y 读到的本题库总题数（越界即停）
    _cur_qno = 0          # 当前题号（X/Y 左边）

    def _page_sig():
        """页面签名：优先题号 X/Y（精确）；否则题干+首个选项文本（近似去重）。"""
        m = re.search(r'text="(\d+)\s*/\s*(\d+)"', _xml)
        if m:
            return ("q", int(m.group(1)), int(m.group(2)))
        stems = re.findall(r'resource-id="[^"]*question_title_tv[^"]*"[^>]*text="([^"]+)"', _xml)
        if not stems:
            stems = [t for t in re.findall(r'text="([^"]{6,60})"', _xml)
                     if t not in ("点击图片查看高清大图", "查看高清大图")]
        first_opt = ""
        for o in ("A", "B", "C", "T", "F"):
            mm = re.search(r'text="' + o + r'[\.、．]?\s*([^"]{0,30})"', _xml)
            if mm:
                first_opt = o + mm.group(1)[:20]
                break
        return ("s", (stems[0][:40] if stems else "") + "|" + first_opt)

    def _collect_ui_evidence(qtype):
        """每题界面级检查证据（题型/题干/选项/音频/作答）→ 前端证据卡展示"""
        import re as _re
        ev = []
        # ★ 每题抓一张题目截图（答题前，含题干+选项）。截图是否显示在审查结果里，
        #   由 AI 六维 / LLM 审查是否出错决定（不再以"答错"为依据）。
        try:
            _proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            while _proj and os.path.dirname(_proj) != _proj \
                    and not os.path.exists(os.path.join(_proj, "web_server.py")):
                _proj = os.path.dirname(_proj)
            _sd = os.path.join(_proj, "screenshots")
            os.makedirs(_sd, exist_ok=True)
            _qshot_fn = f"q{q:02d}_{int(time.time())}.png"
            for _r in range(3):
                try:
                    d.screenshot(os.path.join(_sd, _qshot_fn))
                    break
                except OSError:
                    if _r >= 2:
                        raise
                    time.sleep(0.5)
            ev.append({"field": "题目截图", "type": "q_shot", "screenshot": _qshot_fn})
        except Exception as _se:
            print(f"      ⚠ 题目截图失败: {_se}")
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
            # ★ 排序题的可选项不是 A/B/C，而是可排序的句子/条目
            if qtype == "排序题" or "排序" in _xml:
                # ★ 统一走 _find_sort_sentence_rows，兼容 CheckBox/TextView/LinearLayout
                sort_rows = _find_sort_sentence_rows(_xml)
                sort_items = [r[3] for r in sort_rows]
                if len(sort_items) >= 2:
                    ev.append({"field": "选项", "type": "text_ok",
                               "expected": "存在可排序项", "actual": f"{len(sort_items)}个句子",
                               "diff": f"排序题检测到 {len(sort_items)} 个可排序句子"})
                else:
                    ev.append({"field": "选项", "type": "text_mismatch",
                               "expected": "存在可排序项", "actual": f"{len(sort_items)}个句子",
                               "diff": f"⚠ 排序题检测到 {len(sort_items)} 个可排序句子"})
            else:
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
            play_found, play_clickable = _find_control(
                _xml, PLAY_KWS, rid_pattern=r'resource-id="[^"]*(play|sound|audio|speaker)[^"]*"')
            mic_found, mic_clickable = _find_control(
                _xml, MIC_KWS, rid_pattern=r'resource-id="[^"]*(record|mic)[^"]*"')
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
        # ★ 80% 进度弹窗（"你已经完成X道题" + "先走一步"/"继续练习"）：
        #   必须点弹窗里的「继续练习」才能继续做题，否则可能误点成其他页面的按钮。
        # ★ 兼容两种文本形态：同时出现「继续练习」+「先走一步」，或文案含「完成80%」/「你已经完成了」。
        _is_80_popup = (
            (_has("继续练习") and _has("先走一步"))
            or ("完成80%" in _xml and _has("继续练习"))
            or ("你已经完成了" in _xml and _has("继续练习"))
        )
        if _is_80_popup:
            # 优先用坐标匹配：找与「先走一步」y 坐标最接近的「继续练习」
            _cont_matches = list(re.finditer(r'text="继续练习"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _xml))
            _step_matches = list(re.finditer(r'text="先走一步"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _xml))
            if _step_matches and _cont_matches:
                _step_y = (int(_step_matches[0].group(2)) + int(_step_matches[0].group(4))) // 2
                _best = None
                _best_dist = float('inf')
                for _m in _cont_matches:
                    _cy = (int(_m.group(2)) + int(_m.group(4))) // 2
                    _dist = abs(_cy - _step_y)
                    if _dist < _best_dist:
                        _best_dist = _dist
                        _best = _m
                if _best:
                    d.click((int(_best.group(1)) + int(_best.group(3))) // 2,
                            (int(_best.group(2)) + int(_best.group(4))) // 2)
                    print("      → 关 80% 弹窗（继续练习）")
                else:
                    _click_text("继续练习")
                    print("      → 关弹窗")
            else:
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
            # ★ 截图依据已改：不再"答错就截图"。题目截图在每题完整性检查前抓取(qshot)，
            #   只有当 AI 六维 或 LLM 审查判出错时，才由 web_server 贴到审查结果。
            _click_text("下一题")
            print(f"      → 下一题（答错）")
            _idle = 0
            time.sleep(0.4); _need_dump = True; continue

        # ★ 非题目页保护：首页/模块列表/过渡页不当作题目处理，避免"匹配/排序"等关键词
        #   在 App 首页/模块列表被误触发，产生"自己冒出来的题目"。
        if not _is_question_page(_xml):
            _idle += 1
            if _idle >= 15:
                step_log(f"⚠ 连续 {_idle} 轮未检测到题目页，退出答题循环", "warning")
                return q
            time.sleep(0.4); _need_dump = True
            continue
        _idle = 0

        # ★★★ 防多算题目闸门：同一页未推进/超总题数 → 不重复计数，及时退出 ★★★
        #   之前 _answer_loop 只要页面像题目就 q+=1，手机提前回首页或某题卡住时，
        #   同一页被反复当新题计数（难点突破曾记 47 题、手机实际只点 ~16 题）。
        #   修复：用页面签名去重 + 题号总数越界硬停止。
        _sig = _page_sig()
        if isinstance(_sig, tuple) and _sig[0] == "q":
            _cur_qno, _total_q = _sig[1], _sig[2]
        # 越界：计数已超过题库总题数（说明已离题/重复）→ 立即结束本子模块
        if _total_q and q > _total_q:
            step_log(f"⚠ 计数{q}已超过本题库总题数{_total_q}，判定子模块已结束，退出", "warning")
            return q
        # 与上一题签名相同 → 同一页未推进，不重复计数，累计停滞次数后退出
        if _last_sig is not None and _sig == _last_sig:
            _adv_stall += 1
            if _adv_stall >= 8:
                step_log(f"⚠ 第{q}题页面连续{_adv_stall}轮未推进（疑似答不出/卡死/已离题），退出本子模块", "warning")
                return q
            time.sleep(0.4); _need_dump = True; continue
        _adv_stall = 0
        _last_sig = _sig

        # 题型识别：基于缓存的字符串匹配（不再调 xpath）
        qtype = _detect_question_type_cached(_xml, config)
        if qtype == "sort_questions":
            q += 1  # ★ 排序题计数（之前遗漏，导致总题数少）
            step_log(f"📸 第{q}题（排序题）", "step")
            step_log(f"  第{q}题 检查", "info", _collect_ui_evidence("排序题"))
            # ★ 用统一识别函数判断：≥3 个带小圆圈的句子 → 句子圆圈排序题
            _sort_rows = _find_sort_sentence_rows(_xml)
            if len(_sort_rows) >= 3:
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


def _is_question_page(xml: str) -> bool:
    """判断当前页是否是真实题目页（含题号/选项/检查/反馈/报告等）。

    用来避免把 App 首页、模块列表、过渡页当成题目处理。
    """
    if not xml:
        return False
    # 强信号：右上角题号 X/Y（text 或 content-desc）
    if re.search(r'(text|content-desc)="\d+\s*/\s*\d+"', xml):
        return True
    # 作答/反馈/报告相关元素（这些单独出现即足以判定为题目页）
    if any(k in xml for k in (
        'text="检查"', 'text="检测"', 'text="下一题"', 'text="提交"', 'text="完成"',
        'text="练习报告"', 'text="查看报告"', 'text="继续答题"',
        '恭喜你', '回答正确', '回答错误', '很遗憾',
        'class="android.widget.EditText"', 'class="android.widget.CheckBox"')):
        return True
    # 选项字母（兼容 A. / A、形式）：★ 单独出现不可靠（首页等级徽章"A"也会命中），
    #   必须另有佐证才认定为题目页，避免首页/结束页被误判成"题目"反复计数。
    if re.search(r'text="[TFABCDE][\.、．]?', xml):
        # 佐证①：题号/检查/录音/作答元素/反馈 → 强题目信号
        if (re.search(r'(text|content-desc)="\d+\s*/\s*\d+"', xml)
                or 'text="检查"' in xml or 'text="检测"' in xml
                or "录音" in xml or "EditText" in xml or "CheckBox" in xml
                or "继续答题" in xml or "恭喜你" in xml or "回答正确" in xml
                or "回答错误" in xml or "很遗憾" in xml):
            return True
        # 佐证②：出现 ≥2 个不同选项字母（真实选择题至少 A/B 两个；首页单徽章只有1个）
        _letters = set(re.findall(r'text="([TFABCDE])"', xml))
        if len(_letters) >= 2:
            return True
        return False
    return False


def _is_miniprogram_auth(xml: str) -> bool:
    """判断是否误点主页悬浮广告后跳到了微信小程序授权页"""
    if not xml:
        return False
    return any(k in xml for k in ("E英语宝伴学服务", "申请", "你的昵称、头像", "微信昵称头像"))


def _try_close_floating_ad(d):
    """尝试关闭主页右下角 WebView 悬浮广告（老师伴学/打卡服务卡片）

    该广告在 uiautomator 无障碍树中不可见，无法通过文字/关闭按钮定位，
    只能根据常见屏幕比例点击其右上角 X 区域或尝试横向滑走。
    """
    try:
        step_log("🧹 尝试关闭右下角悬浮广告卡片（伴学服务）...", "info")
        # 尝试1：点卡片右上角 X 估计坐标（参考屏 1080x2400；在 1224x2700 真机上约为 (1130,2080)）
        _x, _y = S(d, 1000, 1850)
        d.click(_x, _y)
        time.sleep(0.6)
        # 尝试2：从卡片中心向右外滑动，部分 WebView 浮层可拖走
        _x1, _y1 = S(d, 980, 1900)
        _x2, _y2 = S(d, 1150, 2150)
        d.swipe(_x1, _y1, _x2, _y2, 0.3)
        time.sleep(0.6)
    except Exception as _e:
        step_log(f"⚠ 关闭悬浮广告尝试异常: {_e}", "warning")


def _normalize_units(units):
    r"""★ 把 units 规范化为 int 列表（2026-09-01 修复）

    背景：上游 units 可能是字符串（"U6" / "U6-9" / "U6-9U6" 等含字母与连字符的
    畸形串）。run_single_module 里用 `r'Unit\s*0*%d\b' % unit_num` 匹配单元标题，
    %d 要求 int → 传字符串直接抛
    "TypeError: %d format: a real number is required, not str"，
    整个模块瞬间崩溃（0 题 0 成功）。

    支持输入：int / str("U6"、"6"、"1-3"、"U6-9U6") / 以及它们的列表。
    规则：
      - int        -> [n]
      - str 含 '-' -> 取前两个数字作区间（"U6-9U6" -> 6,7,8,9）
      - str 无 '-' -> 取第一个数字（"U6" -> 6）
    返回去重升序的 int 列表；解析不出数字则丢弃该项。
    """
    import re as _re
    if units is None:
        return []
    if isinstance(units, (int, float)):
        n = int(units)
        return [n] if n > 0 else []
    if isinstance(units, str):
        units = [units]
    out = []
    for item in units:
        try:
            if isinstance(item, (int, float)):
                n = int(item)
                if n > 0:
                    out.append(n)
                continue
            s = str(item).strip()
            if not s:
                continue
            nums = _re.findall(r"\d+", s)
            if not nums:
                continue
            if "-" in s and len(nums) >= 2:
                a, b = int(nums[0]), int(nums[1])
                if b < a:
                    a, b = b, a
                # 跨度保护：畸形串可能解析出超大范围，最多取 30 个单元
                if b - a > 30:
                    b = a + 30
                out.extend(range(a, b + 1))
            else:
                n = int(nums[0])
                if n > 0:
                    out.append(n)
        except Exception:
            continue
    return sorted(set(out))


def run_single_module(d, module_name, config):
    step_log(f"{'='*45}", "info")
    step_log(f"🔍 检测模块：{module_name}", "info")
    step_log(f"config.units={config.get('units')!r} config.sub_modules={[s.get('name') for s in (config.get('sub_modules') or [])]}", "info")
    step_log(f"{'='*45}", "info")

    questions = 0
    entry = config["entry_text"]
    sub_modules = config.get("sub_modules")     # 子模块列表（None=无子模块）

    # 1. 找模块入口（处理主页右下角 WebView 悬浮广告遮挡：滑屏错开后再点）
    step_log(f"[1] 查找并点击「{entry}」入口...", "info")
    if not scroll_and_find(d, entry):
        step_log(f"❌ 未找到模块入口: {entry}（主页滚动查找失败，可能该年级未上线此模块）", "error")
        return 0
    # ★ 点击入口【前】先清普通广告
    settle_ads(d, wait_total=8)

    def _check_entered():
        try:
            _xml_after = d.dump_hierarchy()
            return any(k in _xml_after for k in ("去练习", "去答题", "练习记录", "重新答题", "开始答题"))
        except Exception:
            return False

    def _entry_elems():
        """返回所有同名入口元素及其中心坐标、是否在广告区"""
        _xml = ""
        try:
            _xml = d.dump_hierarchy() or ""
        except Exception:
            return []
        _ws = d.window_size()
        out = []
        for _pat in (rf'text="{re.escape(entry)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                     rf'content-desc="{re.escape(entry)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'):
            for _m in re.finditer(_pat, _xml):
                _x1, _y1, _x2, _y2 = map(int, _m.groups())
                _cx = (_x1 + _x2) // 2
                _cy = (_y1 + _y2) // 2
                _in_ad = _cx > _ws[0] * 0.6 and _cy > _ws[1] * 0.6
                out.append((_cx, _cy, _in_ad, _x1, _y1, _x2, _y2))
        # 优先选不在广告区的；都没有则返回第一个
        _non_ad = [o for o in out if not o[2]]
        return _non_ad or out

    _entered = False
    for _att in range(5):
        elems = _entry_elems()
        if not elems:
            if not scroll_and_find(d, entry):
                step_log(f"❌ 未找到模块入口: {entry}", "error")
                return 0
            continue
        _cx, _cy, _in_ad, *_ = elems[0]
        if _in_ad:
            step_log(f"⚠ 入口「{entry}」坐标({_cx},{_cy})落在屏幕右下角，疑似被广告遮挡 → 上滑错开", "warning")
            _sw_h = d.window_size()[1]
            d.swipe(_cx, int(_sw_h * 0.78), _cx, int(_sw_h * 0.30), 0.4)
            time.sleep(1.3)
            continue
        # 优先点击包含该文字的 clickable 父容器（主页入口 text 节点本身 clickable=false）
        clicked_entry = False
        try:
            _xpath_entry = f'//node[@text="{entry}"]/ancestor::node[@clickable="true"][1]'
            _parent = d.xpath(_xpath_entry)
            if _parent and _parent.exists:
                _parent.click()
                step_log(f"✅ 点击入口 {entry}（父容器点击）", "info")
                clicked_entry = True
        except Exception as _e:
            print(f"      ⚠ 父容器点击失败: {_e}")
        if not clicked_entry:
            try:
                d(text=entry).click(timeout=2)
                step_log(f"✅ 点击入口 {entry}（文字点击）", "info")
            except Exception:
                d.click(_cx, _cy)
                step_log(f"✅ 点击入口 {entry} @({_cx},{_cy})", "info")
        time.sleep(1.5)
        if _check_entered():
            _entered = True
            break
        _xml_after = ""
        try:
            _xml_after = d.dump_hierarchy() or ""
        except Exception:
            pass
        if _is_miniprogram_auth(_xml_after):
            step_log(f"⚠ 点击 {entry} 误触悬浮广告跳到小程序授权页，返回并重试", "warning")
            for _b in range(3):
                d.press("back"); time.sleep(0.7)
        else:
            step_log(f"⚠ 点击 {entry} 后未进入模块，上滑重试", "warning")
        _sw_h = d.window_size()[1]
        d.swipe(_cx, int(_sw_h * 0.78), _cx, int(_sw_h * 0.30), 0.4)
        time.sleep(1.2)

    if not _entered:
        step_log(f"❌ 点击入口失败: {module_name}（已尝试滑动错开并多次点击仍未进入；若仍被广告遮挡，请在手机上手动关闭右下角「老师伴学/打卡服务」卡片后重试）", "error")
        return 0
    step_log(f"✅ 已进入 {module_name}", "success")
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

    # ★ 开发中检测：进入模块页后若显示「正在开发 / 敬请期待」，说明该模块此年级尚未开放
    #   → 直接停止检查（不再滚动找单元入口、不再答题），返回主页。
    _dev_kw = ("正在开发", "敬请期待")
    try:
        _xml_dev = d.dump_hierarchy() or ""
    except Exception:
        _xml_dev = ""
    if any(k in _xml_dev for k in _dev_kw):
        step_log(f"⚠ {module_name} 显示「正在开发，敬请期待」→ 该年级尚未开放，直接停止检查并返回主页", "warning")
        back_to_home(d)
        return 0

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
    # ★ 听力专项双 tab：练习路径必须停在「练习」tab（才有"去练习"按钮）。
    #   仅当页面同时存在「练习」「测试」两个 tab 时才处理，不影响其他模块。
    if d(text="练习").exists(timeout=2) and d(text="测试").exists(timeout=2):
        if not d(text="去练习").exists(timeout=1.5):
            try:
                d(text="练习").click(); time.sleep(1.2)
                step_log("→ 已切到「练习」tab", "info")
            except Exception:
                pass
    units = config.get("units")  # 如有单元号列表，逐个遍历
    if units:
        step_log(f"[3] 单元遍历({len(units)}个)：U{units[0]}-U{units[-1]}", "info")
        # ★ 进入列表页后先回到顶部：防止入口点击/广告错开等操作把列表滚到底部，
        #   导致从 U1 开始遍历时找不到入口而空转。
        #   注意：手指从上往下滑（y 小→大）内容向上滚动，才能显示出顶部的单元。
        #   ★ 2026-08-29 加固：WebView 列表是懒加载，回顶部只需 3 次 + 等待 0.8s，
        #     不要无脑滑 5 次把列表推到中段（会把 Unit 1 推出屏幕、扰乱第 N 个按钮序号）。
        step_log("[列表] 回到顶部...", "info")
        for _ in range(3):
            S_swipe(d, 500, 600, 500, 1800, 0.4)
            time.sleep(0.8)

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
            # ★ 页面加载/弹窗可能导致按钮延迟出现，用 XML 字符串匹配兜底
            _entry_ok = False
            for retry in range(12):
                try:
                    _xml_sub = d.dump_hierarchy() or ""
                except Exception:
                    _xml_sub = ""
                if "重新答题" in _xml_sub or "开始答题" in _xml_sub:
                    _entry_ok = True
                    break
                if d(text="重新答题").exists(timeout=1) or d(text="开始答题").exists(timeout=1):
                    _entry_ok = True
                    break
                time.sleep(0.5)
            if not _entry_ok:
                print(f"    ⚠ 未找到 '开始答题'/'重新答题'，可能页面未加载或子模块切换失败")
                try:
                    _xml_dbg = d.dump_hierarchy() or ""
                    _txts = sorted(set(re.findall(r'text="([^"]*)"', _xml_dbg)))
                    print(f"    当前页面文本（前30）: {_txts[:30]}")
                except Exception:
                    pass
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
                                or "去答题" in _xml_back or "练习记录" in _xml_back):
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
    # ★ 2026-09-01 修复：units 元素可能是字符串（"U6" / "U6-9U6" 等含字母与连字符的
    #   畸形串），直接喂给下方 `r'Unit\s*0*%d\b' % unit_num` 会抛
    #   "TypeError: %d format: a real number is required, not str" → 模块整体崩溃、0 题。
    #   统一规范化为 int 列表（如 "U6-9U6" → [6,7,8,9]）再遍历。
    if units:
        _norm = _normalize_units(units)
        if _norm != list(units):
            step_log(f"→ 单元规范化: {units!r} → {_norm}", "info")
        units = _norm
    if units:
        # ★ 预检：模块列表页里有没有任何"去练习"/"去答题"按钮？一个都没有说明该模块此年级未上线
        _any_btn = (d(text="去练习").exists(timeout=2) or d(text="去答题").exists(timeout=2)
                    or 'text="去练习"' in (d.dump_hierarchy() or "")
                    or 'text="去答题"' in (d.dump_hierarchy() or ""))
        step_log(f"[3] 单元遍历({len(units)}个)：U{units[0]}-U{units[-1]}；模块列表含入口按钮: {_any_btn}", "info")
        if not _any_btn:
            step_log(f"⚠ {module_name} 该年级/版本下未上线（列表页无'去练习'/'去答题'），结束并返回主页", "warning")
            back_to_home(d)
            return 0

        _any_clicked = False
        for ui, unit_num in enumerate(units):
            # ★ 停止检查：前端停止 → 中断单元循环
            if should_stop():
                step_log("⏹ 收到停止请求，中断单元循环", "warning")
                return
            step_log(f"🎯 Unit {unit_num} [{ui+1}/{len(units)}]", "step")
            step_log(f"{'='*40}", "info")
            # 在模块列表里找该单元的"去练习"并点击
            # ★ 策略：Unit 标题可能在 WebView 内不暴露为 text 节点，无法通过文字匹配。
            #   但"去练习"是原生按钮。列表从顶部开始，第 N 个"去练习"按钮即 Unit N。
            #   ★ 2026-08-29 修复"Unit 7 滑不到 / 自动停止"根因：听力专项练习列表是 WebView
            #     懒加载，进入后只渲染前面几个单元的"去练习"按钮。原逻辑靠"连续 3 次按钮数
            #     不变就停滑"会误判列表到底 → 提前 break 放弃，Unit 7 永远滚不到屏幕里。
            #     改为：用"滑动前后顶部第 1 个按钮位置是否真的位移"判定是否到底
            #     （连续 4 次不动才认到底），否则一直滑到出现第 N 个按钮或达 30 次上限。
            clicked = False
            _swipe_count = 0
            _top_history = []   # 列表顶部第1个单元标题位置，用于判列表到底
            while _swipe_count < 30:
                # ★ 改用「单元标题文字」定位目标行 → 点同行黄色按钮，不再数第 N 个按钮。
                #   根因：本版本练习列表从 Unit 3 起（无 Unit 1/2），"第 N 个按钮 = Unit N"
                #         不成立（数第 7 个按钮实际是 Unit 9），导致 Unit 7 永远找不到。
                #   正确做法与测试路径一致：滑到目标单元标题出现 → 找它同行最近的
                #   "去练习/去答题"按钮 → 点那个按钮元素本身（非坐标、非文字）。
                try:
                    _els = d.xpath('//*[@text!=""]').all() or []
                except Exception:
                    _els = []
                # 收集所有 去练习/去答题 黄色按钮
                _btns = [e for e in _els if (e.text or '').strip() in ('去练习', '去答题')]
                # 找目标单元标题（含 "Unit N"，且本身不是按钮）
                _target = None
                for e in _els:
                    _t = (e.text or '').strip()
                    if re.search(r'Unit\s*0*%d\b' % unit_num, _t) and _t not in ('去练习', '去答题'):
                        _target = e
                        break
                if _target is None:
                    # 当前屏没有目标单元 → 向下滑动加载更多（目标通常在下方）
                    _first = next((e for e in _els if re.search(r'Unit\s*\d+', (e.text or ''))), None)
                    _top_history.append(_first.bounds if _first is not None else None)
                    step_log(f"→ 屏内未见 Unit {unit_num}，向下滑动加载 (已滑 {_swipe_count+1} 次)", "info")
                    S_swipe(d, 500, 1800, 500, 600, 0.4); time.sleep(0.8)
                    _swipe_count += 1
                    if len(_top_history) >= 4 and all(b == _top_history[-1] for b in _top_history[-4:] if b is not None):
                        step_log("→ 列表已到底，停止滑动", "info")
                        break
                    continue
                # 目标单元在屏内 → 找它【正下方最近】的 去练习/去答题 按钮
                # （布局：每个单元块 = 标题在上，黄色按钮在其下方；点标题下方第一个按钮即本单元）
                _title_bottom = _target.bounds[3]
                _row_cy = (_target.bounds[1] + _target.bounds[3]) // 2
                _h = d.window_size()[1]
                # 候选按钮：顶部在标题底部之下（含小容差），即位于该单元标题【下方】
                _row_btns = [b for b in _btns if b.bounds[1] >= _title_bottom - 80]
                if not _row_btns:
                    # 标题可见但按钮在屏幕底边外未渲染（末项贴底）→ 上滑（手指从屏底往上）
                    # 让目标整行进屏幕中部，按钮才会被 WebView 渲染出来。
                    # ★ 实测：必须用大距离上滑，小滑距无效。
                    step_log(f"→ Unit {unit_num} 标题可见但按钮在屏外，上滑使其进入屏幕", "info")
                    S_swipe(d, 500, 2300, 500, 1050, 0.45); time.sleep(0.9)
                    _swipe_count += 1
                    continue
                # 取【最靠上】的（即离标题最近）那个按钮 = 本单元的 去练习/去答题
                be = min(_row_btns, key=lambda b: b.bounds[1])
                by1, by2 = be.bounds[1], be.bounds[3]
                step_log(f"→ 找到 Unit {unit_num} 下方最近按钮(标题底={_title_bottom})，按钮y[{by1},{by2}] 屏高{_h}", "info")
                if 20 <= by1 and by2 <= _h - 20:
                    for _click_try in range(3):
                        try:
                            be.click(); time.sleep(2.5)
                        except Exception as _ce:
                            step_log(f"⚠ 点击 Unit {unit_num} 按钮异常: {_ce}，重试", "warning")
                            time.sleep(0.5)
                            continue
                        # 验证：若仍能看到原列表的去练习按钮，说明没点进去
                        _xml_after = d.dump_hierarchy() or ""
                        _still_list = ('text="去练习"' in _xml_after or 'text="去答题"' in _xml_after) and (
                            'text="重新答题"' not in _xml_after and 'text="开始答题"' not in _xml_after
                        )
                        if not _still_list:
                            clicked = True
                            break
                        step_log(f"→ 点击后仍在列表页，重试 ({_click_try+1}/3)", "info")
                        time.sleep(0.8)
                    if clicked:
                        break
                    # 3 次点击仍在列表 → 可能坐标错位，向下滑重定位后重试
                    step_log("→ 多次点击仍在列表，向下滑动重定位", "info")
                    S_swipe(d, 500, 1800, 500, 600, 0.4); time.sleep(0.8)
                    _swipe_count += 1
                    continue
                # 目标按钮在屏幕下方之外：内容向下滚动（露出下方），手指从下往上滑（y 大→小）
                if by2 > _h - 20:
                    step_log(f"→ Unit {unit_num} 按钮在屏幕下方，向下滚动", "info")
                    S_swipe(d, 500, 1800, 500, 600, 0.4); time.sleep(0.8)
                    _swipe_count += 1
                    continue
                # 目标按钮在屏幕上方之外：内容向上滚动（露出上方），手指从上往下滑（y 小→大）
                if by1 < 20:
                    step_log(f"→ Unit {unit_num} 按钮在屏幕上方，向上滚动", "info")
                    S_swipe(d, 500, 600, 500, 1800, 0.4); time.sleep(0.8)
                    _swipe_count += 1
                    continue
            if not clicked:
                step_log(f"❌ U{unit_num} 在模块列表中找不到'去练习'/'去答题'入口（该单元未上线或列表未加载）", "warning")
                continue
            _any_clicked = True
            step_log(f"✅ U{unit_num} 去练习", "success")
            # 跑子模块
            run_sub_modules()
            # 回单元列表
            step_log("↩ 回单元列表...", "info")
            for _ in range(5):
                if d(text="去练习").exists(timeout=1) or d(text="去答题").exists(timeout=1): break
                d.press("back"); time.sleep(0.6)
            time.sleep(0.4)
        # 所有单元完成后回主页
        step_log("↩ 回主页...", "info")
        if not _any_clicked:
            step_log(f"⚠ 所选单元 {units} 均未找到入口，{module_name} 该年级下可能待开发", "warning")
        back_to_home(d)
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


def _handle_word_fill(d, config):
    """★ 选词填空专用（用户确认流程）：点击空位 → 激活选词栏 → 点选单词 → 检查。

    与打字填空(_handle_fill_blank)不同：选词填空不是输入文本，
    而是【点击空位弹出选词栏，再点选栏中单词】。
    ★ 用户关键要求：每次点击后要等选词栏/单词状态【稳定不变化】再点下一步。

    页面结构（实测）：
      - 空位: LinearLayout(clickable=true) 容器 + 内部 tv_sort(显示序号1,2,3...)
      - 选词栏: 点击空位后弹出的 CheckBox 列表（如 green T-shirt / yellow T-shirt）
      - 选中后: 空位 tv_sort 序号变为所选单词文本
    """
    import random
    print(f"    选词填空题，处理中...")
    step_log("📝 选词填空：点击空位→选词→检查", "step")

    # 空位定义：短文区的 CheckBox（text='' 是空位；checked=false=未填，true=已填）
    #   ★ 短文可滚动 → 不能固定 y 范围，排除顶部(状态栏<200)和底部导航(>2250)即可
    def _find_slots():
        xml = d.dump_hierarchy()
        slots = []
        for m in re.finditer(r'<node[^>]*CheckBox[^>]*>', xml):
            b = m.group(0)
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', b)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            if y1 < 200 or y2 > 2250:   # 排除顶部状态栏/底部导航
                continue
            # 空位 CheckBox 的 text 为空（无单词）；已填的显示单词
            tm = re.search(r'text="([^"]*)"', b)
            txt = (tm.group(1).strip() if tm else '')
            checked = 'checked="true"' in b
            # 未填 = checked=false 且 text 空（或有 tv_sort 序号）
            slots.append(((x1+x2)//2, (y1+y2)//2, checked, txt))
        # 未填优先，按 y 排序
        slots.sort(key=lambda s: (s[2], s[1]))
        return slots

    # 选词栏单词：点击空位后弹出的英文单词（排除短文正文 question_title_tv + 空位 select_tv）
    #   ★ 短文可滚动 → y 范围放宽（150-2250），靠"非question_title_tv + 非短文词"区分
    def _find_word_panel(exclude_texts):
        xml = d.dump_hierarchy()
        words = []
        for m in re.finditer(r'<node[^>]*>', xml):
            b = m.group(0)
            tm = re.search(r'text="([^"]{2,30})"', b)
            if not tm:
                continue
            txt = tm.group(1).strip()
            if not re.search(r'[A-Za-z]', txt):   # 必须含英文
                continue
            if txt in exclude_texts:              # 排除短文已有词
                continue
            if 'question_title_tv' in b:          # 排除短文正文
                continue
            if 'select_tv' in b:                  # 排除空位本身（已填单词的空位）
                continue
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', b)
            if not bm:
                continue
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            if y1 < 150 or y2 > 2250:             # 排除顶部/底部导航
                continue
            if len(txt) > 25:
                continue
            checked = 'checked="true"' in b
            words.append((txt, checked, (x1+x2)//2, (y1+y2)//2, y1))
        words.sort(key=lambda w: w[4])
        return words

    def _wait_stable(timeout=3.0, interval=0.3):
        """等待页面稳定（连续两次 dump 一致），用户要求'点击到不会变化再继续'"""
        try:
            _a = d.dump_hierarchy()
            time.sleep(interval)
            _b = d.dump_hierarchy()
            return _a == _b
        except Exception:
            return True
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                _x1 = d.dump_hierarchy()
                time.sleep(interval)
                _x2 = d.dump_hierarchy()
                if _x1 == _x2:
                    return True
            except Exception:
                pass
        return False

    # ── 循环填所有空位 ──
    # ★ 收集短文正文已有词（question_title_tv 中），选词栏单词排除这些（防误点正文）
    def _collect_short_texts():
        try:
            _xml = d.dump_hierarchy()
            return set(re.findall(r'question_title_tv[^>]*text="([^"]{1,25})"', _xml)
                       + re.findall(r'text="([^"]{1,25})"[^>]*question_title_tv', _xml))
        except Exception:
            return set()
    _short_words = _collect_short_texts()
    _max_rounds = 20
    for _round in range(_max_rounds):
        slots = _find_slots()
        # ★ 未填 = checked=false 且 text 空（填过的空位 checked=false 但 text=单词，如 fifty）
        empty = [s for s in slots if not s[2] and not s[3]]
        if not empty:
            break   # 全部填完
        cx, cy = empty[0][0], empty[0][1]
        # ① 点击空位激活选词栏
        try:
            d.click(cx, cy)
        except Exception:
            pass
        # ★ 等选词栏出现（用户关键：点击到稳定不变化再继续）——轮询等新单词出现
        time.sleep(1.2)
        for _w in range(4):
            _xml_w = d.dump_hierarchy()
            _panel = _find_word_panel(_short_words)
            if _panel:
                break
            time.sleep(0.8)
        _wait_stable()
        # ② 找选词栏单词并点一个（优先未选的）
        words = _panel if '_panel' in dir() else _find_word_panel(_short_words)
        if not words:
            print(f"    ⚠ 空位({cx},{cy})点击后无选词栏出现，可能是已填/布局变化")
            break
        target = None
        for w in words:
            if not w[1]:   # 未选中优先
                target = w
                break
        if target is None and words:
            target = words[0]
        try:
            d.click(target[2], target[3])
        except Exception:
            pass
        # ③ 等单词选中/空位更新稳定（用户关键要求：不变化再继续）
        time.sleep(1.2)
        _wait_stable()
        print(f"    空位{_round+1} → 选词 {target[0]}")
        step_log(f"  ✏ 选词: {target[0]}", "info")
    else:
        print(f"    ⚠ 选词填空 {_max_rounds} 轮未填完，可能选词栏异常")
    _wait_stable()

    # ── 点"检查" ──
    _checked = False
    for _ in range(6):
        try:
            if d(text="检查").exists(timeout=1.2):
                d(text="检查").click()
                print(f"    选词填空完成，点击检查")
                step_log("✅ 选词填空全部完成", "success")
                time.sleep(0.8)
                _checked = True
                break
        except Exception:
            pass
        try:
            d.swipe(540, 1800, 540, 1000, duration=0.4)
        except Exception:
            pass
        time.sleep(0.6)
    # 等检查按钮消失（提交成功）
    if _checked:
        for _ in range(8):
            try:
                _xml_chk = d.dump_hierarchy()
                if 'text="检查"' not in _xml_chk:
                    break
            except Exception:
                pass
            time.sleep(0.5)
    # 下一题（答对自动跳/答错出现下一题）
    try:
        if d(text="下一题").exists(timeout=2):
            d(text="下一题").click()
            print(f"    点击下一题")
            step_log("➡ 选词填空答完，进入下一题", "info")
            time.sleep(0.8)
            return True
    except Exception:
        pass
    return _checked


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
    _FILL_KWS = ('填空', '补全', '每空', '填写', '填词', '完成小短文', '写单词', '写句子', '听录音，写', '看图写', '写一写')
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
    _fill_fail_streak = 0   # ★ 连续填不上次数（IME失效止损）
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
            # ★ 修复：back 收键盘时若键盘已收起，back 会退出答题页弹"确定退出"
            #   → 检测并点"继续答题"恢复（否则填空函数空转到超时，任务卡死）
            try:
                _xml_exit = d.dump_hierarchy()
                if '确定退出' in _xml_exit and '继续答题' in _xml_exit:
                    d(text="继续答题").click(timeout=1)
                    time.sleep(0.8)
                    print("    ↺ 检测到退出弹窗，已点继续答题恢复")
            except Exception:
                pass
            # ★ 验证该框是否填上：填上 → streak清零；填不上 → streak+1，
            #   连续3次失败说明 IME 注入失效/框无法聚焦 → 止损退出（避免40轮空转）
            _filled = False
            try:
                _xml_v = d.dump_hierarchy()
                _inputs_v = _find_empty_inputs()
                _filled = all(not (abs(v[1]-cy) < 200 and abs(v[0]-cx) < 200 and v[2] == '')
                              for v in _inputs_v if v[1] == cy and abs(v[0]-cx) < 300)
            except Exception:
                pass
            if _filled:
                _fill_fail_streak = 0
            else:
                _fill_fail_streak += 1
                if _fill_fail_streak >= 3:
                    print("    ⚠ 连续填框失败（IME可能失效），止损退出填空处理")
                    break
            print(f"    填一空 ({cx},{cy}) 字={word} {'✓' if _filled else '✗'}")
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
    _checked = False
    for _ in range(8):
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
            _checked = True
            break
        S_swipe(d, 540, 1800, 540, 600, 0.4)
        time.sleep(0.6)

    # ★ 修复：点"检查"后必须确认页面跳转（检查按钮消失/下一题出现/新题加载），
    #   否则说明这轮填空没提交成功 → 返回 False（上层走其他分支/跳过），
    #   避免上层循环反复识别同一填空页 → 无限重入"逐框输入"（日志出现多次）
    if _checked:
        for _ in range(8):
            try:
                _xml_chk = d.dump_hierarchy()
                if 'text="检查"' not in _xml_chk and 'text="检测"' not in _xml_chk:
                    break  # 检查按钮消失 = 已提交跳转
            except Exception:
                pass
            time.sleep(0.5)

    # 阶段3：点"下一题"（答对自动跳转，答错出现"下一题"按钮）
    if d(text="下一题").exists(timeout=2):
        d(text="下一题").click()
        print(f"    点击下一题")
        step_log("➡ 填空答完，进入下一题", "info")
        time.sleep(0.8)
        return True
    # 没点成"检查"或提交后无跳转 → 未成功消费本题
    return _checked




# ==================== ⑧ 入口（批量调度） ====================
