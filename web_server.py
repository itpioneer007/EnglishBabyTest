#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
英语宝模块检测 - Web 控制面板
Flask 后端，提供 REST API 和前端页面

启动:
    cd 英语宝模块检测
    python web_server.py

打开浏览器访问: http://localhost:5000
"""

import os
import sys
import json
import time
import threading
import re
import subprocess as sp
from pathlib import Path
from datetime import datetime

# 添加 src 到路径
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flask import Flask, jsonify, request, send_from_directory, render_template, Response
from adb_controller import ADBController
from config_loader import load_config
from inspection_engine import InspectionEngine, QuestionReport, CheckItem

app = Flask(__name__)

# ============================================================
# 全局状态
# ============================================================
task_status = {
    "running": False,
    "current_task": "",
    "progress": [],
    "start_time": "",
    "end_time": "",
    "log": [],
}

_last_screenshot = ""

# 模块坐标（从 uiautomator dump 获取的精确坐标）
MODULE_COORDS = {
    # 教材精学 (人教版下的坐标)
    "课本点读(左)": (203, 1191),
    "课本点读(中)": (540, 1191),
    "巧记单词":     (876, 1191),
    "语音评测":     (203, 1358),
    # 专项突破 (可见)
    "听课文":    (161, 1792),
    "课文动画":  (414, 1792),
    "基础训练":  (666, 1792),
    "一课一练":  (919, 1792),
    "课文配音":  (161, 2033),
    "口语训练":  (414, 2033),
    "复习回顾":  (666, 2033),
    "全脑记词":  (919, 2033),
    # 专项突破 (需滚动)
    "单元自检":      (414, 746),
    "单元练习计划":  (666, 746),
    # 听力专项 (需滚动更深)
    "基础巩固":   (180, 1250),   # 听力专项下的三个阶段
    "综合进阶":   (540, 1250),
    "难点突破":   (900, 1250),
    "听力专项_五上": (414, 1250),   # 五上入口
    "听力专项_五下": (414, 950),    # 五下入口
    "听力专项_六上": (414, 1150),   # 六上入口
    "听力专项_六下": (414, 1050),   # 六下入口
}

# 需要先滚动才能看到的模块
DEEP_MODULES = {
    "单元自检",
    "单元练习计划",
    "教材同步题库",
    "听力训练",
    "你听一刻",
    # 听力专项下的内容
    "基础巩固",
    "综合进阶",
    "难点突破",
    "听力专项_五上",
    "听力专项_五下",
    "听力专项_六上",
    "听力专项_六下",
}

# 底部导航坐标
TABS = {
    "英语": (108, 2233),
    "我":   (972, 2220),
}

SETTINGS_ICON = (1000, 170)
AD_CLOSE = (540, 1821)


# ============================================================
# 工具函数
# ============================================================

def get_adb():
    """获取 ADBController 实例"""
    config = load_config()
    out_dir = PROJECT_ROOT / "outputs" / "web"
    out_dir.mkdir(parents=True, exist_ok=True)
    return ADBController(serial=config.device.serial, screenshot_dir=str(out_dir))


def log_msg(msg: str, level: str = "info"):
    """添加日志"""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
        "level": level,
    }
    task_status["log"].append(entry)
    print(f"[{entry['time']}] [{level}] {msg}")


def clear_status():
    """清空状态"""
    task_status["running"] = False
    task_status["current_task"] = ""
    task_status["progress"] = []
    task_status["start_time"] = ""
    task_status["end_time"] = ""
    task_status["log"] = []


def set_running(task_name: str):
    """设置为运行中"""
    clear_status()
    task_status["running"] = True
    task_status["current_task"] = task_name
    task_status["start_time"] = datetime.now().strftime("%H:%M:%S")


def set_done():
    """设置为完成"""
    task_status["running"] = False
    task_status["end_time"] = datetime.now().strftime("%H:%M:%S")


def update_progress(step: int, total: int, msg: str):
    """更新进度"""
    entry = {"step": step, "total": total, "msg": msg}
    task_status["progress"].append(entry)


# ============================================================
# 后台任务函数
# ============================================================

def run_login_task():
    """后台执行登录"""
    try:
        set_running("login")
        adb = get_adb()
        config = load_config()

        log_msg("启动英语宝APP...")
        update_progress(1, 6, "启动APP")
        adb.launch_app(config.app.package)
        time.sleep(5)

        log_msg("关闭启动广告...")
        update_progress(2, 6, "关闭广告")
        adb.tap(*AD_CLOSE)
        time.sleep(2)

        log_msg("勾选协议...")
        update_progress(3, 6, "勾选协议")
        adb.click_element(text="我已阅读并同意", exact=False)
        time.sleep(1)

        log_msg("点击登录...")
        update_progress(4, 6, "点击登录")
        # 先按 exact 尝试
        if not adb.click_element(text="登录", exact=True):
            adb.tap(540, 1232)  # fallback: 登录按钮已知坐标
        time.sleep(3)

        log_msg("处理协议弹窗...")
        update_progress(5, 6, "协议弹窗")
        if adb.wait_for_element(text="同意", timeout=3):
            adb.click_element(resource_id="agree_tv", exact=False)
            time.sleep(3)

        log_msg("关闭广告弹窗...")
        adb.tap(*AD_CLOSE)
        time.sleep(2)

        adb.screenshot("login_done.png")
        log_msg("✅ 登录完成！", "success")
        update_progress(6, 6, "登录成功")

    except Exception as e:
        log_msg(f"❌ 登录失败: {e}", "error")
    finally:
        set_done()


def run_version_detect_task():
    """后台检测可用版本"""
    try:
        set_running("version_detect")
        config = load_config()
        adb = get_adb()

        log_msg("导航到版本选择页...")
        update_progress(1, 5, "进入'我'页")
        adb.tap(*TABS["我"])
        time.sleep(3)

        update_progress(2, 5, "进入设置")
        adb.tap(*SETTINGS_ICON)
        time.sleep(2)

        update_progress(3, 5, "进入个人信息")
        adb.click_element(text="个人信息", exact=True)
        time.sleep(2)

        update_progress(4, 5, "点击英语所学教材版本")
        adb.click_element(text="英语所学教材版本", exact=True)
        time.sleep(2)

        log_msg("截图版本选择页...")
        adb.screenshot("versions_page.png")
        update_progress(5, 5, "版本页已打开")

        # dump UI 获取版本列表
        elements = adb.dump_ui()
        versions = []
        for elem in elements:
            if elem.text and ("版" in elem.text or "年级" in elem.text):
                versions.append({
                    "text": elem.text,
                    "center": list(elem.center),
                    "bounds": list(elem.bounds),
                })

        # 保存到临时文件供 API 读取
        versions_file = PROJECT_ROOT / "outputs" / "web" / "versions.json"
        with open(versions_file, "w", encoding="utf-8") as f:
            json.dump(versions, f, ensure_ascii=False, indent=2)

        log_msg(f"✅ 检测到 {len(versions)} 个版本元素", "success")
        log_msg(f"  可用版本: {[v['text'] for v in versions]}")

    except Exception as e:
        log_msg(f"❌ 版本检测失败: {e}", "error")
    finally:
        set_done()


def run_full_task(version: str, grade: str, modules: list):
    """一键全流程：登录 → 切换版本 → 选年级 → 测模块 (加速版)"""
    try:
        set_running("full")
        config = load_config()
        adb = get_adb()

        total = 8 + len(modules) * 3
        cur = 0

        # 1. 启动APP
        cur += 1
        log_msg(f"{cur}/{total} 启动APP")
        adb.launch_app(config.app.package)
        time.sleep(4)

        # 2. 关广告
        cur += 1
        log_msg(f"{cur}/{total} 关广告")
        adb.tap(540, 1821)
        time.sleep(1)

        # 3. 登录 (仅当需要时)
        cur += 1
        log_msg(f"{cur}/{total} 检查登录状态")
        elements = adb.dump_ui()
        needs_login = any('登录' in (e.text or '') for e in elements)
        if needs_login:
            log_msg(f"  需要登录")
            adb.click_element(text="我已阅读并同意", exact=False)
            time.sleep(0.5)
            adb.click_element(text="登录", exact=True)
            time.sleep(2)
            if adb.wait_for_element(text="同意", timeout=3):
                adb.tap(540, 1550)
                time.sleep(1.5)
        else:
            log_msg(f"  已登录, 跳过", "success")
        adb.tap(540, 1821)
        time.sleep(1)

        # 4. 切版本 (仅当需要时)
        cur += 1
        log_msg(f"{cur}/{total} 切换版本: {version}")
        # 先检查主页面上的版本文字
        elements = adb.dump_ui()
        on_correct_version = False
        for e in elements:
            t = (e.text or "").replace('（', '(').replace('）', ')')
            v = version.replace('（', '(').replace('）', ')')
            if v in t:
                on_correct_version = True
                break
        if on_correct_version:
            log_msg(f"  已是 {version}, 跳过切换", "success")
        else:
            adb.tap(972, 2220); time.sleep(2)
            adb.tap(1000, 170); time.sleep(1.5)
            adb.click_element(text="个人信息", exact=True); time.sleep(1.5)
            adb.click_element(text="英语所学教材版本", exact=True); time.sleep(1.5)
            adb.click_element(text=version, exact=True); time.sleep(1.5)

        # 5. 回首页
        cur += 1
        log_msg(f"{cur}/{total} 返回首页")
        for _ in range(3):
            adb.press_back(); time.sleep(1)
        adb.tap(108, 2233); time.sleep(3)
        adb.tap(540, 1821); time.sleep(1)

        # 6. 选年级
        if grade:
            cur += 1
            log_msg(f"{cur}/{total} 选择年级: {grade}")
            adb.tap(346, 275); time.sleep(1.5)

            found = False
            for attempt in range(4):
                elements = adb.dump_ui()
                for e in elements:
                    if grade in (e.text or ""):
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  ✅ 已选 {grade}", "success")
                        found = True
                        break
                if found: break
                adb.swipe(540, 1700, 540, 900, 300); time.sleep(1)

            # 关闭弹窗
            adb.press_back(); time.sleep(1)
            adb.press_back(); time.sleep(1)
            adb.tap(108, 2233); time.sleep(3)
            adb.tap(540, 1821); time.sleep(1)

        # 7. 稳定
        cur += 1
        log_msg(f"{cur}/{total} 页面就绪")
        time.sleep(1)

        # 8. 测试模块
        for i, module in enumerate(modules):
            if module not in MODULE_COORDS:
                log_msg(f"⚠ 跳过: {module}", "warning")
                continue

            cx, cy = MODULE_COORDS[module]
            
            if module in DEEP_MODULES:
                log_msg(f"  ⏬ 滚动到 {module}")
                found_deep = False
                for scroll_step in range(5):
                    adb.swipe(200, 1600, 200, 1200, 400)
                    time.sleep(1)
                    elements = adb.dump_ui()
                    for e in elements:
                        if e.text and e.text.strip() == module:
                            cx, cy = e.center
                            log_msg(f"    滚{scroll_step+1}次找到 {module}", "success")
                            found_deep = True; break
                    if found_deep: break
                    if not any('专项突破' in (e.text or '') for e in elements):
                        break
                if not found_deep:
                    log_msg(f"    ⚠ 未找到 {module}", "warning")
                    continue

            cur += 1
            log_msg(f"[{i+1}/{len(modules)}] 进入: {module} ({cur}/{total})")
            adb.tap(cx, cy); time.sleep(1.5)

            cur += 1
            safe_name = f"mod_{i+1:02d}.png"
            adb.screenshot(safe_name)
            log_msg(f"  ✅ {module} 截图 ({cur}/{total}) → {safe_name}", "success")

            cur += 1
            adb.press_back(); time.sleep(1.5)
            adb.tap(540, 1821); time.sleep(1)

        log_msg(f"✅ 完成! {version} {grade} {len(modules)}模块", "success")
        adb.screenshot("99_complete.png")

    except Exception as e:
        log_msg(f"❌ 失败: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


def run_grade_scan_task():
    """全版本年级扫描（调用 grade_scanner.py）"""
    try:
        set_running("grade_scan")
        log_msg("开始全版本年级扫描...")
        scanner = PROJECT_ROOT / "grade_scanner.py"
        r = sp.run(
            [sys.executable, str(scanner)],
            capture_output=True, text=True, timeout=600,
            cwd=str(PROJECT_ROOT),
        )
        if r.returncode == 0:
            log_msg("✅ 全版本年级扫描完成", "success")
        else:
            log_msg(f"⚠ 扫描部分失败: {r.stderr[-200:]}", "warning")
    except Exception as e:
        log_msg(f"❌ 扫描失败: {e}", "error")
    finally:
        set_done()
    try:
        set_running("full")
        config = load_config()
        adb = get_adb()

        total = 8 + len(modules) * 3
        cur = 0

        # 1. 启动APP
        cur += 1
        log_msg(f"1/{total} 启动APP")
        update_progress(cur, total, "启动APP")
        adb.launch_app(config.app.package)
        time.sleep(5)

        # 2. 关闭广告
        cur += 1
        log_msg(f"2/{total} 关闭广告")
        update_progress(cur, total, "关闭广告")
        adb.tap(*AD_CLOSE)
        time.sleep(2)

        # 3. 登录流程
        cur += 1
        log_msg(f"3/{total} 自动登录")
        update_progress(cur, total, "自动登录")
        # 勾协议
        adb.click_element(text="我已阅读并同意", exact=False)
        time.sleep(1)
        # 点登录
        adb.click_element(text="登录", exact=True)
        time.sleep(3)
        # 处理弹窗
        if adb.wait_for_element(text="同意", timeout=3):
            adb.click_element(resource_id="agree_tv", exact=False)
            time.sleep(3)
        adb.tap(*AD_CLOSE)
        time.sleep(2)
        adb.screenshot("01_login_done.png")

        # 4. 切到版本选择页 → 选版本
        cur += 1
        log_msg(f"4/{total} 切换版本: {version}")
        update_progress(cur, total, f"切换版本: {version}")
        adb.tap(*TABS["我"])
        time.sleep(3)
        adb.tap(*SETTINGS_ICON)
        time.sleep(2)
        adb.click_element(text="个人信息", exact=True)
        time.sleep(2)
        adb.click_element(text="英语所学教材版本", exact=True)
        time.sleep(2)
        adb.click_element(text=version, exact=True)
        time.sleep(3)

        # 5. 返回主页面
        cur += 1
        log_msg(f"5/{total} 返回主页面")
        update_progress(cur, total, "返回主页面")
        for _ in range(3):
            adb.press_back()
            time.sleep(1)
        adb.tap(*TABS["英语"])
        time.sleep(6)
        adb.tap(*AD_CLOSE)
        time.sleep(2)
        adb.screenshot("02_back_home.png")

        # 6. 选择年级（在主页面顶部点年级切换器）
        if grade:
            cur += 1
            log_msg(f"6/{total} 选择年级: {grade}")
            update_progress(cur, total, f"选择年级: {grade}")
            adb.tap(346, 275)
            time.sleep(3)

            # 动态查找年级文字（支持滚动）
            found = False
            for attempt in range(4):
                elements = adb.dump_ui()
                for elem in elements:
                    if grade in elem.text:
                        adb.tap(elem.center[0], elem.center[1])
                        log_msg(f"  ✅ 已选 \"{grade}\" at {elem.center}", "success")
                        found = True
                        break
                if found:
                    break
                # 没找到，滚屏
                adb.swipe(540, 1700, 540, 900, 300)
                time.sleep(2)

            if not found:
                log_msg(f"  ⚠ 未找到年级 \"{grade}\"", "warning")
            time.sleep(3)
            # 关闭弹窗（点左上角）
            adb.tap(108, 100)
            time.sleep(1)
            adb.screenshot("03_grade_selected.png")

        # 7. 等待页面稳定
        cur += 1
        log_msg(f"{'7' if grade else '6'}/{total} 页面稳定")
        update_progress(cur, total, "页面已就绪")
        time.sleep(3)

        # 8. 逐模块检测
        for i, module in enumerate(modules):
            if module not in MODULE_COORDS:
                log_msg(f"⚠ 跳过未知模块: {module}", "warning")
                continue

            cx, cy = MODULE_COORDS[module]

            # 深度模块需先滚到专项突破底部
            if module in DEEP_MODULES:
                log_msg(f"  ⏬ 滚动到深度模块 {module}")
                for _ in range(2):
                    adb.swipe(540, 1900, 540, 600, 500)
                    time.sleep(2)
                # 重新读取位置 (滚动后坐标可能变)
                elements = adb.dump_ui()
                for elem in elements:
                    if elem.text and elem.text.strip() == module:
                        cx, cy = elem.center
                        log_msg(f"  📍 找到 {module} at ({cx},{cy})", "success")
                        break

            cur += 1
            log_msg(f"[{i+1}/{len(modules)}] 进入: {module} ({cur}/{total})")
            update_progress(cur, total, f"进入 {module}")
            adb.tap(cx, cy)
            time.sleep(3)

            cur += 1
            adb.screenshot(f"module_{module}.png")
            log_msg(f"  ✅ {module} 截图完成 ({cur}/{total})", "success")
            update_progress(cur, total, f"{module} 截图完成")

            cur += 1
            adb.press_back()
            time.sleep(3)
            adb.tap(*AD_CLOSE)
            time.sleep(2)
            log_msg(f"  返回首页 ({cur}/{total})")
            update_progress(cur, total, "返回首页")

        log_msg(f"✅ 全流程完成！版本={version}, 年级={grade}, 模块={len(modules)}个", "success")
        adb.screenshot("99_complete.png")

    except Exception as e:
        log_msg(f"❌ 流程失败: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


def run_inspect_loop():
    """
    逐题巡检循环 (稳定版)
    
    核心逻辑:
      1. 导航到 AI检测 考试页
      2. 对每题: 截图→点右侧选项(970, y)→点底部按钮×2(检查+下一题)
      3. 遇到问题就停，不卡住
    
    按钮约定:
      - 底部按钮 (540, 2174): 选完选项后点一次→显示答案, 再点一次→跳下一题
      - 选项位置: 右侧选项标签区 (x≈900-1000) 不是图片中央
    """
    try:
        set_running("inspect_loop")
        config = load_config()
        adb = get_adb()

        # 1. 启动 + 导航
        log_msg("启动APP")
        adb.launch_app(config.app.package)
        time.sleep(4)
        adb.tap(540, 1821)  # 关广告
        time.sleep(0.5)
        adb.tap(108, 2233)  # 英语tab
        time.sleep(3)
        adb.tap(540, 1821)

        # 2. 滚到单元自检
        log_msg("滚动到单元自检")
        for i in range(4):
            adb.swipe(200, 1600, 200, 1200, 400)
            time.sleep(0.5)
            elements = adb.dump_ui()
            for e in elements:
                if e.text and '单元自检' in e.text:
                    adb.tap(e.center[0], e.center[1])
                    break
            if any('单元自检' in (e.text or '') for e in elements):
                break
        time.sleep(3)
        adb.tap(540, 1821)

        # 3. 等加载 + 点AI检测去答题
        log_msg("进入AI检测")
        time.sleep(6)
        elements = adb.dump_ui()
        for e in elements:
            if e.text == '去答题' and e.clickable and e.center[1] < 800:
                adb.tap(e.center[0], e.center[1])
                break
        time.sleep(5)

        # 4. 关规则弹窗 + 开始答题
        adb.tap(540, 1578)
        time.sleep(0.5)
        adb.tap(554, 2116)
        time.sleep(10)

        # 5. 逐题巡检
        log_msg("逐题巡检")
        questions = []
        last = 0
        
        for step in range(80):
            if not task_status["running"]:
                break

            elements = adb.dump_ui(retries=2)
            cur = None
            for e in elements:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    cur = int(m.group(1))
                    break
            
            if not cur:
                log_msg("不在考题页，结束", "warning")
                break
            if cur == last:
                time.sleep(0.3)
                continue
            last = cur

            adb.screenshot(f"q{cur:02d}.png")
            questions.append({"idx": cur, "screenshot": f"q{cur:02d}.png"})
            log_msg(f"Q{cur}", "success")
            update_progress(cur, 40, f"Q{cur}")

            # 点右侧选项或中央（取决于布局）
            for e in elements:
                if e.clickable and 700 < e.bounds[1] < 1700:
                    if e.center[0] > 450:
                        adb.tap(e.center[0], e.bounds[1] + 30)
                    else:
                        adb.tap((e.bounds[0] + e.bounds[2]) // 2, (e.bounds[1] + e.bounds[3]) // 2)
                    break
            time.sleep(1)

            # 连点两次底部按钮 (检查→下一题)
            adb.tap(540, 2174)
            time.sleep(1.5)
            adb.tap(540, 2174)
            time.sleep(1.5)

            if cur >= 40:
                log_msg("✅ 40题完成!", "success")
                break

        # 6. 保存报告
        out = PROJECT_ROOT / "outputs" / "questions" / "inspect_report.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)
        log_msg(f"✅ 报告: {out.name} ({len(questions)}题)", "success")

    except Exception as e:
        log_msg(f"❌ 异常: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


def run_inspect_questions_task():
    """自动化巡检 AI检测 题目：
    1. 启动APP, 关广告, 进英语tab
    2. 滚到专项突破底部 → 单元自检
    3. 点 AI检测的 去答题 (870, 756)
    4. 关规则弹窗 (540, 1578) → 点开始答题 (554, 2116)
    5. 逐题截图+解析, 推进直到没有"下一题"按钮
    """
    report = {"questions": []}
    try:
        set_running("inspect_questions")
        config = load_config()
        adb = get_adb()

        # 1. 启动APP
        log_msg("启动APP...")
        sp.run(['adb', '-s', config.device.serial, 'shell', 'am', 'force-stop', 'com.dinoenglish.yyb'])
        time.sleep(2)
        sp.run(['adb', '-s', config.device.serial, 'shell', 'am', 'start', '-n', 'com.dinoenglish.yyb/.base.SplashActivity'])
        time.sleep(5)
        adb.tap(540, 1821)  # 关启动广告
        time.sleep(3)
        adb.tap(948, 1821)  # 关可能的第二个
        time.sleep(2)

        # 2. 滚到专项突破底部 → 单元自检
        log_msg("滚动到单元自检...")
        adb.tap(108, 2233)  # 英语tab
        time.sleep(5)
        for _ in range(2):
            adb.swipe(540, 1500, 540, 800, 400)
            time.sleep(2)
        # 小幅调整
        adb.swipe(540, 1500, 540, 1100, 400)
        time.sleep(2)

        # 动态找 单元自检
        elements = adb.dump_ui()
        for elem in elements:
            if elem.text and '单元自检' in elem.text:
                adb.tap(elem.center[0], elem.center[1])
                log_msg(f"  ✅ 进入单元自检 at {elem.center}", "success")
                break
        time.sleep(4)

        # 3. 点 AI检测的 去答题
        log_msg("点 AI检测 去答题...")
        adb.tap(870, 756)
        time.sleep(6)

        # 4. 关规则弹窗
        log_msg("关闭训练规则弹窗...")
        adb.tap(540, 1578)
        time.sleep(2)

        # 5. 点开始答题
        log_msg("点开始答题...")
        adb.tap(554, 2116)
        time.sleep(8)  # AI生成题目

        # 6. 逐题巡检
        log_msg("开始逐题巡检...")
        out_dir = PROJECT_ROOT / "outputs" / "questions"
        out_dir.mkdir(parents=True, exist_ok=True)

        for q_idx in range(50):  # 最多 50 题
            elements = adb.dump_ui()
            # 找当前进度
            progress = ""
            question_text = ""
            for e in elements:
                t = e.text or ""
                if re.match(r'^\d+/\d+$', t.strip()):
                    progress = t
                if ('听' in t or '看' in t or '选' in t or '读' in t or '写' in t or '听音' in t) and len(t) > 5 and len(t) < 80:
                    if not question_text:
                        question_text = t

            # 截图
            shot_path = out_dir / f"q_{q_idx+1:02d}.png"
            sp.run(['adb', '-s', config.device.serial, 'shell', 'screencap', '-p', '/sdcard/_q.png'])
            sp.run(['adb', '-s', config.device.serial, 'pull', '/sdcard/_q.png', str(shot_path)])
            sp.run(['adb', '-s', config.device.serial, 'shell', 'rm', '/sdcard/_q.png'])

            # 检测题目类型
            question_type = "未知"
            if any('听录音' in e.text or '🔊' in e.text for e in elements):
                question_type = "听力题"
            elif any('A.' in e.text or 'B.' in e.text or 'C.' in e.text for e in elements):
                question_type = "选择题"
            elif any('读' in e.text and '单词' in e.text for e in elements):
                question_type = "朗读题"
            elif any('写' in e.text and ('单词' in e.text or '字母' in e.text) for e in elements):
                question_type = "拼写题"

            has_image = any(e.text in ['A', 'B', 'C', 'D'] and e.clickable for e in elements)

            report["questions"].append({
                "idx": q_idx + 1,
                "progress": progress,
                "text": question_text,
                "type": question_type,
                "screenshot": str(shot_path.name),
            })

            log_msg(f"题 {q_idx+1}: {progress} | {question_type} | {question_text[:40]}", "info")

            # 检查是否有"下一题"按钮
            has_next = any('下一' in e.text or '提交' in e.text for e in elements)
            if not has_next:
                # 直接看截图/UI找下一题按钮
                # 通常右下角有"下一题"按钮
                for e in elements:
                    if e.clickable and e.text:
                        # 猜的"下一题"按钮位置
                        pass

            # 假设"下一题"按钮在右下角 (约 950, 1700~1900)
            adb.tap(960, 1850)
            time.sleep(2)

            # 检查是否还在题目页 (有 X/40)
            elements_after = adb.dump_ui()
            on_question = any(re.match(r'^\d+/\d+$', (e.text or '').strip()) for e in elements_after)
            if not on_question:
                log_msg(f"  题目已结束 (q_idx={q_idx+1})", "info")
                break

        # 保存报告
        report_path = PROJECT_ROOT / "outputs" / "questions" / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        log_msg(f"✅ 巡检完成: 共 {len(report['questions'])} 题", "success")
        log_msg(f"报告: {report_path}", "info")

    except Exception as e:
        log_msg(f"❌ 巡检失败: {e}", "error")
        import traceback
        traceback.print_exc()
    finally:
        set_done()


# ============================================================
# Flask 路由
# ============================================================

@app.route("/")
def index():
    """前端页面"""
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """设备状态 + 任务状态"""
    config = load_config()
    device_ok = False
    try:
        r = sp.run(["adb", "-s", config.device.serial, "get-state"],
                   capture_output=True, text=True, timeout=5,
                   encoding="utf-8", errors="replace")
        device_ok = r.returncode == 0 and "device" in r.stdout.lower()
    except Exception:
        pass

    return jsonify({
        "device_connected": device_ok,
        "device_serial": config.device.serial,
        "current_version": _get_current_version_from_config(),
        "task_status": task_status,
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    """触发自动登录"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_login_task, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "login"})


@app.route("/api/versions", methods=["GET", "POST"])
def api_versions():
    """检测可用版本"""
    if request.method == "GET":
        # 返回已缓存的版本列表
        versions_file = PROJECT_ROOT / "outputs" / "web" / "versions.json"
        if versions_file.exists():
            with open(versions_file, "r", encoding="utf-8") as f:
                versions = json.load(f)
            return jsonify({"versions": versions})
        return jsonify({"versions": [], "msg": "尚未检测，请先 POST /api/versions 触发检测"})

    # POST: 触发版本检测
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_version_detect_task, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "version_detect"})


@app.route("/api/version-grades")
def api_version_grades():
    """返回版本→年级映射表（已扫描的缓存数据）"""
    grades_file = PROJECT_ROOT / "outputs" / "web" / "all_grades.json"
    if grades_file.exists():
        with open(grades_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({"error": "尚未扫描年级数据，请先运行 grade_scanner.py"}), 404


@app.route("/api/version-grades/scan", methods=["POST"])
def api_scan_grades():
    """触发全版本年级扫描（慢，约3分钟）"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_grade_scan_task, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/run-full", methods=["POST"])
def api_run_full():
    """一键全流程运行：登录 → 切换版本 → 选年级 → 测模块"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供参数"}), 400

    version = data.get("version", "")
    grade = data.get("grade", "")
    modules = data.get("modules", [])

    if not version:
        return jsonify({"error": "请选择版本"}), 400
    if not modules:
        return jsonify({"error": "请选择至少一个模块"}), 400

    t = threading.Thread(target=run_full_task, args=(version, grade, modules), daemon=True)
    t.start()
    return jsonify({
        "status": "started",
        "task": "full",
        "version": version,
        "grade": grade,
        "modules": modules,
    })


@app.route("/api/inspect-questions", methods=["POST"])
def api_inspect_questions():
    """AI检测单元自检题目巡检：一题一截图+识别"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_inspect_questions_task, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "inspect_questions"})


@app.route("/api/questions/report")
def api_questions_report():
    """获取最近一次巡检报告"""
    report_path = PROJECT_ROOT / "outputs" / "questions" / "report.json"
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"questions": [], "msg": "尚未巡检"})


# ============================================================
# 四步检查 API
# ============================================================

_inspect_engine = None
_current_screenshot = ""

def get_inspect_engine():
    global _inspect_engine
    if _inspect_engine is None:
        _inspect_engine = InspectionEngine(adb_controller=get_adb())
    return _inspect_engine


@app.route("/api/check/step", methods=["POST"])
def api_check_step():
    """执行一步检查 (check=1/2/3/4)"""
    data = request.get_json() or {}
    check_num = data.get("check", 1)

    engine = get_inspect_engine()
    screenshot = _current_screenshot or "outputs/screenshots/q_current.png"

    # 截图当前题目
    adb = get_adb()
    adb.screenshot("q_current.png")
    screenshot = str(PROJECT_ROOT / "outputs" / "screenshots" / "q_current.png")

    result = None
    if check_num == 1:
        result = engine.check_1_stem(screenshot)
    elif check_num == 2:
        result = engine.check_2_content(screenshot)
    elif check_num == 3:
        result = engine.check_3_image(screenshot)
    elif check_num == 4:
        result = engine.check_4_answer(screenshot)

    if result is None:
        return jsonify({"error": f"无效的检查编号: {check_num}"}), 400

    return jsonify({
        "check": check_num,
        "name": result.name,
        "passed": result.passed,
        "actual": result.actual_text[:80],
        "similarity": round(result.similarity, 3),
        "details": result.details,
        "error": result.error,
    })


@app.route("/api/check/full", methods=["POST"])
def api_check_full():
    """执行全部四项检查"""
    engine = get_inspect_engine()
    adb = get_adb()
    adb.screenshot("q_current.png")
    screenshot = str(PROJECT_ROOT / "outputs" / "screenshots" / "q_current.png")

    report = engine.run_full_check(screenshot)
    return jsonify(engine.to_dict(report))


# ============================================================
# 听力专项 专属API — 与CLI脚本一致的工作流
# ============================================================

@app.route("/api/inspect/listening-run", methods=["POST"])
def api_inspect_listening_run():
    """
    听力专项自动巡检 (与CLI脚本 inspect_u6.py 行为一致)
    
    请求参数:
        version: "新湘鲁六上" / "新湘鲁五上" / ...
        unit: 6 (单元号)
        stage: "基础巩固" / "综合进阶" / "难点突破"
        docx: 脚本文件名 (已在uploads目录的)
    """
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    data = request.get_json() or {}
    version_label = data.get("version", "新湘鲁六上")
    unit = data.get("unit", 6)
    stage = data.get("stage", "基础巩固")
    docx_file = data.get("docx", "")

    # 启动线程
    t = threading.Thread(
        target=run_listening_inspect,
        args=(version_label, unit, stage, docx_file),
        daemon=True,
    )
    t.start()
    return jsonify({
        "status": "started",
        "task": "listening_inspect",
        "params": {"version": version_label, "unit": unit, "stage": stage},
    })


def run_listening_inspect(version_label: str, unit: int, stage: str, docx_file: str):
    """
    听力专项巡检主循环 (完全复用 inspect_u6.py 的逻辑)
    """
    try:
        set_running("listening_inspect")
        config = load_config()
        adb = get_adb()

        log_msg(f"🚀 听力专项巡检: {version_label} Unit{unit} {stage}")

        # 1. 启动APP + 导航到首页
        log_msg("启动APP")
        adb.launch_app(config.app.package)
        time.sleep(4)

        # 2. 关闭广告 (不用固定坐标, 用UI识别)
        log_msg("关闭广告")
        for _ in range(3):
            elements = adb.dump_ui(retries=1)
            found_close = False
            for e in elements:
                t = (e.text or '').strip()
                # 各种关闭按钮
                if t in ['关闭', '关闭广告', '×', 'X', 'Close', '跳过', '忽略']:
                    adb.tap(e.center[0], e.center[1])
                    log_msg(f"  关闭广告: '{t}' at {e.center}")
                    found_close = True
                    break
                # resource-id 包含 close/cancel
                if 'close' in e.resource_id.lower() or 'cancel' in e.resource_id.lower():
                    adb.tap(e.center[0], e.center[1])
                    found_close = True
                    break
            if not found_close:
                # 首次兜底: 点屏幕中部(常见广告关闭位置)
                adb.tap(540, 1800)
                time.sleep(0.5)
                adb.tap(540, 800)
            time.sleep(1)

        # 3. 确保在英语tab + 检查是否跑到了"消息"页
        adb.tap(108, 2233)
        time.sleep(1)
        # 检查当前页面 - 如果看到"消息"标题, 按返回
        elements = adb.dump_ui()
        if any('消息' in (e.text or '') and e.center[1] < 300 for e in elements):
            log_msg("⚠ 进入了消息页, 按返回", "warning")
            adb.press_back()
            time.sleep(2)
            adb.tap(108, 2233)  # 重新点英语tab
            time.sleep(1)

        # 4. 导航到专项突破
        log_msg("导航到专项突破")
        found = False
        for attempt in range(3):
            elements = adb.dump_ui()
            for e in elements:
                if e.text and '专项突破' in e.text:
                    # 只在有效区域点击 (排除顶部导航栏和底部Tab)
                    if 400 < e.center[1] < 2000:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点'专项突破' at {e.center}")
                        found = True
                        break
            if found:
                break
            # 没找到就向下滚动一点
            adb.swipe(540, 1500, 540, 1000, 300)
            time.sleep(1)
        if not found:
            log_msg("  兜底: 点(414, 1700)", "warning")
            adb.tap(414, 1700)
        time.sleep(3)

        # 5. 反复滚动找"听力专项"
        log_msg("寻找听力专项")
        found_listening = False
        for scroll_i in range(10):
            elements = adb.dump_ui()
            for e in elements:
                if e.text and '听力专项' in (e.text or ''):
                    cx, cy = e.center
                    # 验证点击区域在屏内
                    if 200 < cy < 2200 and cx > 50 and cx < 1030:
                        log_msg(f"  发现'听力专项' at {e.center}")
                        adb.tap(cx, cy)
                        found_listening = True
                        break
            if found_listening:
                break
            # 向下滚动
            adb.swipe(540, 1600, 540, 600, 500)
            time.sleep(1)
        time.sleep(3)

        # 6. 选择对应版本年级 (五上/六上等)
        log_msg(f"选择版本: {version_label}")
        time.sleep(2)
        elements = adb.dump_ui()
        # 检查是否跑到消息页/错误页
        if any('消息' in (e.text or '') and e.center[1] < 200 for e in elements):
            adb.press_back()
            time.sleep(2)
            elements = adb.dump_ui()
        grade_keywords = {"五上": "五上", "五下": "五下", "六上": "六上", "六下": "六下"}
        target_kw = ""
        for k, v in grade_keywords.items():
            if k in version_label:
                target_kw = v
                break
        if target_kw:
            found_grade = False
            for e in elements:
                if e.text and target_kw in (e.text or ''):
                    cx, cy = e.center
                    if 200 < cy < 2200:
                        adb.tap(cx, cy)
                        log_msg(f"  选中 {target_kw} at ({cx},{cy})")
                        found_grade = True
                        break
            if not found_grade:
                log_msg(f"  ⚠ 未找到 {target_kw}, 尝试兜底", "warning")
                adb.tap(540, 1200)
        time.sleep(3)

        # 7. 选择Unit
        log_msg(f"选择 Unit {unit}")
        elements = adb.dump_ui()
        found_unit = False
        for e in elements:
            if e.text and f"Unit {unit}" in (e.text or ''):
                cx, cy = e.center
                if 200 < cy < 2200:
                    adb.tap(cx, cy)
                    log_msg(f"  Unit {unit} at ({cx},{cy})")
                    found_unit = True
                    break
        if not found_unit:
            log_msg(f"  ⚠ 未找到 Unit {unit}, 尝试兜底", "warning")
            adb.tap(540, 1400)
        time.sleep(3)

        # 8. 选择阶段 (基础巩固/综合进阶/难点突破)
        log_msg(f"选择阶段: {stage}")
        elements = adb.dump_ui()
        for e in elements:
            if e.text and stage == (e.text or '').strip():
                adb.tap(e.center[0], e.center[1])
                log_msg(f"  {stage} at {e.center}")
                break
        time.sleep(3)

        # 9. 开始答题 → 轮流尝试 "开始答题"/"去答题"→ 关弹窗 → 等待考题加载
        log_msg("开始答题")
        for attempt in range(5):
            elements = adb.dump_ui()
            # 先检查是否已经在考题页
            in_question = any(re.match(r'^\d+/\d+$', (e.text or "").strip()) for e in elements)
            if in_question:
                log_msg("  已在考题页!", "success")
                break
            # 找"开始答题"/"去答题"按钮
            found_btn = False
            for e in elements:
                t = (e.text or '').strip()
                if t in ['开始答题', '去答题', '开始', 'Start']:
                    if e.clickable and e.center[1] < 2000:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点'{t}' at {e.center}")
                        found_btn = True
                        break
            if not found_btn:
                # 可能已经进入题目但还没加载, 或弹窗挡住了
                # 尝试点屏幕底部中间 (有些APP的确认在底部)
                adb.tap(540, 2100)
                # 关可能存在的弹窗
                adb.tap(540, 1800)
            time.sleep(2)

        # 再多等一会儿, 确保题目渲染完成
        time.sleep(2)

        # 10. 逐题巡检循环
        log_msg(f"逐题巡检开始: 脚本={docx_file or '无'}")
        last_q = 0
        questions_reviewed = []
        # 记录是否遇到结果页, 增加"下一题"按钮点击
        
        # 加载脚本数据 (用于LLM审查)
        from src.review_agent import ReviewAgent, ReviewConfig
        from src.parse_yingyubao_docx import parse

        agent = None
        docx_path = ""
        if docx_file:
            docx_path = str(UPLOAD_DIR / docx_file)
            if Path(docx_path).exists():
                cfg = ReviewConfig(docx_path=docx_path, unit=unit, stage=stage,
                                   screenshot_dir=str(PROJECT_ROOT / "screenshots"), verbose=False)
                agent = ReviewAgent(cfg)
                log_msg(f"  脚本已加载: {docx_file} (共{len(agent.script_questions)}题)", "success")
            else:
                log_msg(f"  ⚠ 脚本不存在: {docx_path}", "warning")

        for loop in range(80):
            if not task_status["running"]:
                log_msg("任务被手动停止", "warning")
                break

            elements = adb.dump_ui(retries=2)
            all_texts = [(e.text or '').strip() for e in elements]

            # ====== 检测是否在结果页 (有"正确答案"文本) ======
            if any('正确答案' in t for t in all_texts):
                log_msg("[结果页] 刚答完一题, 找'下一题'", "info")
                found_next = False
                for e in elements:
                    t = (e.text or '').strip()
                    if t in ['下一题', '完成', '继续', 'Next']:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  点'{t}' at {e.center}")
                        found_next = True
                        break
                if not found_next:
                    adb.tap(540, 2100)  # 底部兜底
                time.sleep(1.5)
                continue

            # ====== 读题号 ======
            cur = None
            total_q = 0
            for e in elements:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    cur = int(m.group(1))
                    total_q = int(m.group(2))
                    break
            if not cur:
                log_msg("不在考题页,结束", "warning")
                break
            if cur == last_q:
                time.sleep(0.3)
                continue
            last_q = cur

            # 截图
            shot_name = f"q{cur:02d}.png"
            adb.screenshot(shot_name)
            shot_path = str(PROJECT_ROOT / "screenshots" / shot_name)
            log_msg(f"Q{cur:02d}", "success")
            update_progress(cur, total_q, f"Q{cur}")

            # 用ReviewAgent做四维审查 (如果脚本已加载)
            review_result = None
            if agent:
                try:
                    # 找对应脚本题目
                    matching_qs = [q for q in agent.script_questions if q.global_idx == cur]
                    if matching_qs:
                        script_q = matching_qs[0]
                        r = agent._review_one(script_q, shot_path)
                        review_result = {
                            "stem": "✅" if r.stem_check.passed else "❌",
                            "content": "✅" if r.content_check.passed else "❌",
                            "image": "✅" if r.image_check.passed else "❌",
                            "answer": "✅" if r.answer_check.passed else "❌",
                            "score": r.overall_score,
                        }
                        log_msg(f"  审查: 题干{review_result['stem']} 内容{review_result['content']} 配图{review_result['image']} 作答{review_result['answer']} 得分{review_result['score']:.2f}")
                        
                        # 自动加入反馈
                        from src.feedback_loop import FeedbackSample
                        agent.feedback.add(FeedbackSample(
                            question_id=f"{version_label}-U{unit}-Q{cur:02d}",
                            check_dimension="all",
                            human_judgment="通过" if r.overall_passed else "不通过",
                            ai_judgment="通过" if r.overall_passed else "不通过",
                            ai_reason=r.content_check.details[0] if r.content_check.details else "",
                            question_type=script_q.type_2,
                            screenshot=shot_name,
                        ))
                except Exception as e:
                    log_msg(f"  审查异常: {e}", "warning")

            questions_reviewed.append({
                "idx": cur, "screenshot": shot_name, "review": review_result
            })

            # 点击选项
            found_option = False
            for e in elements:
                if e.clickable and 400 < e.bounds[1] < 2000 and (e.bounds[2]-e.bounds[0]) > 100:
                    # 优先选中间偏左的选项区域
                    if e.center[0] < 150: continue  # 太左可能是返回键
                    adb.tap(e.center[0], e.center[1])
                    found_option = True
                    break
            if not found_option:
                # 兜底: 点屏幕中央
                adb.tap(540, 800)
            time.sleep(1.5)

            # 找"检查"按钮, 点它
            found_check = False
            for _ in range(3):
                new_elems = adb.dump_ui()
                for e in new_elems:
                    t = (e.text or '').strip()
                    if t in ['检查', 'Check', '提交', '下一题', '完成']:
                        adb.tap(e.center[0], e.center[1])
                        log_msg(f"  '检查'点中 ({e.center[0]},{e.center[1]})")
                        found_check = True
                        break
                if found_check:
                    break
                adb.tap(540, 2100)
                time.sleep(0.5)
            time.sleep(1.5)

            # 完成
            if cur >= total_q:
                log_msg(f"✅ 全部 {total_q} 题完成!", "success")
                break

        # 保存审查结果
        if agent and questions_reviewed:
            agent.export_report(str(PROJECT_ROOT / "outputs" / f"review_{docx_file.replace('.docx','')}.md"))
            agent.export_json(str(PROJECT_ROOT / "outputs" / f"review_{docx_file.replace('.docx','')}.json"))

        set_done()
        log_msg(f"✅ 听力专项巡检完成! {len(questions_reviewed)}题", "success")

    except Exception as e:
        import traceback
        log_msg(f"❌ 巡检失败: {e}", "error")
        log_msg(traceback.format_exc(), "error")
        set_done()


@app.route("/api/inspect/run", methods=["POST"])
def api_inspect_run():
    """启动逐题巡检 (任务版)"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409
    t = threading.Thread(target=run_inspect_loop, daemon=True)
    t.start()
    return jsonify({"status": "started", "task": "inspect_loop"})


@app.route("/api/modules")
def api_modules():
    """获取可用模块列表"""
    return jsonify({
        "教材精学": {
            "课本点读(左)": (203, 1191),
            "课本点读(中)": (540, 1191),
            "巧记单词":     (876, 1191),
            "语音评测":     (203, 1358),
        },
        "专项突破 (可见)": {
            "听课文":    (161, 1792),
            "课文动画":  (414, 1792),
            "基础训练":  (666, 1792),
            "一课一练":  (919, 1792),
            "课文配音":  (161, 2033),
            "口语训练":  (414, 2033),
            "复习回顾":  (666, 2033),
            "全脑记词":  (919, 2033),
        },
        "专项突破 (需滚动)": {
            "单元自检":     (414, 746),
            "单元练习计划": (666, 746),
        },
        "📢 听力专项": {
            "听力专项_五上": (414, 1250),
            "听力专项_五下": (414, 950),
            "听力专项_六上": (414, 1150),
            "听力专项_六下": (414, 1050),
        },
    })


@app.route("/api/grades", methods=["POST"])
def api_grades():
    """检测当前版本的可用年级列表（含新/老教材标记）"""
    if task_status["running"]:
        return jsonify({"error": "已有任务在运行"}), 409

    config = load_config()
    adb = get_adb()

    try:
        # 确保在主页，打开年级选择弹窗
        adb.tap(346, 275)  # 切换器
        time.sleep(3)

        elements = adb.dump_ui()
        if not elements:
            return jsonify({"error": "UI dump失败", "grades": []})

        # 解析年级数据
        grades = []
        seen = set()
        for elem in elements:
            text = elem.text
            if not text:
                continue
            # 检测是否含年级/册文字
            is_book = any(k in text for k in ['年级', '册'])
            is_new_tag = '新教材' in text
            if is_book or is_new_tag:
                if text not in seen:
                    seen.add(text)
                    # 找容器坐标（可点击区域）
                    container = None
                    for ce in elements:
                        if ce.clickable and elem.center[0] >= ce.bounds[0] and elem.center[0] <= ce.bounds[2] \
                                and elem.center[1] >= ce.bounds[1] and elem.center[1] <= ce.bounds[3]:
                            container = list(ce.center)
                            break

                    grades.append({
                        "text": text,
                        "center": list(elem.center),
                        "container": container,
                        "is_new_tag": is_new_tag,
                        "is_book": is_book,
                    })

        # 关闭弹窗
        adb.press_back()
        time.sleep(1)

        # 结构化输出
        book_grades = [g for g in grades if g["is_book"]]
        log_msg(f"✅ 检测到 {len(book_grades)} 个年级选项")

        return jsonify({"grades": grades, "book_grades": book_grades})

    except Exception as e:
        log_msg(f"❌ 年级检测失败: {e}", "error")
        return jsonify({"error": str(e), "grades": []})


@app.route("/api/screenshot/<filename>")
def api_screenshot(filename):
    """获取截图"""
    screenshot_dir = PROJECT_ROOT / "outputs" / "web"
    if (screenshot_dir / filename).exists():
        return send_from_directory(str(screenshot_dir), filename)
    # 也查 outputs/screenshots
    alt_dir = PROJECT_ROOT / "outputs" / "screenshots"
    if (alt_dir / filename).exists():
        return send_from_directory(str(alt_dir), filename)
    return jsonify({"error": "未找到截图"}), 404


@app.route("/api/screenshot/latest")
def api_screenshot_latest():
    """获取最新截图"""
    screenshot_dir = PROJECT_ROOT / "outputs" / "web"
    png_files = sorted(screenshot_dir.glob("*.png"), key=os.path.getmtime, reverse=True)
    if png_files:
        return send_from_directory(str(screenshot_dir), png_files[0].name)
    return jsonify({"error": "无截图"}), 404


@app.route("/api/log")
def api_log():
    """获取日志"""
    return jsonify(task_status["log"])


@app.route("/api/hardware-info")
def api_hardware_info():
    """获取手机信息"""
    config = load_config()
    info = {"serial": config.device.serial, "screen": "1080x2400"}
    try:
        r = sp.run(["adb", "-s", config.device.serial, "shell", "getprop", "ro.product.model"],
                   capture_output=True, text=True, timeout=5,
                   encoding="utf-8", errors="replace")
        if r.returncode == 0:
            info["model"] = r.stdout.strip()
        r2 = sp.run(["adb", "-s", config.device.serial, "shell", "getprop", "ro.product.brand"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace")
        if r2.returncode == 0:
            info["brand"] = r2.stdout.strip()
    except Exception:
        pass
    return jsonify(info)


def _get_current_version_from_config() -> str:
    """从配置文件获取当前版本"""
    # 上次检测到的人教版(PEP)版本
    return "人教版（PEP）（2024审定）"


# ============================================================
# 🔵 审查智能体 路由区 — 脚本上传 + 知识库 + 审查结果
# ============================================================

UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

@app.route("/api/upload-docx", methods=["POST"])
def api_upload_docx():
    """上传 DOCX 脚本文件, 自动导入知识库"""
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".docx"):
        return jsonify({"error": "仅支持 .docx 文件"}), 400
    save_path = UPLOAD_DIR / file.filename
    file.save(str(save_path))
    try:
        from src.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        stats = kb.add_bulk_from_docx(str(save_path))
        return jsonify({
            "success": True, "filename": file.filename,
            "knowledge_stats": {
                "questions_parsed": stats.get("questions", 0),
                "vocab_added": stats.get("vocab", 0),
                "patterns_added": stats.get("patterns", 0),
            },
            "message": f"已导入 {stats.get('questions',0)} 题到知识库",
        })
    except Exception as e:
        return jsonify({"error": f"解析失败: {str(e)}"}), 500


@app.route("/api/upload/list")
def api_upload_list():
    """列出已上传的 DOCX 文件"""
    files = []
    for f in sorted(UPLOAD_DIR.glob("*.docx")):
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return jsonify({"files": files})


@app.route("/api/knowledge/status")
def api_knowledge_status():
    """知识库状态"""
    try:
        from src.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        summary = kb.summary()
        total_entries = sum(s["vocab"] + s["patterns"] for s in summary)
        return jsonify({
            "total_entries": total_entries,
            "grades": [s["key"] for s in summary],
            "detail": summary,
        })
    except Exception as e:
        return jsonify({"total_entries": 0, "error": str(e)})


_review_results = {}

@app.route("/api/review/run", methods=["POST"])
def api_review_run():
    """运行审查智能体"""
    data = request.get_json() or {}
    docx_file = data.get("docx", "")
    unit = data.get("unit", 0)
    stage = data.get("stage", "")
    docx_path = ""
    if docx_file:
        docx_path = str(UPLOAD_DIR / docx_file)
        if not Path(docx_path).exists():
            return jsonify({"error": f"文件 {docx_file} 不存在"}), 404
    else:
        files = sorted(UPLOAD_DIR.glob("*.docx"), key=os.path.getmtime, reverse=True)
        if files: docx_path = str(files[0])
        else: return jsonify({"error": "未找到脚本文件"}), 404
    try:
        from src.review_agent import ReviewAgent, ReviewConfig
        cfg = ReviewConfig(docx_path=docx_path, unit=unit, stage=stage,
                           screenshot_dir=str(PROJECT_ROOT / "screenshots"), verbose=False)
        agent = ReviewAgent(cfg)
        results = agent.review()
        global _review_results
        _review_results = {
            "timestamp": datetime.now().isoformat(),
            "docx": Path(docx_path).name,
            "total": len(results),
            "passed": sum(1 for r in results if r.overall_passed),
            "avg_score": round(sum(r.overall_score for r in results) / len(results), 2) if results else 0,
            "results": [r.to_dict() for r in results],
        }
        return jsonify(_review_results)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/review/results")
def api_review_results():
    return jsonify(_review_results or {"results": [], "total": 0})


@app.route("/api/review/export", methods=["POST"])
def api_review_export():
    try:
        py_content = ""
        if _review_results:
            r = _review_results
            py_content = f"# 英语宝审查报告\n\n生成时间: {r['timestamp']}\n脚本: {r['docx']}\n"
            py_content += f"总题数: {r['total']} | 通过: {r['passed']}/{r['total']} | 综合得分: {r['avg_score']}\n\n"
            py_content += "| # | 题型 | 题干 | 内容 | 配图 | 作答 | 总评 |\n|---|---|---|---|---|---|---|\n"
            for rr in r.get("results", []):
                def ic(p): return "Y" if p else "N"
                py_content += f"| Q{rr['idx']:02d} | {rr['type'][:10]} | {ic(rr['stem']['passed'])} | {ic(rr['content']['passed'])} | {ic(rr['image']['passed'])} | {ic(rr['answer']['passed'])} | {'PASS' if rr['overall_passed'] else 'FAIL'} ({rr['overall_score']}) |\n"
        return jsonify({"content": py_content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  英语宝模块检测 - Web 控制面板")
    print("=" * 50)
    print(f"  项目路径: {PROJECT_ROOT}")
    print(f"  启动: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
