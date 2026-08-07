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
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uiautomator2 as u2
from common.tools import (
    S, S_swipe, S_h, S_w,
    close_ad, dismiss_global_popups, ensure_grade, scroll_and_find,
)
from common.logger import step_log
from common.screenshot import shot_to_file
from engine import _handle_match_question, _handle_sort_question

APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"

UNITS = [1]  # U1 验证；打通后 [1,2,3,4]

def _resolve_units(units, default_units):
    """把外部传入的单元范围解析为列表；None 则用默认全部单元"""
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
        m = _re.match(r'^(\d+)\s*-\s*(\d+)$', part)
        if m:
            result.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            result.append(int(part))
    return result or list(default_units)



def _answer_loop(d, max_q=60):
    """单元自检答题循环：点选项→检查→(答对自动跳/答错点下一题)→最后一题查看报告
    
    题型处理：
    - 选择/判断(TF): 点选项→检查
    - 匹配: 点方框→点字母 A-E（全部点完→检查）
    - 排序: 图片(直接点)/句子(激活+序号)
    - 其他题型: 检测到后暂停提示（用户告知方法）
    """
    q = 0
    unknown_cnt = 0  # 连续未知题型计数（防空转）
    for i in range(max_q):
        # 中途弹窗"继续答题（0S）" → 点击
        if d(textContains="继续答题").exists(timeout=0.6):
            d(textContains="继续答题").click()
            print("      → 继续答题弹窗")
            time.sleep(0.6)
            continue
        # 最后一题 → 查看报告
        if d(text="查看报告").exists(timeout=0.6):
            d(text="查看报告").click()
            print("      → 查看报告！单元自检完成")
            step_log(f"📊 单元自检完成，共{q}题", "success")
            time.sleep(0.8)
            return q
        # 答错后"下一题" → 点它
        if d(text="下一题").exists(timeout=0.6):
            d(text="下一题").click()
            print("      → 下一题(答错)")
            step_log(f"  答错 → 下一题", "warning")
            time.sleep(0.6)
            continue
        # 新题：找选项
        opt = None
        for kw in ("T", "F", "A", "B", "C", "D", "E"):
            try:
                if d(text=kw).exists(timeout=0.4):
                    opt = kw
                    break
            except Exception:
                pass
        if opt:
            d(text=opt).click()
            print(f"      → 选 {opt}")
            step_log(f"  第{q}题: 选 {opt} → 检查", "info")
            time.sleep(0.35)
            # 等检查出现并点击
            for _ in range(10):
                try:
                    if d(text="检查").exists(timeout=0.15):
                        d(text="检查").click()
                        print(f"      → 检查")
                        time.sleep(0.6)
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            q += 1
            continue

        # 其他题型：检测排序/匹配/填空
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "
        if any(kw in texts for kw in ("匹配", "配对", "为人物选择", "选择正确的描述")):
            _handle_match_question(d, {})
            q += 1
            continue
        if any(kw in texts for kw in ("排序", "给图片排序", "给句子排序", "按顺序")):
            # ★ CheckBox 圆圈排序分流（与 engine._answer_loop / 听力专项 _test_answer_loop 统一）：
            #   CheckBox 整行句子（宽>800 带文本，圆圈排序题特征）≥3 → 直接点句子（序号自动填）
            #   否则 → 方框排序（点方框激活+点序号）
            _has_circle = 0
            try:
                _xml2 = d.dump_hierarchy()
                import re as _re2
                for _m in _re2.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*/?>', _xml2):
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
                _handle_sentence_sort(d, {})
            else:
                _handle_sort_question(d, {})
            q += 1
            continue
        # 填空题检测：核心判断 = 界面存在 EditText 输入框（不依赖题干文字！
        #   补全短文/补全对话题题干文字是图片渲染，uiautomator dump 不到关键词）
        #   只要存在 EditText 就一定是需要输入的填空/补全题
        #   ★ 注意：进入本题时 App 可能自动弹出键盘挡住 EditText（dump 看不到），
        #     先按 back 收起键盘再重检（与 engine._handle_fill_blank 开场逻辑一致）
        import re as _re
        has_edittext = False
        try:
            _xml = d.dump_hierarchy()
            has_edittext = bool(_re.search(r'class="android\.widget\.EditText"', _xml))
        except Exception:
            pass
        if not has_edittext and any(kw in texts for kw in ("完成小短文", "完成短文", "每空", "填空", "完成句子")):
            # 键盘可能弹出挡住 → back 收起再重检
            d.press("back"); time.sleep(0.4)
            try:
                _xml = d.dump_hierarchy()
                has_edittext = bool(_re.search(r'class="android\.widget\.EditText"', _xml))
            except Exception:
                pass
        if has_edittext or any(kw in texts for kw in ("完成小短文", "完成短文", "每空", "填空", "完成句子")):
            from engine import _handle_fill_blank
            if _handle_fill_blank(d, {}):
                q += 1
                continue

        # 未知题型 → 提示用户（连续 3 次未知说明页面异常，退出避免空转/误退）
        texts2 = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        print(f"    ⚠ 未知题型，请告知处理方法: {texts2[:6]}")
        unknown_cnt += 1
        if unknown_cnt >= 3:
            print(f"    ⚠ 连续 {unknown_cnt} 次未知题型，退出循环")
            return q
        try:
            _shot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
            shot_to_file(d, os.path.join(_shot_dir, f"unknown_type_{q}.jpg"), width=640)
        except Exception:
            pass
        time.sleep(2.5)
    return q


def _enter_unit(d, unit_num):
    """在单元自检列表页进入指定单元的答题

    ★ 优先按标题文字匹配（如"Unit 3单元评价"）精确定位，不依赖列表顺序；
      下滑逐屏查找（列表可能多屏），找到该单元行后点其"去答题"。
    """
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
            # 在该行附近找"去答题"按钮
            for e in elements:
                if (e.text or "").strip() == "去答题":
                    dy = abs(e.bounds[1] - row_y)
                    if dy < 300:  # 同行
                        try:
                            e.click()
                        except Exception:
                            d.click((e.bounds[0]+e.bounds[2])//2, (e.bounds[1]+e.bounds[3])//2)
                        print(f"    ✅ 点击去答题 (U{unit_num})")
                        time.sleep(1.2)
                        _after_enter_unit(d)
                        return True
        # 未找到 → 下滑
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)

    # 方式2（兜底）：按第 unit_num 个"去答题"按钮（原逻辑）
    btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
            if (e.text or "").strip() == "去答题"]
    btns.sort(key=lambda e: e.bounds[1])
    idx = unit_num - 1
    for _ in range(5):
        if idx < len(btns):
            break
        S_swipe(d, 540, 1800, 540, 600, 0.3); time.sleep(0.4)
        btns = [e for e in (d.xpath('//*[@text!=""]').all() or [])
                if (e.text or "").strip() == "去答题"]
        btns.sort(key=lambda e: e.bounds[1])
    if idx >= len(btns):
        print(f"    ❌ 找不到 U{unit_num} 的去答题")
        return False
    btns[idx].click()
    print(f"    ✅ 点击去答题 (U{unit_num})")
    time.sleep(1.2)
    _after_enter_unit(d)
    return True


def _after_enter_unit(d):
    """进入单元后的公共处理：弹窗 + 开始答题（重试等待，页面可能慢加载）"""
    # 弹窗"好的，我知道啦~"（最多等8秒，页面加载慢时延迟出现）
    for _ in range(6):
        if d(text="好的，我知道啦~").exists(timeout=1):
            d(text="好的，我知道啦~").click()
            print(f"    ✅ 好的，我知道啦~")
            time.sleep(0.8)
            break
        time.sleep(0.5)
    # 开始答题（最多等8秒）
    for _ in range(6):
        if d(text="开始答题").exists(timeout=1):
            d(text="开始答题").click()
            print(f"    ✅ 开始答题")
            time.sleep(1.6)
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
    print(f"\n📋 单元自检 · 单元 {_units[0]}-{_units[-1]} · {len(_units)}个单元")

    # 进入单元自检：主页直接有入口（新版主页改版后"单元自检"入口直接可见）
    # 先确保在 App 主页（防止退过头到桌面）
    for _ in range(4):
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        if "switch_textbook_tv" in xml or "教材精学" in xml or "专项突破" in xml:
            break
        if "游戏助手" in xml and "英语学习" in xml:
            d.app_start(APP_PACKAGE)
            time.sleep(4)
            break
        d.press("back"); time.sleep(0.6)

    if not d(text="单元自检").exists(timeout=2):
        # 主页下滑找专项突破下的单元自检
        found = False
        for _ in range(6):
            if d(text="单元自检").exists(timeout=1):
                found = True
                break
            S_swipe(d, 540, 1800, 540, 600, 0.4); time.sleep(0.4)
        if not found:
            # 尝试点专项突破后再下滑
            if d(text="专项突破").exists(timeout=1):
                d(text="专项突破").click(); time.sleep(0.8)
            for _ in range(6):
                if d(text="单元自检").exists(timeout=1):
                    found = True
                    break
                S_swipe(d, 540, 1800, 540, 600, 0.4); time.sleep(0.4)
        if not found:
            print("  ❌ 找不到单元自检入口")
            return 0
    d(text="单元自检").click()
    print("  ✅ 已进入单元自检")
    time.sleep(3)

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
    d.press("home"); time.sleep(0.4)
    d.app_stop(APP_PACKAGE); time.sleep(0.8)
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
