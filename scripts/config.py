"""
英语宝 · 模块配置表
=================
MODULE_CONFIG 一表管理所有模块差异。
"""
import uiautomator2 as u2
import time

"""
步骤8：批量调度（多模块 + 年级切换 + 回主页 + 汇总）
===================================================
通过 MODULE_CONFIG 一表管理所有模块差异。
TARGET_MODULES 列表配置要跑的模块顺序。
"""

import uiautomator2 as u2
import time

# ═══════════ 模块列表（逗号分隔即可） ═══════════
TARGET_MODULES = ["听力专项"]
# ═══════════ 切换年级/版本 ══════════════════
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"
# ═══════════════════════════════════════════

APP_PACKAGE = "com.dinoenglish.yyb"

# ==================== ① 模块配置表 ====================
MODULE_CONFIG = {
    "听力训练": {
        "entry_text": "听力训练",
        "entry_actions": [],                            # 直接进入，无需额外操作
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续", "下一步"],
        "finish_texts": ["完成", "提交", "结束"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "单元自检": {
        "entry_text": "单元自检",
        "entry_actions": [
            {"type": "click", "text": "去答题", "timeout": 4},
            {"type": "close_ad"},                         # 广告❌关闭（非文字按钮）
            {"type": "close_popup", "text": ["好的，我知道啦~", "我知道了", "确定", "好的"], "timeout": 3},
        ],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续", "下一页"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "单词学习": {
        "entry_text": "单词听写",                       # 界面真实名
        "entry_actions": [
            {"type": "click", "text": "去学习", "timeout": 4},
            {"type": "close_popup", "text": ["开始学习", "我知道了", "好的"], "timeout": 2},
        ],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "听力专项": {
        "entry_text": "听力专项",
        # 单元遍历：逐个点击"去练习"。有 units 时 entry_actions 里的去练习自动跳过
        "units": [1],  # Unit 1-9, 测试先跑 U1
        "entry_actions": [],  # 由 unit loop 点击去练习
        # 子模块：每个单元内，基础巩固→综合进阶→难点突破，中间左滑
        "sub_modules": [
            {"name": "基础巩固", "enter_action": None},
            {"name": "综合进阶", "enter_action": "swipe_left_sub"},
            {"name": "难点突破",  "enter_action": "swipe_left_sub"},
        ],
        "post_entry_actions": [
            {"type": "click", "text": "开始答题", "timeout": 1},
            {"type": "click", "text": "重新答题", "timeout": 1},
        ],
        # 报告页：前N-1个子模块点"继续练习"，最后子模块点左上角回单元列表
        "report_action": {
            "trigger": {"type": "click", "text": "练习报告"},
            "after_report": [
                {"type": "click", "text": "继续练习", "timeout": 3},
            ],
        },
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
        "question_types": {
            "sort": {
                "detect_text": ["排序", "按顺序", "排序题", "给句子排序", "将句子排成", "排成正确的顺序", "按正确顺序排列"],
                "action": "sort_questions",
            },
            "match": {
                "detect_text": ["匹配", "配对", "为人物选择", "选择正确的描述"],
                "action": "match_questions",
            },
        },
    },
    "口语训练": {
        "entry_text": "口语训练",
        "entry_actions": [],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    "单词听写": {
        "entry_text": "单词听写",
        "entry_actions": [],
        "post_entry_actions": [],
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "empty_text": ["暂无数据"],
        "has_pagination": True,
    },
    # ====== 新增模块：复制以下模板，改 key 和 content ======
    # "新模块": {
    #     "entry_text": "主页显示文字",
    #     "entry_actions": [
    #         {"type": "click", "text": "入口按钮", "timeout": 4},
    #         {"type": "close_popup", "text": ["弹窗按钮1", "弹窗按钮2"], "timeout": 3},
    #     ],
    #     "post_entry_actions": [],
    #     "next_button_texts": ["下一题", "继续"],
    #     "finish_texts": ["完成", "提交"],
    #     "empty_text": ["暂无数据"],
    #     "has_pagination": True,
    # },
}

# ==================== ② 通用弹窗（全模块生效） ====================
GLOBAL_POPUPS = ["允许", "取消", "关闭", "以后再说", "暂不", "跳过"]
