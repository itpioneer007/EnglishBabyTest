"""
英语宝 APP 元素永久记录 (APP Element Knowledge Base)
=====================================================

用户明确要求：把每个 APP 元素是干什么的、在什么位置，永久记录下来，可复用。

本文件是所有自动化（版本切换、模块遍历、题目检查等）的"地图"。
- 每个元素都有：名称、作用说明、坐标（1080x2400 分辨率下确认）、可靠度。
- 坐标在有变化时由自动化脚本自动回写 / 修正。
- 动态查找优先用 dump_ui/ OCR 的 find_element(text=...)，坐标作为兜底。

分辨率: 1080 x 2400 (小米/主流安卓)
包名: com.dinoenglish.yyb

🟢 重要规则：所有教材版本默认使用 "2024年审定版"（新版本书籍）。
   版本名称统一带 "(2024审定)" 后缀，如 湘少版(2024审定)、人教版(PEP)(2024审定)。
   自动化查找版本时优先匹配 "xxx(2024审定)"，找不到再尝试无后缀。

===== 底部 Tab 导航 =====
- tab_english (英语):     (108, 2233)   — 主学习页（教材精学 + 专项突破）
- tab_me      (我):       (972, 2220)   — 个人中心页

===== "我" 页面内元素 =====
- settings_gear (⚙️设置): (1000, 170)   — 右上角齿轮，进入设置
- 个人信息 行:            find_element(text="个人信息", exact=True)
- 英语所学教材版本 行:     find_element(text="英语所学教材版本", exact=True)  （点右侧箭头进入版本选择）

===== 版本选择页 =====
- 各版本条目:             find_element(text="湘少版五年级上册", exact=True) 等
- 确定/保存按钮:          按页面可见文案动态查找

===== 主学习页（英语 tab）顶部 =====
- grade_selector (年级/版本选择条): (346, 275) — 点击打开"切换课本"弹窗
- 小学Tab:                (144, 182)

===== 年级切换弹窗（"切换课本"）=====
- 年级格子坐标（3列）:
    行1: 一年级上(180,670) 一年级下(540,670) 二年级上(900,670)
    行2: 二年级下(180,1172) 三年级上(540,1172) 三年级下(900,1172)
    行3: 四年级上(180,1674) 四年级下(540,1674) 五年级上(900,1674)

===== 主学习页模块（人教版下确认，其他版本可能位移，需 dump 确认）=====
教材精学:
    - 课本点读(左): (203, 1191)   - 课本点读(中): (540, 1191)
    - 巧记单词:     (876, 1191)   - 语音评测:     (203, 1358)
专项突破:
    - 听课文: (161, 1792)  课文动画: (414, 1792)  基础训练: (666, 1792)  一课一练: (919, 1792)
    - 课文配音: (161, 2033) 口语训练: (414, 2033)  复习回顾: (666, 2033)  全脑记词: (919, 2033)
听力专项（专项突破内）: (919, 1854)

===== 设置页 → 个人信息页（已 USB 验证）=====
- 个人信息 行:           center=(200, 317)   # 整行可点，y=317 命中
- 英语所学教材版本 行:    text="英语所学教材版本" at (315, 1358)  # 右侧箭头 (700, 1358)

===== 版本选择页 → 选版本（已 USB 验证）=====
- 湘少版(2024审定) 卡片: text at (306, 1009)，卡片中部 (300, 700) 可点
- 湘鲁版(2024审定) 卡片: text at (774, 1009)
- 人教版(PEP)(2024审定): text at (306, 1780)  ← 切到这个就成人教版
- 教科版(2024审定):     text at (774, 1780)
（点选后 APP 自动返回上一页，无需确认按钮）

===== 切年级（"切换课本"弹窗，已 USB 验证）=====
- 弹窗入口: 点主学习页顶部年级/版本条 (346, 275)
- 六年级上册: text at (179, 1874)  ← 在第三行第一列
- 其它常用: 六年级下册 (539, 870), 五年级上册, 四年级上/下册, 三年级上/下册
（点选后 APP 自动关闭弹窗并刷新主学习页）

===== 通用 =====
- 关闭广告: (540, 1821)  （启动/返回时可能的弹窗）
- 返回键: adb.press_back()
"""

# ---------------------------------------------------------------------------
# 结构化元素表（程序可读，便于动态查找 + 坐标兜底）
# ---------------------------------------------------------------------------

# 分辨率
SCREEN_W, SCREEN_H = 1080, 2400

# 底部 Tab
TAB_ENGLISH = {"name": "英语tab", "desc": "主学习页：教材精学+专项突破", "coord": (108, 2233), "reliable": "high"}
TAB_ME = {"name": "我tab", "desc": "个人中心页", "coord": (972, 2220), "reliable": "high"}

# 我页面
SETTINGS_GEAR = {"name": "设置齿轮⚙️", "desc": "我页右上角，进入设置", "coord": (1000, 170), "reliable": "high"}
PERSONAL_INFO = {"name": "个人信息", "desc": "设置页内的行，点进个人资料", "text": "个人信息", "reliable": "dynamic"}
TEXTBOOK_VERSION = {"name": "英语所学教材版本", "desc": "设置页内的行，点右侧箭头进入版本选择", "text": "英语所学教材版本", "reliable": "dynamic"}

# 主学习页顶部
GRADE_SELECTOR = {"name": "年级/版本选择条", "desc": "英语tab顶部，点开切换课本弹窗", "coord": (346, 275), "reliable": "high"}

# 关闭广告
CLOSE_AD = {"name": "关闭广告", "desc": "启动/返回时可能弹出的广告，点中间偏下", "coord": (540, 1821), "reliable": "medium"}

# 已知版本名称（用于版本选择页动态查找）
KNOWN_VERSIONS = [
    "人教版(PEP)(2024审定)",
    "湘少版五年级上册",
    "湘少版五年级下册",
    "新湘鲁六年级上册",
    "新湘鲁六年级下册",
    "新湘鲁五年级上册",
    "新湘鲁五年级下册",
]


def find_coord(element: dict) -> tuple:
    """取一个元素记录里的坐标（若有）。"""
    return element.get("coord", (0, 0))


# ---------------------------------------------------------------------------
# 运行时更新：把自动化中最新确认的坐标写回本文件，形成"越用越准"的地图
# ---------------------------------------------------------------------------
import os
import re

_THIS_FILE = os.path.abspath(__file__)


def update_coord(name: str, coord: tuple, desc: str = ""):
    """把确认过的坐标写回本文件对应元素的 coord 字段（in-place 编辑）。"""
    if not os.path.exists(_THIS_FILE):
        return False
    with open(_THIS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        # 匹配 'NAME = {"name": "...", ...}' 这种赋值
        m = re.match(r"^(\w+)\s*=\s*\{", line)
        if m and m.group(1) == name:
            # 找到这个 dict 的结束 '}'
            depth = 0
            block = []
            j = i
            while j < len(lines):
                block.append(lines[j])
                depth += lines[j].count("{") - lines[j].count("}")
                if depth <= 0 and j > i:
                    break
                j += 1
            # 重写这一块，更新 coord
            block_text = "".join(block)
            new_block = re.sub(
                r'"coord":\s*\([^)]*\)',
                f'"coord": {coord}',
                block_text,
                1,
            )
            if desc:
                new_block = re.sub(
                    r'"desc":\s*"[^"]*"',
                    f'"desc": "{desc}"',
                    new_block,
                    1,
                )
            new_lines.append(new_block)
            i = j + 1
            replaced = True
        else:
            new_lines.append(line)
            i += 1

    if replaced:
        with open(_THIS_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"  [地图更新] {name} -> coord={coord}")
    return replaced


if __name__ == "__main__":
    print("英语宝 APP 元素地图已加载")
    print(f"屏幕分辨率: {SCREEN_W}x{SCREEN_H}")
    print(f"底部Tab: 英语{TAB_ENGLISH['coord']} / 我{TAB_ME['coord']}")
    print(f"设置齿轮: {SETTINGS_GEAR['coord']}")
    print(f"年级选择器: {GRADE_SELECTOR['coord']}")
    print(f"已知版本: {KNOWN_VERSIONS}")
