"""设备管理：动态获取/选择 adb 设备序列号

解决多设备场景：队友手机占用了默认连接，导致本机设备离线。

核心机制：
- 设置 os.environ['ANDROID_SERIAL'] = 序列号
- uiautomator2 的 u2.connect() 原生读取 ANDROID_SERIAL → 所有模块自动连对设备，无需改模块代码
"""
import os


def list_devices():
    """返回所有已连接的 adb 设备: [{'serial': 'xxx', 'state': 'device'}]"""
    try:
        from adbutils import adb
        return [{"serial": d.serial, "state": "device"} for d in adb.device_list()]
    except Exception:
        return []


def get_serial():
    """当前选中的设备序列号（环境变量，空=默认）"""
    return os.environ.get("ANDROID_SERIAL", "").strip()


def set_device(serial):
    """设置当前设备序列号（写环境变量，u2.connect 全局生效）"""
    if serial:
        os.environ["ANDROID_SERIAL"] = serial
    else:
        os.environ.pop("ANDROID_SERIAL", None)


def get_device():
    """连接当前选中的设备（未设置则 u2.connect 默认）"""
    import uiautomator2 as u2
    return u2.connect()


def device_ok(serial=None):
    """检查指定（或当前）设备是否在线"""
    try:
        import uiautomator2 as u2
        old = os.environ.get("ANDROID_SERIAL", "")
        if serial:
            os.environ["ANDROID_SERIAL"] = serial
        d = u2.connect()
        info = d.info
        if serial:
            os.environ["ANDROID_SERIAL"] = old
        return bool(info)
    except Exception:
        return False


if __name__ == "__main__":
    print("检测到的设备:")
    for dev in list_devices():
        print(f"  {dev['serial']}  [{dev['state']}]")
    print(f"当前选中: {get_serial() or '(默认)'}")
