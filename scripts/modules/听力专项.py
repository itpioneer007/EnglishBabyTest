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
    smart_find_unit_row, applock_blocked,
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

def _test_answer_loop(d, max_q=30):
    """测试卷答题循环：点选项→检查→(答对自动跳/答错点下一题)→最后一题查看报告
    
    处理题型：选择/判断(TF)、匹配(点方框+字母)、排序(点方框+序号)、中途"继续答题"弹窗
    ★ 计数从第1题开始（先 q+=1 再打印/记录，与 engine._answer_loop 一致）
    """
    q = 0
    _idle = 0  # 连续空转计数：无选项/无按钮但页面没变化 → 防漏答最后一题后死循环
    _ev_q = -1  # 已发证据卡的题号（每题只发一次）
    total_q = 0   # 总题数（界面右上角 "当前/总" 的右边数字，用户指出总题数在右上角右边）
    cur_q = 0     # 当前题号
    for i in range(max_q):
        # ★ 每题界面级完整性检查证据（题型/题干/选项/音频/作答）→ 前端证据卡
        if q != _ev_q:
            try:
                _xml_ev = d.dump_hierarchy()
                from common.evidence import collect_ui_evidence
                step_log(f"  第{q+1}题 完整性检查", "info",
                         collect_ui_evidence(_xml_ev, qtype="听力专项测试"))
                _ev_q = q
            except Exception:
                pass
        # 中途弹窗"继续答题（0S）" → 点击
        if d(textContains="继续答题").exists(timeout=0.8):
            d(textContains="继续答题").click()
            print("      → 继续答题弹窗")
            time.sleep(0.6)
            _idle = 0
            continue
        # 练习子模块完成 → 练习报告（防卡：测试循环误入练习部分时）
        if d(text="练习报告").exists(timeout=0.8):
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
        if d(text="查看报告").exists(timeout=0.8):
            d(text="查看报告").click()
            print("      → 查看报告！测试完成")
            step_log(f"📊 测试完成，共{q}题", "success")
            time.sleep(0.8)
            return q
        # 答错后"下一题" → 点它
        if d(text="下一题").exists(timeout=0.8):
            d(text="下一题").click()
            print("      → 下一题(答错)")
            step_log(f"  答错 → 下一题", "warning")
            time.sleep(0.6)
            _idle = 0
            continue
        # 新题：找选项
        # ⚠ 关键修复：上一版正则 `text="X"[^>]*clickable="true"` 要求「同一节点」同时有
        #   字母 text 和 clickable。但真实 App 选项字母在【不可点击的子 TextView】上，
        #   可点击的是【父容器】，导致正则永不命中 → 字母题全部答不了（"不会答题"）。
        #   现改为：遍历整节点，单独提取 text 与 bounds（不要求 clickable/属性顺序），
        #   点击用坐标点击 d.click(x,y)。仍只 dump 一次，保留速度优化。
        xml_now = d.dump_hierarchy() if d else ""

        # ★ 读取总题数（界面右上角 "当前/总"，用户指出总题数在右上角右边）
        _m = re.search(r'text="(\d+)/(\d+)"', xml_now)
        if _m:
            cur_q = int(_m.group(1)); total_q = int(_m.group(2))

        # ★ 排序题优先检测（必须放在字母/图片选项之前！）
        #   排序题界面含 CheckBox(序号圆圈 img_sort_btn) 或 题干含"排序"，
        #   会被下方"图片选项"分支(找 CheckBox)误捕获 → 点到序号圆圈而非图片 → 排序失败。
        #   正确解法：图片排序(img_sort_btn)→_handle_sort_question 直接点所有大图片；
        #            句子排序(题干"排序")→_handle_sentence_sort 直接点所有句子；序号自动填。
        if 'img_sort_btn' in xml_now or '排序' in xml_now:
            from engine import _handle_sort_question
            # ★ 图片排序(img_sort_btn)与方框排序(题干"排序")都走 _handle_sort_question，
            #   它内部按"有没有大图"自动区分：图片模式A / 方框模式B。
            #   （之前 Q17 含"排序"被错路由到 _handle_sentence_sort 圆圈排序，
            #    导致只点一个句子就放弃，且计数错乱）
            _handle_sort_question(d, {})
            q += 1
            _idle = 0
            step_log(f"  第{q}题(排序): 处理完毕 → 检查 (总题数 {total_q})", "info")
            if d(text="查看报告").exists(timeout=1.5):
                d(text="查看报告").click()
                step_log(f"📊 测试完成，共{q}题", "success")
                time.sleep(0.8)
                return q
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
            time.sleep(0.25)
            # 等检查出现（★ 优化：减少 sleep）
            for _ in range(6):
                if d(text="检查").exists(timeout=0.2):
                    d(text="检查").click()
                    print(f"      → 检查")
                    time.sleep(0.4)
                    break
                time.sleep(0.15)
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
            d.click(*_img_xy)
            opt = "图片选项"
            q += 1
            print(f"      → 选 图片选项 (CheckBox)")
            step_log(f"  第{q}题: 选图片选项 → 检查", "info")
            time.sleep(0.25)
            for _ in range(6):
                if d(text="检查").exists(timeout=0.2):
                    d(text="检查").click()
                    time.sleep(0.4)
                    break
                time.sleep(0.15)
            continue
        # 匹配题：点第一个方框 → 点字母
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "
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
        texts2 = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        _no_opt_text = "".join(texts2)
        if d(text="查看报告").exists(timeout=0.5) or "查看报告" in _no_opt_text:
            d(text="查看报告").click()
            print("      → 查看报告！测试完成")
            step_log(f"📊 测试完成，共{q}题", "success")
            time.sleep(0.8)
            return q
        if d(text="完成").exists(timeout=0.5) or d(text="提交").exists(timeout=0.5):
            step_log(f"📊 测试结束信号（完成/提交），共{q}题", "success")
            return q
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
        print(f"    ⚠ 无选项({_idle}): {texts2[:6]}")
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
        d(text="听力专项").click(); time.sleep(1.2)
        # ★ OPPO 应用锁偶发弹出（使用面部验证/密码验证）→ 明确报错，避免静默失败
        if applock_blocked(d):
            print("  ❌ 被系统应用锁（使用面部验证/密码验证）挡住，请先在手机上解锁「听力专项」，再重新运行")
            return 0
    if not d(text="测试").exists(timeout=3):
        print("  ❌ 找不到测试 tab"); return 0
    d(text="测试").click(); time.sleep(1.2)
    print("  ✅ 已进入测试 tab")

    for ui, unit_num in enumerate(_tunits):
        print(f"\n  🎯 测试目标 [{unit_num}] [{ui+1}/{len(_tunits)}]")
        # ★ 智能定位：数字/区间/关键词（期中/期末/AI检测…）随机应变找"去答题"
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

    # 2. 关广告 + 确认年级
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    # ★ 仅命令行单跑时需要；多模块调度器已在开头统一切换一次，不重复
    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败")
        return 1

    # 3. 跑听力专项（练习 + 测试）
    run_all(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())

