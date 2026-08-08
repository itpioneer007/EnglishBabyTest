"""
src/batch_runner.py — 批量任务编排器
=====================================

职责：串联整个审查流水线
  Phase 1 (引擎):    导航APP → 截屏 → 记录题目元数据
  Phase 2 (审查):    喂截图 + 题目数据 → ReviewAgent 六维审查
  Phase 3 (验证):    抽取样本 → ConsistencyChecker 一致性检查
  Phase 4 (导出):    ReportExporter → HTML/CSV/ZIP 一键输出

使用方式:
    runner = BatchRunner(plan, on_progress=callback, on_complete=callback)
    runner.start()       # 后台线程启动
    runner.pause()       # 暂停
    runner.resume()      # 继续
    runner.cancel()      # 取消
    runner.estimate_time()  # 预估耗时
"""

import json
import os
import sys
import threading
import time
from pathlib import Path
from datetime import datetime


class BatchRunner:
    """批量任务编排器"""

    def __init__(self, plan: dict, on_progress=None, on_complete=None):
        """
        Args:
            plan: {
                "version": "新湘鲁六上",
                "units": [6, 7, 8, 9],
                "stages": ["基础巩固", "综合进阶"],
                "docx": "脚本文件路径(可选)",
                "verify_consistency": True,   # 是否启用一致性验证
                "verify_sample": 5,           # 一致性验证抽样数量
            }
            on_progress: fn(status_dict) — 进度回调
            on_complete: fn(result_dict) — 完成回调
        """
        self.plan = plan
        self.on_progress = on_progress or (lambda s: None)
        self.on_complete = on_complete or (lambda r: None)

        # 状态
        self.running = False
        self.paused = False
        self.cancelled = False

        # 任务队列
        self.pending = []
        self.completed = []
        self.current = None
        self._build_task_queue()

        # 进度统计
        self.stats = {
            "total_modules": len(self.pending),
            "completed_modules": 0,
            "total_questions": 0,
            "passed_questions": 0,
            "failed_questions": 0,
            "uncertain_questions": 0,
            "started_at": "",
            "elapsed": 0,
            "phases": {"engine": "", "review": "", "verify": "", "export": ""},
        }

    # ============================================================
    # 任务队列构建
    # ============================================================

    def _build_task_queue(self):
        units = self.plan.get("units", [1])
        stages = self.plan.get("stages", ["基础巩固"])
        version = self.plan.get("version", "")

        for u in units:
            for s in stages:
                self.pending.append({
                    "version": version,
                    "unit": u,
                    "stage": s,
                    "task_id": f"{version}_U{u}_{s}",
                })

    # ============================================================
    # 生命周期管理
    # ============================================================

    def start(self):
        """启动批量任务（后台线程）"""
        if self.running:
            return
        self.running = True
        self.cancelled = False
        self.stats["started_at"] = datetime.now().isoformat()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def pause(self):
        """暂停"""
        self.paused = True

    def resume(self):
        """恢复"""
        self.paused = False

    def cancel(self):
        """取消"""
        self.cancelled = True
        self.running = False

    def estimate_time(self) -> str:
        """粗略预估耗时"""
        total = len(self.pending)
        if total == 0:
            return "无任务"
        mins = total * 8  # 每模块约 8 分钟（引擎3 + 审查4 + 导出1）
        if self.plan.get("verify_consistency"):
            mins += 10
        if mins < 60:
            return f"约{mins}分钟"
        return f"约{mins//60}小时{mins%60}分钟"

    # ============================================================
    # 主执行循环
    # ============================================================

    def _run(self):
        """主流水线，在后台线程中执行"""
        try:
            self._notify_progress("开始批量任务", phase="init")

            # ====== Phase 1: 引擎遍历 ======
            self._notify_progress("Phase 1/4: 引擎遍历截屏...", phase="engine")
            self._phase_engine()

            if self.cancelled:
                return

            # ====== Phase 2: AI 审查 ======
            self._notify_progress("Phase 2/4: AI 审查中...", phase="review")
            self._phase_review()

            if self.cancelled:
                return

            # ====== Phase 3: 一致性验证（可选）=====
            if self.plan.get("verify_consistency"):
                self._notify_progress("Phase 3/4: 一致性验证...", phase="verify")
                self._phase_verify()

            if self.cancelled:
                return

            # ====== Phase 4: 报告导出 ======
            self._notify_progress("Phase 4/4: 生成报告...", phase="export")
            self._phase_export()

            # 完成
            self._notify_progress("所有阶段完成", phase="done")
            self.on_complete(self.stats)

        except Exception as e:
            self._notify_progress(f"流水线异常: {e}", phase="error")
            self.on_complete({"error": str(e), **self.stats})
        finally:
            self.running = False

    def _check_pause_cancel(self):
        """检查暂停/取消状态"""
        while self.paused and self.running:
            time.sleep(0.5)
        if self.cancelled:
            raise InterruptedError("任务已取消")

    # ============================================================
    # Phase 1: 引擎遍历
    # ============================================================

    def _phase_engine(self):
        """
        引擎阶段：连接手机 → 遍历模块 → 截屏保存。

        实际环境调用 scripts.engine.run_single_module()
        Mock 环境从 data/inspection_state.json 读取已有数据。
        """
        t0 = time.time()

        for task in self.pending:
            self._check_pause_cancel()
            self.current = task
            unit = task["unit"]
            stage = task["stage"]

            self._notify_progress(
                f"引擎: U{unit} {stage} 遍历中...",
                phase="engine", detail=task
            )

            # 尝试连接真实设备运行引擎
            try:
                self._run_engine_for_task(task)
            except (ImportError, FileNotFoundError, OSError) as e:
                # 设备不可用 → 使用已有数据
                self._notify_progress(
                    f"设备不可用，使用已有数据: U{unit} {stage}",
                    phase="engine", detail={"unit": unit, "status": "cached"}
                )

            task["status"] = "engine_done"
            self.completed.append(task)
            self.stats["completed_modules"] = len(self.completed)
            self._on_progress_callback(task)

        self.stats["phases"]["engine"] = f"{time.time() - t0:.0f}s"

    def _run_engine_for_task(self, task: dict):
        """尝试通过 ADB + uiautomator2 操控真实手机"""
        unit = task["unit"]
        stage = task["stage"]
        version = task["version"]

        # 延迟导入，避免无设备时报错
        PROJECT_ROOT = Path(__file__).parent.parent
        SCRIPTS_DIR = str(PROJECT_ROOT / "scripts")
        if SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, SCRIPTS_DIR)

        from config import MODULE_CONFIG, GRADE_LEVEL, BOOK_VERSION, APP_PACKAGE
        from engine import u2, close_ad, dismiss_global_popups, ensure_grade, run_single_module, back_to_home

        d = u2.connect()
        d.app_stop(APP_PACKAGE)
        time.sleep(1)
        d.app_start(APP_PACKAGE)
        time.sleep(5)

        dismiss_global_popups(d)
        close_ad(d)

        if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
            raise RuntimeError("年级切换失败")

        # 找到匹配的模块
        matching = [m for m in self.plan.get("stages", []) if stage in m]
        for mod_name in [stage] + matching:
            cfg = MODULE_CONFIG.get(mod_name)
            if cfg:
                run_single_module(d, mod_name, cfg)
                break

    # ============================================================
    # Phase 2: AI 审查
    # ============================================================

    def _phase_review(self):
        """
        审查阶段：从 inspection_state.json 加载题目数据，
        逐题调用 ReviewAgent 进行六维审查。
        """
        t0 = time.time()

        # 加载题目数据
        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        if not state_path.exists():
            self._notify_progress("无审查数据，跳过审查阶段", phase="review")
            return

        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        questions = state.get("questions", [])
        if not questions:
            self._notify_progress("审查数据为空", phase="review")
            return

        self._notify_progress(f"开始审查 {len(questions)} 道题目...", phase="review")

        # 导入 ReviewAgent
        from src.review_agent import ReviewAgent
        agent = ReviewAgent()

        total = len(questions)
        passed = 0
        failed = 0
        uncertain = 0

        for i, qd in enumerate(questions):
            self._check_pause_cancel()

            qid = qd.get("qid", f"Q{i+1}")
            self._notify_progress(
                f"审查: {qid} ({i+1}/{total})...",
                phase="review",
                detail={"qid": qid, "progress": f"{i+1}/{total}"}
            )

            try:
                shot = qd.get("screenshot", "")
                if not shot or not Path(shot).exists():
                    # 尝试在 screenshots/ 目录下查找
                    shot_path = Path(__file__).parent.parent / "screenshots" / shot
                    if not shot_path.exists():
                        qd["overall_passed"] = False
                        qd["error_dimensions"] = ["截图缺失"]
                        failed += 1
                        continue
                    shot = str(shot_path)

                # 构造题目对象
                from src.parse_yingyubao_docx import YingYuBaoQuestion
                q = YingYuBaoQuestion(
                    global_idx=qd.get("idx", i+1),
                    stem=qd.get("stem", ""),
                    recording=qd.get("recording", ""),
                    answer=qd.get("script_answer", ""),
                    type_2=qd.get("question_type", ""),
                )

                # 六维审查
                r = agent._create_empty_review()
                agent._review_batch(q, shot, r)

                # 写回结果
                qd["stem_reason"] = str(r.stem_check.details[:3]) if r.stem_check.details else ""
                qd["content_reason"] = str(r.content_check.details[:3]) if r.content_check.details else ""
                qd["image_reason"] = str(r.image_check.details[:3]) if r.image_check.details else ""
                qd["answer_reason"] = str(r.answer_check.details[:3]) if r.answer_check.details else ""

                # 综合判定
                all_checks = [r.stem_check, r.content_check, r.image_check, r.answer_check]
                error_dims = []
                for attr_name, check in [("题干", r.stem_check), ("内容", r.content_check),
                                          ("配图", r.image_check), ("作答", r.answer_check)]:
                    if not check.passed:
                        error_dims.append(attr_name)

                qd["overall_passed"] = len(error_dims) == 0
                qd["overall_score"] = sum(c.score for c in all_checks) / len(all_checks)
                qd["error_dimensions"] = error_dims

                if qd["overall_passed"]:
                    passed += 1
                elif error_dims:
                    failed += 1
                else:
                    uncertain += 1

            except Exception as e:
                qd["overall_passed"] = False
                qd["error_dimensions"] = [f"审查异常: {str(e)[:60]}"]
                failed += 1

        # 保存审查结果
        state["questions"] = questions
        state["review_stats"] = {
            "total": total, "passed": passed, "failed": failed, "uncertain": uncertain,
            "pass_rate": round(passed / total, 3) if total else 0,
            "reviewed_at": datetime.now().isoformat(),
        }
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        self.stats["total_questions"] = total
        self.stats["passed_questions"] = passed
        self.stats["failed_questions"] = failed
        self.stats["uncertain_questions"] = uncertain
        self.stats["phases"]["review"] = f"{time.time() - t0:.0f}s"

    # ============================================================
    # Phase 3: 一致性验证
    # ============================================================

    def _phase_verify(self):
        """从已审查题目中抽取样本做一致性验证"""
        t0 = time.time()

        sample_size = self.plan.get("verify_sample", 5)
        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"

        if not state_path.exists():
            self._notify_progress("无数据可做一致性验证", phase="verify")
            return

        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        questions = state.get("questions", [])
        if not questions:
            return

        # 随机抽样但优先取不通过的
        failed_qs = [q for q in questions if not q.get("overall_passed")]
        sample = (failed_qs + questions)[:sample_size]

        from src.review_agent import ReviewAgent
        from src.consistency_checker import ConsistencyChecker
        from src.parse_yingyubao_docx import YingYuBaoQuestion

        agent = ReviewAgent()
        checker = ConsistencyChecker(agent)

        q_dict = {}
        s_dict = {}
        for qd in sample:
            qid = qd.get("qid", "")
            q = YingYuBaoQuestion(
                global_idx=qd.get("idx", 0), stem=qd.get("stem", ""),
                type_2=qd.get("question_type", ""),
                answer=qd.get("script_answer", ""),
            )
            q_dict[qid] = q
            s_dict[qid] = qd.get("screenshot", "")

        self._notify_progress(
            f"一致性验证: {len(q_dict)} 题 × 3 次...",
            phase="verify", detail={"sample": len(q_dict)}
        )

        reports = checker.check_batch(q_dict, s_dict, runs=3)
        summary = checker.summary()

        # 保存一致性报告
        out_path = Path(__file__).parent.parent / "outputs" / "consistency_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        self.stats["consistency"] = summary
        self.stats["phases"]["verify"] = f"{time.time() - t0:.0f}s"

    # ============================================================
    # Phase 4: 报告导出
    # ============================================================

    def _phase_export(self):
        """生成 HTML/CSV/ZIP 报告"""
        t0 = time.time()

        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        if not state_path.exists():
            self._notify_progress("无数据可导出", phase="export")
            return

        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        questions = state.get("questions", [])
        if not questions:
            self._notify_progress("无题目数据可导出", phase="export")
            return

        from src.report_exporter import ReportExporter

        last = self.completed[-1] if self.completed else {}
        metadata = {
            "version": self.plan.get("version", ""),
            "unit": last.get("unit", 1),
            "stage": last.get("stage", "基础巩固"),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        exporter = ReportExporter()
        results = exporter.export_all(
            questions, metadata=metadata, version=metadata["version"],
            unit=metadata["unit"], stage=metadata["stage"],
        )

        self._notify_progress(
            f"报告已生成: HTML×2 + CSV + ZIP",
            phase="export", detail=results
        )

        self.stats["export_files"] = results
        self.stats["phases"]["export"] = f"{time.time() - t0:.0f}s"

    # ============================================================
    # 内部辅助
    # ============================================================

    def _notify_progress(self, message: str, phase: str = "", detail=None):
        """通知进度"""
        status = {
            "message": message,
            "phase": phase,
            "detail": detail,
            "running": self.running,
            "paused": self.paused,
            "completed": len(self.completed),
            "total": len(self.pending),
            "stats": self.stats,
        }
        self.on_progress(status)

    def _on_progress_callback(self, task: dict):
        """单个模块完成后的回调"""
        self._notify_progress(
            f"模块完成: {task['task_id']}",
            phase="engine",
            detail={"task": task, "completed_count": len(self.completed)}
        )
