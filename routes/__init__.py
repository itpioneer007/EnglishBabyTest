# routes/__init__.py
# 三人协作路由注册入口
# A: 无路由（审查函数直接被B的巡检循环调用）
# B: batch_routes.py   → 批量自动化
# C: trace_routes.py   → 错误溯源 + export_routes.py → 输出交付

from .batch_routes import register as register_batch
from .trace_routes import register as register_trace
from .export_routes import register as register_export
