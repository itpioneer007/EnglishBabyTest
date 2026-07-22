#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单元自检 - 逐题巡检 (题型自适应版)

题型自动检测 + 自适应作答:
  - 听力题: 检测录音按钮 → 选文字/图片选项
  - 选择题: 检测A/B/C/D选项文字 → tap
  - 拼写题: 检测输入框+键盘 → 点字母
  - 口语题: 检测录音按钮 → 标记为需人工验证

用法: python run_inspection.py
"""

import os, sys, time, re, json, subprocess as sp
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from adb_controller import ADBController
from config_loader import load_config

PROJECT = Path(__file__).parent.absolute()
OUT = PROJECT / 'outputs' / 'questions'
OUT.mkdir(parents=True, exist_ok=True)

config = load_config()
adb = ADBController(serial=config.device.serial, screenshot_dir=str(PROJECT / 'outputs' / 'screenshots'))
SERIAL = config.device.serial

# ============================================================
def dump_ui():
    r = sp.run(['adb','-s',SERIAL,'shell','uiautomator','dump','/sdcard/_d.xml'], capture_output=True, text=True, timeout=15)
    if r.returncode != 0: return ''
    r2 = sp.run(['adb','-s',SERIAL,'shell','cat','/sdcard/_d.xml'], capture_output=True, text=True, timeout=5)
    sp.run(['adb','-s',SERIAL,'shell','rm','/sdcard/_d.xml'])
    return r2.stdout

def parse_els(xml):
    els = []
    for m in re.finditer(r'<node[^>]*?text=\"([^\"]*)\" clickable=\"(true|false)\"'
                         r'[^>]*?bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"', xml):
        text, click = m.group(1), m.group(2)=='true'
        x1,y1,x2,y2 = map(int, m.groups()[2:6])
        rid_m = re.search(r'resource-id=\"([^\"]*)\"', m.group(0))
        rid = rid_m.group(1).split('/')[-1] if rid_m else ''
        cls_m = re.search(r'class=\"([^\"]*)\"', m.group(0))
        cls = cls_m.group(1).split('.')[-1] if cls_m else ''
        els.append({'text':text,'clickable':click,'center':((x1+x2)//2,(y1+y2)//2),
                    'bounds':(x1,y1,x2,y2),'rid':rid,'cls':cls})
    return els

def snapshot(name):
    sp.run(['adb','-s',SERIAL,'shell','screencap','-p','/sdcard/_s.png'])
    sp.run(['adb','-s',SERIAL,'pull','/sdcard/_s.png',str(OUT/name)])
    sp.run(['adb','-s',SERIAL,'shell','rm','/sdcard/_s.png'])

def close_ads():
    adb.tap(540, 1821); time.sleep(0.3)
# ============================================================

def find_progress(els):
    for e in els:
        m = re.match(r'^(\d+)/(\d+)$', (e['text'] or '').strip())
        if m: return int(m.group(1)), int(m.group(2))
    return None, None

def classify_q(els):
    """自适应题型检测"""
    texts = ' '.join(e['text'] for e in els)
    has_abcd = sum(1 for e in els if e['text'] in ['A','B','C','D'])
    has_letter_options = any(re.match(r'^[A-D]\.', e['text']) for e in els)
    has_keyboard = any('keyboard' in e['rid'].lower() or 'keys' in e['rid'].lower() for e in els)
    
    # 更准确: 检测有没有选项文字
    options_present = has_abcd or has_letter_options
    
    if '听音' in texts or '听句' in texts or '听' in texts:
        if options_present: return '听力/选择题'
        return '听力题'
    if '写' in texts or has_keyboard:
        return '拼写题'
    if '朗读' in texts or '读一' in texts or '说一' in texts:
        return '口语题'
    if '连' in texts and '线' in texts:
        return '连线题'
    if options_present:
        return '选择题'
    return '通用题'

def find_check_btn(els):
    for e in els:
        if '检查' in e['text'] and e['clickable']: return e['center']
    return (540, 2174)  # 默认

def find_sound_btn(els):
    for e in els:
        if e['rid'] == 'play_box' and e['clickable']: return e['center']
    return None

def answer_question(els):
    """检测题型并尝试作答"""
    q_type = classify_q(els)
    
    # 找选项: 无文字+可点击且在选项区(y=800~1500)
    options = []
    for e in els:
        if not e['text'] and e['clickable']:
            y = e['bounds'][1]
            if 750 < y < 1600:
                options.append(e)
        elif e['text'] in ['A','B','C','D'] and e['clickable']:
            options.append(e)
        elif re.match(r'^[A-D]\.', e['text']) and e['clickable']:
            options.append(e)
    
    # 点录音按钮（如果有）
    sound_btn = find_sound_btn(els)
    if sound_btn:
        adb.tap(*sound_btn)
        time.sleep(1)
    
    # 选选项（如果有）
    if options:
        adb.tap(*options[0]['center'])
        time.sleep(1)
        return f'选{len(options)}选项', q_type
    
    # 检测是否有键盘（拼写题）
    kbd_options = []
    for e in els:
        if e['text'] and len(e['text']) == 1 and e['text'].isalnum() and e['clickable']:
            y = e['bounds'][1]
            if y > 1500:  # 键盘区
                kbd_options.append(e)
    if kbd_options:
        # 随便点个字母
        letter = kbd_options[0]
        adb.tap(*letter['center'])
        time.sleep(0.5)
        return f'键盘输入{letter["text"]}', q_type
    
    return '无操作', q_type

def main():
    global q_idx, report
    
    # 预计已经在考试页面(17/37), 直接从题目页开始
    print('=' * 50)
    print('🚀 湘少六上Unit1 逐题巡检')
    print('=' * 50)
    
    report = {'version':'湘少版(2024审定)','unit':'Unit 1','questions':[]}
    last_q = 0
    same_count = 0
    q_max = 37
    
    for loop in range(80):
        # dump
        xml = dump_ui()
        els = parse_els(xml)
        
        cur, total = find_progress(els)
        if not cur:
            time.sleep(3)
            continue
        total = total or q_max
        
        # 如果进度未变, 等待
        if cur == last_q:
            same_count += 1
            if same_count > 5:
                # 检查是否结束或卡住
                print(f'⚠ 进度卡在{cur}/{total} ({same_count}次)')
                adb.tap(*find_check_btn(els))  # 再点检查
                time.sleep(3)
                same_count = 0
                continue
            time.sleep(2)
            continue
        same_count = 0
        last_q = cur
        
        # 截图
        fname = f'q{cur:02d}.png'
        snapshot(fname)
        
        # 检测题型 + 作答
        q_type = classify_q(els)
        answer_log, q_type = answer_question(els)
        
        # 点检查
        check_btn = find_check_btn(els)
        adb.tap(*check_btn)
        time.sleep(2)
        
        entry = {
            'idx': cur,
            'progress': f'{cur}/{total}',
            'type': q_type,
            'action': answer_log,
            'screenshot': fname,
        }
        report['questions'].append(entry)
        
        print(f'  Q{cur:2d}/{total} [{q_type}] {answer_log}')
        
        if cur >= total:
            print(f'\n✅ 全部{total}题完成')
            break
    
    # 保存报告
    rpath = OUT / 'report.json'
    with open(rpath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'\n✅ 报告: {rpath}')

if __name__ == '__main__':
    main()
