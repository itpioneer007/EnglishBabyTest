"""
英语宝 · 单元自检 模块
=====================
独立可运行：python modules/单元自检.py

流程：主页下滑 → 专项突破 → 单元自检 → 点"去答题"（按单元顺序）
  → 好的，我知道啦~ → 开始答题 → 答题界面（36题/单元）
  → 遇到不同题型用对应方法处理（选择/判断/排序/匹配/其他）
  → 最后一题答完点检查 → 查看报告 → back → 下一单元

批量调用：from modules.单元自检 import run_module; run_module(d)
"""
import os
import sys, os, time
import re 
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
    smart_find_unit_row,
)
from common.logger import step_log
from common.evidence import collect_ui_evidence
from common.screenshot import shot_to_file
from engine import _handle_match_question, _handle_sort_question

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "六年级上册"
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

UNITS = _env_units()  # U1 验证；打通后 [1,2,3,4]

def _resolve_units(units, default_units):
    """把外部传入的单元范围解析为列表；None 则用默认全部单元
    ★ 支持关键词目标（"期中"/"期末"/"AI检测"等非数字）直接透传"""
    if units is None:
        return list(default_units)
    if isinstance(units, list):
        return list(units)
    if isinstance(units, int):
        return [units]
    import re as _re
    result = []
    for part in str(units).split(','):
        part = part.strip()
        if not part:
            continue
        m = _re.match(r'^(\d+)\s*-\s*(\d+)$', part)
        if m:
            result.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            result.append(int(part))
        else:
            result.append(part)   # ★ 关键词（期中/期末/AI检测等）透传，按名字找
    return result or list(default_units)



def _handle_reading_multi(d, xml=None):
    """阅读理解多小题：一屏含多道小题（每道小题有 T/F 或 A-E 选项组），
    ★ 必须把所有小题都选完（每组选1个选项，checked=true），"检查"按钮才会出现！
    （用户确认：检查不是自带的，漏选任何小题都找不到"检查"按钮）
    返回 True=已处理完成（点过检查）；False=非多小题页面（单小题，走原逻辑）
    xml: 外部传入的 dump_hierarchy() 结果（速度优化：避免函数内重复 dump）
    """
    import re as _re
    time.sleep(0.2)

    # ★ 排除匹配题：匹配题页面也有 A-E 字母选项（作为配对目标），
    #   但题型完全不同（点方框→点字母配对），不能让多小题逻辑误处理
    if xml is None:
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return False
    if any(kw in xml for kw in ('匹配', '配对', '为人物选择', '选择正确的描述')):
        return False

    def _groups(_xml):
        """解析页面 XML 中所有字母选项，按 y 聚类分组（同小题选项 y 相近）"""
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
        # 一组至少 2 个字母选项才算有效小题（T/F 或 A-E）
        return [g for g in groups if len(g) >= 2]

    groups = _groups(xml)
    if len(groups) < 2:
        return False  # 单小题/无选项 → 走原逻辑

    print(f"    📖 阅读理解多小题: {len(groups)} 道小题待选")
    step_log(f"📖 阅读多小题 {len(groups)} 道，逐题选选项", "step")

    # 循环：把所有未选中的小题都选上（含下滑发现的新小题），全部选完 → 找检查
    no_new = 0
    for _ in range(len(groups) + 12):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        groups = _groups(xml)
        # 找未选中的小题（组内没有任何 checked=true）
        pending = [g for g in groups if not any(o[4] for o in g)]
        if pending:
            # 点该组最左选项（T/A 优先），保证该小题被标记已答
            g = sorted(pending[0], key=lambda o: o[1])
            o = g[0]
            d.click(o[1], o[2])
            print(f"      → 小题: 选 {o[0]}")
            time.sleep(0.6)
            no_new = 0
            continue
        # 全部已选 → 下滑找"检查"（检查在页面底部，可能需要下滑）
        if d(text="检查").exists(timeout=1.0):
            d(text="检查").click()
            print("    ✅ 多小题全部选完，点击检查")
            step_log("✅ 阅读多小题全部选完，已检查", "success")
            time.sleep(0.8)
            return True
        # 下滑找更多小题 / 检查按钮
        S_swipe(d, 540, 1800, 540, 800, 0.4)
        time.sleep(0.4)
        no_new += 1
        if no_new >= 4:
            break
    # 兜底：再尝试点检查（可能已在页面）
    for _ in range(4):
        if d(text="检查").exists(timeout=0.8):
            d(text="检查").click()
            print("    ✅ 多小题兜底点击检查")
            time.sleep(0.8)
            return True
        S_swipe(d, 540, 1800, 540, 800, 0.4)
        time.sleep(0.4)
    return True


def _wait_page_ready(d, q, wait_s=10):
    """等待页面切换到新题（答完一题点"检查/下一题"后调用）：
    ★ 用户反馈核心：H5 页面切换慢，题号先变、内容后渲染。若只等题号推进，
      内容未渲染期间上一题残留的 A 还在屏幕上 → 被误点（36题记成38题）！
    等待条件（需同时满足「题号推进」+「新题内容出现」）：
      - 题号 X/36 的 X > q（页面已切到新题，q=已处理题数）
      - 且满足其一：
        EditText 出现（填空页渲染完成）
        / 题干长文本 ≥3 条（题号+倒计时+题干/选项）
        / 字母选项 + ≥2 条长文本（题干存在，确认不是残留）
    返回 True=就绪 / False=超时
    """
    import re as _re
    for _ in range(wait_s):
        try:
            _txts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text and e.text.strip()]
            _long = [t for t in _txts if len(t.strip()) >= 6]
            _xml = d.dump_hierarchy()
            # 读题号 X/36
            _x = 0
            for _t in _txts:
                _m = _re.match(r'^(\d+)\s*/\s*\d+$', _t.strip())
                if _m:
                    _x = int(_m.group(1))
                    break
            if _x <= q:
                # 题号未推进（还在旧题/残留/加载中）→ 继续等
                time.sleep(1.0)
                continue
            # 题号已推进 → 检查新题内容是否渲染
            if 'class="android.widget.EditText"' in _xml:
                return True
            if len(_long) >= 3:
                return True
            if any(t in _txts for t in ("T", "F", "A", "B", "C", "D", "E")) and len(_long) >= 2:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def _wait_new_ready(d, q, max_wait=2.5):
    """★ 速度优化：点"检查/下一题"后轮询等待新题就绪，就绪立即返回（不固定 sleep）。
    就绪条件（任一）：
      - 出现"下一题"按钮（答错状态）
      - 题号 X > q 且 新题内容渲染（EditText / 长文本≥3 / 字母+题干）
      - "继续答题"倒计时消失（过渡完成）
    返回：True=就绪 / False=超时
    轮询间隔 0.5s（速度优化：从 0.3s 调大，减少设备交互次数）
    """
    import re as _re
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            _xml = d.dump_hierarchy()
            # 答错：出现"下一题"按钮 → 就绪
            if '下一题' in _xml:
                return True
            # 倒计时过渡页：等它消失（App 3s 自动跳）
            if '继续答题' in _xml:
                time.sleep(0.5)
                continue
            # 题号推进 + 内容渲染（基于本次 _xml 一次解析，不再单独 xpath）
            _txts = [t for t in re.findall(r'text="([^"]*)"', _xml) if t and t.strip()]
            _x = 0
            for _t in _txts:
                _m = _re.match(r'^(\d+)\s*/\s*\d+$', _t.strip())
                if _m:
                    _x = int(_m.group(1))
                    break
            if _x > q:
                _long = [t for t in _txts if len(t.strip()) >= 6]
                if 'class="android.widget.EditText"' in _xml or len(_long) >= 3:
                    return True
                if any(t in _txts for t in ("T", "F", "A", "B", "C", "D", "E")) and len(_long) >= 2:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _answer_loop(d, max_q=200):
    """单元自检答题循环 —— ★ 用户确认的最原始简单流程：
    判断题型 → 调用对应回答方法 → 点"检查"
    → 答对自动跳下一题 / 答错点"下一题" → 重复
    → 最后一题：点"检查" → 点"查看报告" → back 一次返回单元列表
    → 中间的"继续答题"倒计时不用管（3s后自动跳过），只等待不点击。

    题型路由（顺序重要）：
      填空(EditText) → 阅读多小题(多组字母) → 单选/判断(字母)
      → 匹配(人物配对) → 排序(图片/句子) → 其他
    """
    q = 0
    unknown_cnt = 0  # 连续未知题型计数（防空转）
    # 进入时读当前题号 X/Y 初始化 q（中途接管时计数不错位）
    for _ in range(3):
        try:
            _txt_init = [e.text for e in (d.xpath('//*[@text!=""]').all() or [])
                         if e.text and e.text.strip()]
            for _t in _txt_init:
                _m0 = re.match(r'^(\d+)\s*/\s*(\d+)$', _t.strip())
                if _m0:
                    _x0, _y0 = int(_m0.group(1)), int(_m0.group(2))
                    if _x0 > 0 and _y0 >= _x0:
                        q = _x0 - 1   # 已做完 = 当前题号-1
                        print(f"      → 接管第 {_x0}/{_y0} 题，q={q}")
                        break
            if q > 0:
                break
        except Exception:
            pass
        time.sleep(1.0)
    for i in range(max_q):
        # ── 0. 中途退出确认弹窗（有"确定退出"）→ 点"继续答题"恢复 ──
        try:
            xml0 = d.dump_hierarchy()
        except Exception:
            xml0 = ""
        if '确定退出' in xml0 and '继续答题' in xml0:
            _m = re.search(r'text="继续答题"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml0)
            if _m:
                d.click((int(_m.group(1)) + int(_m.group(3))) // 2,
                        (int(_m.group(2)) + int(_m.group(4))) // 2)
            else:
                d(textContains="继续答题").click()
            print("      → 恢复答题(退出确认弹窗)")
            time.sleep(0.6)
            continue
        # ── 1. 纯"继续答题"倒计时过渡页 → 不用点，轮询等它自动消失（3s内）──
        if '继续答题' in xml0:
            print("      → 继续答题倒计时，等待自动跳转")
            # 轮询等待倒计时消失（最多4s）；消失后新题通常已加载
            _t0 = time.time()
            while time.time() - _t0 < 4.0:
                try:
                    if '继续答题' not in d.dump_hierarchy():
                        break
                except Exception:
                    break
                time.sleep(0.5)
            continue
        # ── 2. 最后一题 → 点"查看报告" → back 一次回单元列表 ──
        if '查看报告' in xml0:
            print("      → 查看报告出现，点击")
            step_log(f"📊 单元自检完成，共{q}题", "success")
            d(text="查看报告").click()
            time.sleep(3.0)   # 等报告刷新
            d.press("back")   # ★ 一次 back 返回单元列表（用户确认）
            time.sleep(1.0)
            return q
        # ── 3. 答错 → 点"下一题" → 轮询等新题就绪（不固定3s）──
        if '下一题' in xml0:
            d(text="下一题").click()
            print("      → 下一题(答错)")
            step_log(f"  答错 → 下一题", "warning")
            # 轮询等新题加载完成（题号推进+内容渲染；答对自动跳/答错出下一题均覆盖）
            if not _wait_new_ready(d, q, max_wait=2.5):
                time.sleep(0.6)   # 超时兜底
            continue
        # ── 4. 填空检测（EditText 强特征，提前于字母选项）──
        #   ★ 关键：填空页进入时 App 自动弹键盘 → 键盘挡住 EditText（dump 看不到），
        #     只剩题干文字 → 必须同时用「题干填空关键词」判断（无 EditText 也进填空）！
        _has_edittext = 'class="android.widget.EditText"' in xml0
        _has_letter = bool(re.search(r'text="[TFABCDE]"', xml0))
        _fill_hint = any(kw in xml0 for kw in
                         ('填空', '补全', '每空', '填写', '填词', '完成小短文'))
        if _has_edittext or (_fill_hint and not _has_letter):
            from engine import _handle_fill_blank
            if _handle_fill_blank(d, {}):
                q += 1
                print(f"      → 第{q}题(填空)")
                step_log(f"  第{q}题 填空完成", "info")
                continue
        # ── 5. 阅读多小题检测（多组字母选项）──
        # ★ 速度优化：传入已 dump 的 xml0，避免函数内重复 dump
        if _handle_reading_multi(d, xml0):
            q += 1
            print(f"      → 第{q}题(阅读多小题)")
            step_log(f"  第{q}题 阅读多小题完成", "info")
            continue
        # ── 5.5 自评题（"阅读与写作"等：不支持在线作答，页面有"我答对了/我答错了"）──
        #   ★ 必须放在单选检测之前！自评题页面可能含标题字母（如"A"），
        #     会被单选检测误判成选项点击 → 死循环！
        if '我答对了' in xml0 or '我答错了' in xml0:
            if '我答对了' in xml0:
                d(text="我答对了").click()
            else:
                d(text="我答错了").click()
            q += 1
            print(f"      → 第{q}题(自评题)")
            step_log(f"  第{q}题 自评完成", "info")
            time.sleep(3.0)   # 等交卷/报告/跳转
            # 交卷后去向处理：有题号→继续循环；有查看报告→点击→back；
            # 回主页（有"单元自检"入口）→ 点进列表；否则直接返回
            try:
                _xml_end = d.dump_hierarchy()
                if re.search(r'\d+\s*/\s*\d+', _xml_end):
                    continue   # 还在答题页，继续循环
                if '查看报告' in _xml_end:
                    d(text="查看报告").click()
                    time.sleep(3.0)
                    d.press("back")
                    time.sleep(0.6)
                    return q
                if '单元自检' in _xml_end:
                    d(text="单元自检").click()   # 主页 → 回单元自检列表
                    time.sleep(0.6)
                    return q
                print(f"      → 自评题完成，训练已交卷")
                return q
            except Exception:
                return q
        # ── 6. 单选/判断（字母选项 T/F/A-E）──
        # ★ 速度优化：直接用已 dump 的 xml0 一次正则找字母，替代 7 次 d(text=kw).exists()
        #   设备交互（每次交互 ~0.2-0.3s，7次≈2s → 1次≈0）
        opt = None
        _m_opt = re.search(r'text="([TFABCDE])"', xml0)
        if _m_opt:
            opt = _m_opt.group(1)
        if opt:
            q += 1
            # ★ 修复 StaleObjectException：页面切换/加载中元素会过期。
            #   点击前重新 dump 验证 opt 仍在，且点击用坐标（避免 d(text=).click() 查两次）
            _clicked = False
            for _try in range(3):
                try:
                    _xml_try = d.dump_hierarchy()
                    _mt = re.search(r'text="' + opt + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _xml_try)
                    if _mt:
                        _ox = (int(_mt.group(1)) + int(_mt.group(3))) // 2
                        _oy = (int(_mt.group(2)) + int(_mt.group(4))) // 2
                        d.click(_ox, _oy)
                        _clicked = True
                        break
                except Exception:
                    pass
                time.sleep(0.4)
            if not _clicked:
                try:
                    d(text=opt).click()
                except Exception:
                    print(f"      → 选 {opt} 点击失败（页面可能加载中），跳过")
            print(f"      → 选 {opt}")
            step_log(f"  第{q}题: 选 {opt} → 检查", "info")
            # 界面级完整性检查证据 → 前端证据卡（复用已 dump 的 xml0）
            try:
                step_log(f"  第{q}题 完整性检查", "info", collect_ui_evidence(xml0, qtype="单元自检"))
            except Exception:
                pass
            time.sleep(0.3)
            # 等"检查"出现并点击
            for _ in range(8):
                try:
                    if d(text="检查").exists(timeout=0.1):
                        d(text="检查").click()
                        print(f"      → 检查")
                        time.sleep(0.3)
                        break
                except Exception:
                    pass
                time.sleep(0.15)
            # ★ 点检查后轮询等新题就绪（答对自动跳/答错出下一题均覆盖），不固定3s
            if not _wait_new_ready(d, q, max_wait=2.5):
                time.sleep(0.6)   # 超时兜底
            continue
        # ── 7. 匹配题 ──
        # ★ 速度优化：基于已 dump 的 xml0 正则提取文本，不再单独 xpath
        texts = " ".join(re.findall(r'text="([^"]*)"', xml0))
        if any(kw in texts for kw in ("匹配", "配对", "为人物选择", "选择正确的描述")):
            if _handle_match_question(d, {}):
                q += 1
            continue
        # ── 8. 排序题（圆圈/图片/方框）──
        if any(kw in texts for kw in ("排序", "给图片排序", "给句子排序", "按顺序")):
            _has_circle = 0
            try:
                import re as _re2
                for _m in _re2.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*/?>', xml0):
                    _tag = _m.group(0)
                    _tm = _re2.search(r'text="([^"]{6,})"', _tag)
                    _bm = _re2.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _tag)
                    if not (_tm and _bm):
                        continue
                    _x1, _y1 = int(_bm.group(1)), int(_bm.group(2))
                    if (int(_bm.group(3)) - _x1) > 800 and 700 < _y1 < 1900:
                        _has_circle += 1
            except Exception:
                pass
            if _has_circle >= 3:
                from engine import _handle_sentence_sort
                _ok = _handle_sentence_sort(d, {})
            else:
                _ok = _handle_sort_question(d, {})
            if _ok:
                q += 1
            continue
        # ── 9. 未知题型 → 提示，连续多次退出防空转 ──
        # ★ 速度优化：基于已 dump 的 xml0 正则提取文本
        texts2 = [t for t in re.findall(r'text="([^"]*)"', xml0) if t and t.strip()]
        print(f"    ⚠ 未知题型，请告知处理方法: {texts2[:6]}")
        unknown_cnt += 1
        if unknown_cnt >= 5:
            print(f"    ⚠ 连续 {unknown_cnt} 次未知题型，退出循环")
            return q
        time.sleep(1.5)
    return q


def _enter_unit(d, unit_num):
    """在单元自检列表页进入指定单元的答题 —— ★ 随机应变按名字定位

    unit_num: 数字(1)/区间("1-3")/关键词("期中"/"期末"/"AI检测"/"湘少三上期中评价")
    流程: 智能定位（忽略"湘少X上"前缀；关键词先点筛选 tab 再匹配标题）
          → 找到标题行 → 点同行"去答题"
    """
    # ★ 等待列表加载完成（进入单元自检页后 H5 列表可能慢加载，空白时直接找会失败）
    for _ in range(6):
        try:
            _xml_wait = d.dump_hierarchy()
            if ('单元评价' in _xml_wait or '去答题' in _xml_wait
                    or '重新答题' in _xml_wait or '继续答题' in _xml_wait):
                break
        except Exception:
            pass
        time.sleep(0.8)
    # ★ 方式0：智能定位（支持数字/区间/关键词，自动处理 期中/期末 tab）
    #   ★ 按钮多状态（用户确认）：首次="去答题"，答过="重新答题"，
    #     中途退出="继续答题"，已交卷显示"已评测 N分"（点它=重新答题）
    #   ★ prefer_restart=True：不接受"继续答题"（上次中途退出）——必须从第 1 题重头测，
    #     避免漏测中途退出前的题目（用户实测：U3 中途退出后从第 12 题开始，前 11 题漏检）
    if smart_find_unit_row(d, unit_num, click_text="去答题", prefer_restart=True):
        print(f"    ✅ 智能定位按钮 ({unit_num})")
        time.sleep(0.6)
        _after_enter_unit(d)
        return True
    # 关键词目标若智能定位失败 → 直接返回（不误点其他单元）
    if not str(unit_num).isdigit():
        print(f"    ❌ 找不到目标 [{unit_num}]（含筛选 tab 均尝试）")
        return False

    # 方式1：按 Unit N 标题文字匹配（可靠，不受列表顺序/滚动影响）
    import re as _re
    target_title = _re.compile(rf"Unit\s*{unit_num}\s*单元评价")
    for _ in range(8):
        elements = (d.xpath('//*[@text!=""]').all() or [])
        # 找目标单元标题
        row = None
        for e in elements:
            t = (e.text or "").strip()
            if target_title.search(t):
                row = e
                break
        if row:
            row_y = row.bounds[1]
            # 在该行附近找按钮（去答题/重新答题/继续答题/已评测 —— 多状态）
            # ★ 用户确认：默认先测前面的单元（Unit1 就在最顶部），找到同行按钮
            #   就**直接点击**，绝不下滑！（之前 y<350 遮挡区过滤 → 下滑反而把
            #   Unit1 滚出屏幕 → 永远找不到 → 死循环）
            for e in elements:
                t = (e.text or "").strip()
                if t in ("去答题", "重新答题", "继续答题"):
                    dy = abs(e.bounds[1] - row_y)
                    if dy < 300:  # 同行 → 直接点击（顶部版本条只是视觉覆盖，可点中）
                        try:
                            e.click()
                        except Exception:
                            d.click((e.bounds[0]+e.bounds[2])//2, (e.bounds[1]+e.bounds[3])//2)
                        print(f"    ✅ 点击[{t}] (U{unit_num})")
                        time.sleep(0.6)
                        _after_enter_unit(d)
                        return True
        # 未找到目标行 → 下滑（只有找不到目标单元才下滑）
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)

    # 方式2（兜底）：按第 unit_num 个按钮（去答题/重新答题/继续答题）
    # ★ 用户确认：不按 y<350 过滤（Unit1 就在顶部，直接点；下滑反而滚出屏幕）
    btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
            if (e.text or "").strip() in ("去答题", "重新答题", "继续答题")]
    btns.sort(key=lambda e: e.bounds[1])
    idx = unit_num - 1
    for _ in range(5):
        if idx < len(btns):
            break
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)
        btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                if (e.text or "").strip() in ("去答题", "重新答题", "继续答题")]
        btns.sort(key=lambda e: e.bounds[1])
    if idx >= len(btns):
        print(f"    ❌ 找不到 U{unit_num} 的答题按钮")
        return False
    btns[idx].click()
    print(f"    ✅ 点击答题按钮 (U{unit_num})")
    time.sleep(0.6)
    _after_enter_unit(d)
    return True


def _after_enter_unit(d):
    """进入单元后的公共处理：弹窗 + 开始答题（重试等待，页面可能慢加载）
    ★ 修复：可能连续弹多个"训练规则说明"（点一次"好的，我知道啦~"后可能再弹一个），
      循环点直到弹窗消失；再点"开始答题"。
    ★ 若出现"重新答题"（中途恢复页/重测入口）→ 点它重头开始（保证从第1题测，
      避免恢复上次中途进度漏测前段题目）
    """
    # 弹窗"好的，我知道啦~"（循环点，直到弹窗全部消失；最多12次）
    for _ in range(12):
        if d(text="好的，我知道啦~").exists(timeout=1):
            d(text="好的，我知道啦~").click()
            print(f"    ✅ 好的，我知道啦~")
            time.sleep(0.4)
        else:
            break
    # ★ 重头开始：出现"重新答题"（恢复页入口）→ 点它（从第1题重测）
    for _ in range(3):
        if d(text="重新答题").exists(timeout=0.6):
            d(text="重新答题").click()
            print(f"    ✅ 重新答题（重头开始）")
            time.sleep(1.0)
            break
        time.sleep(0.3)
    # 开始答题（最多等8秒）
    for _ in range(6):
        if d(text="开始答题").exists(timeout=1):
            d(text="开始答题").click()
            print(f"    ✅ 开始答题")
            time.sleep(1.0)
            return True
        time.sleep(0.5)
    return True


def run_module(d, units=None):
    """核心入口：跑完单元自检指定单元，返回题数

    units: 单元范围，如 [1,2] 或 '1-2'；None=默认全部
    """
    t0 = time.time()
    total = 0
    _units = _resolve_units(units, UNITS)
    _desc = "、".join(str(x) for x in _units)
    print(f"\n📋 单元自检 · 目标: {_desc} · {len(_units)}项")

    # 进入单元自检：主页直接有入口（新版主页"单元自检"入口第一屏可见）
    # ★ 不再 back 循环找主页！main()/调度器已保证在英语宝主页，
    #   直接找"单元自检"入口点击即可（若中途答题残留弹窗则先处理）
    for _ in range(3):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        # 中途退出确认弹窗 → 先点「确定退出」
        if '确定退出' in xml:
            try:
                d(text='确定退出').click()
                print("    ⏏ 退出中途答题弹窗")
                time.sleep(0.6)
                continue
            except Exception:
                pass
        break
    # 找"单元自检"入口并点击（主页入口是 name_tv 文本 + 外层可点击容器）
    # ★ 修复：不能直接用 d(text="单元自检").click()——exists() 可能命中列表页
    #   残留文字或不可点击节点，click 时崩溃。用 dump 找可点击容器坐标点，并验证进入。
    def _find_entry_coord():
        """在主页找"单元自检"入口可点击容器坐标；找不到返回 None"""
        import re as _re
        try:
            xml = d.dump_hierarchy()
        except Exception:
            return None
        for m in _re.finditer(r'text="单元自检"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
            tx1, ty1, tx2, ty2 = (int(m.group(i)) for i in range(1, 5))
            # 找包含该文本的可点击祖先（从该位置向上找最近 clickable=true 容器）
            # 简化：直接点文本中心（容器通常覆盖文本）
            return ((tx1 + tx2) // 2, (ty1 + ty2) // 2)
        return None

    _entry = _find_entry_coord()
    if not _entry:
        # 主页下滑找（单元自检入口通常在第二屏）
        for _ in range(6):
            S_swipe(d, 540, 1800, 540, 600, 0.4); time.sleep(0.4)
            _entry = _find_entry_coord()
            if _entry:
                break
    if not _entry:
        print("  ❌ 找不到单元自检入口")
        return 0
    # 坐标点击入口
    d.click(_entry[0], _entry[1])
    print(f"  ✅ 点击单元自检入口 @{_entry}")
    time.sleep(3)
    # 验证进入列表页（出现"去答题/重新答题/继续答题/已评测"任一）
    _in_list = False
    for _ in range(6):
        try:
            xml = d.dump_hierarchy()
            if any(k in xml for k in ("去答题", "重新答题", "继续答题", "已评测", "考前突破")):
                _in_list = True
                break
        except Exception:
            pass
        time.sleep(1.0)
    if not _in_list:
        print("  ⚠ 未检测到单元列表特征，继续尝试")
    print("  ✅ 已进入单元自检")
    time.sleep(1)

    # 逐单元执行
    for ui, unit_num in enumerate(_units):
        print(f"\n  🎯 单元自检 Unit {unit_num} [{ui+1}/{len(UNITS)}]")
        if not _enter_unit(d, unit_num):
            continue
        q = _answer_loop(d)
        total += q
        print(f"  ✅ U{unit_num} 完成: {q} 题")
        # back 回单元自检列表
        for _ in range(4):
            if d(text="去答题").exists(timeout=1.5):
                break
            d.press("back"); time.sleep(0.6)

    print(f"✅ 单元自检完成: {total} 题, 耗时 {time.time()-t0:.0f}s")
    return total


def main():
    d = u2.connect()
    print("✅ 设备已连接")
    # ★ 不再无条件重启 App！用户确认：设备已在英语宝主页时，多余的
    #   press home → app_stop → app_start 会"退出主页再重进"，拖慢且易弹广告。
    #   但若设备在英语宝的其他页面（列表/答题页），需 back 回主页；
    #   back 过头到桌面则冷启动。
    try:
        _cur = d.app_current()
        _is_yyb = (_cur or {}).get("package") == APP_PACKAGE
    except Exception:
        _is_yyb = False
    if _is_yyb:
        # back 循环回主页（主页特征：switch_textbook_tv / 教材精学 / 专项突破）
        _at_home = False
        for _ in range(8):
            try:
                xml = d.dump_hierarchy()
                if 'switch_textbook_tv' in xml or '教材精学' in xml or '专项突破' in xml:
                    _at_home = True
                    break
            except Exception:
                pass
            d.press("back"); time.sleep(0.6)
        if not _at_home:
            d.app_start(APP_PACKAGE); time.sleep(3)   # 退过头到桌面 → 冷启动
    else:
        d.press("home"); time.sleep(0.4)
        d.app_start(APP_PACKAGE); time.sleep(3)
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    # ★ 仅命令行单跑时需要；多模块调度器已在开头统一切换一次，不重复
    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败")
        return 1
    run_module(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
