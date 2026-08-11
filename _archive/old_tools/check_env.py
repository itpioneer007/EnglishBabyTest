"""环境检查脚本"""
import uiautomator2 as u2

d = u2.connect()
print(f"✅ 设备连接: {d.device_info.get('serial')}")
print(f"📱 分辨率: {d.window_size()}")
print(f"📦 App版本: {d.app_info('com.dinoenglish.yyb').get('versionName', '?')}")

# 前10个可点击元素
els = d.xpath('//*[@clickable="true"]').all()
print(f"\n可点击元素 (共{len(els)}个, 显示前10):")
for e in (els or [])[:10]:
    t = (e.text or "").strip()
    rid = e.attrib.get("resource-id", "").rsplit("/", 1)[-1]
    b = e.attrib.get("bounds", "")
    print(f"  [{rid}] text='{t}' bounds={b}")

d.screenshot("env_check.png")
print("\n📸 截图已保存: env_check.png")
print("✅ 环境正常")
