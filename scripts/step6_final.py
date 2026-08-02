"""
步骤6：完整模块配置表 + 弹窗处理 + 分页支持
=============================================
通过 MODULE_CONFIG 一表管理所有模块差异：

  entry_text       主页显示文字
  entry_button     二次入口按钮 (None=无需二次点击)
  entry_popups     入口后弹窗 [{text:弹窗按钮, action:click}]
  next_buttons     下一题按钮文字列表
  finish_buttons   完成按钮文字列表
  answer_options   答题选项 ["A","B","C","T","F"]
  check_buttons    检查按钮列表
  empty_text       空态标志文字
  wait_after       等待秒数

新增模块只需加一行 MODULE_CONFIG["新模块"] = {...}
"""

import uiautomator2 as u2, time

# ═══════════ 改这一行即可切换目标模块 ═══════════
TARGET_MODULE = "单元自检"
# ═════════════════════════════════════════════════

MODULE_CONFIG = {
    # ── 听力训练：直接答题，无二次入口 ──
    "听力训练": {
        "entry_text": "听力训练",
        "entry_button": None,              # None=无二次入口
        "entry_popups": [],
        "next_buttons": ["下一题", "继续", "下一步"],
        "finish_buttons": ["完成", "提交", "结束"],
        "answer_options": ["A", "B", "C", "T", "F"],
        "check_buttons": ["检查", "提交"],
        "empty_text": ["暂无数据"],
        "wait_after": 3,
    },
    # ── 单元自检：点"去答题" → 弹窗 → 答题 ──
    "单元自检": {
        "entry_text": "单元自检",
        "entry_button": {"text": "去答题"},   # 二次入口
        "entry_popups": [
            {"text": "好的，我知道啦~", "action": "click"},
            {"text": "我知道了", "action": "click"},
            {"text": "确定", "action": "click"},
            {"text": "关闭", "action": "click"},
        ],
        "next_buttons": ["下一题", "继续", "下一页"],
        "finish_buttons": ["完成", "提交"],
        "answer_options": ["A", "B", "C", "T", "F"],
        "check_buttons": ["检查", "提交"],
        "empty_text": ["暂无数据"],
        "wait_after": 2,
    },
    # ── 单词学习：点"去学习" → 答题 ──
    "单词学习": {
        "entry_text": "单词听写",             # 界面真实名
        "entry_button": {"text": "去学习"},
        "entry_popups": [],
        "next_buttons": ["下一题", "继续"],
        "finish_buttons": ["完成", "提交"],
        "answer_options": ["A", "B", "C", "T", "F"],
        "check_buttons": ["检查", "提交"],
        "empty_text": ["暂无数据"],
        "wait_after": 2,
    },
    # ── 听力专项：点"去练习" → 再"开始答题/重新答题" → 答题 ──
    "听力专项": {
        "entry_text": "听力专项",
        "entry_button": {"text": "去练习"},
        "entry_popups": [],
        "next_buttons": ["下一题", "继续"],
        "finish_buttons": ["完成", "提交"],
        "answer_options": ["A", "B", "C", "T", "F"],
        "check_buttons": ["检查", "提交"],
        "empty_text": ["暂无数据"],
        "wait_after": 2,
    },
}
# ==================== 通用弹窗关闭 ====================
GLOBAL_POPUPS = [
    {"text": "允许", "action": "click"},
    {"text": "取消", "action": "click"},
    {"text": "关闭", "action": "click"},
    {"text": "以后再说", "action": "click"},
    {"text": "暂不", "action": "click"},
    {"text": "跳过", "action": "click"},
]

def dismiss_popups(d, popups):
    """处理弹窗列表，返回是否处理了弹窗"""
    for p in popups:
        try:
            if d(text=p["text"]).exists(timeout=1):
                d(text=p["text"]).click()
                print(f"  🔔 关闭弹窗: {p['text']}")
                time.sleep(1.2)
                return True
        except Exception:
            pass
    return False

# ==================== 主流程 ====================
d = u2.connect()
cfg = MODULE_CONFIG.get(TARGET_MODULE)
if not cfg:
    print(f"❌ 未知模块: {TARGET_MODULE}"); exit(1)
print(f"✅ 目标: {TARGET_MODULE}")

# 回主页 + 启动
for _ in range(5):
    d.press("back"); time.sleep(1)
d.app_start("com.dinoenglish.yyb"); time.sleep(5)

# 确认年级
if not d(textContains="五年级上册").exists(timeout=5):
    print("❌ 不在五年级上册"); exit(1)
print("✅ 已确认 五年级上册")

# 1. 找模块（支持向上滑）
entry = cfg["entry_text"]
print(f"🔍 查找「{entry}」...")
for i in range(8):
    if d(text=entry).exists(timeout=1.5): break
    d.swipe(500,1400,500,400,0.3); time.sleep(1)
if not d(text=entry).exists(timeout=2):
    print(f"❌ 找不到 {entry}"); exit(1)
d(text=entry).click()
print(f"✅ 已进入 {TARGET_MODULE}")
time.sleep(cfg["wait_after"])

# 2. 空态检测
for kw in cfg["empty_text"]:
    if d(text=kw).exists(timeout=2):
        print(f"⚠ {TARGET_MODULE} {kw}，结束"); exit(0)

# 3. 处理全局弹窗
dismiss_popups(d, GLOBAL_POPUPS)

# 4. 二次入口
if cfg["entry_button"]:
    btn = cfg["entry_button"]["text"]
    print(f"🔍 查找入口「{btn}」...")
    if not d(text=btn).exists(timeout=3):
        for _ in range(3):
            d.swipe(500,1400,500,400,0.3); time.sleep(1)
            if d(text=btn).exists(timeout=1.5): break
    if d(text=btn).exists(timeout=2):
        d(text=btn).click()
        print(f"✅ 点击 {btn}")
        time.sleep(3)
        # 处理入口后续弹窗（如"训练规则说明"）
        for _ in range(3):
            if not dismiss_popups(d, cfg["entry_popups"]):
                break
            time.sleep(1)

# 5. 答题循环
q = 0
next_kw = cfg["next_buttons"]
finish_kw = cfg["finish_buttons"]
while q < 20:
    # 全局弹窗
    dismiss_popups(d, GLOBAL_POPUPS)

    # 完成判定
    for kw in finish_kw:
        if d(text=kw).exists(timeout=0.5):
            d(text=kw).click()
            print(f"  ⏹ {kw}，结束"); break
    else:
        # 截图
        d.screenshot("test.png")
        q += 1
        print(f"📸 第{q}题 → test.png")

        # 选答案
        for opt in cfg["answer_options"]:
            try:
                if d(text=opt).exists(timeout=0.3):
                    d(text=opt).click(); time.sleep(0.3)
                    break
            except Exception: pass

        # 检查按钮
        for kw in cfg["check_buttons"]:
            try:
                if d(text=kw).exists(timeout=1):
                    d(text=kw).click(); time.sleep(1)
                    break
            except Exception: pass

        # 下一题
        found = False
        for kw in next_kw:
            try:
                if d(text=kw).exists(timeout=2):
                    d(text=kw).click(); time.sleep(2)
                    found = True
                    break
            except Exception: pass
        if not found:
            for kw in finish_kw:
                try:
                    if d(text=kw).exists(timeout=1):
                        d(text=kw).click(); break
                except Exception: pass
            break
        continue
    break

print(f"\n✅ {TARGET_MODULE} 结束，共{q}道题")
