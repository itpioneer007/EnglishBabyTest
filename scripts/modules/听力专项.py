"""
英语宝 · 听力专项 模块
=====================
独立可运行：python -m modules.听力专项  （或在 scripts/ 下 python modules/听力专项.py）

流程：启动 → 关广告 → 确认年级 → 进听力专项
  第一部分「练习」：遍历 U1-U9
    → 点"去练习" → 基础巩固 → 左滑 → 综合进阶 → 左滑 → 难点突破
    → 每个子模块答题 → 练习报告 → 继续练习(前2个) / back(最后1个)
  第二部分「测试」：测试 tab → 遍历 U1-U5
    → 去答题 → 好的我知道啦 → 开始答题 → 答题循环(17题) → 查看报告 → back

批量调用：from modules.听力专项 import run_module; run_module(d)

★ 排序题两种类型（防混淆）：
  1. 句子圆圈排序题（听录音，给句子排序）：句子前是圆圈，底部序号一进就在，
     不需要激活 → 直接按顺序点句子，序号自动 1,2,3... 填入 → _handle_sentence_sort
  2. 空方框排序题：句子是空方框，需点方框激活 → 底部序号按钮才出现 → 点序号
     → _handle_sort_question
"""
import os
import re
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.logger import step_log
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, back_to_home, scroll_and_find,
    smart_find_unit_row, applock_blocked, settle_ads,
)
from engine import run_single_module

# ═══════════ 模块配置 ═══════════
APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"


def _env_units():
    """从环境变量读取单元范围 (scheduler 设置); 未设置时默认 Unit 1"""
    f = os.environ.get("YYB_UNIT_FROM", "")
    t = os.environ.get("YYB_UNIT_TO", "")
    if f.isdigit():
        f = int(f)
        t = int(t) if t.isdigit() else f
        return list(range(f, t + 1))
    return [1]

UNITS = _env_units()  # 练习部分：U1-U9；测试先跑 U1
TEST_UNITS = _env_units()  # 测试部分：U1-U5；测试先跑 U1


def _resolve_units(units, default_units):
    """把外部传入的单元范围解析为列表；None 则用默认全部单元
    ★ 支持关键词目标（"期中"/"期末"/"AI检测"等非数字）直接透传"""
    if units is None:
        return list(default_units)
    if isinstance(units, list):
        return list(units)
    if isinstance(units, int):
        return [units]
    # 字符串：'1-3' / '1,3,5' / '1' 或列表字符串 / 关键词
    import re as _re
    result = []
    for part in str(units).split(","):
        part = part.strip()
        if not part:
            continue
        m = _re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            result.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            result.append(int(part))
        else:
            result.append(part)   # ★ 关键词（期中/期末/AI检测等）透传，按名字找
    return result or list(default_units)

CONFIG = {
    "entry_text": "听力专项",
    "units": UNITS,
    "entry_actions": [],
    "sub_modules": [
        {"name": "基础巩固", "enter_action": None},
        {"name": "综合进阶", "enter_action": "swipe_left_sub"},
        {"name": "难点突破",  "enter_action": "swipe_left_sub"},
    ],
    "post_entry_actions": [
        {"type": "click", "text": "开始答题", "timeout": 1},
        {"type": "click", "text": "重新答题", "timeout": 1},
    ],
    "report_action": {
        "trigger": {"type": "click", "text": "练习报告"},
        "after_report": [{"type": "click", "text": "继续练习", "timeout": 3}],
    },
    "next_button_texts": ["下一题", "继续"],
    "finish_texts": ["完成", "提交"],
    "empty_text": ["暂无数据"],
    "has_pagination": True,
    "question_types": {
        "sort": {
            # 排序题：把句子（所有可点击选项）全部点完才会出现"检查"按钮
            "detect_text": ["排序", "按顺序", "排序题", "给句子排序", "将句子排成", "排成正确的顺序", "按正确顺序排列"],
            "action": "sort_questions",
        },
        "match": {
            "detect_text": ["匹配", "配对", "为人物选择", "选择正确的描述"],
            "action": "match_questions",
        },
        "select_fill": {
            # ★ 选词填空（听力专项新题型）：句子中嵌空格框(CheckBox select_tv)，
            #   底部词库(select_btn)。交互：点空格激活 → 点词库词填入该空格。
            #   页面特征：含"选词填空/选词"关键词 + select_btn 词库词。
            "detect_text": ["选词填空", "选词", "听音选词", "从方框中选择", "选择正确的单词填空"],
            "action": "select_fill_questions",
        },
        "fill_blank": {
            # ★ 表格/短文补全（键盘注入）：页面有 EditText，复用 _handle_fill_blank
            #   （FastInputIME 注入）。页面特征：含"补全/填空/完成"关键词。
            "detect_text": ["补全表格", "选择正确的选项", "补全", "填空", "完成小短文", "填写",
                            "按要求完成句子", "完成句子", "句型转换", "改为", "将句子"],
            "action": "fill_blank_questions",
        },
    },
}


def run_module(d, units=None):
    """第一部分：练习模块——跑完听力专项指定单元+子模块，返回题数

    units: 单元范围，如 [1,2,3] 或 '1-3'；None=默认全部
    """
    t0 = time.time()
    _units = _resolve_units(units, UNITS)
    _cfg = dict(CONFIG)
    _cfg["units"] = _units
    print(f"\n📋 听力专项·练习 · 单元 {_units[0]}-{_units[-1]} · {len(_units)}个单元")
    q = run_single_module(d, "听力专项", _cfg)
    print(f"✅ 练习部分完成: {q} 题, 耗时 {time.time()-t0:.0f}s")
    return q


# ═══════════ 第二部分：测试模块 ═══════════

def _test_answer_loop(d, max_q=45):
    """测试卷答题循环：点选项→检查→(答对自动跳/答错点下一题)→最后一题查看报告
    
    处理题型：选择/判断(TF)、匹配(点方框+字母)、排序(点方框+序号)、中途"继续答题"弹窗
    ★ 计数从第1题开始（先 q+=1 再打印/记录，与 engine._answer_loop 一致）
    """
    q = 0
    _idle = 0  # 连续空转计数：无选项/无按钮但页面没变化 → 防漏答最后一题后死循环
    _blank = 0  # 空白/未响应连续次数（ATX 卡顿或系统对话框干扰，最多容忍 10 次不占空转额度）
    _ev_q = -1  # 已发证据卡的题号（每题只发一次）
    total_q = 0   # 总题数（界面右上角 "当前/总" 的右边数字，用户指出总题数在右上角右边）
    cur_q = 0     # 当前题号
    for i in range(max_q):
        # ★ 提速：整轮只 dump 一次（原来证据卡再 dump 一次 + 4 个 exists 各查一次，
        #   无弹窗时每题白等 ~3.2s）。弹窗/结束/选项判断全部用字符串匹配同一份 xml_now。
        # ★ 加保护：设备端 uiautomator 偶发异常（如 Errno 22）时重试 dump，不冒泡崩溃
        try:
            xml_now = d.dump_hierarchy() if d else ""
        except Exception:
            time.sleep(0.5)
            try:
                xml_now = d.dump_hierarchy() if d else ""
            except Exception:
                xml_now = ""
        if not xml_now:
            _blank += 1
            if _blank >= 5:
                step_log(f"⚠ dump 连续失败 {_blank} 次，退出", "error")
                return q
            continue

        # ★ evidence 收集移到"反馈消失后"块（见下方）—— 防止 dump 到反馈页导致题干误提取
        if q != _ev_q:
            pass  # 占位：evidence 在反馈等待循环之后收集
        # 中途弹窗"继续答题（0S）" → 点击（textContains 语义 → 子串匹配）
        if '继续答题' in xml_now:
            d(textContains="继续答题").click()
            print("      → 继续答题弹窗")
            time.sleep(0.6)
            _idle = 0
            continue
        # 练习子模块完成 → 练习报告（防卡：测试循环误入练习部分时）
        if 'text="练习报告"' in xml_now:
            d(text="练习报告").click()
            print("      → 练习报告（本轮结束）")
            step_log(f"📊 练习报告（本轮结束，共{q}题）", "success")
            time.sleep(0.8)
            # 报告页 → 继续练习/back 退出
            if d(textContains="继续练习").exists(timeout=1.5):
                d(textContains="继续练习").click()
                time.sleep(0.8)
            return q
        # 最后一题 → 查看报告
        if 'text="查看报告"' in xml_now:
            d(text="查看报告").click()
            print("      → 查看报告！测试完成")
            step_log(f"📊 测试完成，共{q}题", "success")
            time.sleep(0.8)
            return q
        # 答错后"下一题" → 点它
        if 'text="下一题"' in xml_now:
            # ★ 答错题目截图：捕获当前答错画面（含反馈+题目），供人工核验错题，
            #   并同步到前端「最近截图」展示（web_server 识别 evidence 写入面板）
            _wrong_shot = ""
            try:
                # ★ 截图前等 0.8s：题目内容（排序项/选项）渲染有延迟，
                #   立即截图会截到空白/半渲染画面（用户实测"排序题内容还没出来"）
                time.sleep(0.8)
                _shot_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "screenshots")
                os.makedirs(_shot_dir, exist_ok=True)
                _wrong_shot = f"wrong_q{q+1:02d}.png"
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
            d(text="下一题").click()
            print("      → 下一题(答错)")
            step_log(f"  第{q+1}题 答错截图", "warning",
                     evidence=[{"field": "错题截图", "type": "wrong_shot",
                                "screenshot": _wrong_shot}] if _wrong_shot else None)
            # ★ 竞态修复：等新题加载（"下一题"消失 或 出现选项/录音/查看报告），
            #   替代固定 sleep(0.6)——快则省时，慢则防 dump 到过渡页误判
            _t_w = time.time()
            while time.time() - _t_w < 2.0:
                try:
                    _xw = d.dump_hierarchy()
                    _xtxt = "".join(re.findall(r'text="([^"]+)"', _xw))
                    # 新题就绪信号：出现作答元素（字母/图片选项/录音/输入框）或"查看报告"
                    if ('text="[TFABCDE]"' in _xw or re.search(r'text="[TFABCDE]"', _xw)
                            or "点击录音" in _xtxt or "EditText" in _xw
                            or 'text="查看报告"' in _xw or "继续答题" in _xtxt):
                        break
                    # 题号推进（右上角 X/Y 中的 X 变化）
                    _m_pr = re.search(r'text="(\d+)/(\d+)"', _xw)
                    if _m_pr and int(_m_pr.group(1)) > q + 1:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            _idle = 0
            continue
        # ★ 回答后的反馈浮层（恭喜你 回答正确 / 很遗憾 回答错误）→ 原地等待其消失并
        #   重新 dump。★ 关键：不这样做的话反馈页会被当成"无选项"空转一轮，每题多耗
        #   一次 for 迭代额度，17题×2轮可能超出 max_q 导致提前静默返回（实测踩过坑）。
        for _fb in range(6):  # ★ 延长到6轮(2.4s)，确保答错反馈页完全消失
            if '恭喜你' in xml_now or '回答正确' in xml_now or '回答错误' in xml_now or '很遗憾' in xml_now:
                time.sleep(0.4)
                xml_now = d.dump_hierarchy() if d else ""
            else:
                break
        # ★ 2026-08-30 修复：过渡页/大题封面误识别为答题页（用户反馈 Q11 "听句子"题
        #   页面只有"分值:10分 + 继续答题(1S)"按钮，没真正题目内容，但旧逻辑发了证据卡
        #   → 审查卡显示"音频控件未检测到/选项未检测到"，加大检查人员工作量）
        #   判断：页面有"继续答题"/"开始答题"按钮 OR 仅有"分值"且无任何作答元素 → 过渡页
        if "继续答题" in xml_now or "开始答题" in xml_now or "测试题目选题" in xml_now:
            _is_transition = True
        else:
            # 有分值但没题目内容（无字母选项/CheckBox/EditText/录音按钮/序号按钮）→ 过渡页
            _has_score = "分值" in xml_now
            _has_no_q_elm = (
                not re.search(r'text="[TFABCDE]"', xml_now)
                and "EditText" not in xml_now
                and "CheckBox" not in xml_now
                and "点击录音" not in xml_now and "原音" not in xml_now
                and "img_sort_btn" not in xml_now
                and "排序" not in xml_now
            )
            _is_transition = _has_score and _has_no_q_elm
        if _is_transition:
            # 过渡页：跳过 evidence 收集（不计数 +1，避免污染题数）
            if "继续答题" in xml_now:
                d(textContains="继续答题").click()
                time.sleep(0.5)
            elif "开始答题" in xml_now:
                # 试卷封面"开始答题"→ 点进入（避免空转退出）
                try:
                    d(text="开始答题").click(); time.sleep(0.8)
                except Exception:
                    pass
            _idle = 0
            continue

        # ★ 反馈浮层消失后再发 evidence（用户实测：旧逻辑循环开头 dump，可能 dump 到
        #   反馈页"恭喜你，答对了"，题干就提取不到题目而是反馈文字 → 证据卡"未提取到题干文字"）
        if q != _ev_q:
            try:
                from common.evidence import collect_ui_evidence
                # ★ 过滤反馈残留：若 xml_now 仍含"恭喜你/回答正确/回答错误/很遗憾"，
                #   再等 0.5s 重 dump（防止答错后立即转新题时新题题干还没渲染完）
                for _ed in range(3):
                    if '恭喜你' not in xml_now and '回答正确' not in xml_now \
                            and '回答错误' not in xml_now and '很遗憾' not in xml_now:
                        break
                    time.sleep(0.5)
                    xml_now = d.dump_hierarchy() if d else ""
                # ★ 稳定等待：dump 后固定等 0.8s 再重新 dump 作为 evidence 源，
                #   确保题干渲染完成（首题更长 2s：试卷说明→答题页）
                if q == 0:
                    time.sleep(2.0)
                else:
                    time.sleep(0.8)
                xml_now = d.dump_hierarchy() if d else ""
                step_log(f"  第{q+1}题 完整性检查", "info",
                         collect_ui_evidence(xml_now, qtype="听力专项测试"))
                _ev_q = q
            except Exception:
                pass
        # 新题：找选项（复用上面的 xml_now）
        # ⚠ 关键修复：上一版正则 `text="X"[^>]*clickable="true"` 要求「同一节点」同时有
        #   字母 text 和 clickable。但真实 App 选项字母在【不可点击的子 TextView】上，
        #   可点击的是【父容器】，导致正则永不命中 → 字母题全部答不了（"不会答题"）。
        #   现改为：遍历整节点，单独提取 text 与 bounds（不要求 clickable/属性顺序），
        #   点击用坐标点击 d.click(x,y)。

        # ★ 读取总题数（界面右上角 "当前/总"，用户指出总题数在右上角右边）
        _m = re.search(r'text="(\d+)/(\d+)"', xml_now)
        if _m:
            cur_q = int(_m.group(1)); total_q = int(_m.group(2))

        # ★ 排序题优先检测（必须放在字母/图片选项之前！）
        #   排序题界面含 CheckBox(序号圆圈 img_sort_btn) 或 题干含"排序"，
        #   会被下方"图片选项"分支(找 CheckBox)误捕获 → 点到序号圆圈而非图片 → 排序失败。
        #   正确解法（★ 三分类，判别逻辑与 engine._answer_loop 一致）：
        #   图片排序(img_sort_btn) → _handle_sort_question 模式A（直接点大图）；
        #   圆圈排序(≥3个 宽>800 整句 CheckBox) → _handle_sentence_sort（直接点句子，序号自动填）；
        #   方框排序(其余含"排序") → _handle_sort_question 模式B（点方框激活→点底部序号）。
        if 'img_sort_btn' in xml_now or '排序' in xml_now:
            from engine import _handle_sort_question, _handle_sentence_sort
            if 'img_sort_btn' in xml_now:
                _handle_sort_question(d, {})   # 图片排序 模式A
            else:
                # ★ 圆圈排序判别：句子本身是宽>800 的整行 CheckBox（文本≥6字符，y 700-1900）
                _circle_cnt = 0
                for _m4 in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*/?>', xml_now):
                    _t4 = _m4.group(0)
                    _tm4 = re.search(r'text="([^"]{6,})"', _t4)
                    _bm4 = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _t4)
                    if not (_tm4 and _bm4):
                        continue
                    _x4, _y4 = int(_bm4.group(1)), int(_bm4.group(2))
                    if (int(_bm4.group(3)) - _x4) > 800 and 700 < _y4 < 1900:
                        _circle_cnt += 1
                if _circle_cnt >= 3:
                    _handle_sentence_sort(d, {})   # 圆圈排序：直接点句子
                else:
                    _handle_sort_question(d, {})   # 方框排序 模式B
            q += 1
            _idle = 0
            step_log(f"  第{q}题(排序): 处理完毕 → 检查 (总题数 {total_q})", "info")
            # 排序可能是最后一题 → 查看报告（界面已被排序处理点击过，需重新 dump；
            #   轮询最多 ~1.6s，等价原 exists(1.5) 但用字符串匹配更快）
            for _r in range(4):
                if 'text="查看报告"' in d.dump_hierarchy():
                    d(text="查看报告").click()
                    step_log(f"📊 测试完成，共{q}题", "success")
                    time.sleep(0.8)
                    return q
                time.sleep(0.4)
            continue

        opt = None
        opt_xy = None
        import re as _re_opt
        # ★ 字母选项：稳健提取（finditer 整节点，单独取 text + bounds）
        for m in _re_opt.finditer(r'<node[^>]*>', xml_now):
            tag = m.group(0)
            tm = _re_opt.search(r'text="([TFABCDE])"', tag)
            if not tm:
                continue
            bm = _re_opt.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = map(int, bm.groups())
            if y1 > 320 and (x2 - x1) >= 20 and (y2 - y1) >= 20:  # 选项中区且尺寸合理
                opt = tm.group(1)
                opt_xy = ((x1 + x2) // 2, (y1 + y2) // 2)
                break
        # ★ u2 原生兜底：dump 偶发截断/漏节点（实测页面有 T/F 但手写正则未命中），
        #   d(text=...) 内部会自动重新 dump 且带超时重试，比手写正则更稳。
        if opt is None:
            for _ch in ("T", "F", "A", "B", "C", "D", "E"):
                try:
                    if d(text=_ch).exists(timeout=0.3):
                        _b = d(text=_ch).bounds
                        _x1, _y1, _x2, _y2 = _b[0], _b[1], _b[2], _b[3]
                        if _y1 > 320 and (_x2 - _x1) >= 20 and (_y2 - _y1) >= 20:
                            opt = _ch
                            opt_xy = ((_x1 + _x2) // 2, (_y1 + _y2) // 2)
                            break
                except Exception:
                    continue
        if opt:
            q += 1  # ★ 先计数再打印：第1题从1开始（原逻辑先打印第0题再+1，导致计数偏移）
            d.click(*opt_xy) if opt_xy else d(text=opt).click()
            print(f"      → 选 {opt}")
            step_log(f"  第{q}题: 选 {opt} → 检查", "info")
            time.sleep(0.15)
            # 等检查出现（★ 提速：缩短轮询间隔，通常首轮即命中）
            for _ in range(6):
                if d(text="检查").exists(timeout=0.15):
                    d(text="检查").click()
                    print(f"      → 检查")
                    time.sleep(0.3)
                    break
                time.sleep(0.1)
            continue
        # ★ 图片题选项：字母选项没有时，检测 CheckBox 候选（用户反馈：第16题是图片题）
        #   真机验证：选项 CheckBox 的 clickable="false"（如 T/F 判断框、图片选项框），
        #   故此处【不要求 clickable】，只校验 bounds 在选项区（与字母分支一致）。
        _img_xy = None
        for m in _re_opt.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*>', xml_now):
            tag = m.group(0)
            bm = _re_opt.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bm:
                continue
            x1, y1, x2, y2 = map(int, bm.groups())
            if y1 > 400:  # y>400 选项区
                _img_xy = ((x1 + x2) // 2, (y1 + y2) // 2)
                break
        if _img_xy:
            # ★ 图片题截图：供脚本生成时视觉识别补全选项内容/答案
            #   （脚本图片题选项只有"A./B."占位 → 识别截图填内容，审查可核对）
            try:
                _img_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "screenshots", "script_imgs")
                os.makedirs(_img_dir, exist_ok=True)
                _img_f = f"listen_q{q+1:02d}.png"
                for _ir in range(3):
                    try:
                        d.screenshot(os.path.join(_img_dir, _img_f))
                        break
                    except OSError:
                        if _ir >= 2:
                            raise
                        time.sleep(0.4)
                print(f"      → 图片题截图: script_imgs/{_img_f}")
            except Exception:
                pass
            d.click(*_img_xy)
            opt = "图片选项"
            q += 1
            print(f"      → 选 图片选项 (CheckBox)")
            step_log(f"  第{q}题: 选图片选项 → 检查", "info")
            time.sleep(0.15)
            for _ in range(6):
                if d(text="检查").exists(timeout=0.15):
                    d(text="检查").click()
                    time.sleep(0.3)
                    break
                time.sleep(0.1)
            continue
        # 匹配题：点第一个方框 → 点字母（★ 提速：用 xml_now 正则提取文本，省一次 xpath 查询）
        texts = " ".join(re.findall(r'text="([^"]+)"', xml_now))
        if any(kw in texts for kw in ("匹配", "配对")):
            q += 1  # ★ 先计数（与选择分支一致，第1题从1开始）
            from engine import _handle_match_question
            _handle_match_question(d, {})
            _idle = 0
            continue
        # ★ 排序题已在上方「排序题优先检测」块处理（img_sort_btn / 题干含"排序"），
        #   此处不再重复；保留空分支避免误触（若上方未捕获将 fall through 到无选项分支）。
        # 无选项无按钮 → 检查页面/加载中/最后一题报告页
        # ★ 空转保护：页面没变化连续多轮 → 可能已答完最后一题但"查看报告"未识别到，
        #   再检测一次"查看报告/完成"再退出，避免漏答/提前 back
        # ★ 提速：文本提取用 xml_now 正则，省掉 xpath 全量查询；查看报告保留一次
        #   新 dump 兜底（报告页可能在迭代中途才出现，等价原 exists(0.5) 的新鲜度）
        _no_opt_list = re.findall(r'text="([^"]+)"', xml_now)
        _no_opt_text = "".join(_no_opt_list)
        if ('text="查看报告"' in xml_now or "查看报告" in _no_opt_text
                or 'text="查看报告"' in d.dump_hierarchy()):
            d(text="查看报告").click()
            print("      → 查看报告！测试完成")
            step_log(f"📊 测试完成，共{q}题", "success")
            time.sleep(0.8)
            return q
        if 'text="完成"' in xml_now or 'text="提交"' in xml_now:
            step_log(f"📊 测试结束信号（完成/提交），共{q}题", "success")
            return q
        # ★ 异常页恢复（实测 web 运行曾在 Q1 连续 12 轮"无选项"退出 0 题）：
        #   ① 系统验证弹窗（点到广告触发，safecenter）→ back 退出 + 清广告；
        #   ② 页面空白/ATX 卡顿（dump 只有状态栏）→ 关广告/弹窗后仍空白则等待重试，
        #      不占空转额度（最多 10 次），给无障碍服务恢复时间。
        if 'com.oplus.safecenter' in xml_now or '面部验证' in xml_now or '密码验证' in xml_now:
            d.press("back"); time.sleep(0.8)
            settle_ads(d, wait_total=4)
            print("    🔔 检测到系统验证弹窗（疑似点到广告），已退出并清广告，重新解析")
            continue
        if re.search(r"\d+/\d+", _no_opt_text) is None and len(_no_opt_list) <= 4:
            _c1 = _c2 = False
            try:
                _c1 = dismiss_global_popups(d)
            except Exception:
                pass
            try:
                _c2 = close_ad(d)
            except Exception:
                pass
            if _c1 or _c2:
                print("    🔔 页面疑似被广告/弹窗盖住，已关闭，重新解析")
                time.sleep(0.5)
                continue
            if _blank < 10:
                _blank += 1
                print(f"    ⏳ 页面空白/未响应（{_blank}/10），等待后重试…")
                time.sleep(1.5)
                continue
        else:
            _blank = 0  # 页面有内容（有题号/文本），重置空白计数
        _idle += 1
        if _idle >= 12:
            # ★ 页面仍显示题号（如 "1/17"）说明确实在答题页，只是选项未渲染/加载慢，
            #   多等几轮再退出（用户反馈：测试答题界面 T/F 按钮有时延迟出现）
            _qno_m = re.search(r"\d+/\d+", _no_opt_text)
            if _qno_m:
                step_log(f"⚠ 答题页选项未渲染（{_idle}轮，题号 {_qno_m.group(0)}），继续等待…", "warning")
                if _idle >= 25:
                    step_log(f"⚠ 连续 {_idle} 轮无有效选项，退出", "warning")
                    return q
                time.sleep(2.0)
                continue
            step_log(f"⚠ 连续 {_idle} 轮无有效选项（可能停在非答题页/最后一题未识别），退出", "warning")
            return q
        print(f"    ⚠ 无选项({_idle}): {_no_opt_list[:6]}")
        time.sleep(0.4)
    return q


def run_test_module(d, test_units=None):
    """第二部分：测试模块——测试 tab 遍历指定单元，返回题数

    test_units: 单元范围，如 [1,2] 或 '1-2'；None=默认全部
    """
    t0 = time.time()
    total = 0
    _tunits = _resolve_units(test_units, TEST_UNITS)
    _desc = "、".join(str(x) for x in _tunits)
    print(f"\n📋 听力专项·测试 · 目标: {_desc} · {len(_tunits)}项")

    # 确认在听力专项页 → 点"测试" tab
    if not d(text="测试").exists(timeout=3):
        if not scroll_and_find(d, "听力专项"):
            print("  ❌ 找不到听力专项入口"); return 0
        # ★ 广告延迟加载（冷重启后 4-6s 甚至更晚才弹出）：点击入口前先关广告，
        #   避免"点空 / 广告刚弹出瞬间误点"→ 导航被带歪（用户实测根因）
        settle_ads(d, wait_total=6)
        d(text="听力专项").click(); time.sleep(1.2)
        # ★ 系统验证弹窗（点到广告触发，用户定位：只有点广告才会弹）→ 先等自动消失；
        #   持续不退 → back 关闭 + 清广告重试一次
        if applock_blocked(d):
            _cleared = False
            for _lk in range(10):
                time.sleep(0.5)
                if not applock_blocked(d):
                    _cleared = True
                    break
            if _cleared:
                print("  ⏳ 系统验证弹窗已自动消失，继续…")
            else:
                d.press("back"); time.sleep(0.8)
                settle_ads(d, wait_total=6)
                if not applock_blocked(d):
                    print("  ⏳ 系统验证弹窗已关闭（疑似点到广告），已清广告，继续…")
                else:
                    print("  ❌ 被系统验证（使用面部验证/密码验证）挡住，请先解锁「听力专项」，再重新运行")
                    return 0
        # ★ 进入模块页后广告可能刚好弹出 → 再关干净一次再找 tab
        settle_ads(d, wait_total=6)
    if not d(text="测试").exists(timeout=3):
        print("  ❌ 找不到测试 tab"); return 0
    # ★ 点"测试" tab 前再确认无广告（广告常在页面切换瞬间弹出）
    settle_ads(d, wait_total=4)
    d(text="测试").click(); time.sleep(1.2)
    print("  ✅ 已进入测试 tab")

    for ui, unit_num in enumerate(_tunits):
        print(f"\n  🎯 测试目标 [{unit_num}] [{ui+1}/{len(_tunits)}]")
        # ★ 智能定位：数字/区间/关键词（期中/期末/AI检测…）随机应变找"去答题"
        #   ★ App 测试模块已恢复：正常点击测试 tab 后逐单元测（此前下线时自动跳过）
        found = smart_find_unit_row(d, unit_num, click_text="去答题")
        if not found:
            print(f"  ❌ 找不到目标 [{unit_num}] 的去答题"); continue
        time.sleep(0.8)
        # 规则弹窗"好的，我知道啦~"
        if d(text="好的，我知道啦~").exists(timeout=3):
            d(text="好的，我知道啦~").click(); time.sleep(0.8)
        # 开始答题
        if d(text="开始答题").exists(timeout=3):
            d(text="开始答题").click(); time.sleep(1.2)
        # 答题循环
        q = _test_answer_loop(d)
        total += q
        print(f"  ✅ U{unit_num} 测试完成: {q} 题")
        # back 回测试列表
        for _ in range(3):
            if d(text="去答题").exists(timeout=1.5):
                break
            d.press("back"); time.sleep(0.6)
        # 回到测试 tab
        if d(text="测试").exists(timeout=2):
            d(text="测试").click(); time.sleep(0.8)

    print(f"✅ 测试部分完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
    return total


def run_all(d):
    """练习 + 测试 完整流程"""
    q1 = run_module(d)        # 练习
    q2 = run_test_module(d)   # 测试
    print(f"\n📊 听力专项汇总: 练习 {q1} 题 + 测试 {q2} 题")
    return q1 + q2


def main():
    d = u2.connect()
    print("✅ 设备已连接")

    # 1. 重启 App 回主页
    d.press("home"); time.sleep(0.4)
    d.app_stop(APP_PACKAGE); time.sleep(0.8)
    d.app_start(APP_PACKAGE); time.sleep(3)

    # 2. 关广告 + 确认年级（★ settle_ads 循环关，消除"点空/广告刚弹出时误点"竞态）
    settle_ads(d, wait_total=12)
    # ★ 仅命令行单跑时需要；多模块调度器已在开头统一切换一次，不重复
    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败")
        return 1

    # 3. 跑听力专项（练习 + 测试）
    run_all(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())

