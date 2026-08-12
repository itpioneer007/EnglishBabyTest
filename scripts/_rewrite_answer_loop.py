# -*- coding: utf-8 -*-
"""重写 单元自检.py 的 _answer_loop —— 回到用户确认的最原始简单流程"""
import io

f = 'scripts/modules/单元自检.py'
src = io.open(f, encoding='utf-8').read()

start = src.index('def _answer_loop(')
end = src.index('def _enter_unit(')

NEW_FUNC = '''def _answer_loop(d, max_q=60):
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
                _m0 = re.match(r'^(\\d+)\\s*/\\s*(\\d+)$', _t.strip())
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
            _m = re.search(r'text="继续答题"[^>]*bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"', xml0)
            if _m:
                d.click((int(_m.group(1)) + int(_m.group(3))) // 2,
                        (int(_m.group(2)) + int(_m.group(4))) // 2)
            else:
                d(textContains="继续答题").click()
            print("      → 恢复答题(退出确认弹窗)")
            time.sleep(1.5)
            continue
        # ── 1. 纯"继续答题"倒计时过渡页 → 不用点，等3s自动跳转 ──
        if '继续答题' in xml0:
            print("      → 继续答题倒计时，等待自动跳转(3s)")
            time.sleep(3.5)
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
        # ── 3. 答错 → 点"下一题" → 等页面切换（约3s）──
        if '下一题' in xml0:
            d(text="下一题").click()
            print("      → 下一题(答错)")
            step_log(f"  答错 → 下一题", "warning")
            time.sleep(3.0)   # 等新题加载完成（用户确认需等3s，防残留误点）
            continue
        # ── 4. 填空检测（EditText 强特征，提前于字母选项）──
        _has_edittext = 'class="android.widget.EditText"' in xml0
        if _has_edittext:
            from engine import _handle_fill_blank
            if _handle_fill_blank(d, {}):
                q += 1
                print(f"      → 第{q}题(填空)")
                step_log(f"  第{q}题 填空完成", "info")
                continue
        # ── 5. 阅读多小题检测（多组字母选项）──
        if _handle_reading_multi(d):
            q += 1
            print(f"      → 第{q}题(阅读多小题)")
            step_log(f"  第{q}题 阅读多小题完成", "info")
            continue
        # ── 6. 单选/判断（字母选项 T/F/A-E）──
        opt = None
        for kw in ("T", "F", "A", "B", "C", "D", "E"):
            try:
                if d(text=kw).exists(timeout=0.3):
                    opt = kw
                    break
            except Exception:
                pass
        if opt:
            q += 1
            d(text=opt).click()
            print(f"      → 选 {opt}")
            step_log(f"  第{q}题: 选 {opt} → 检查", "info")
            # 界面级完整性检查证据 → 前端证据卡
            try:
                step_log(f"  第{q}题 完整性检查", "info", collect_ui_evidence(d.dump_hierarchy(), qtype="单元自检"))
            except Exception:
                pass
            time.sleep(0.35)
            # 等"检查"出现并点击
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
            # ★ 点检查后等页面切换（答对自动跳/答错出下一题），约3s
            time.sleep(3.0)
            continue
        # ── 7. 匹配题 ──
        texts = ""
        for e in (d.xpath('//*[@text!=""]').all() or []):
            texts += (e.text or "") + " "
        if any(kw in texts for kw in ("匹配", "配对", "为人物选择", "选择正确的描述")):
            if _handle_match_question(d, {}):
                q += 1
            continue
        # ── 8. 排序题（圆圈/图片/方框）──
        if any(kw in texts for kw in ("排序", "给图片排序", "给句子排序", "按顺序")):
            _has_circle = 0
            try:
                import re as _re2
                for _m in _re2.finditer(r'<node[^>]*class="android\\.widget\\.CheckBox"[^>]*/?>', xml0):
                    _tag = _m.group(0)
                    _tm = _re2.search(r'text="([^"]{6,})"', _tag)
                    _bm = _re2.search(r'bounds="\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]"', _tag)
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
        texts2 = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        print(f"    ⚠ 未知题型，请告知处理方法: {texts2[:6]}")
        unknown_cnt += 1
        if unknown_cnt >= 5:
            print(f"    ⚠ 连续 {unknown_cnt} 次未知题型，退出循环")
            return q
        time.sleep(2.5)
    return q


'''

src = src[:start] + NEW_FUNC + src[end:]
io.open(f, 'w', encoding='utf-8').write(src)
print("替换完成")
print("新函数长度:", len(NEW_FUNC))
