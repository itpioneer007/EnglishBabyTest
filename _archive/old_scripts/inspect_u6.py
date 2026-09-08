"""
inspect_u6.py — Unit 6 基础巩固自动巡检 (v2: 智能题型识别)
================================================================
核心改进:
  1. 按题型分类处理:
     - 听音选择词汇 (text): 用UI的text匹配答案字母 (A/B/C)
     - 听音选择图片 (image): 视觉模型判断图片内容后, 点对应的图片位置
  2. 修复了原先"无脑点第一个选项"的bug
  3. 配图检查: 无论是否有图片, 都用视觉模型分析当前题目的配图是否匹配
  4. 答题操作: 根据题型采用不同策略
"""
import sys, time, subprocess as sp, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from src.adb_controller import ADBController
from src.config_loader import load_config
from src.reviewer_common import LLMClient
from src.parse_yingyubao_docx import parse

# ----- 配置 -----
config = load_config()
SERIAL = config.device.serial
adb = ADBController(serial=SERIAL, screenshot_dir=str(Path("screenshots").absolute()))
OUT = Path("screenshots")
OUT.mkdir(exist_ok=True)

# ----- 加载 DOCX 脚本 -----
DOCX = r"D:\压缩包存储\听力专项新湘鲁五上U6-9\260717新湘鲁五上听力专项（已二校）.docx"
script_qs = parse(DOCX)
script_qs = [q for q in script_qs if q.unit == 6 and q.stage == "基础巩固"][:14]
script_map = {q.global_idx: q for q in script_qs}

# ----- LLM -----
llm = LLMClient.from_config()


# ================================================================
# UI 工具
# ================================================================
def dump_xml():
    """获取UI XML, 返回原始字符串"""
    r = sp.run(['adb','-s',SERIAL,'shell','uiautomator','dump','/sdcard/_d.xml'],
               capture_output=True, text=True, timeout=15)
    if r.returncode != 0: return ""
    return sp.run(['adb','-s',SERIAL,'shell','cat','/sdcard/_d.xml'],
                  capture_output=True, text=True, timeout=3).stdout

def parse_ui(xml):
    """简易解析: 提取所有元素的 text, content-desc, bounds, clickable"""
    import xml.etree.ElementTree as ET
    elems = []
    if not xml or '<hierarchy' not in xml:
        return elems
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return elems
    for n in root.iter('node'):
        bounds = n.get('bounds', '')
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
        if not m: continue
        x1,y1,x2,y2 = map(int, m.groups())
        elems.append({
            'text': n.get('text', ''),
            'desc': n.get('content-desc', ''),
            'clickable': n.get('clickable') == 'true',
            'bounds': (x1,y1,x2,y2),
            'center': ((x1+x2)//2, (y1+y2)//2),
        })
    return elems


# ================================================================
# 智能点击: 根据题型选择策略
# ================================================================
def click_text_option(elems, answer_letter):
    """
    听音选择词汇 (text options): 找带 'A' 'B' 'C' 字母的选项, 点击匹配的那个
    注意: A/B/C字母标签可能不可点击, 需要找其所在区域的可点击父容器
    策略:
      1. 先找所有标签为A/B/C的元素(无论是否可点击)
      2. 按y坐标排序获取对应位置
      3. 在对应位置附近找可点击元素, 或直接点标签的中心
    """
    answer_letter = answer_letter.upper().strip()

    # 1. 找所有A/B/C标签(不管是否clickable)
    labels = {}  # letter -> center_x, center_y
    for e in elems:
        t = e['text'].strip()
        if t in ['A','B','C','D']:
            cx = (e['bounds'][0] + e['bounds'][2]) // 2
            cy = (e['bounds'][1] + e['bounds'][3]) // 2
            labels[t] = (cx, cy, e['bounds'])

    if labels:
        sorted_letters = sorted(labels.keys(), key=lambda k: labels[k][1])  # sort by y
        # 找到答案字母在排序中的位置
        if answer_letter in labels:
            cx, cy, bounds = labels[answer_letter]
            # 找覆盖该坐标的可点击元素
            for e in elems:
                if not e['clickable']: continue
                ex1, ey1, ex2, ey2 = e['bounds']
                if (ex2-ex1) < 150: continue  # 太小不是选项容器
                if ey1 < 100 or ey2 > 1900: continue  # 超出屏幕
                if ex1 <= cx <= ex2 and ey1 <= cy <= ey2:
                    return e, f"parent covers '{answer_letter}' at {e['center']}"
            return {'center': (cx, cy), 'text': answer_letter}, f"direct tap '{answer_letter}'"

    # 2. 兜底: 非clickable也有text接近的
    for e in elems:
        x1, y1, x2, y2 = e['bounds']
        if not (200 <= y1 <= 1800): continue
        t = e['text'].strip()
        if re.match(r'^[A-D][\.\、\s]', t) or (len(t) <= 4 and t[0] in 'ABCD'):
            cx, cy = (x1+x2)//2, (y1+y2)//2
            for ce in elems:
                if not ce['clickable']: continue
                cex1, cey1, cex2, cey2 = ce['bounds']
                if cex1 <= cx <= cex2 and cey1 <= cy <= cey2:
                    return ce, f"parent of '{t}' at {ce['center']}"
            return {'center': (cx, cy), 'text': t}, f"direct tap '{t}'"

    # 3. 终极兜底: 最大的可点击元素
    big = [e for e in elems if e['clickable'] and 400 < e['bounds'][1] < 1800 and (e['bounds'][2]-e['bounds'][0]) > 200]
    if big:
        big.sort(key=lambda x: x['bounds'][1])
        return big[0], f"fallback #{answer_letter}"

    return None, "无任何可点击元素"


def click_image_option(elems, answer_letter, q):
    """
    听音选择图片 (image options): 视觉模型判断哪张图匹配答案, 点击对应位置
    策略: 用UI dump找到A/B标签位置, 再找覆盖标签的可点击父容器(图片本身)
    """
    answer_letter = answer_letter.upper().strip()

    # Step 1: 用UI dump找A/B标签位置, 并找对应的可点击图片容器
    # A/B标签可能不是clickable, 但其父容器(图片)是
    img_targets = {}  # letter -> {center, bounds, clickable_elem}
    for e in elems:
        t = e['text'].strip()
        if t in ['A','B','C','D']:
            cx, cy = e['center']
            # 找覆盖该标签的可点击父容器(图片本身)
            for ce in elems:
                if not ce['clickable']: continue
                cex1, cey1, cex2, cey2 = ce['bounds']
                if (cex2-cex1) < 200: continue  # 图片容器宽度应该>200
                if cex1 <= cx <= cex2 and cey1 <= cy <= cey2:
                    img_targets[t] = {
                        'center': ce['center'],
                        'bounds': ce['bounds'],
                        'clickable_elem': ce,
                    }
                    break
            else:
                # 没有可点击父容器, 用标签本身
                img_targets[t] = {
                    'center': e['center'],
                    'bounds': e['bounds'],
                    'clickable_elem': None,
                }

    if answer_letter not in img_targets:
        return None, f"找不到选项 {answer_letter} (img_targets: {list(img_targets.keys())})"

    # Step 2: 用视觉模型判断哪张图与答案匹配
    shot_path = str(OUT / f"q{q.global_idx:03d}.png")
    match_prompt = (
        f"你是英语听力题配图识别专家。\n"
        f"录音内容: {q.recording}\n"
        f"正确答案: {q.answer}\n"
        f"题型: {q.type_2}\n\n"
        f"请看截图,告诉我:\n"
        f"1. A图片画的是什么?\n"
        f"2. B图片画的是什么?\n"
        f"3. 哪张图与录音/答案匹配? (A还是B)\n"
        f"用1-2行回答,末尾格式必须是: 匹配选项=X"
    )
    try:
        match_info = llm.ask(match_prompt, image_path=shot_path)
        print(f"    [匹配] {match_info[:200]}")
    except Exception as e:
        return None, f"图片匹配失败: {e}"

    # 提取匹配的选项字母
    matched = None
    m = re.search(r'匹配选项\s*=\s*([A-D])', match_info)
    if m:
        matched = m.group(1).upper()
    else:
        m2 = re.search(r'([A-D])\s*(图片|选项|图).{0,3}(匹配|对应|正确)', match_info)
        if m2:
            matched = m2.group(1).upper()

    if matched and matched != answer_letter:
        return None, f"⚠ 视觉模型判断={matched}, 脚本答案={answer_letter} | {match_info[:100]}"

    # Step 3: 点击目标图片
    target = img_targets[answer_letter]
    cx, cy = target['center']
    return target['clickable_elem'] or {'center': (cx, cy), 'text': f'image-{answer_letter}'}, f"图片 {answer_letter} at ({cx},{cy})"


# ================================================================
# 主循环
# ================================================================
print("=" * 60)
print(f"Unit 6 基础巩固 — {len(script_qs)} 题自动巡检")
print("=" * 60)

results = []
last_q = 0
STOP_NEXT = False  # 用户控制停止信号

for loop in range(60):
    if STOP_NEXT:
        print("\n收到停止信号,退出循环")
        break

    xml = dump_xml()
    sp.run(['adb','-s',SERIAL,'shell','rm','/sdcard/_d.xml'], capture_output=True)

    # 读题号
    cur = None
    for m in re.finditer(r'text="(\d+)/(\d+)"', xml):
        cur = int(m.group(1))
        total = int(m.group(2))
        break
    if not cur:
        print(f"⏹ 不在考题页 (loop {loop+1}),退出")
        break

    # ====== 检测是否在结果页 ======
    elems_raw = parse_ui(xml)
    has_result_page = any("正确答案" in e['text'] for e in elems_raw)
    if has_result_page:
        # 结果页: 不处理,直接找"下一题"按钮
        print(f"\n[结果页] 上一题刚答完,点击'下一题'")
        for e in elems_raw:
            t = (e['text'] or '').strip()
            if t in ['下一题', '完成', '继续', 'Next']:
                cx, cy = e['center']
                adb.tap(cx, cy)
                print(f"  推进: 点'{t}' at ({cx},{cy})")
                break
        else:
            # 兜底: 屏幕底部
            adb.tap(540, 1700)
        time.sleep(2)
        continue

    if cur == last_q:
        time.sleep(0.4); continue
    last_q = cur

    # 取脚本数据
    script = script_map.get(cur)
    elems = parse_ui(xml)
    texts = [e['text'] for e in elems if e['text']]

    print(f"\n{'─'*60}")
    print(f"  Q{cur:02d}/{total}  |  题型: {script.type_2 if script else '?'}  |  答案: {script.answer if script else '?'}")

    # ====== 截图 ======
    _t0 = time.time()
    adb.screenshot(f"q{cur:03d}.png")
    shot_path = str(OUT / f"q{cur:03d}.png")

    # ====== (3) 配图检查 ======
    has_image_option = bool(script and "图片" in script.type_2)  # 选项本身是图片
    img_result = "⏭ 纯文字题"

    if llm:
        if has_image_option:
            prompt = (
                f"你是英语听力题配图质检专家。\n"
                f"录音: {script.recording}\n"
                f"答案: {script.answer}\n"
                f"题型: {script.type_2}\n\n"
                f"截图中有两张配图(A和B)。请判断:\n"
                f"1. A图片内容是否清晰完整?\n"
                f"2. B图片内容是否清晰完整?\n"
                f"3. 哪张与录音匹配?是否真对应?有没有图片错放/乱放/截断/模糊?\n"
                f"用2行回答,末尾格式: [✅/⚠/❌] + 理由"
            )
        else:
            prompt = (
                f"你是英语听力题题干质检专家。\n"
                f"题目: {script.stem}\n"
                f"答案: {script.answer}\n"
                f"录音: {script.recording}\n"
                f"题型: {script.type_2}\n\n"
                f"请看截图(选项是文字),判断:\n"
                f"1. 题目文字是否完整、清晰?\n"
                f"2. 选项文字是否与脚本选项一致?有无错字/漏字?\n"
                f"3. APP实际显示的答案文字与脚本答案是否匹配?\n"
                f"用2行回答,末尾格式: [✅/⚠/❌] + 理由"
            )
        try:
            # 所有题都发图给视觉模型(纯文字题需要验证文字,图片题需要验证图片)
            img_result = llm.ask(prompt, image_path=shot_path)
            icon = "✅" if "✅" in img_result else ("⚠" if "⚠" in img_result else "❌" if "❌" in img_result else "🤖")
            print(f"  配图: {icon} {img_result[:150]}")
            print(f"  用时: {time.time() - _t0:.0f}s")
        except Exception as e:
            img_result = f"LLM异常: {e}"
            print(f"  配图: ❌ {img_result[:80]}")
    else:
        print(f"  配图: {img_result} (无LLM)")

    # ====== (4) 作答检查: 选对选项 ======
    answer_check = ""
    if not script:
        answer_check = "⚠ 无脚本数据, 跳过作答"
        print(f"  作答: {answer_check}")
    else:
        if has_image_option:
            target, reason = click_image_option(elems, script.answer, script)
        else:
            target, reason = click_text_option(elems, script.answer)

        if target is None:
            answer_check = f"❌ {reason}"
            print(f"  作答: {answer_check}")
            STOP_NEXT = True
            print("  ⚠ 已触发停止标志,下一轮循环退出 (请检查后手动继续)")
        else:
            cx, cy = target['center']
            adb.tap(cx, cy)
            answer_check = f"✅ {reason} → 点({cx},{cy})"
            print(f"  作答: {answer_check}")
        time.sleep(1)

    # ====== 推进到下一题: 找"检查"按钮并点击 ======
    # APP流程: 选完选项 → 弹出"检查"按钮 → 点击 → 进入下一题
    # 备用: 多次点击屏幕底部 (某些题型直接显示下一题按钮)
    found_check = False
    for attempt in range(4):
        time.sleep(0.8)
        new_xml = dump_xml()
        sp.run(['adb','-s',SERIAL,'shell','rm','/sdcard/_d.xml'], capture_output=True)
        new_elems = parse_ui(new_xml)
        # 找"检查"按钮
        for e in new_elems:
            t = (e['text'] or e['desc']).strip()
            if t in ['检查', 'Check', '提交', '确认', '下一题', '完成']:
                cx, cy = e['center']
                adb.tap(cx, cy)
                print(f"  推进: 点'{t}' at ({cx},{cy})")
                found_check = True
                time.sleep(1.5)
                break
        if found_check: break
        # 兜底: 点屏幕底部中央 (很多情况下检查按钮在底部)
        if attempt == 1:
            adb.tap(540, 1700); time.sleep(0.5)
        if attempt == 2:
            adb.tap(540, 1100); time.sleep(0.5)
        if attempt == 3:
            adb.tap(540, 2050); time.sleep(0.5)

    if not found_check:
        print("  推进: ⚠ 未找到'检查'按钮, 已尝试兜底点击")

    # ====== 记录结果 ======
    results.append({
        "idx": cur,
        "type": script.type_2 if script else "?",
        "script_answer": script.answer if script else "?",
        "image_check": img_result[:200] if isinstance(img_result, str) else str(img_result),
        "answer_check": answer_check,
        "screenshot": f"q{cur:03d}.png",
    })

    if cur >= total:
        print(f"\n✅ 全部 {total} 题完成!")
        break

# ====== 保存报告 ======
with open(OUT / "review_u6_basic.json", "w", encoding="utf-8") as f:
    json.dump({"total": len(results), "results": results}, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"完成 {len(results)} 题 | 报告: {OUT / 'review_u6_basic.json'}")
