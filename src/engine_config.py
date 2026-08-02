"""
引擎配置表（engine_config.py）
==============================
只放数据，不放逻辑。所有模块/按钮/版本信息集中管理。
"""

APP_PACKAGE = "com.dinoenglish.yyb"

# ================================================================
# 模块配置 — 一表定义每个模块的入口、按钮、完成标志
# ================================================================
MODULES = {
    "听力专项": {
        "entry_text": "听力专项",          # 主页显示文字
        "next_button": ["下一题", "继续"], # 题间切换（优先级从高到低）
        "finish_indicator": "重新答题",    # 完成/回到单元页标志
        "need_unit": True,                 # 需要点"去练习/开始答题"
        "start_button": ["重新答题"],      # 答题页入口
        "answer_mode": "mixed",            # mixed=ABCTF混合, tf=纯TF判断
    },
    "听力训练": {
        "entry_text": "听力训练",
        "next_button": ["下一题", "继续"],
        "finish_indicator": "暂无数据",    # 湘少版六年级上册暂无数据
        "need_unit": False,
        "start_button": [],
        "answer_mode": "tf",               # TF判断题
    },
    "单词学习": {
        "entry_text": "单词听写",          # 界面真实名
        "next_button": ["下一题", "继续"],
        "finish_indicator": "重新答题",
        "need_unit": True,                 # 需点 Unit 标题
        "start_button": ["我要听写", "再���写一次"],
        "answer_mode": "dictation",        # 听写模式（无ABC选项）
    },
    "听课文": {
        "entry_text": "听课文",
        "next_button": ["下一题", "继续"],
        "finish_indicator": "重新答题",
        "need_unit": False,
        "start_button": [],
        "answer_mode": "mixed",
    },
    "口语训练": {
        "entry_text": "口语训练",
        "next_button": ["下一题", "继续"],
        "finish_indicator": "暂无数据",
        "need_unit": False,
        "start_button": [],
        "answer_mode": "mixed",
    },
    "知识过关": {
        "entry_text": "知识过关",
        "next_button": ["下一题", "继续"],
        "finish_indicator": "暂无数据",
        "need_unit": False,
        "start_button": [],
        "answer_mode": "mixed",
    },
}

# ================================================================
# 模块别名 — 用户说法 → 界面真实名称
# ================================================================
MODULE_ALIAS = {
    "听力": "听力专项",
    "单词": "单词学习", "词汇": "单词学习",
    "课文": "听课文", "阅读": "听课文",
    "口语": "口语训练", "跟读": "口语训练",
    "语法": "语法讲解",
    "过关": "知识过关",
}

# ================================================================
# 已验证的版本切换路径（2026-07-31 湘鲁→湘少，u2纯文字验证）
# ================================================================
VERSION_SWITCH_PATH = [
    # 主页 → "我"tab
    ("tap_text", "我"),
    # 设置页
    ("tap_text_contains", "设"),           # "设置" 或 gear图标
    # 学生资料
    ("tap_text", "学生资料"),
    # 英语所学教材版本
    ("tap_text", "英语所学教材版本"),
    # 选目标版本（如 "湘少版(2024审定)"）
    ("tap_text", "{target_version}"),       # 占位符，运行时替换
    # 返回主页
    ("back", 3),
    # 点版本号
    ("tap_text_contains", "审定"),
    # 选目标年级（如 "六年级上册"）
    ("tap_text", "{target_grade}"),         # 占位符，运行时替换
]

# 常见弹窗关闭按钮
POPUP_BUTTONS = ["允许", "取消", "关闭", "以后再说", "暂不", "知道了", "稍后", "跳过"]

# 答题选项文字（按优先级）
ANSWER_OPTIONS = ["A", "B", "C", "T", "F"]
