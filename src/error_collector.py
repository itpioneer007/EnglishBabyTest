"""
src/error_collector.py — 错误收集 & 输出目录
负责人：C 同学

职责：
  巡检完成后，将错误题目统一收集到输出文件夹：
  
  {output_dir}/{version}/U{unit}_{stage}_{date}/
    ├── errors/
    │   ├── Q{idx}/
    │   │   ├── screenshot.png    ← APP原图
    │   │   ├── marked.png        ← 红框标注出错区域
    │   │   └── error.json        ← {dimensions, reasons, suggestions}
    │   └── Q{idx}/
    └── summary.csv               ← 所有错误题汇总

调用方：
  B: 批量跑完 → 调用 collector.collect(review_results)
  C: 导出API → 调用 collector.collect()
"""

import json
import csv
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional


class ErrorCollector:
    """错误收集 & 输出目录管理"""

    def __init__(self, output_root: str = None):
        base = Path(output_root or Path(__file__).parent.parent / "outputs")
        self.root = Path(base)
        self.current_dir: Optional[Path] = None

    def init_module_dir(self, version: str, unit: int, stage: str) -> Path:
        """初始化一个模块的输出目录"""
        date = datetime.now().strftime('%Y%m%d')
        dir_name = f"U{unit}_{stage}_{date}"
        self.current_dir = self.root / version / dir_name
        self.current_dir.mkdir(parents=True, exist_ok=True)
        (self.current_dir / "errors").mkdir(exist_ok=True)
        return self.current_dir

    def collect(self, review_results: dict, version: str, unit: int, stage: str) -> dict:
        """
        收集一个模块的所有错误题目

        Args:
            review_results: 巡检结果 {qid: _review_item, ...}
            version/unit/stage: 模块信息

        Returns:
            {total, failed, error_items: [...], output_dir}
        """
        # ===== C 在这里实现 =====
        self.init_module_dir(version, unit, stage)
        errors_dir = self.current_dir / "errors"

        # 筛选不通过的题目
        failed = {k: v for k, v in review_results.items()
                  if not v.get("overall_passed")}

        error_items = []
        for qid, q in failed.items():
            q_dir = errors_dir / f"Q{str(q.get('idx',0)).zfill(2)}"
            q_dir.mkdir(parents=True, exist_ok=True)

            # 1. 复制截图
            shot = q.get("screenshot", "")
            shot_src = Path(__file__).parent.parent / "screenshots" / shot
            if shot_src.exists():
                shutil.copy2(shot_src, q_dir / "screenshot.png")

            # 2. 保存错误详情JSON
            error_data = {
                "qid": qid,
                "question_type": q.get("question_type", ""),
                "overall_score": q.get("overall_score", 0),
                "script_answer": q.get("script_answer", ""),
                "stem": q.get("stem", ""),
                "recording": q.get("recording", ""),
                "failed_dimensions": [],
                "suggestions": [],
                "reasons": {}
            }
            for dim in ["stem", "content", "image", "answer", "post_error", "audio", "report"]:
                key = dim[:3]
                if not q.get(f"ai_{key}", True):
                    error_data["failed_dimensions"].append(dim)
                    error_data["reasons"][dim] = q.get(f"{dim}_reason", "")
                    error_data["suggestions"].append(f"[{dim}] {q.get(f'{dim}_reason','')[:50]}")

            with open(q_dir / "error.json", "w", encoding="utf-8") as f:
                json.dump(error_data, f, ensure_ascii=False, indent=2)

            error_items.append(error_data)

        # 3. 生成汇总CSV
        self._write_summary(error_items)

        return {
            "total": len(review_results),
            "failed": len(error_items),
            "error_items": error_items,
            "output_dir": str(self.current_dir)
        }

    def _write_summary(self, error_items: list):
        """写错误汇总CSV"""
        csv_path = self.current_dir / "summary.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["题号", "题型", "得分", "错误维度", "理由", "修改建议"])
            for e in error_items:
                writer.writerow([
                    e.get("qid", ""),
                    e.get("question_type", ""),
                    e.get("overall_score", 0),
                    ", ".join(e.get("failed_dimensions", [])),
                    "; ".join(e.get("reasons", {}).values()),
                    "; ".join(e.get("suggestions", []))
                ])
