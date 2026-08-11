"""步骤5：模块配置表 + 自动适配入口"""
import uiautomator2 as u2, time

# ═══════ 模块配置表 — 改这一行即可切换 ═══════
TARGET_MODULE = "单元自检"
# ═══════════════════════════════════════════════

MODULE_CONFIG = {
    "听力训练": {
        "entry_text": "听力训练",
        "has_entry_button": False,         # 进入后无二次点击，直接答题
        "entry_button_text": "",           # 无需
        "next_button_texts": ["下一题", "继续", "下一步"],
        "finish_texts": ["完成", "提交", "结束"],
        "wait_after_entry": 3,
    },
    "单元自检": {
        "entry_text": "单元自检",
        "has_entry_button": True,          # 进入后要点"去答题"才进答题
        "entry_button_text": "去答题",
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "wait_after_entry": 2,
    },
    "单词学习": {
        "entry_text": "单词听写",          # 界面真实名
        "has_entry_button": True,
        "entry_button_text": "去学习",
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "wait_after_entry": 2,
    },
    "听力专项": {
        "entry_text": "听力专项",
        "has_entry_button": True,          # 需要点"去练习"进单元
        "entry_button_text": "去练习",
        "next_button_texts": ["下一题", "继续"],
        "finish_texts": ["完成", "提交"],
        "wait_after_entry": 2,
    },
    # 新增模块只需加一行，格式如上
}

# ==================== 主流程 ====================
d = u2.connect()
cfg = MODULE_CONFIG.get(TARGET_MODULE)
if not cfg:
    print(f"❌ 未知模块: {TARGET_MODULE}，请加入 MODULE_CONFIG")
    exit(1)
e = cfg["entry_text"]
print(f"✅ 设备已连接，目标: {TARGET_MODULE}（界面: {e}）")

# 回主页 + 启动
for _ in range(5):
    d.press("back"); time.sleep(0.4)
d.app_start("com.dinoenglish.yyb"); time.sleep(2.5)

# 确认年级
print("🔍 确认「五年级上册」...")
if not d(textContains="五年级上册").exists(timeout=5):
    print("❌ 不在五年级上册"); exit(1)
print("✅ 已确认")

# 查找模块（支持向上滑）
print(f"🔍 查找「{e}」...")
for i in range(8):
    if d(text=e).exists(timeout=1.5): break
    d.swipe(500,1400,500,400,0.3); time.sleep(0.4)
if not d(text=e).exists(timeout=2):
    print(f"❌ 找不到 {e}"); exit(1)
d(text=e).click(timeout=2)
print(f"✅ 已进入 {TARGET_MODULE}")
time.sleep(cfg["wait_after_entry"])

# 检查空态
if d(text="暂无数据").exists(timeout=3):
    print(f"⚠ {TARGET_MODULE} 暂无数据，结束"); exit(0)

# 二次入口（如"去练习"）
if cfg["has_entry_button"]:
    btn = cfg["entry_button_text"]
    print(f"🔍 查找入口按钮「{btn}」...")
    if not d(text=btn).exists(timeout=3):
        # 尝试滑动
        for _ in range(3):
            d.swipe(500,1400,500,400,0.3); time.sleep(0.4)
            if d(text=btn).exists(timeout=1.5): break
    if d(text=btn).exists(timeout=2):
        d(text=btn).click()
        print(f"✅ 点击 {btn}")
        time.sleep(1.2)
    else:
        print(f"⚠ 未找到「{btn}」，尝试直接答题")

# 答题循环
q = 0
next_kw = cfg["next_button_texts"]
finish_kw = cfg["finish_texts"]
while q < 20:
    # 完成判定
    for kw in finish_kw:
        if d(text=kw).exists(timeout=0.15):
            d(text=kw).click()
            print(f"  ⏹ {kw}，结束")
            break
    else:
        # 截图
        d.screenshot("test.png")
        q += 1
        print(f"📸 已截图第{q}题 → test.png")

        # 选答案（A/B/C/T/F）
        for opt in ("A","B","C","T","F"):
            if d(text=opt).exists(timeout=0.1):
                d(text=opt).click(); time.sleep(0.3)
                break
        # 检查按钮
        for kw in ("检查","提交"):
            if d(text=kw).exists(timeout=1):
                d(text=kw).click(); time.sleep(0.4)
                break

        # 下一题
        found = False
        for kw in next_kw:
            if d(text=kw).exists(timeout=2):
                d(text=kw).click(); time.sleep(0.8)
                found = True
                break
        if not found:
            for kw in finish_kw:
                if d(text=kw).exists(timeout=1):
                    d(text=kw).click(); break
            break
        continue
    break

print(f"\n✅ {TARGET_MODULE} 遍历结束，共{q}道题")
