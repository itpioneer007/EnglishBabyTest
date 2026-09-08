"""连手机验证：选 湘少版 时是否打印 '版本不存在' 并终止。
复用 scheduler._switch_if_needed（与网站 /api/run-full 同一路径）。
"""
import sys, time
sys.path.insert(0, r"C:\Users\yangj\Desktop\EnglishBabyTest-yangjiangliu\scripts")
from common.logger import step_log
# 让 step_log 同时进 stdout
import common.logger as L
_orig = L.step_log
def _log(msg, level="info"):
    print(f"[{level}] {msg}", flush=True)
    return _orig(msg, level)
L.step_log = _log

import uiautomator2 as u2
from scheduler import _switch_if_needed

d = u2.connect()
print(">> device:", d.device_info.get("serial"), flush=True)
print(">> 调用 _switch_if_needed('湘少版','五年级上册') ...", flush=True)
ok = _switch_if_needed(d, "湘少版", "五年级上册")
print(f">> 返回: {ok}  (False=版本不存在, 应终止)", flush=True)
