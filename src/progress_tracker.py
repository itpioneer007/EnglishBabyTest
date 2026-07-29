"""
src/progress_tracker.py — 批量任务进度持久化
负责人：B

职责：
  1. 保存批量任务进度到 data/batch_progress.json
  2. 支持断点续传（崩溃后从上次中断的 task 继续）
  3. 保存历史完成记录到 data/batch_history.json

调用方：
  src.batch_runner.BatchRunner
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class ProgressTracker:
    """批量任务进度管理"""

    def __init__(self, root_dir: str = None):
        base = Path(root_dir or Path(__file__).parent.parent)
        self.data_dir = base / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.progress_file = self.data_dir / "batch_progress.json"
        self.history_file = self.data_dir / "batch_history.json"

    def save(self, status: dict):
        """保存当前进度"""
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

    def load(self) -> Optional[dict]:
        """加载上次进度（断点续传用）"""
        if self.progress_file.exists():
            with open(self.progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("pending") and len(data["pending"]) > 0:
                return data
        return None

    def clear(self):
        """清除进度（跑完或取消后）"""
        if self.progress_file.exists():
            self.progress_file.unlink()

    def record_history(self, plan: dict, results: list, duration: str):
        """记录一条完成的批量任务到历史"""
        history = []
        if self.history_file.exists():
            with open(self.history_file, "r", encoding="utf-8") as f:
                history = json.load(f)

        entry = {
            "plan": plan,
            "total_modules": len(results),
            "passed_modules": sum(1 for r in results if r.get("all_passed", False)),
            "duration": duration,
            "completed_at": datetime.now().isoformat(),
            "results": results,
        }
        history.insert(0, entry)  # 最新排在前面
        history = history[:50]     # 只保留最近50条

        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
