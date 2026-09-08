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
    smart_find_unit_row, applock_blocked, settle_ads, enter_module_by_entry,
)
from engine import run_single_module

# ═══════════ 模块配置 ═══════════
APP_PACKAGE = "com.dinoenglish.yyb"


def resolve_grade_version(grade=None, version=None):
    """年级/版本的唯一来源：调用方显式传入（来自 UI 年级版本栏）> 环境变量 > 兜底默认值。

    ★ 关键：不再在模块导入时固化（旧写法 GRADE_LEVEL=os.environ.get(...) 在首次导入后失效，
      导致换年级后自动化仍用旧年级）。改为每次调用时实时解析，保证跟随 UI 栏选择。
    """
    g = (grade or os.environ.get("YYB_GRADE") or "六年级上册").strip()
    v = (version or os.environ.get("YYB_VERSION") or "湘少版").strip()
    return g, v


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
            #   （FastInputIME 注入）。页面特征：含"补全/填空/完成/写单词"关键词。
            "detect_text": ["补全表格", "选择正确的选项", "补全", "填空", "完成小短文", "填写",
                            "按要求完成句子", "完成句子", "句型转换", "改为", "将句子",
                            "写单词", "写句子", "听录音，写", "看图写", "写一写"],
            "action": "fill_blank_questions",
        },
    },
}


def run_module(d, units=None, grade=None, version=None):
    """第一部分：练习模块——跑完听力专项指定单元+子模块，返回题数

    units: 单元范围，如 [1,2,3] 或 '1-3'；None=默认全部
    grade/version: 目标年级/版本（来自 UI 年级版本栏）；不传则回退环境变量/默认
    """
    grade, version = resolve_grade_version(grade, version)
    # ★ 自我纠正：进入模块前确认 App 已切到用户选择的年级/版本，
    #   避免沿用上一次运行残留的旧年级（用户根因：换年级不生效）
    try:
        _ok = ensure_grade(d, grade, version)
        if not _ok:
            print(f"  ❌ 年级/版本确认失败，终止任务")
            return 0
    except Exception as e:
        print(f"  ⚠ 年级确认异常(继续): {e}")
    t0 = time.time()
    _units = _resolve_units(units, UNITS)
    _cfg = dict(CONFIG)
    _cfg["units"] = _units
    step_log(f"📋 听力专项·练习 · 单元 {_units[0]}-{_units[-1]} · {len(_units)}个单元", "info")
    q = run_single_module(d, "听力专项", _cfg)
    print(f"✅ 练习部分完成: {q} 题, 耗时 {time.time()-t0:.0f}s")
    return q


# ═══════════ 第二部分：测试模块 ═══════════

def _test_answer_loop(d, max_q=45, stop_check=None):
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

    def _is_instruction_page(xml):
        """判断当前页是否为大题/题型说明页（非真正题目页）。

        核心规则：
          1) 页面右上角有题号 "X/Y"（text 或 content-desc，如 6/16）→ 真实题目页。
          2) 有选项字母 A/B/C/D/T/F（含 A./A、/A. xxx 等）→ 真实题目页。
          3) 有输入框/CheckBox → 真实题目页。
          4) 无题号、无选项，但有"继续答题"/"分值"/"共N分"/大题序号 → 说明页。
        """
        if not xml:
            return False
        # 1) 有题号 → 真实题目页
        if re.search(r'(text|content-desc)="\d+\s*/\s*\d+"', xml):
            return False
        # 2) 有选项字母 → 真实题目页（注意不强制结尾引号，可匹配 A. xxx 完整选项）
        if re.search(r'text="[TFABCDE][\.、．]?', xml):
            return False
        # 3) 有输入框/CheckBox → 真实题目页
        if 'class="android.widget.EditText"' in xml or 'class="android.widget.CheckBox"' in xml:
            return False
        # 4) 有"继续答题"按钮 → 说明页
        if '继续答题' in xml:
            return True
        # 5) 无题号、无选项，但有说明页文字 → 说明页
        texts = "".join(re.findall(r'text="([^"]+)"', xml))
        if ('分值' in texts or re.search(r'[（(]共\s*\d+\s*分[）)]', texts)) \
                and ('听' in texts or 'listen' in texts.lower()):
            return True
        if re.search(r'[ⅠⅡⅢⅣⅤ][\.．、]\s*听', texts):
            return True
        return False

    for i in range(max_q):
        # ★ 停止信号检查：前端点"停止"会置 _STOP_REQUESTED=True，这里命中即中断答题循环
        #   避免填空题/无选项分支死等时停止按钮无效（同步循环不检查则无法中断）
        if stop_check is not None and stop_check():
            step_log(f"⏹ 收到停止信号，终止答题（已答 {q} 题）", "warning")
            return q
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
        # ★ 中途弹窗/大题说明页"继续答题（XS）" → 跳过，不当作题目计数
        #   测试卷每完成一个大题（如Ⅰ.听单词）进入下一个大题（如Ⅱ.听句子）前，
        #   会出现题型说明页；若把它当题，会导致真实题号整体错位。
        if _is_instruction_page(xml_now):
            # ★ 调试：输出被判定为说明页时的页面文本，便于判断是否误杀真实题目
            try:
                _dbg_texts = [t for t in re.findall(r'text="([^"]+)"', xml_now) if t.strip()][:15]
                _dbg_msg = f"[DEBUG-说明页] 第{q+1}题位置，页面文本: {_dbg_texts}"
                print(f"      {_dbg_msg}")
                step_log(_dbg_msg, "warning")
            except Exception:
                pass
            # 循环点击"继续答题"直到真正离开说明页（倒计时未结束可能需多点几次）
            for _ic in range(5):
                if '继续答题' in xml_now:
                    try:
                        d(textContains="继续答题").click()
                        print("      → 跳过题型说明页，点击继续答题")
                    except Exception as _e:
                        print(f"      ⚠ 点击继续答题失败: {_e}")
                time.sleep(0.7)
                xml_now = d.dump_hierarchy() if d else ""
                if not _is_instruction_page(xml_now):
                    break
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
        # ★ 截图依据已改：不再"答错就截图"。题目截图在每题完整性检查前抓取(qshot)，
        #   只有当 AI六维 或 LLM 审查判出错时，才由 web_server 把该截图贴到审查结果。
        if 'text="下一题"' in xml_now:
            d(text="下一题").click()
            print("      → 下一题(答错)")
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
        # ★ 基于当前页面题号收集 evidence：说明页跳过，真实题目页按右上角题号记录。
        #   避免"一题答对+evidence 收集后 _ev_q 追上 q，导致下一题被跳过"的问题。
        try:
            from common.evidence import collect_ui_evidence
            # 说明页/过渡页直接跳过
            if _is_instruction_page(xml_now):
                continue
            # 真实题目页：从右上角题号读取当前题号
            _m_qno = re.search(r'text="(\d+)\s*/\s*\d+"', xml_now)
            if _m_qno:
                cur_page_q = int(_m_qno.group(1))
                if _ev_q < cur_page_q:
                    # 稳定等待，确保题干渲染完成（首题更长 2s：试卷说明→答题页）
                    if q == 0:
                        time.sleep(2.0)
                    else:
                        time.sleep(0.8)
                    xml_now = d.dump_hierarchy() if d else ""
                    # 等待后再次确认不是说明页
                    if _is_instruction_page(xml_now):
                        continue
                    # ★ 每题抓一张题目截图（答题前，含题干+选项，无反馈浮层）。
                    #   是否显示在审查结果由 AI/LLM 审查是否出错决定（不再以"答错"为依据）
                    _qshot = ""
                    try:
                        # ★ 截图存到 项目根/screenshots（与 web_server 的 /api/screenshot 一致，否则前端读不到）
                        _proj = os.path.dirname(os.path.abspath(__file__))
                        while _proj and os.path.dirname(_proj) != _proj \
                                and not os.path.exists(os.path.join(_proj, "web_server.py")):
                            _proj = os.path.dirname(_proj)
                        _sd = os.path.join(_proj, "screenshots")
                        os.makedirs(_sd, exist_ok=True)
                        _qshot = f"q{cur_page_q:02d}.png"
                        for _r in range(3):
                            try:
                                d.screenshot(os.path.join(_sd, _qshot))
                                break
                            except OSError:
                                if _r >= 2:
                                    raise
                                time.sleep(0.5)
                    except Exception as _se:
                        print(f"      ⚠ 题目截图失败: {_se}")
                        _qshot = ""
                    _ev = collect_ui_evidence(xml_now, qtype="听力专项测试")
                    if _qshot:
                        _ev.append({"field": "题目截图", "type": "q_shot", "screenshot": _qshot})
                    step_log(f"  第{cur_page_q}题 完整性检查", "info", _ev)
                    _ev_q = cur_page_q
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
        # ★ 填空题（听录音填写单词/完成句子/补全短文）：页面有 EditText + 题干含关键词
        #   测试卷常见："听录音，填写单词，完成句子。" → 用 FastInputIME 注入占位词，避免空转卡死
        _texts_all = " ".join(re.findall(r'text="([^"]+)"', xml_now))
        if 'class="android.widget.EditText"' in xml_now and any(kw in _texts_all for kw in ("填写单词", "完成句子", "填空", "补全短文", "填写", "完成小短文", "写单词", "写句子", "听录音，写", "看图写", "写一写")):
            # ★ 停止信号：填空题分支也检查，保证卡在此类题时仍能中断
            if stop_check is not None and stop_check():
                step_log(f"⏹ 收到停止信号，终止答题（已答 {q} 题）", "warning")
                return q
            q += 1
            print(f"      → 第{q}题识别为填空/填写题")
            step_log(f"  第{q}题: 填空/填写题 → 自动填入占位词", "info")
            try:
                from engine import _handle_fill_blank
                _handle_fill_blank(d, {})
            except Exception as _e:
                print(f"      ⚠ 填空处理异常: {_e}")
                step_log(f"  第{q}题 填空处理异常，跳过", "warning")
            _idle = 0
            # ★ 兜底提交：部分测试卷填空题无"检查"按钮，只有"下一题/提交/完成"，
            #   _handle_fill_blank 找不到检查就会返回且不前进；若下一轮仍识别为填空题
            #   会再次填空 → 死循环。这里主动找"下一题/提交/完成"并点击，让流程前进。
            #   （若 _handle_fill_blank 已点"检查"并进入反馈页，则"下一题"会被命中并点击）
            time.sleep(0.6)
            for _sb in ("下一题", "提交", "完成", "确定"):
                try:
                    if d(text=_sb).exists(timeout=0.6):
                        d(text=_sb).click()
                        print(f"      → 填空后点 {_sb}")
                        step_log(f"  第{q}题 填空提交：{_sb}", "info")
                        break
                except Exception:
                    pass
            # 等一帧，让反馈/新题出现
            time.sleep(0.8)
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
        # ★ 兜底：说明页漏到此处，直接跳过不走空转
        if _is_instruction_page(xml_now):
            print("      → 兜底跳过说明页")
            _idle = 0
            continue
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


# ═══════════ 测试选择器解析与匹配 ═══════════
def _parse_test_selectors(test_units):
    """前端/旧调用传入的 test_units → 选择器列表 [{tab,units,papers}]；
    返回 None 表示『枚举全部』（全部 tab 下所有卷）。"""
    raw = test_units
    if isinstance(raw, (list, tuple)):
        raw = ','.join(str(x) for x in raw)
    raw = (raw or '').strip()
    if raw in ('', 'all', '全部'):
        return None
    if raw == '考前突破':
        return [{'tab': '考前突破', 'units': None, 'papers': None}]
    if '|' in raw:
        sels = []
        for part in raw.split(';'):
            seg = part.strip()
            if not seg:
                continue
            bits = seg.split('|')
            tab = (bits[0].strip() or None) if len(bits) > 0 else None
            units = (bits[1].strip() or None) if len(bits) > 1 else None
            papers = (bits[2].strip() or None) if len(bits) > 2 else None
            sels.append({'tab': tab, 'units': units, 'papers': papers})
        return sels or None
    if re.fullmatch(r'(\d+(-\d+)?)(,\d+(-\d+)?)*', raw):
        return [{'tab': '单元', 'units': raw, 'papers': None}]
    return [{'tab': raw, 'units': None, 'papers': None}]


_TAB_ALIAS = {
    '全部': ['全部'],
    '单元': ['单元'],
    '期中': ['期中', '期中评价'],
    '期末': ['期末', '期末评价', '期末测评'],
    '考前突破': ['考前突破'],
}


def _click_test_tab(d, tab):
    """点测试页筛选 tab；tab=None/『全部』→ 点『全部』。找不到返回 False。"""
    name = tab or '全部'
    for c in _TAB_ALIAS.get(name, [name]):
        try:
            if d(text=c).exists(timeout=1.5):
                d(text=c).click(); time.sleep(1.0)
                return True
        except Exception:
            pass
    try:
        if d(text=name).exists(timeout=1.5):
            d(text=name).click(); time.sleep(1.0)
            return True
    except Exception:
        pass
    return False


_PAPER_KW = ('阶段评价', '期末评价', '期中评价', '单元评价', '阶段测评',
             '期末测评', '期中测评', 'Units', 'Unit ')


def _is_paper_title(t):
    tab_names = {'全部', '单元', '期中', '期末', '考前突破', '阶段测评',
                 '期末测评', '专项', '月测', '月度'}
    if not t or t in tab_names:
        return False
    return any(k in t for k in _PAPER_KW)


def _unit_match(t, units):
    if not units:
        return True
    m = re.match(r'^(\d+)\s*-\s*(\d+)$', units)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if re.search(r'Units?\s*%d\s*[-–~]\s*%d' % (a, b), t, re.I):
            return True
        for n in range(a, b + 1):
            if re.search(r'Unit\s*%d(?:\D|$)' % n, t, re.I):
                return True
        return False
    for part in units.split(','):
        part = part.strip()
        if re.fullmatch(r'\d+', part):
            n = int(part)
            if re.search(r'Unit\s*%d(?:\D|$)' % n, t, re.I):
                return True
    return False


def _paper_match(t, papers):
    if not papers:
        return True
    p = papers.upper()
    if 'A' in p and 'B' in p:
        return True
    if p == 'A':
        return ('（A）' in t) or ('(A)' in t) or ('A卷' in t)
    if p == 'B':
        return ('（B）' in t) or ('(B)' in t) or ('B卷' in t)
    return True


def _paper_has_ab(t):
    """标题是否含 A/B 卷字样（用于判断当前版本是否分卷）。"""
    return (('（A）' in t) or ('(A)' in t) or ('A卷' in t)
            or ('（B）' in t) or ('(B)' in t) or ('B卷' in t))


def _collect_papers_current(d):
    """测试页当前视图：收集所有 (卷标题, 去答题按钮) 对
    ★ 配对规则：卷标题在上、去答题按钮在其【下方最近】。只接受位于标题下方
      （按钮 top >= 标题 bottom - 80）的按钮，避免误配到上方卷的按钮。
      末项卷标题贴屏底时按钮在屏外未渲染（best=None），由调用方滑动加载。"""
    try:
        els = d.xpath('//*[@text!=""]').all()
    except Exception:
        return []
    out = []
    for e in els:
        t = (e.text or '').strip()
        if not _is_paper_title(t):
            continue
        row_bottom = e.bounds[3]
        cand = [b for b in els
                if (b.text or '').strip() in ('去答题', '重新答题', '继续答题')
                and b.bounds[1] >= row_bottom - 80]
        if cand:
            best = min(cand, key=lambda b: b.bounds[1])  # 最靠上（离标题最近）
            out.append((t, best))
    return out


def run_test_module(d, test_units=None, grade=None, version=None, stop_check=None):
    """第二部分：测试模块——按选择器点对应筛选 tab 与卷（支持 A/B 卷、单元范围）

    选择器字符串（前端弹窗产出）：TAB|UNITS|PAPERS
      TAB   : 全部/单元/期中/期末/考前突破（点对应筛选 tab）
      UNITS : 单元范围——'1-5'/'6-10'（六下阶段评价）或 '2,3'（三下 Unit N）
      PAPERS: A / B / AB（默认 AB；三下无分卷时自动忽略）
    兼容旧式：纯数字/区间 → 单元 tab 按单元号；关键词 → 直接作为 tab 名；
              ''/all/全部 → 枚举全部 tab 下所有卷。
    """
    grade, version = resolve_grade_version(grade, version)
    try:
        ensure_grade(d, grade, version)
    except Exception as e:
        print(f"  ⚠ 年级确认异常(继续): {e}")
    t0 = time.time()
    total = 0

    # 确认在听力专项页 → 点"测试" tab
    if not d(text="测试").exists(timeout=3):
        if not enter_module_by_entry(d, "听力专项"):
            print("  ❌ 找不到/进不去听力专项入口"); return 0
        settle_ads(d, wait_total=6)
    if not d(text="测试").exists(timeout=3):
        print("  ❌ 找不到测试 tab"); return 0
    settle_ads(d, wait_total=4)
    d(text="测试").click(); time.sleep(1.2)
    print("  ✅ 已进入测试 tab")

    selectors = _parse_test_selectors(test_units)
    if selectors is None:
        selectors = [{'tab': '全部', 'units': None, 'papers': None}]

    for sel in selectors:
        tab = sel.get('tab')
        units = sel.get('units')
        papers = sel.get('papers')
        clicked = _click_test_tab(d, tab)
        if tab and tab != '全部' and not clicked:
            step_log(f"⚠ 测试页无『{tab}』分类（当前版本可能未提供），跳过", "warning")
            continue
        processed = set()
        _scroll_attempts = 0
        _max_scroll = 12
        _last_titles = None
        _no_new_count = 0
        while True:
            # 每次回到该 tab 视图，保证元素新鲜
            _click_test_tab(d, tab)
            all_p = _collect_papers_current(d)
            # 统计当前屏卷标题，检测是否滑到底（连续2屏无新卷则认为到底）
            _current_titles = tuple(sorted({t for (t, b) in all_p}))
            if _last_titles == _current_titles:
                _no_new_count += 1
            else:
                _no_new_count = 0
                _last_titles = _current_titles
            matched = [(t, b) for (t, b) in all_p
                       if _unit_match(t, units) and _paper_match(t, papers)
                       and t not in processed]
            if not matched and papers:
                # ★ fallback：用户选了 A/B 卷，但当前版本测试页根本没有 A/B 卷字样
                #   （如湘鲁版 2024 六上听力专项测试只有「Unit N 单元评价」），
                #   则退化成「忽略卷限制，直接按单元找去答题按钮点进去」。
                _has_ab = any(_paper_has_ab(t) for (t, b) in all_p)
                if not _has_ab:
                    step_log(f"  ℹ 测试页无 A/B 卷字样，按单元直接点『去答题』（忽略卷限制）", "info")
                    matched = [(t, b) for (t, b) in all_p
                               if _unit_match(t, units) and t not in processed]
            if not matched:
                # 未找到目标卷 → 向下滑动查看更多（处理 WebView 懒加载列表）
                if _no_new_count >= 2 or _scroll_attempts >= _max_scroll:
                    step_log(f"⚠ 测试列表已滑到底或未找到目标卷（units={units}, papers={papers}），停止", "warning")
                    break
                step_log("→ 未找到目标卷，向下滑动查看更多", "info")
                S_swipe(d, 540, 2000, 540, 700, 0.4)
                time.sleep(1.0)
                _scroll_attempts += 1
                continue
            title, btn = matched[0]
            processed.add(title)
            step_log(f"  🎯 测试目标卷「{title}」", "info")
            try:
                bx = (btn.bounds[0] + btn.bounds[2]) // 2
                by = (btn.bounds[1] + btn.bounds[3]) // 2
                try:
                    btn.click()
                except Exception:
                    d.click(bx, by)
            except Exception as e:
                step_log(f"  ❌ 点击「{title}」去答题失败: {e}", "error")
                continue
            time.sleep(0.8)
            if d(text="好的，我知道啦~").exists(timeout=3):
                d(text="好的，我知道啦~").click(); time.sleep(0.8)
            if d(text="开始答题").exists(timeout=3):
                d(text="开始答题").click(); time.sleep(1.2)
            q = _test_answer_loop(d, stop_check=stop_check)
            total += q
            step_log(f"  ✅ {title} 测试完成: {q} 题", "info")
            # back 回测试列表
            for _ in range(4):
                if d(text="去答题").exists(timeout=1.5) or d(text="重新答题").exists(timeout=1.5):
                    break
                d.press("back"); time.sleep(0.6)
            # 回到测试页（点测试 tab 恢复筛选视图）
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
    # ★ 命令行单跑时按 UI/环境变量所选年级切换；多模块调度器已在开头统一切换一次
    _grade, _version = resolve_grade_version()
    if not ensure_grade(d, _grade, _version):
        print("❌ 年级切换失败")
        return 1

    # 3. 跑听力专项（练习 + 测试）
    run_all(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())

