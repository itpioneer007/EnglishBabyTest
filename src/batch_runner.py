"""
src/batch_runner.py — 批量任务调度器
负责人：B

职责：接受批量计划 → 循环调 run_listening_inspect → 记录进度
"""

import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable


class BatchRunner:
    """批量任务调度器"""

    def __init__(self, plan: dict, on_progress: Optional[Callable] = None,
                 on_complete: Optional[Callable] = None):
        self.plan = plan
        self.on_progress = on_progress
        self.on_complete = on_complete

        self.running = False
        self.paused = False
        self.current = None
        self.completed = []
        self.pending = []
        self.failed = []
        self.max_retries = 3

        self._started_at = None
        self._total_modules = 0

        from src.progress_tracker import ProgressTracker
        self.tracker = ProgressTracker()

        self._build_queue()

    # ============================================
    # 任务队列
    # ============================================

    def _build_queue(self):
        self.pending = []
        for u in self.plan.get("units", []):
            for s in self.plan.get("stages", []):
                self.pending.append({"unit": u, "stage": s})
        self._total_modules = len(self.pending)

    def estimate_time(self) -> str:
        n = len(self.pending)
        if n == 0:
            return "无需执行"
        minutes = n * 6         # 每个模块6分钟（含导航+审查+异常）
        if minutes >= 60:
            return f"约{minutes // 60}小时{minutes % 60}分钟"
        return f"约{minutes}分钟"

    # ============================================
    # 核心执行
    # ============================================

    def run_all(self):
        """串行执行所有 pending 任务"""
        self._started_at = datetime.now()

        while self.pending and self.running:
            # 暂停等待
            while self.paused and self.running:
                time.sleep(1)

            if not self.running:
                break

            task = self.pending.pop(0)
            self.current = task
            module_key = f"U{task['unit']}_{task['stage']}"
            self._notify()

            started = datetime.now()
            try:
                result = self._run_one_module(task)
                duration = (datetime.now() - started).total_seconds()
                result["duration"] = f"{int(duration // 60)}m{int(duration % 60)}s"
                result["module_key"] = module_key
                self.completed.append(result)
                self.tracker.save(self._status_dict())
            except Exception as e:
                # 重试逻辑
                retries = 0
                while retries < self.max_retries and self.running:
                    retries += 1
                    print(f"[BatchRunner] {module_key} 失败 (尝试{retries}/{self.max_retries}): {e}")
                    try:
                        time.sleep(3)
                        result = self._run_one_module(task)
                        self.completed.append(result)
                        break
                    except Exception:
                        traceback.print_exc()
                else:
                    # 全部重试失败
                    self.failed.append({
                        "unit": task["unit"],
                        "stage": task["stage"],
                        "reason": str(e)[:200],
                        "retries": retries,
                    })

            self.current = None
            self._notify()

        # 完成
        self.running = False
        duration = (datetime.now() - self._started_at).total_seconds()
        dur_str = f"{int(duration // 60)}m{int(duration % 60)}s"
        self.tracker.record_history(self.plan, self.completed, dur_str)
        self.tracker.clear()

        if self.on_complete:
            self.on_complete({
                "completed": self.completed,
                "failed": self.failed,
                "duration": dur_str,
            })

    def _run_one_module(self, task: dict) -> dict:
        """执行单个模块的巡检（复用现有 run_listening_inspect）"""
        # import 放在函数内部，避免模块加载时循环引用
        from web_server import run_listening_inspect

        version = self.plan.get("version", "新湘鲁六上")
        unit = task["unit"]
        stage = task["stage"]
        docx = self.plan.get("docx", "")

        print(f"\n{'=' * 50}")
        print(f"  BatchRunner: U{unit} {stage}")
        print(f"  版本={version}  脚本={docx or 'AI自动生成'}")
        print(f"{'=' * 50}")

        # 直接调用现有的单模块巡检
        run_listening_inspect(version, unit, stage, docx)

        # 读巡检结果
        result = self._read_module_result(unit, stage)
        return result

    def _read_module_result(self, unit: int, stage: str) -> dict:
        """读取刚跑完的模块的结果"""
        import json
        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        if not state_path.exists():
            return {"unit": unit, "stage": stage, "questions": 0, "passed": 0, "failed": 0}

        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        questions = state.get("questions", {})
        all_qs = list(questions.values())
        passed = sum(1 for q in all_qs if q.get("overall_passed"))
        return {
            "unit": unit,
            "stage": stage,
            "questions": len(all_qs),
            "passed": passed,
            "failed": len(all_qs) - passed,
        }

    # ============================================
    # 控制
    # ============================================

    def start(self):
        self.running = True
        self.paused = False
        self._started_at = datetime.now()
        t = threading.Thread(target=self.run_all, daemon=True)
        t.start()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def cancel(self):
        self.running = False
        self.paused = False

    # ============================================
    # 状态导出（供 batch_routes.py 的 /api/batch/status 消费）
    # ============================================

    def _status_dict(self) -> dict:
        elapsed = (datetime.now() - self._started_at).total_seconds() if self._started_at else 0
        done = len(self.completed)
        total = done + len(self.pending)
        avg = elapsed / max(done, 1)
        eta = avg * len(self.pending)

        min_left = int(eta // 60)
        sec_left = int(eta % 60)
        eta_str = f"{min_left}m{sec_left}s" if eta > 0 else "--"

        return {
            "running": self.running,
            "paused": self.paused,
            "plan": self.plan,
            "completed": self.completed,
            "current": self.current,
            "pending": list(self.pending),
            "failed_modules": list(self.failed),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "eta_remaining": eta_str,
        }

    def _notify(self):
        if self.on_progress:
            self.on_progress(self._status_dict())
