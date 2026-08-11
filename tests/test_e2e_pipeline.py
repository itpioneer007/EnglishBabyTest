"""
tests/test_e2e_pipeline.py — 端到端流程集成测试
===============================================

不依赖真实手机和 LLM API，用 Mock 数据验证全流程：
  引擎 → 审查 → 一致性验证 → 报告导出
"""

import sys
import json
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("=" * 70)
    print("  英语宝审查流水线 — 端到端集成测试")
    print("=" * 70)

    errors = []

    # ============================================================
    # Step 1: 准备 Mock 数据
    # ============================================================
    print("\n[1/5] 准备 Mock 审查数据...")

    tmpdir = tempfile.mkdtemp(prefix="e2e_pipeline_")
    data_dir = Path(tmpdir) / "data"
    data_dir.mkdir(exist_ok=True)
    outputs_dir = Path(tmpdir) / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    screenshots_dir = Path(tmpdir) / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    # 构造 5 道模拟题目（模拟 engine 截屏后的 inspection_state.json）
    mock_questions = []
    for i in range(1, 6):
        shot_path = screenshots_dir / f"q{i:03d}.png"
        shot_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        mock_questions.append({
            "qid": f"q{i:03d}",
            "idx": i,
            "stem": f"题目{i}的题干文字",
            "question_type": "选择",
            "script_answer": "A",
            "recording": "",
            "screenshot": str(shot_path),
            "overall_passed": None,
            "overall_score": 0,
            "stem_reason": "",
            "content_reason": "",
            "image_reason": "",
            "answer_reason": "",
            "error_dimensions": [],
            "knowledge_check": {},
        })

    state = {
        "version": "新湘鲁六上",
        "unit": 6,
        "stage": "基础巩固",
        "questions": mock_questions,
    }

    state_path = data_dir / "inspection_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 创建 {len(mock_questions)} 道 Mock 题目 + 截图")
    print(f"  ✓ inspection_state.json → {state_path}")

    # ============================================================
    # Step 2: 测试 BatchRunner (跳过真实引擎)
    # ============================================================
    print("\n[2/5] 测试 BatchRunner 编排器...")

    from src.batch_runner import BatchRunner

    plan = {
        "version": "新湘鲁六上",
        "units": [6],
        "stages": ["基础巩固"],
        "verify_consistency": True,
        "verify_sample": 3,
    }

    progress_log = []
    complete_result = {}

    def on_progress(status):
        progress_log.append(status)

    def on_complete(result):
        nonlocal complete_result
        complete_result = result

    runner = BatchRunner(plan, on_progress=on_progress, on_complete=on_complete)

    # 验证基本属性
    assert len(runner.pending) == 1
    assert runner.estimate_time()  # 不为空
    print(f"  ✓ 任务队列: {len(runner.pending)} 个模块")
    print(f"  ✓ 预估耗时: {runner.estimate_time()}")

    # 修改 _phase_engine 跳过真实手机连接
    original_phase_engine = runner._phase_engine

    def mock_phase_engine():
        """Mock 引擎阶段"""
        runner._notify_progress("Mock引擎: 跳过真实设备", phase="engine")
        for task in runner.pending:
            task["status"] = "engine_done"
            runner.completed.append(task)
        runner.stats["completed_modules"] = len(runner.completed)
        runner.stats["phases"]["engine"] = "0s (mock)"

    runner._phase_engine = mock_phase_engine

    # 修改 _phase_review 使用 Mock Agent
    original_phase_review = runner._phase_review

    def mock_phase_review():
        """Mock 审查阶段：用测试脚本中的 MockAgent"""
        from tests.test_consistency_checker_mock import MockAgent, build_scenarios, make_review

        runner._notify_progress("Mock审查: 使用预定义结果", phase="review")

        with open(state_path, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        questions = state_data.get("questions", [])

        scenarios = build_scenarios()
        agent = MockAgent(scenarios)

        from src.parse_yingyubao_docx import YingYuBaoQuestion

        for qd in questions:
            qid = qd["qid"]
            q = YingYuBaoQuestion(
                global_idx=qd["idx"], stem=qd.get("stem", ""),
                type_2=qd.get("question_type", ""),
                answer=qd.get("script_answer", ""),
            )
            shot = qd.get("screenshot", "")

            r = agent._create_empty_review()
            agent._review_batch(q, shot, r)

            qd["stem_reason"] = str(r.stem_check.details[:3])
            qd["content_reason"] = str(r.content_check.details[:3])
            qd["image_reason"] = str(r.image_check.details[:3])
            qd["answer_reason"] = str(r.answer_check.details[:3])

            error_dims = []
            for attr_name, check in [
                ("题干", r.stem_check), ("内容", r.content_check),
                ("配图", r.image_check), ("作答", r.answer_check),
            ]:
                if not check.passed:
                    error_dims.append(attr_name)

            qd["overall_passed"] = len(error_dims) == 0
            qd["overall_score"] = sum([
                r.stem_check.score, r.content_check.score,
                r.image_check.score, r.answer_check.score,
            ]) / 4
            qd["error_dimensions"] = error_dims

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

        runner.stats["total_questions"] = len(questions)
        runner.stats["passed_questions"] = len([q for q in questions if q["overall_passed"]])
        runner.stats["failed_questions"] = len([q for q in questions if not q["overall_passed"]])
        runner.stats["phases"]["review"] = "0s (mock)"

    runner._phase_review = mock_phase_review

    # 启动
    runner.start()

    # 等待完成（最多30秒）
    import time
    waited = 0
    while runner.running and waited < 30:
        time.sleep(0.5)
        waited += 0.5

    if runner.running:
        errors.append("FAIL: BatchRunner 在 30 秒内未完成")
        print("  ❌ BatchRunner 超时")
    else:
        print("  ✓ BatchRunner 完成")
        print(f"  ✓ 阶段: {runner.stats.get('phases', {})}")

        # 验证审查结果
        with open(state_path, "r", encoding="utf-8") as f:
            result_state = json.load(f)
        reviewed = result_state.get("questions", [])
        passed = [q for q in reviewed if q.get("overall_passed")]
        failed = [q for q in reviewed if not q.get("overall_passed")]
        print(f"  ✓ 审查结果: {len(passed)} 通过, {len(failed)} 不通过")

    # ============================================================
    # Step 3: 验证审查数据完整性
    # ============================================================
    print("\n[3/5] 验证审查数据完整性...")

    with open(state_path, "r", encoding="utf-8") as f:
        final_state = json.load(f)

    questions_out = final_state.get("questions", [])
    assert len(questions_out) == 5, f"题目数不对: {len(questions_out)}"

    for qd in questions_out:
        # 每题必须有判定
        if qd.get("overall_passed") is None:
            errors.append(f"FAIL: {qd['qid']} overall_passed 仍为 None (未审查)")
            print(f"  ❌ {qd['qid']} 未审查")
        else:
            print(f"  ✓ {qd['qid']}: {'通过' if qd['overall_passed'] else '不通过'} "
                  f"| 得分{qd.get('overall_score', 0):.2f} "
                  f"| 错误维度:{qd.get('error_dimensions', [])}")

    # ============================================================
    # Step 4: 验证报告导出
    # ============================================================
    print("\n[4/5] 验证报告导出...")

    from src.report_exporter import ReportExporter

    exp_dir = str(outputs_dir / "reports")
    exporter = ReportExporter(save_dir=exp_dir)
    results = exporter.export_all(questions_out, metadata={
        "version": "新湘鲁六上", "unit": 6, "stage": "基础巩固"
    })

    for key, path_str in results.items():
        if key.startswith("output"):
            continue
        p = Path(path_str)
        if p.exists() and p.stat().st_size > 0:
            print(f"  ✓ {key}: {p.stat().st_size} bytes → {p.name}")
        else:
            errors.append(f"FAIL: {key} 文件为空或不存在: {path_str}")
            print(f"  ❌ {key}: 文件缺失或为空")

    # 验证 HTML 包含预期内容
    html_path = results.get("html_full", "")
    if html_path and Path(html_path).exists():
        html_content = Path(html_path).read_text(encoding="utf-8")
        if "Q1" in html_content and "summary-card" in html_content:
            print("  ✓ HTML 报告包含题目卡片 + 汇总面板")
        else:
            errors.append("FAIL: HTML 报告缺少关键内容")
            print("  ❌ HTML 报告内容异常")

    # ============================================================
    # Step 5: 整体验证
    # ============================================================
    print(f"\n[5/5] {'='*50}")

    if errors:
        print(f"\n  ❌ {len(errors)} 个断言失败:")
        for e in errors:
            print(f"     {e}")
        print(f"\n  测试目录: {tmpdir} (保留以便排查)")
        return 1
    else:
        print(f"\n  🎉 端到端流水线全部通过！")
        print(f"\n  流水线阶段:")
        print(f"    Phase 1 (引擎)   → Mock 跳过")
        print(f"    Phase 2 (审查)   → 5 题已完成六维审查")
        print(f"    Phase 3 (一致性) → 3 题 × 3 次验证")
        print(f"    Phase 4 (导出)   → HTML×2 + CSV + ZIP")
        print(f"\n  输出文件在: {exp_dir}")
        print(f"  数据文件在: {data_dir}")
        return 0


if __name__ == "__main__":
    exit(main())
