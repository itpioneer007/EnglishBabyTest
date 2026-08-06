"""固定路径操作：五年级上册 → 听力专项"""
import uiautomator2 as u2
import time

d = u2.connect()
print("✅ 设备已连接")

# 1. 启动 App（已在运行则跳过）
d.app_start("com.dinoenglish.yyb")
time.sleep(2.5)
print("🚀 App 已启动")

# 2. 确认已在五年级上册（不点击，仅检测）
print("🔍 确认「五年级上册」...")
if not d(textContains="五年级上册").exists(timeout=5):
    print("  ❌ 不在五年级上册，请先手动切换")
    exit(1)
print("✅ 已确认 五年级上册")

# 3. 向上滑找到听力专项
print("🔍 查找「听力专项」...")
for i in range(8):
    if d(text="听力专项").exists(timeout=1.5):
        break
    d.swipe(500, 1400, 500, 400, duration=0.3)
    time.sleep(0.4)
if not d(text="听力专项").exists(timeout=2):
    print("  ❌ 找不到听力专项")
    exit(1)

d(text="听力专项").click(timeout=2)
print("✅ 已点击 听力专项")
time.sleep(1.2)

# 4. 截图
d.screenshot("fixed_path.png")
print("📸 截图: fixed_path.png")
print("✅ 固定路径完成")
