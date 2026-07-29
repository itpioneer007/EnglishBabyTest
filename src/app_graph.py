"""
英语宝 APP — 全页面导航地图 (Page Graph)
========================================

这个文件是英语宝 APP 的"地图"：定义了 APP 中每个页面的位置、定位方式、导航路径、
可交互元素和退出方式。任何自动化任务（版本切换、年级切换、模块选择、答题遍历）
都基于这张地图来规划路径。

设计原则：
  - 每个页面是一个 PageNode，记录：类型、如何定位、如何进入、如何退出、有什么元素
  - 页面间导航路径由 Graph 计算（BFS 最短路径）
  - 坐标都是 1080x2400 下验证过的，没有验证的标为 `to_verify`
  - 新增页面只需添加一个 PageNode，不影响已有逻辑

========== 页面清单（9 个已知节点） ==========

1. MAIN        — 主学习页（英语 tab）：底部5个tab + 版本年级选择 + 模块网格
2. ME          — "我"页面：顶部个人信息卡 + 中间功能入口
3. SETTINGS    — 设置页：个人信息、账号安全等行
4. PERSONAL    — 个人信息页：教材版本行 + 年级等
5. VERSION_PICK — 版本选择页：4张版本卡片的弹窗页（有返回箭头）
6. GRADE_POPUP — 年级切换弹窗：12个年级格子的 overlay
7. MODULE_LIST — 模块单元列表：如"听力专项"→Unit1-12 + "去练习"按钮
8. QUESTION    — 答题页：单个题目 + 选项 + 检查/下一题按钮
9. RESULT_POPUP — 完成弹窗/下一题确认弹窗（overlay）

========== 页面关系图 ==========

    MAIN ──── tab_me ────→  ME
     │                       │
     │ grade_selector   settings_gear
     ↓                       ↓
 GRADE_POPUP              SETTINGS
     │                       │
     │ tap grade         personal_info
     ↓                       ↓
    MAIN (reload)         PERSONAL
                              │
                         textbook_version
                              ↓
                         VERSION_PICKER
                              │
                         tap version
                              ↓
                         PERSONAL (return)

    MAIN ──── tap_module ────→ MODULE_LIST
     │                            │
     │ press_back            tap 去练习
     ←──────────────────────────  │
                                  ↓
                              QUESTION
                                  │
                            完成/弹窗
                                  ↓
                              RESULT_POPUP
                                  ↓
                              MODULE_LIST (or next question)
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum, auto


# ============================================================
# 页面类型常量
# ============================================================

class PAGE:
    """所有页面类型的常量名"""
    MAIN = "main"                      # 主学习页
    ME = "me"                          # 我页面
    SETTINGS = "settings"             # 设置页
    PERSONAL = "personal"              # 个人信息页
    VERSION_PICKER = "version_picker"  # 版本选择页
    GRADE_POPUP = "grade_popup"        # 年级切换弹窗
    MODULE_LIST = "module_list"        # 模块单元列表
    QUESTION = "question"              # 答题页
    RESULT_POPUP = "result_popup"      # 完成弹窗
    UNKNOWN = "unknown"                # 未知页面


@dataclass
class PageElement:
    """页面上的一个可交互元素"""
    name: str                # 元素标识名（如 "listen_special"）
    description: str         # 作用说明
    coord: tuple = (0, 0)    # 坐标 (已验证)
    text_match: str = ""     # 通过 uiautomator 文本匹配（备选）
    verified: bool = True    # 坐标是否已验证


@dataclass
class PageNode:
    """APP 中的一个页面节点"""
    page_type: str                  # PAGE 常量
    name: str                       # 中文页面名
    description: str = ""           # 页面特征描述

    # --- 定位特征 (用于判断"我是否在这个页面") ---
    detect_texts: list[str] = field(default_factory=list)   # 页面含有的独特文字
    detect_coord: tuple = (0, 0)    # 特征坐标点

    # --- 导航 ---
    parent: str = ""                # 按返回键回到哪个页面
    is_overlay: bool = False        # 是否弹窗/overlay

    # --- 退出方式（不止按返回） ---
    exit_tap: tuple = (0, 0)        # 点这个坐标也能离开（如 tab）
    exit_label: str = ""            # exit_tap 的说明

    # --- 页面上的交互元素 ---
    elements: dict[str, PageElement] = field(default_factory=dict)

    def has_element(self, name: str) -> bool:
        return name in self.elements

    def element_coord(self, name: str) -> Optional[tuple]:
        e = self.elements.get(name)
        return e.coord if e and e.coord != (0, 0) else None


# ============================================================
# 全页面定义
# ============================================================

PAGES = {
    PAGE.MAIN: PageNode(
        page_type=PAGE.MAIN,
        name="主学习页（英语 tab）",
        description="APP 首页，顶部年级版本条 + 教材精学/专项突破模块网格 + 底部5个tab + 轮播广告",
        detect_texts=["教材精学", "专项突破"],
        parent="",                                  # 最外层，无 parent
        elements={
            "grade_selector": PageElement(
                "grade_selector", "顶部年级选择条，点它弹出切换课本", (346, 275)),
            "tab_english": PageElement(
                "tab_english", "底部英语 tab，回到主学习页", (108, 2233)),
            "tab_me": PageElement(
                "tab_me", "底部我 tab", (972, 2220)),
            "section_basic": PageElement(
                "section_basic", "教材精学区域标签(y=1054)", (135, 1054),
                verified=False),
            "section_special": PageElement(
                "section_special", "专项突破区域标签(y=1335)", (135, 1335),
                verified=False),
            # 模块坐标（湘少版五上验证，其它版本可能不同）
            # 教材精学 row1 (y≈1191)
            "kebendianfu": PageElement(
                "kebendianfu", "课本点读", (203, 1191)),
            "qiaojidanci": PageElement(
                "qiaojidanci", "巧记单词", (540, 1191)),
            "yuyinpingce": PageElement(
                "yuyinpingce", "语音评测", (876, 1191)),
            # 专项突破 row1 (y≈1613)
            "tingkewen": PageElement(
                "tingkewen", "听课文", (161, 1613)),
            "kewendonghua": PageElement(
                "kewendonghua", "课文动画", (414, 1613)),
            "kewenpeiyin": PageElement(
                "kewenpeiyin", "课文配音", (666, 1613)),
            "kouyuxunlian": PageElement(
                "kouyuxunlian", "口语训练", (919, 1613)),
            # 专项突破 row2 (y≈1854)
            "fuxihuigu": PageElement(
                "fuxihuigu", "复习回顾", (161, 1854)),
            "quannaocici": PageElement(
                "quannaocici", "全脑记词", (414, 1854)),
            "dancitingxie": PageElement(
                "dancitingxie", "单词听写", (666, 1854)),
            "listen_special": PageElement(
                "listen_special", "听力专项 — 注意图标中心 y=1810", (919, 1810),
                text_match="听力专项"),
            # 专项突破 row3 (y≈2088)
            "yufajiangjie": PageElement(
                "yufajiangjie", "语法讲解", (161, 2088)),
            "zhishiguoguan": PageElement(
                "zhishiguoguan", "知识过关", (414, 2088)),
            "quweilianxi": PageElement(
                "quweilianxi", "趣味练习", (666, 2088)),
            "tinglixunlian": PageElement(
                "tinglixunlian", "听力训练", (919, 1951)),
        },
    ),

    PAGE.ME: PageNode(
        page_type=PAGE.ME,
        name="我页面",
        description="个人中心，顶部头像+信息卡，底部我 tab 高亮",
        detect_texts=["设置", "我的积分", "我的钱包"],
        parent=PAGE.MAIN,                           # 按返回→主学习页
        exit_tap=(108, 2233), exit_label="英语tab回到主学习页",
        elements={
            "settings_gear": PageElement(
                "settings_gear", "右上角⚙️设置齿轮", (1000, 170)),
        },
    ),

    PAGE.SETTINGS: PageNode(
        page_type=PAGE.SETTINGS,
        name="设置页",
        description="账号安全、个人信息、消息设置等行",
        detect_texts=["设置", "个人信息", "账号安全"],
        parent=PAGE.ME,
        elements={
            "personal_info_row": PageElement(
                "personal_info_row", "个人信息行，整行可点", (400, 320)),
            "textbook_version_row": PageElement(
                "textbook_version_row", "英语所学教材版本行",
                text_match="英语所学教材版本"),
        },
    ),

    PAGE.PERSONAL: PageNode(
        page_type=PAGE.PERSONAL,
        name="个人信息页",
        description="姓名、年级、英语所学教材版本等",
        detect_texts=["个人信息", "英语所学教材版本", "年级"],
        parent=PAGE.SETTINGS,
        elements={
            "textbook_version_arrow": PageElement(
                "textbook_version_arrow", "英语所学教材版本行右侧箭头", (700, 1358)),
        },
    ),

    PAGE.VERSION_PICKER: PageNode(
        page_type=PAGE.VERSION_PICKER,
        name="版本选择页",
        description="选择教材版本，4张版本卡片（湘少/湘鲁/人教/教科）",
        detect_texts=["选择教材版本", "英语教材版本"],
        parent=PAGE.PERSONAL,
        is_overlay=False,  # 这是一个有返回箭头的页面，不是弹窗
        elements={
            "xs_version_card": PageElement(
                "xs_version_card", "湘少版(2024审定)卡片", (306, 1009),
                text_match="湘少版(2024审定)"),
            "xl_version_card": PageElement(
                "xl_version_card", "湘鲁版(2024审定)卡片", (774, 1009),
                text_match="湘鲁版(2024审定)"),
            "rj_version_card": PageElement(
                "rj_version_card", "人教版(PEP)(2024审定)卡片", (306, 1780),
                text_match="人教版(PEP)(2024审定)"),
            "jk_version_card": PageElement(
                "jk_version_card", "教科版(2024审定)卡片", (774, 1780),
                text_match="教科版(2024审定)"),
        },
    ),

    PAGE.GRADE_POPUP: PageNode(
        page_type=PAGE.GRADE_POPUP,
        name="切换课本弹窗",
        description="年级选择弹窗，覆盖在主学习页上方，12个年级格子",
        detect_texts=["切换课本"],
        parent=PAGE.MAIN,
        is_overlay=True,
        elements={
            # 年级坐标因版本/布局而异，用 text_match 动态查找
            "grade_grid_header": PageElement(
                "grade_grid_header", "弹窗顶部标题区域", (540, 350),
                verified=False),
        },
    ),

    PAGE.MODULE_LIST: PageNode(
        page_type=PAGE.MODULE_LIST,
        name="模块单元列表",
        description="进入某个模块后，显示 Unit 1-N 及各自的「去练习」按钮",
        detect_texts=["当前版本", "去练习", "练习记录"],
        parent=PAGE.MAIN,
        elements={
            "tab_practice": PageElement(
                "tab_practice", "练习 tab", (402, 385),
                verified=True),
            "tab_test": PageElement(
                "tab_test", "测试 tab", (678, 385),
                verified=True),
            # Unit 的「去练习」按钮通过 text_match="去练习" 动态查找；
            # 每个 Unit 的 y 不同，按需 dump 定位
        },
    ),

    PAGE.QUESTION: PageNode(
        page_type=PAGE.QUESTION,
        name="答题页",
        description="单道题：题目(图/文)、选项ABCD、检查/下一题按钮",
        detect_texts=["检查"],
        parent=PAGE.MODULE_LIST,
        elements={
            "btn_check": PageElement(
                "btn_check", "检查按钮", text_match="检查",
                verified=False),
            "btn_next": PageElement(
                "btn_next", "下一题按钮", text_match="下一题",
                verified=False),
        },
    ),

    PAGE.RESULT_POPUP: PageNode(
        page_type=PAGE.RESULT_POPUP,
        name="完成/结果弹窗",
        description="做完一题或全部完成后的弹窗",
        detect_texts=["下一题", "完成", "正确"],
        parent=PAGE.QUESTION,
        is_overlay=True,
    ),
}


# ============================================================
# 导航图 (PageGraph)
# ============================================================

@dataclass
class NavigationPlan:
    """一次从 A 页面到 B 页面的导航计划"""
    source: str
    target: str
    steps: list[str]     # 每步的文字说明
    success: bool = True
    message: str = ""


class PageGraph:
    """页面导航图，提供页面间路径规划"""

    def __init__(self, adb=None):
        self.pages = PAGES
        self.adb = adb
        self.current_page = ""

        # 前向导航边: (from_page, element, coord, to_page)
        self.forward_edges: list[tuple[str, str, tuple, str]] = [
            (PAGE.MAIN, "tab_me", (972, 2220), PAGE.ME),
            (PAGE.ME, "settings_gear", (1000, 170), PAGE.SETTINGS),
            (PAGE.SETTINGS, "personal_info", (400, 320), PAGE.PERSONAL),
            (PAGE.PERSONAL, "textbook_version", (700, 1358), PAGE.VERSION_PICKER),
            (PAGE.MAIN, "grade_selector", (346, 275), PAGE.GRADE_POPUP),
        ]

    def get(self, page_type: str) -> Optional[PageNode]:
        return self.pages.get(page_type)

    def is_at(self, page_type: str) -> bool:
        """判断是否在某个页面（需要 adb 已连接）"""
        node = self.get(page_type)
        if not node or not self.adb:
            return False
        try:
            elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        except Exception:
            return False

        # MAIN 页面特殊处理：检测底部 tab bar (英语 tab 在 y>2200)
        if page_type == PAGE.MAIN:
            has_english_tab = any(
                (e.text or '').strip() == "英语" and e.center[1] > 2000
                for e in elems
            )
            # 还要避免与 MODULE_LIST 冲突：有"去练习"/"开始答题"/"当前版本"等
            inside_module_marker = any(
                (e.text or '').strip() in ("去练习", "开始答题", "重排答题")
                for e in elems
            ) or any("当前版本" in (e.text or '') for e in elems)
            return has_english_tab and not inside_module_marker

        for e in elems:
            t = (e.text or "").strip()
            for dt in node.detect_texts:
                if dt in t:
                    return True
        return False

    def detect_current_page(self) -> str:
        """检测当前在哪个页面"""
        if not self.adb:
            return PAGE.UNKNOWN
        for pt in [PAGE.QUESTION, PAGE.RESULT_POPUP, PAGE.MODULE_LIST,
                   PAGE.GRADE_POPUP, PAGE.VERSION_PICKER, PAGE.PERSONAL,
                   PAGE.SETTINGS, PAGE.ME, PAGE.MAIN]:
            if self.is_at(pt):
                self.current_page = pt
                return pt
        return PAGE.UNKNOWN

    def path_to(self, target: str) -> list[str]:
        """
        BFS 双向搜索最短路径：向前（tap元素）+ 向后（按返回）。
        返回自然语言步骤列表。
        """
        if self.current_page == target:
            return []

        from collections import deque

        # BFS: (page, path_steps)
        q = deque()
        q.append((self.current_page, []))
        visited = {self.current_page}

        while q:
            cur, path = q.popleft()

            # --- 后向: 按返回---
            cur_node = self.get(cur)
            if cur_node and cur_node.parent and cur_node.parent not in visited:
                parent = cur_node.parent
                new_path = path + [(f"从 [{cur_node.name}] 按返回 → [{parent}]", parent)]
                if parent == target:
                    self.current_page = target
                    return [s for s, _ in new_path]
                visited.add(parent)
                q.append((parent, new_path))

            # --- 前向: tap 元素 ---
            for fp, ename, coord, tp in self.forward_edges:
                if fp == cur and tp not in visited:
                    new_path = path + [(f"点 {ename} @ {coord} → [{self.get(tp).name}]", tp)]
                    if tp == target:
                        self.current_page = target
                        return [s for s, _ in new_path]
                    visited.add(tp)
                    q.append((tp, new_path))

        return [f"⚠ 无法计算从 {self.current_page} → {target} 的路径"]

    def navigate_to(self, target: str) -> bool:
        """
        通过 ADB 实际导航到目标页面（自动双向：前进/后退）。
        返回 True 表示已在目标页。
        """
        if self.current_page == target or self.is_at(target):
            self.current_page = target
            return True
        if not self.adb:
            return False

        target_node = self.get(target)
        if not target_node:
            return False

        # 先退到共同祖先
        for _ in range(8):
            if self.is_at(target):
                self.current_page = target
                return True
            self.adb.press_back()
            time.sleep(1.0)

        # 兜底：在 MAIN 页面尝试 exit_tap
        for _ in range(3):
            if self.is_at(target):
                self.current_page = target
                return True
            cur_node = self.get(self.current_page) or self.get(PAGE.MAIN)
            if cur_node and cur_node.exit_tap != (0, 0):
                x, y = cur_node.exit_tap
                self.adb.tap(x, y)
                time.sleep(2.0)

        self.current_page = target if self.is_at(target) else self.current_page
        return self.current_page == target


# ============================================================
# 模块名 → 坐标 快速查询
# ============================================================

# 已知模块名 → main page 坐标映射 (湘少版2024审定 五年级上册 验证)
# 坐标格式: (x, y_text) — 实际图标中心应在 y_text 上方 50px 左右（避免点到广告或文字下沿）
# 注意：教材精学在 y≈1100 区域，专项突破分多行在 y≈1613 到 2200+

MODULE_NAME_TO_COORD = {
    # ===== 教材精学 (3个) =====
    "课本点读": (203, 1191),
    "巧记单词": (540, 1191),
    "语音评测": (876, 1191),
    # ===== 专项突破 (16+ 个) =====
    # Row 1
    "听课文": (161, 1613),
    "课文动画": (414, 1613),
    "课文配音": (666, 1613),
    "口语训练": (919, 1613),
    # Row 2
    "复习回顾": (161, 1854),
    "全脑记词": (414, 1854),
    "单词听写": (666, 1854),
    "听力专项": (919, 1810),  # 图标中心 (文字y=1854, 但有Bite Tongue广告条在y=1898)
    # Row 3
    "语法讲解": (161, 2088),
    "知识过关": (414, 2088),
    "趣味练习": (666, 2088),
    "听力训练": (919, 1951),
    # Row 4 (需要向下滚动)
    "单元自检": (161, 533),    # 滚后 y
    "单元学习计划": (414, 533),  # 滚后 y
    "乐听一刻": (666, 533),     # 滚后 y
    "教材同步题库": (919, 533),  # 滚后 y
}

# 哪些模块需要先向下滚动才能点到
MODULE_NEEDS_SCROLL = {
    "单元自检", "单元学习计划", "乐听一刻", "教材同步题库",
}

# 不同模块的内页布局类型（关键发现：模块子页不统一！）
# - "tab_practice_test": 有"当前版本"+"练习/测试"tabs+Unit列表+去练习按钮（如听力专项）
# - "unit_list_simple": 直接Unit列表+箭头（如知识过关）
MODULE_INNER_LAYOUT = {
    "听力专项": "tab_practice_test",
    "课本点读": "tab_practice_test",  # 推测
    "巧记单词": "tab_practice_test",  # 推测
    "语音评测": "tab_practice_test",  # 推测
    "听课文": "tab_practice_test",    # 推测
    "课文动画": "tab_practice_test",  # 推测
    "课文配音": "tab_practice_test",  # 推测
    "口语训练": "tab_practice_test",  # 已验证有练习/测试
    "复习回顾": "tab_practice_test",  # 推测
    "全脑记词": "tab_practice_test",  # 推测
    "单词听写": "tab_practice_test",  # 推测
    "听力训练": "tab_practice_test",  # 推测
    "语法讲解": "tab_practice_test",  # 推测
    "趣味练习": "tab_practice_test",  # 推测
    "知识过关": "unit_list_simple",   # 已验证：直接 Unit+箭头
    "单元自检": "unit_list_simple",   # 已验证：直接 Unit+箭头
    "单元学习计划": "unit_list_simple",  # 推测
    "乐听一刻": "unit_list_simple",     # 推测
    "教材同步题库": "unit_list_simple",  # 推测
}


if __name__ == "__main__":
    print("英语宝 APP 页面地图已加载")
    print(f"已录入页面: {len(PAGES)} 个")
    for k, v in PAGES.items():
        elems = [name for name in v.elements]
        print(f"  [{k:20s}] {v.name}  (元素: {', '.join(elems[:4])}{'...' if len(elems)>4 else ''})")
    print(f"\n模块坐标映射: {len(MODULE_NAME_TO_COORD)} 个")
