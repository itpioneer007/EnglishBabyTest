"""
src/report_exporter.py — 报告生成 & 导出
负责人：C

职责：
  1. 生成 HTML 报告（全部题目 + 仅错误题目）
  2. 生成 CSV 表格（方便老师导入 Excel 批注）
  3. 打包错误截图 zip
  4. 按版本/Unit/日期组织输出目录结构

调用方：
  routes/export_routes.py → 各导出 API
  src/batch_runner.BatchRunner → 批量跑完自动调用

输出目录结构约定:
  {save_dir}/
    ├── 新湘鲁六上/
    │   ├── U6_基础巩固_20260728/
    │   │   ├── report_full.html       # 全量报告
    │   │   ├── report_errors.html     # 仅错误报告
    │   │   ├── errors.csv             # 错误表格
    │   │   └── screenshots/           # 错误截图
    │   │       ├── q03.png
    │   │       └── q07.png
    │   └── U7_基础巩固_20260728/
    │       └── ...
    └── latest/                        # 快捷入口：软链到最新
        └── report.html
"""

import json
import csv
import io
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional


class ReportExporter:
    """报告导出器"""

    def __init__(self, save_dir: str = None):
        base = Path(save_dir or str(Path(__file__).parent.parent / "outputs" / "reports"))
        self.save_dir = Path(base)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def export_html_full(self, questions: dict, metadata: dict = None) -> str:
        """
        生成全量HTML报告
        Args:
            questions: {qid: _review_item, ...}
            metadata: {version, unit, stage, docx}
        Returns:
            报告文件路径
        """
        # ===== C 在这里实现 =====
        # TODO(C): 生成完整的、好看的HTML报告
        # 参考 templates/index.html 中的 q-card 样式
        pass

    def export_html_errors(self, questions: dict, metadata: dict = None) -> str:
        """仅导出错误题目HTML"""
        pass

    def export_csv(self, questions: dict) -> str:
        """导出错误题目CSV"""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["题号", "题型", "脚本答案", "综合得分", "通过",
                         "题干理由", "内容理由", "配图理由", "作答理由"])

        for qid, q in questions.items():
            if not q.get("overall_passed"):
                writer.writerow([
                    qid, q.get("question_type", ""), q.get("script_answer", ""),
                    q.get("overall_score", 0), "否",
                    q.get("stem_reason", ""), q.get("content_reason", ""),
                    q.get("image_reason", ""), q.get("answer_reason", "")
                ])

        csv_path = self.save_dir / f"errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path.write_text(buf.getvalue(), encoding="utf-8-sig")
        return str(csv_path)

    def export_screenshots_zip(self, questions: dict, shots_dir: str = None) -> str:
        """打包错误截图"""
        import zipfile

        shots = Path(shots_dir or Path(__file__).parent.parent / "screenshots")
        zip_path = self.save_dir / f"screenshots_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            for qid, q in questions.items():
                if not q.get("overall_passed"):
                    shot = q.get("screenshot", "")
                    if shot:
                        shot_path = shots / shot
                        if shot_path.exists():
                            zf.write(shot_path, f"{qid}_{shot}")

        return str(zip_path)

    def organize_output_dir(self, version: str, unit: int, stage: str) -> Path:
        """创建按版本/Unit/日期组织的输出目录"""
        date_str = datetime.now().strftime('%Y%m%d')
        dir_name = f"U{unit}_{stage}_{date_str}"
        out_dir = self.save_dir / version / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir
