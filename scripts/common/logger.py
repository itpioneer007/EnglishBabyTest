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
_stop_check = None    # web_server 注入的停止检查函数（返回 True = 应停止）
_current_module = ""  # ★ 当前检测的模块名（scheduler 设置，供错题定位用）
_current_stage = ""   # ★ 当前子模块/阶段（如 基础巩固/综合进阶/练习/测试）
# ★ 2026-09-23 新增：当前正在作答的**单元号**。
#   为什么必须单独上报：脚本层比对要按单元在 docx 里定位段小段落，而
#   `inspection_state["unit"]` 记的是**本轮单元范围**（如 "5-6"）。
#   web_server 旧实现直接 `int(str(unit).split("-")[0])` → 连跑 U5-6 时永远取 5，
#   于是 U6 的题全部拿 U5 脚本比对 → 整单元假错（用户实测：App 上明明是
#   "Sit in the sun and have fun."，报告却写 App="You'll see the moon and the stars."）。
#   模块每进入一个单元调用一次 set_current_unit()，web_server 优先读它。
_current_unit = 0
# ★ 2026-09-23 新增：模块名 → 本次运行挂载的脚本文件名（web_server 调度前注入）。
#   让模块内部（口语训练图片题）能直接拿到脚本该小题的题面，
#   不必再用视觉模型猜图（省一次 LLM 调用，且避免猜出参考答案）。
_module_scripts = {}

def set_log_callback(fn):
    """注入日志回调（web_server 启动时调用）"""
    global _log_callback
    _log_callback = fn

def set_stop_check(fn):
    """注入停止检查回调（web_server 启动时调用）"""
    global _stop_check
    _stop_check = fn

def set_current_module(name: str, stage: str = ""):
    """★ 设置当前检测模块上下文（scheduler 每开始一个模块时调用）
    供 web_server 错题定位记录：哪个模块、哪个子模块、第几题。"""
    global _current_module, _current_stage
    _current_module = name or ""
    _current_stage = stage or ""

def get_current_module():
    """返回当前模块上下文 (module, stage)"""
    return _current_module, _current_stage

def set_current_unit(n):
    """★ 模块进入某个单元时调用（口语训练等按单元跑的模块）。

    0/None 表示"未知/不按单元"。web_server 做脚本层比对时优先用它，
    而不是去猜 state["unit"]（那可能是 "5-6" 这样的范围）。
    """
    global _current_unit
    try:
        _current_unit = int(str(n).strip().split("-")[0]) if str(n).strip() else 0
    except Exception:
        _current_unit = 0

def get_current_unit() -> int:
    """返回当前正在作答的单元号（0 = 未知）"""
    return _current_unit

def set_module_scripts(mapping):
    """★ web_server 调度前注入 {模块名: 上传脚本文件名}"""
    global _module_scripts
    _module_scripts = dict(mapping or {})

def get_module_script(module: str) -> str:
    """取某模块本次挂载的脚本文件名（"" = 未挂载）"""
    try:
        return str((_module_scripts or {}).get(module, "") or "")
    except Exception:
        return ""

def should_stop():
    """供模块内部答题循环调用：收到停止请求返回 True"""
    if _stop_check:
        try:
            return bool(_stop_check())
        except Exception:
            pass
    return False

def step_log(msg, level="info", evidence=None):
    """模块内部打流程日志 → 前端实时可见; evidence=结构化审查证据(差异高亮)"""
    if _log_callback:
        # ★ 2026-09-20：区分 None 与 []
        #   None = 调用方没提供证据（普通流程日志，不是一道题）
        #   []   = 调用方明确说"这是一道题，但本轮没有可展示的证据"
        #   旧写法 `if evidence:` 把 [] 归进"没传"分支 → 下游 web_server.log_msg
        #   收到 evidence=None → 不登记这道题 → 题目从审查结果里凭空消失
        #   （口语训练 20 题只剩每个大题的第 1 小题，即最典型的现场表现）。
        if evidence is not None:
            _log_callback(msg, level, evidence)
        else:
            _log_callback(msg, level)
    else:
        # 没有注入回调时（命令行直接运行模块），回退到 print
        try:
            print(f"    [{level}] {msg}")
        except UnicodeEncodeError:
            print(f"    [{level}] {msg.encode('gbk', errors='replace').decode('gbk')}")
