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
    # 专项突破 (深度-需先滚动)
    "单元自检":      (414, 746),  # 滚动后位置
    "单元练习计划":  (666, 746),
}

# 需要先滚动才能看到的模块
DEEP_MODULES = {
    "单元自检",
    "单元练习计划",
    "教材同步题库",
    "听力训练",
    "你听一刻",
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
    """一键全流程：登录 → 切换版本 → 选年级 → 测模块"""


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
