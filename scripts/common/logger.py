"""全局日志通道：让模块内部也能把流程日志送到 web_server 前端

用法：
  from common.logger import step_log
  step_log("现在开始处理第3题", "step")
  step_log("检测到补全短文题型，开始逐个输入方框", "info")

web_server 启动时需注入回调：
  from common.logger import set_log_callback
  set_log_callback(lambda msg,level: log_msg(msg,level))
"""
_log_callback = None  # web_server 注入的日志函数

def set_log_callback(fn):
    """注入日志回调（web_server 启动时调用）"""
    global _log_callback
    _log_callback = fn

def step_log(msg, level="info"):
    """模块内部打流程日志 → 前端实时可见"""
    if _log_callback:
        _log_callback(msg, level)
    else:
        # 没有注入回调时（命令行直接运行模块），回退到 print
        print(f"    [{level}] {msg}")
