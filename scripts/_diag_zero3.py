import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from modules.听力专项 import run_module

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
d = u2.connect(SERIAL)
print(">> 已连接", SERIAL)
print(">> 用 run_single_module 同款逻辑跑 五年级上册 听力专项 U1 ...")
q = run_module(d, units="1", grade="五年级上册", version="湘少版（2024审定）")
print(">> run_module 返回题数:", q)
