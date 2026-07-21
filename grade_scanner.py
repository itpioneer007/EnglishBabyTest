#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全版本年级扫描器

遍历每个教材版本 → 打开年级选择器 → 记录可用年级
输出: JSON 格式, 版本→年级映射

用法:
    python grade_scanner.py
    结果保存到 outputs/web/all_grades.json
"""

import os, sys, time, json, re, subprocess as sp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from adb_controller import ADBController
from config_loader import load_config

PROJECT = os.path.dirname(os.path.abspath(__file__))

def switch_version(adb, version):
    """切换到指定版本并返回首页"""
    for attempt in range(2):
        # 点"我" tab
        adb.tap(972, 2220)
        time.sleep(4)

        # 点设置图标
        adb.tap(1000, 170)
        time.sleep(3)

        # dump 看是否到了设置页
        elements = adb.dump_ui(retries=2)
        has_settings = any("个人信息" in e.text for e in elements)

        if has_settings:
            # 点"个人信息"
            adb.click_element(text="个人信息", exact=True)
            time.sleep(2)

            # 点"英语所学教材版本"
            adb.click_element(text="英语所学教材版本", exact=True)
            time.sleep(2)

            # 选择目标版本
            adb.click_element(text=version, exact=True)
            time.sleep(3)

            # 返回首页
            for _ in range(3):
                adb.press_back()
                time.sleep(1)
            adb.tap(108, 2233)
            time.sleep(6)
            return
        else:
            # 没到位，退回去重试
            adb.press_back()
            time.sleep(2)
            print(f"  重试版本切换 ({attempt+1})")


def detect_grades(adb):
    """打开年级选择器并检测可用年级"""
    adb.tap(346, 275)  # 点切换器
    time.sleep(3)

    # dump 弹窗
    r = sp.run(['adb', 'shell', 'uiautomator', 'dump', '/sdcard/_g.xml'],
               capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return {"version_text": "", "grades": [], "has_new": False}

    r2 = sp.run(['adb', 'shell', 'cat', '/sdcard/_g.xml'],
                capture_output=True, text=True, timeout=5)
    sp.run(['adb', 'shell', 'rm', '/sdcard/_g.xml'])
    xml = r2.stdout

    # 提取当前版本文字
    version_text = ""
    for m in re.finditer(r'text="([^"]*)"', xml):
        t = m.group(1)
        if ('版' in t or '审定' in t) and '切换' not in t and '教材' not in t and '如何' not in t:
            version_text = t

    # 提取年级+册, 按位置排序去重
    items = []
    seen_texts = set()
    for m in re.finditer(
        r'text="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        text = m.group(1)
        y1 = int(m.group(3))
        is_book = any(k in text for k in ['年级', '册'])
        is_new = '新教材' in text
        is_bad = any(k in text for k in ['版', '切换', '审定', '教材', '如何', '2024'])

        if is_book and text not in seen_texts:
            seen_texts.add(text)
            items.append({"text": text, "y": y1})
        elif is_new and text not in seen_texts:
            seen_texts.add(text)
            items.append({"text": text, "y": y1, "is_new_tag": True})

    items.sort(key=lambda x: x['y'])
    grade_names = [i['text'] for i in items if '年级' in i['text'] or '册' in i['text']]
    has_new = any(i.get('is_new_tag') for i in items)

    # 关闭弹窗（用back）
    adb.press_back()
    time.sleep(2)

    return {
        "version_text": version_text,
        "grades": grade_names,
        "has_new_textbook_tag": has_new,
    }


def main():
    config = load_config()
    adb = ADBController(serial=config.device.serial,
                        screenshot_dir="outputs/screenshots")

    # 重启 APP
    sp.run(['adb', 'shell', 'am', 'force-stop', 'com.dinoenglish.yyb'])
    time.sleep(2)
    sp.run(['adb', 'shell', 'am', 'start', '-n', 'com.dinoenglish.yyb/.base.SplashActivity'])
    time.sleep(5)
    adb.tap(540, 1821)  # 关广告
    time.sleep(3)

    # 要检测的版本
    versions = [
        "湘少版(2024审定)",
        "湘鲁版(2024审定)",
        "人教版(PEP)(2024审定)",
        "教科版(2024审定)",
        "教科版",
    ]

    results = {}
    for v in versions:
        print(f"[{versions.index(v)+1}/{len(versions)}] 检测: {v} ...")
        switch_version(adb, v)
        data = detect_grades(adb)
        results[v] = data
        print(f"   版本文字: {data['version_text']}")
        print(f"   可用年级: {data['grades']}")
        print(f"   有新教材标: {data['has_new_textbook_tag']}")

    # 保存结果
    out_dir = os.path.join(PROJECT, "outputs", "web")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "all_grades.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果保存到: {out_path}")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
