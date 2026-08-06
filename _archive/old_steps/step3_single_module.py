"""步骤3：单项模块遍历（听力训练）"""
import uiautomator2 as u2
import time

d = u2.connect()
print("✅ 设备已连接")

# 回到主页
for _ in range(5):
    d.press("back"); time.sleep(0.4)
d.app_start("com.dinoenglish.yyb"); time.sleep(2.5)

# 确认年级
print("🔍 确认「五年级上册」...")
if not d(textContains="五年级上册").exists(timeout=5):
    print("❌ 不在五年级上册"); exit(1)
print("✅ 已确认")

# 进听力训练
print("🔍 查找「听力训练」...")
for i in range(8):
    if d(text="听力专项").exists(timeout=1.5): break
    d.swipe(500,1400,500,400,0.3); time.sleep(0.4)
if not d(text="听力专项").exists(timeout=2):
    print("❌ 找不到听力训练"); exit(1)
d(text="听力专项").click(timeout=2)
print("✅ 已进入听力训练")
time.sleep(1.6)

# 检查空态
if d(text="暂无数据").exists(timeout=3):
    print("⚠ 听力训练暂无数据，结束")
    exit(0)

# 答题循环
q = 0
next_kw = ("下一题","继续","下一步","Next")
while q < 20:
    # 截图
    d.screenshot(f"hearing_Q{q+1}.png")
    q += 1
    print(f"📸 已截图第{q}题")

    # 下一题
    found = False
    for kw in next_kw:
        if d(text=kw).exists(timeout=2):
            d(text=kw).click()
            print(f"  ⏩ 点击 {kw}")
            time.sleep(0.8)
            found = True
            break
    if not found:
        for kw in ("完成","提交","结束"):
            if d(text=kw).exists(timeout=1):
                d(text=kw).click()
                print(f"  ⏹ {kw}，结束")
                break
        break

print(f"\n✅ 听力训练遍历结束，共{q}道题")
