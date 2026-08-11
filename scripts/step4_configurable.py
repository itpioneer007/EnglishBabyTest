"""步骤4：可配置模块名"""
import uiautomator2 as u2, time

# ═══════ 改这一行即可切换目标模块 ═══════
TARGET_MODULE = "单元自检"
# ═════════════════════════════════════════

d = u2.connect()
print(f"✅ 设备已连接，目标: {TARGET_MODULE}")

# 回到主页
for _ in range(5):
    d.press("back"); time.sleep(1)
d.app_start("com.dinoenglish.yyb"); time.sleep(5)

# 确认年级
print("🔍 确认「五年级上册」...")
if not d(textContains="五年级上册").exists(timeout=5):
    print("❌ 不在五年级上册"); exit(1)
print("✅ 已确认")

# 查找模块（支持向上滑）
print(f"🔍 查找「{TARGET_MODULE}」...")
for i in range(8):
    if d(text=TARGET_MODULE).exists(timeout=1.5): break
    d.swipe(500,1400,500,400,0.3); time.sleep(1)

if not d(text=TARGET_MODULE).exists(timeout=2):
    print(f"❌ 找不到 {TARGET_MODULE}")
    print("  当前主页模块列表:")
    for e in (d.xpath('//*[@text!=""]').all() or []):
        t = e.text or ""
        if len(t) > 1 and t[0] not in "0123456789%:.国":
            print(f"    {t}")
    exit(1)

d(text=TARGET_MODULE).click(timeout=2)
print(f"✅ 已进入 {TARGET_MODULE}")
time.sleep(4)

# 检查空态
if d(text="暂无数据").exists(timeout=3):
    print(f"⚠ {TARGET_MODULE} 暂无数据，结束")
    exit(0)

# 答题循环
q = 0
next_kw = ("下一题","继续","下一步","Next")
while q < 20:
    # 截图 → 统一命名 test.png（覆盖保存）
    d.screenshot("test.png")
    q += 1
    print(f"📸 已截图第{q}题 → test.png")

    # 下一题
    found = False
    for kw in next_kw:
        if d(text=kw).exists(timeout=2):
            d(text=kw).click()
            print(f"  ⏩ 点击 {kw}")
            time.sleep(2)
            found = True
            break
    if not found:
        for kw in ("完成","提交","结束"):
            if d(text=kw).exists(timeout=1):
                d(text=kw).click()
                print(f"  ⏹ {kw}，结束")
                break
        break

print(f"\n✅ {TARGET_MODULE} 遍历结束，共{q}道题")
