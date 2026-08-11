"""
检测模块（engine_detector.py）
==============================
单个模块的完整检测流程：
  导航 → 空态检测 → 答题循环（选答案→检查→下一题）→ 返回

已验证通过的流程（2026-07-31 湘少版六年级上册）：
  听力专项：15题 mixed模式（ABC + TF混排）
  单词���写：15题 dictation模式（无ABC选项，纯听写）
  听力训练：暂无数据（空态检测）
"""

import os, time
from engine_config import ANSWER_OPTIONS
from engine_navigator import navigate_to_module, enter_unit_and_start, back_to_home, handle_popup, is_on_home

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots", "engine")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def check_empty(d, config: dict) -> bool:
    """检查空态（暂无数据/模块无内容）"""
    indicator = config.get("finish_indicator", "")
    if indicator == "暂无数据":
        for _ in range(8):
            if d(text="暂无数据").exists(timeout=1.5):
                return True
            time.sleep(1)
    return d(text="暂无数据").exists(timeout=2)


def answer_one(d, config: dict):
    """答一道题：选选项 → 点检查"""
    mode = config.get("answer_mode", "mixed")

    if mode == "dictation":
        # 听写模式：无ABC选项，跳过选答案步骤
        return

    # 选选项（A/B/C/T/F）
    for opt in ANSWER_OPTIONS:
        try:
            if d(text=opt).exists(timeout=0.6):
                d(text=opt).click()
                time.sleep(0.8)
                break
        except Exception:
            pass

    # 点检查按钮
    for btn in ("检查", "提交"):
        try:
            if d(text=btn).exists(timeout=1.5):
                d(text=btn).click()
                time.sleep(1.2)
                break
        except Exception:
            pass


def go_next(d, config: dict) -> bool:
    """点下一题/继续，返回是否成功跳转"""
    # 先处理弹窗
    handle_popup(d)

    for btn in config.get("next_button", ["下一题"]):
        try:
            if d(text=btn).exists(timeout=1.5):
                d(text=btn).click()
                return True
        except Exception:
            pass

    # 尝试"完成/退出"
    for btn in ("完成", "结束", "退出练习"):
        try:
            if d(text=btn).exists(timeout=1):
                d(text=btn).click()
                return True
        except Exception:
            pass
    return False


def detect_module(d, module_name: str, config: dict) -> dict:
    """
    检测单个模块。

    返回: {"module": str, "total": int, "status": "成功"|"失败", "shots": []}
    """
    result = {"module": module_name, "total": 0, "status": "失败", "shots": []}
    print(f"\n{'='*45}")
    print(f"🔍 开始检测: {module_name}")
    print(f"{'='*45}")

    # 1. 进入模块
    entry = config.get("entry_text", module_name)
    if not navigate_to_module(d, entry):
        print(f"  ❌ 进模块失败")
        return result

    # 2. 进入单元 + 开始按钮
    enter_unit_and_start(d, config)
    time.sleep(2)

    # 3. 空态检测
    if check_empty(d, config):
        print(f"  ⚠ 模块 [{module_name}] 暂无数据")
        result["status"] = "成功"
        return result

    # 4. 答题循环
    question_num = 1
    while question_num <= 20:
        # 完成判定
        finish = config.get("finish_indicator", "")
        if finish and finish != "暂无数据":
            if d(text=finish).exists(timeout=1):
                break

        # 截图
        shot = os.path.join(OUTPUT_DIR, f"{module_name}_Q{question_num}.png")
        try:
            d.screenshot(shot)
            result["shots"].append(shot)
            print(f"  📸 第 {question_num} 题")
        except Exception as e:
            print(f"  ⚠ 截图失败 {e}")

        # 答题
        answer_one(d, config)
        time.sleep(0.5)

        # 下一题
        if go_next(d, config):
            question_num += 1
            time.sleep(1)
        else:
            # 可能是最后一题，检查是否回到单元页
            if d(text=finish).exists(timeout=2):
                break
            question_num += 1  # 乐观计数
            time.sleep(1.5)

    result["total"] = question_num - 1 if question_num > 1 else question_num
    result["status"] = "成功"
    print(f"  ✅ {module_name} 检测完成: {result['total']} 题")

    # 5. 返回主页
    back_to_home(d)
    return result
