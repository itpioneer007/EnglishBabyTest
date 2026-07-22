#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单元自检 题目自动化巡检 (第3项: 图片+脚本+完整性检查)

流程:
  1. 启动APP, 关广告
  2. 到专项突破 → 单元自检 → AI检测(870,756) → 去答题
  3. 关规则弹窗 → 开始答题(554, 2116)
  4. 逐题: 点选项 → 点"检查" → 截图+记录 → 自动下一题
  5. 全部跑完生成 report.json + 截图
"""

import os, sys, time, re, json, subprocess as sp
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from adb_controller import ADBController
from config_loader import load_config

PROJECT = Path(__file__).parent.absolute()
OUT_DIR = PROJECT / 'outputs' / 'questions'
OUT_DIR.mkdir(parents=True, exist_ok=True)

config = load_config()
adb = ADBController(serial=config.device.serial, screenshot_dir=str(PROJECT / 'outputs' / 'screenshots'))
SERIAL = config.device.serial

def dump():
    """获取当前 UI"""
    r = sp.run(['adb', '-s', SERIAL, 'shell', 'uiautomator', 'dump', '/sdcard/_d.xml'],
               capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        return ''
    r2 = sp.run(['adb', '-s', SERIAL, 'shell', 'cat', '/sdcard/_d.xml'],
                capture_output=True, text=True, timeout=5)
    sp.run(['adb', '-s', SERIAL, 'shell', 'rm', '/sdcard/_d.xml'])
    return r2.stdout


def close_all_popups(adb):
    """关闭所有可能弹出的广告/弹窗
    谨慎: 只点确认是X按钮的位置, 避免误点内容
    """
    # 中央大广告 X (close_iv 资源ID, 已知位置)
    adb.tap(540, 1821)
    time.sleep(0.5)


def is_main_page(elements):
    """判断是否在主页(而不是考试页)"""
    texts = ' '.join(e['text'] for e in elements)
    # 主页有这些特征
    main_features = ['教材精学', '专项突破', '我的练习', '我的班级']
    score = sum(1 for f in main_features if f in texts)
    return score >= 2


def is_exam_page(elements):
    """判断是否在考试页"""
    cur, total = find_progress(elements)
    if cur:
        return True
    texts = ' '.join(e['text'] for e in elements)
    if '练习结束还剩' in texts or '训练规则' in texts:
        return True
    return False


def ensure_exam_page(adb, max_retries=3):
    """确保在考试页，如果不是则尝试恢复"""
    for attempt in range(max_retries):
        xml = dump()
        elements = parse_elements(xml)
        if is_exam_page(elements):
            return True
        print(f'  ⚠ 不在考试页 (尝试{attempt+1}/{max_retries})')
        # 关弹窗
        close_all_popups(adb)
        time.sleep(2)
    return False

def parse_elements(xml):
    """解析UI元素"""
    elements = []
    for m in re.finditer(
        r'<node[^>]*?text="([^"]*)"[^>]*?clickable="(true|false)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml):
        text = m.group(1)
        clickable = m.group(2) == 'true'
        x1, y1, x2, y2 = map(int, m.groups()[2:6])
        elements.append({
            'text': text,
            'clickable': clickable,
            'center': ((x1+x2)//2, (y1+y2)//2),
            'bounds': (x1, y1, x2, y2),
        })
    return elements

def find_progress(elements):
    """找进度数字 X/40"""
    for e in elements:
        m = re.match(r'^(\d+)/(\d+)$', (e['text'] or '').strip())
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None

def find_options(elements):
    """找选项 (图片选项, 没有A/B文字)
    选项特征: 无文字, 可点击, y在题目图片区 (800-1500)
    """
    options = []
    for e in elements:
        text = e['text'].strip()
        # 选项A/B 单独的字母 (少见)
        if text in ['A', 'B', 'C', 'D'] and e['clickable']:
            options.append(e)
            continue
        # 图片选项: 无文字 + 可点击 + y在1000附近
        if not text and e['clickable']:
            y1 = e['bounds'][1]
            # 题目图片区 y大概在 800-1500
            if 800 < y1 < 1500:
                options.append(e)
    return options

def find_check_button(elements):
    """找检查按钮"""
    for e in elements:
        if e['text'] == '检查' and e['clickable']:
            return e['center']
    # 默认位置
    return (540, 2174)

def find_next_button(elements):
    """找下一题/继续按钮"""
    for e in elements:
        t = e['text']
        if ('下一' in t or '继续' in t or '交卷' in t) and e['clickable']:
            return e['center']
    return None

def find_question_text(elements):
    """找题目文字"""
    for e in elements:
        t = e['text']
        if len(t) > 4 and len(t) < 80:
            if any(k in t for k in ['听', '看', '选', '读', '写', '请', '配', '下列', '哪', '图', '单词', '句子', '音', '说', '正', '错']):
                return t
    return ''

def classify_question(elements):
    """分类题目"""
    text_blob = ' '.join(e['text'] for e in elements)
    if '录音' in text_blob or '听音' in text_blob:
        return '听力题'
    if '朗读' in text_blob or '口语' in text_blob or '读一读' in text_blob or '说一' in text_blob:
        return '口语题'
    if '拼写' in text_blob or '写' in text_blob and ('单词' in text_blob or '字母' in text_blob):
        return '拼写题'
    if '选择' in text_blob or any(e['text'] in ['A', 'B', 'C', 'D'] for e in elements):
        return '选择题'
    if '填空' in text_blob:
        return '填空题'
    if '连线' in text_blob or '配对' in text_blob:
        return '配对题'
    return '通用题'

# ============================================================
# 主流程
# ============================================================

def main():
    report = {'questions': []}

    # 1. 启动APP
    print('1/8 启动APP...')
    sp.run(['adb', '-s', SERIAL, 'shell', 'am', 'force-stop', 'com.dinoenglish.yyb'])
    time.sleep(2)
    sp.run(['adb', '-s', SERIAL, 'shell', 'am', 'start', '-n', 'com.dinoenglish.yyb/.base.SplashActivity'])
    time.sleep(5)

    # *** 关键: 先关所有弹窗 ***
    print('  关闭所有弹窗...')
    close_all_popups(adb)
    time.sleep(2)

    # 2. 到英语tab - 之前可能误点伴学, 这里多关一次
    print('2/8 到英语tab...')
    close_all_popups(adb)  # 再关一次以防万一
    adb.tap(108, 2233)  # 英语tab
    time.sleep(5)
    close_all_popups(adb)  # 到主页后也可能有弹窗

    # 3. 滚到单元自检 (左侧小幅度逐次滚动)
    print('3/8 滚动到单元自检...')
    close_all_popups(adb)
    adb.swipe(200, 1600, 200, 1200, 400)
    time.sleep(2)

    elements = parse_elements(dump())
    found_dyzj = False
    for e in elements:
        if '单元自检' in e['text']:
            adb.tap(*e['center'])
            print(f'  ✓ 进入单元自检 at {e["center"]}')
            found_dyzj = True
            break

    if not found_dyzj:
        print('  ⚠ 第一次没找到, 继续小滚...')
        for i in range(5):
            adb.swipe(200, 1600, 200, 1200, 400)
            time.sleep(2)
            elements = parse_elements(dump())
            for e in elements:
                if '单元自检' in e['text']:
                    adb.tap(*e['center'])
                    found_dyzj = True
                    break
            if found_dyzj:
                print(f'  ✓ 第{i+2}次滚动找到 单元自检')
                break
            # 检查是否滑过头了
            has_zx = any('专项突破' in e['text'] for e in elements)
            if not has_zx:
                print(f'  ⚠ 第{i+2}次滚动: 已过头(无专项突破), 停止')
                break

    if not found_dyzj:
        print('  ❌ 找不到单元自检')
        adb.screenshot('no_dyzj_final.png')
        with open(OUT_DIR / 'report.json', 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return
    time.sleep(4)
    close_all_popups(adb)  # 单元自检页可能也有伴学弹窗

    # 4. 点 AI检测 去答题
    print('4/8 点AI检测(870,756)...')
    adb.tap(870, 756)
    time.sleep(6)
    close_all_popups(adb)  # 可能有新弹窗

    # 5. 关规则弹窗
    print('5/8 关规则弹窗(540,1578)...')
    adb.tap(540, 1578)
    time.sleep(2)
    close_all_popups(adb)

    # 6. 开始答题 - AI需要时间生成
    print('6/8 开始答题(554,2116), AI生成题目中...')
    adb.tap(554, 2116)
    # 等待并重试找题目页
    found_q = False
    for wait in range(15):
        time.sleep(3)
        close_all_popups(adb)  # 等待中可能出弹窗
        xml = dump()
        elements = parse_elements(xml)
        cur, total = find_progress(elements)
        if cur:
            print(f'  ✓ 找到题目页 ({wait*3}秒后), 当前 {cur}/{total}')
            found_q = True
            break
    if not found_q:
        adb.screenshot('failed_to_load.png')
        print('  ❌ AI生成题目超时')
        with open(OUT_DIR / 'report.json', 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return

    # 7. 逐题巡检
    print('7/8 逐题巡检...')
    last_progress = 0
    stuck_count = 0

    for q_idx in range(50):
        # 每次都先关弹窗
        close_all_popups(adb)

        # 找当前进度 (重试3次)
        cur = None
        for _ in range(3):
            xml = dump()
            elements = parse_elements(xml)
            cur, total = find_progress(elements)
            if cur:
                break
            time.sleep(2)

        if not cur:
            adb.screenshot(f'Q_end_after_{last_progress}.png')
            xml2 = dump()
            elements2 = parse_elements(xml2)
            texts = [e['text'] for e in elements2 if e['text'] and len(e['text']) < 20]
            print(f'  结束页文字: {texts[:10]}')
            print(f'  截图: Q_end_after_{last_progress}.png')
            break
        stuck_count = 0

        # 检测题目类型
        q_type = classify_question(elements)
        question_text = find_question_text(elements)
        options = find_options(elements)

        # 截图 (每个题目一张)
        screenshot_path = OUT_DIR / f'q_{cur:02d}.png'
        sp.run(['adb', '-s', SERIAL, 'shell', 'screencap', '-p', '/sdcard/_qs.png'])
        sp.run(['adb', '-s', SERIAL, 'pull', '/sdcard/_qs.png', str(screenshot_path)])
        sp.run(['adb', '-s', SERIAL, 'shell', 'rm', '/sdcard/_qs.png'])

        entry = {
            'idx': cur,
            'progress': f'{cur}/{total}',
            'text': question_text[:50],
            'type': q_type,
            'option_count': len(options),
            'screenshot': screenshot_path.name,
        }
        report['questions'].append(entry)
        print(f'  Q{cur:2d}: [{q_type}] 选项{len(options)}个 {question_text[:35]}', end='')

        # 点选项 (如果有)
        if options:
            adb.tap(*options[0]['center'])
            time.sleep(1)
            print(f' → 选{options[0]["text"]}', end='')
        else:
            print(' (无选项)', end='')

        # 找"检查"按钮
        xml = dump()
        elements = parse_elements(xml)
        check_pos = find_check_button(elements)
        if check_pos:
            adb.tap(*check_pos)
            print(' → 检查', end='')
            time.sleep(2)

        # 找"下一题"或自动进入下一题
        xml = dump()
        elements = parse_elements(xml)
        next_pos = find_next_button(elements)
        if next_pos:
            adb.tap(*next_pos)
            print(' → 下一题', end='')
            time.sleep(2)
        print()

        # 检查进度是否前进
        if cur <= last_progress and q_idx > 0:
            print(f'  ⚠ 进度未前进 (cur={cur}, last={last_progress})')
            time.sleep(3)
        last_progress = cur

    # 8. 保存报告
    print()
    print('8/8 保存报告...')
    report_path = OUT_DIR / 'report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print()
    print('=' * 60)
    print(f'✅ 巡检完成! 共 {len(report["questions"])} 题')
    print('=' * 60)

    # 统计
    type_count = {}
    for q in report['questions']:
        t = q['type']
        type_count[t] = type_count.get(t, 0) + 1

    print('\n题型分布:')
    for t, n in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f'  {t:8s}: {n}题')

    print(f'\n前10题:')
    for q in report['questions'][:10]:
        print(f'  Q{q["idx"]:2d} [{q["type"]:5s}] {q["text"][:40]}')

    print(f'\n报告: {report_path}')
    print(f'截图: {OUT_DIR}/')


if __name__ == '__main__':
    main()
