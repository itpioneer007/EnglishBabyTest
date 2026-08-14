# -*- coding: utf-8 -*-
"""文档专项检查点：需求文档里"机器可判"但当前六维未覆盖的检查项

覆盖文档要求（对应"口语训练检测流程及注意事项.txt" + "E英语宝模块检测智能体需求.docx"）：
  1. check_paper_header  — 试卷首页/单元目录：标题、总分、时量、按钮文字
  2. check_report_page   — 报告页核对：总分 = 各题得分之和、结果图标、题干
  3. check_score_display — 每题分值核对：页面显示的分值是否合理/与脚本一致

实现：截图 + LLM 视觉判断（复用 reviewer_common.LLMClient），结果经 step_log
回传前端（web_server 的 log 回调已注入），并打印到控制台。
"""
import sys
import io
import os
import time

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)                 # 项目根（src 包）
sys.path.insert(0, os.path.join(_PROJ, "scripts"))  # common 包

from src.reviewer_common import LLMClient  # noqa: E402
from common.logger import step_log  # noqa: E402


def _llm():
    """懒加载 LLM 客户端（首次调用初始化，失败返回 None 不阻塞答题）"""
    try:
        return LLMClient.from_config()
    except Exception as e:
        print(f"  ⚠ LLM初始化失败: {e}")
        return None


def _ask(llm, prompt, shot=""):
    """调用 LLM（带截图）；失败返回 None，不抛异常阻塞流程"""
    try:
        if shot:
            return llm.ask(prompt, image_path=shot)
        return llm.ask(prompt)
    except Exception as e:
        print(f"  ⚠ LLM调用失败: {e}")
        return None


def _save_shot(d, tag: str) -> str:
    """截图保存到 screenshots/ 并返回路径（供 LLM 视觉检查）"""
    try:
        import re
        _dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
        os.makedirs(_dir, exist_ok=True)
        fn = f"doc_check_{tag}_{int(time.time())}.png"
        path = os.path.join(_dir, fn)
        for _r in range(2):
            try:
                d.screenshot(path)
                return path
            except OSError:
                time.sleep(0.5)
        return ""
    except Exception:
        return ""


def check_paper_header(d, module_name: str = "", expect_title: str = ""):
    """试卷首页 / 单元目录核对（文档：试卷标题、总分及时量、按钮文字）

    在进入单元、点击"开始答题"之前调用。截图后 LLM 判断：
      - 页面标题/模块名是否正确
      - 是否有异常文字（乱码/截断/错别字）
      - 按钮（开始答题/重新答题/继续答题）是否完整可点
    """
    try:
        shot = _save_shot(d, "header")
        if not shot:
            return None
        llm = _llm()
        if not llm:
            return None
        prompt = (
            "请检查这张英语学习App的试卷首页/单元页截图，逐项判断：\n"
            f"1. 页面标题是否正确？（期望模块: {module_name or '未知'}）\n"
            "2. 标题/文字是否有乱码、截断、错别字？\n"
            "3. 总分/时量/单元信息（如有显示）是否清晰完整？\n"
            "4. 主要按钮（开始答题/重新答题/继续答题）是否完整可见可点击？\n"
            "5. 是否有任何异常（如文字重叠、元素缺失）？\n\n"
            "回答格式: [通过/不通过 | 置信度:0-100] | 理由，逐项列出"
        )
        ans = _ask(llm, prompt, shot)
        passed = bool(ans and "通过" in ans and "不通过" not in ans)
        step_log(
            f"📋 试卷首页检查: {'通过' if passed else '⚠ 发现问题'} | {ans[:200] if ans else 'LLM无返回'}",
            "info" if passed else "warning",
        )
        print(f"    [试卷首页检查] {'✅' if passed else '⚠'}: {(ans or '')[:120]}")
        return passed
    except Exception as e:
        print(f"  ⚠ 试卷首页检查异常: {e}")
        return None


def check_report_page(d, module_name: str = ""):
    """报告页核对（文档：总分=每题得分之和、每大题结果图标与作答一致、题干正确）

    在答题完成、出现"练习报告"页时调用。截图后 LLM 判断总分与各题得分逻辑是否合理。
    """
    try:
        time.sleep(0.8)  # 等报告页渲染稳定
        shot = _save_shot(d, "report")
        if not shot:
            return None
        llm = _llm()
        if not llm:
            return None
        prompt = (
            "请检查这张英语学习App的练习报告页截图，逐项判断：\n"
            f"1. 报告页标题是否正确？（模块: {module_name or '未知'}）\n"
            "2. 总分是否显示？总分与各题/各大题得分之和是否合理一致？\n"
            "3. 每题/每大题的结果图标（对勾/叉号/分数）是否清晰可辨？\n"
            "4. 题目/题干文字是否有乱码、截断、错别字？\n"
            "5. 是否有任何异常（如分数为0但明显答对、文字重叠）？\n\n"
            "回答格式: [通过/不通过 | 置信度:0-100] | 理由，逐项列出"
        )
        ans = _ask(llm, prompt, shot)
        passed = bool(ans and "通过" in ans and "不通过" not in ans)
        step_log(
            f"📊 报告页核对: {'通过' if passed else '⚠ 发现问题'} | {ans[:200] if ans else 'LLM无返回'}",
            "info" if passed else "warning",
        )
        print(f"    [报告页核对] {'✅' if passed else '⚠'}: {(ans or '')[:120]}")
        return passed
    except Exception as e:
        print(f"  ⚠ 报告页核对异常: {e}")
        return None


def check_score_display(d, expect_score: str = ""):
    """每题分值核对（文档：当前大题及当前页面全部小题分值是否正确）

    在每题作答页调用。截图后 LLM 判断页面显示的分值是否正常。
    expect_score: 脚本里已知的分值（如有），用于对照。
    """
    try:
        shot = _save_shot(d, "score")
        if not shot:
            return None
        llm = _llm()
        if not llm:
            return None
        prompt = (
            "请检查这张英语学习App的题目作答页截图：\n"
            f"1. 页面是否显示了本题/本大题的分值？（期望分值: {expect_score or '未知'}）\n"
            "2. 分值数字是否清晰、无乱码/截断/重叠？\n"
            "3. 题干文字是否完整？（判断分值显示位置是否合理）\n\n"
            "回答格式: [通过/不通过 | 置信度:0-100] | 理由"
        )
        ans = _ask(llm, prompt, shot)
        passed = bool(ans and "通过" in ans and "不通过" not in ans)
        step_log(
            f"📏 分值检查: {'通过' if passed else '⚠ 分值异常'} | {ans[:200] if ans else 'LLM无返回'}",
            "info" if passed else "warning",
        )
        return passed
    except Exception as e:
        print(f"  ⚠ 分值检查异常: {e}")
        return None
