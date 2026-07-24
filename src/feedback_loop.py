"""
feedback_loop.py — AI 审查精准度反馈优化系统 (v2: 三阶段正向反馈)
=====================================================================

三阶段提升机制:
  阶段1 Prompt迭代 — 用已知答案的题测试 → 看 AI 判断对不对 → 改 prompt
  阶段2 对比优化 — AI 结果 vs 人工标注 → 发现系统性错误 → 加规则
  阶段3 反馈闭环 — 正确/错误样本存档 → 每次审查自动加载 → 持续学习

与审查流程的集成:
  每次审查后, 审查智能体自动记录 AI 判断结果
  人工确认后存入反馈数据库
  下次审查时自动加载反馈作为 few-shot 示例

用法:
    from src.feedback_loop import FeedbackStore, FeedbackSample, ThreeStageTrainer
    
    # 初始化
    store = FeedbackStore()
    
    # 添加一条反馈
    store.add(sample)
    
    # 获取反馈统计
    stats = store.get_stats()
    
    # 构建 few-shot prompt
    prompt_prefix = store.build_fewshot_prompt()
    
    # 三阶段训练
    trainer = ThreeStageTrainer(llm, store)
    trainer.run_phase1_test("请判断这张图...")  # Prompt 迭代
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ============================================================
# 反馈样本 (v2: 增加维度)
# ============================================================

@dataclass
class FeedbackSample:
    """一条审查反馈 — 扩展版"""
    # 题目标识
    question_id: str = ""             # 题目编号 (如 "U6-Q01")
    docx_script_id: int = 0           # DOCX 中的全局题号
    unit: int = 0                     # 单元
    
    # 审查维度
    check_dimension: str = ""         # 审查维度: stem/content/image/answer
    question_type: str = ""           # 题型: 听音选择词汇/听音选择图片/...

    # 判断结果
    human_judgment: str = ""          # 人工判断: 通过/不通过
    ai_judgment: str = ""             # AI判断: 通过/不通过
    ai_reason: str = ""               # AI 给出的理由

    # 人工反馈
    human_note: str = ""              # 人工备注（AI 哪里错了）
    suggested_fix: str = ""           # 建议修复方案

    # 元数据
    image_type: str = ""              # 配图类型: 有图/无图/纯图
    screenshot: str = ""              # 截图路径
    knowledge_ref: str = ""           # 关联的知识库条目
    timestamp: str = ""               # 记录时间

    def is_ai_correct(self) -> bool:
        return self.human_judgment == self.ai_judgment


class FeedbackStore:
    """
    反馈样本存储 (v2: 支持多维分析 + 趋势跟踪)

    文件: data/feedback_samples.json
    结构:
      {
        "good": [ 正确样本... ],
        "bad":  [ 错误样本... ],
        "stats": { ... },
        "trend": [ ... 每日准确率 ... ]
      }
    """

    PATH = "data/feedback_samples.json"

    def __init__(self):
        self.data = {
            "good": [],
            "bad": [],
            "stats": {},
            "trend": [],
        }
        self._load()

    def _load(self):
        p = Path(self.PATH)
        if p.exists():
            self.data = json.loads(p.read_text(encoding="utf-8"))

    def _save(self):
        # 更新统计
        good = self.data["good"]
        bad = self.data["bad"]
        total = len(good) + len(bad)
        good_count = len(good)
        bad_count = len(bad)
        
        # 维度分析
        dim_stats = {}
        for entry in good + bad:
            dim = entry.get("check_dimension", "unknown")
            if dim not in dim_stats:
                dim_stats[dim] = {"total": 0, "correct": 0, "wrong": 0}
            dim_stats[dim]["total"] += 1
            if entry.get("human_judgment") == entry.get("ai_judgment"):
                dim_stats[dim]["correct"] += 1
            else:
                dim_stats[dim]["wrong"] += 1
        for d in dim_stats:
            t = dim_stats[d]["total"]
            c = dim_stats[d]["correct"]
            dim_stats[d]["accuracy"] = f"{c/t*100:.1f}%" if t else "N/A"

        self.data["stats"] = {
            "total": total,
            "good_samples": good_count,
            "bad_samples": bad_count,
            "accuracy": f"{good_count/total*100:.1f}%" if total else "N/A",
            "dimension_accuracy": dim_stats,
            "last_updated": datetime.now().isoformat(),
        }

        Path(self.PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.PATH).write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, sample: FeedbackSample):
        """添加一条反馈"""
        entry = {
            "question_id": sample.question_id,
            "docx_script_id": sample.docx_script_id,
            "unit": sample.unit,
            "check_dimension": sample.check_dimension,
            "question_type": sample.question_type,
            "human_judgment": sample.human_judgment,
            "ai_judgment": sample.ai_judgment,
            "ai_reason": sample.ai_reason[:200],
            "human_note": sample.human_note,
            "suggested_fix": sample.suggested_fix,
            "image_type": sample.image_type,
            "screenshot": sample.screenshot,
            "knowledge_ref": sample.knowledge_ref,
            "timestamp": sample.timestamp or datetime.now().isoformat(),
        }
        if sample.is_ai_correct():
            self.data["good"].append(entry)
        else:
            self.data["bad"].append(entry)
        self._save()

    def add_from_review(self, question_id: str, check_dimension: str,
                        human_judgment: str, ai_judgment: str,
                        ai_reason: str = "", human_note: str = "",
                        screenshot: str = "", **kwargs):
        """从审查结果快速添加反馈"""
        sample = FeedbackSample(
            question_id=question_id,
            check_dimension=check_dimension,
            human_judgment=human_judgment,
            ai_judgment=ai_judgment,
            ai_reason=ai_reason,
            human_note=human_note,
            screenshot=screenshot,
            **kwargs
        )
        self.add(sample)

    # ============================================================
    # 统计查询
    # ============================================================

    def get_stats(self) -> dict:
        """获取当前准确率统计"""
        return self.data.get("stats", {})

    def get_good_examples(self) -> list:
        """获取正确样本"""
        return self.data.get("good", [])

    def get_bad_examples(self) -> list:
        """获取错误样本"""
        return self.data.get("bad", [])

    def get_bad_patterns(self) -> list[str]:
        """分析高频错误模式 (按维度+题型)"""
        patterns = {}
        for entry in self.data["bad"]:
            key = f"{entry.get('check_dimension', '?')} | {entry.get('question_type', '?')}"
            patterns[key] = patterns.get(key, 0) + 1
        total = sum(patterns.values())
        return [
            f"{k}: {v}次 ({v/total*100:.0f}%)"
            for k, v in sorted(patterns.items(), key=lambda x: -x[1])
        ]

    def get_dimension_accuracy(self) -> dict:
        """获取各维度准确率"""
        return self.data.get("stats", {}).get("dimension_accuracy", {})

    # ============================================================
    # Few-shot Prompt 构建 (核心: 让 AI 从历史中学)
    # ============================================================

    def build_fewshot_prompt(self, max_samples: int = 3, 
                             dim_filter: str = None) -> str:
        """
        用反馈样本构建 few-shot prompt 前缀
        
        Args:
            max_samples: 每种类型最多取几个
            dim_filter: 只取特定维度的样本 (如 "image"/"answer")
            
        Returns:
            str: 可插入审查 prompt 前面的示例
        """
        good = self.data["good"]
        bad = self.data["bad"]

        # 过滤维度
        if dim_filter:
            good = [g for g in good if g.get("check_dimension") == dim_filter]
            bad = [b for b in bad if b.get("check_dimension") == dim_filter]

        # 取最新的样本
        good = good[-max_samples:]
        bad = bad[-max_samples:]

        parts = []
        if good:
            parts.append("【正确的审查示例(请参考)】")
            for g in good:
                qid = g.get("question_id", "?")
                note = g.get("human_note", "")[:60]
                judge = g.get("ai_judgment", "")
                parts.append(f"  Q{qid}: AI判断={judge} ✅ {note}")

        if bad:
            parts.append("\n【之前AI判断错误的示例(请避免)】")
            for b in bad:
                qid = b.get("question_id", "?")
                human = b.get("human_judgment", "")
                ai = b.get("ai_judgment", "")
                note = b.get("human_note", "")[:60]
                parts.append(f"  Q{qid}: AI={ai}, 正确={human} ❌ {note}")

        return "\n".join(parts) + "\n" if parts else ""

    def build_rules(self) -> str:
        """
        从错误模式自动生成审查规则
        Returns: str (可用作审查 prompt 中的规则部分)
        """
        bad = self.data["bad"]
        if not bad:
            return ""

        rules = []
        
        # 检查配图识别错误
        image_errors = [b for b in bad if b.get("check_dimension") == "image" 
                        and b.get("ai_judgment") == "不通过"
                        and b.get("human_judgment") == "通过"]
        if image_errors:
            rules.append("- 配图检查: 如果截图中的图片与录音内容明显相关, 即使图片简单, 也应判定为通过")

        # 检查作答判断错误
        answer_errors = [b for b in bad if b.get("check_dimension") == "answer"]
        if answer_errors:
            rules.append("- 作答检查: 只要存在可点击元素(LinearLayout/Button), 就应判定为可作答")

        # 检查内容匹配错误
        content_errors = [b for b in bad if b.get("check_dimension") == "content"]
        if content_errors:
            rules.append("- 内容检查: 优先以脚本为准对比, 注意脚本和APP可能使用同义词")

        return "\n".join(rules)


# ============================================================
# 三阶段训练器
# ============================================================

class ThreeStageTrainer:
    """
    三阶段训练器 — 逐步提升审查准确率

    阶段1: Prompt 迭代
    阶段2: 对比优化  
    阶段3: 反馈闭环
    """

    def __init__(self, llm=None, store: FeedbackStore = None):
        self.llm = llm
        self.store = store or FeedbackStore()
        self.history = []

    # ----------------------------------------------------------
    # 阶段1: Prompt 迭代
    # ----------------------------------------------------------

    def run_phase1_test(self, prompt: str, expected_pass: bool = None,
                        image_path: str = None) -> dict:
        """
        测试一个 prompt 的效果
        
        Args:
            prompt: 要测试的 prompt 文本
            expected_pass: 期望的结果 (True=通过 / False=不通过 / None=仅测试)
            image_path: 截图（如果需要看图）

        Returns:
            {"prompt": ..., "result": ..., "passed": ..., "match": ...}
        """
        if not self.llm:
            return {"error": "无 LLM 客户端"}

        result = self.llm.ask(prompt, image_path=image_path)
        passed = "通过" in result or "✅" in result

        match = None
        if expected_pass is not None:
            match = (passed == expected_pass)

        entry = {
            "prompt": prompt[:200],
            "result": result[:200],
            "passed": passed,
            "expected": expected_pass,
            "match": match,
            "timestamp": datetime.now().isoformat(),
        }
        self.history.append(entry)
        return entry

    def compare_prompts(self, prompts: list[str], test_cases: list[dict]) -> list:
        """
        对比多个 prompt 在多个测试用例上的效果
        
        Args:
            prompts: ["prompt A", "prompt B", ...]
            test_cases: [{"prompt": ..., "expected": True/False, "image": ...}, ...]

        Returns:
            [{"prompt": "A", "total": 10, "pass": 8, "accuracy": "80%"}, ...]
        """
        results = []
        for i, p in enumerate(prompts):
            correct = 0
            total = len(test_cases)
            for tc in test_cases:
                final_prompt = p + "\n" + tc.get("prompt", "")
                r = self.run_phase1_test(
                    final_prompt,
                    expected_pass=tc.get("expected"),
                    image_path=tc.get("image"),
                )
                if r.get("match") is True:
                    correct += 1
            results.append({
                "prompt_idx": i,
                "prompt_preview": p[:80],
                "total": total,
                "correct": correct,
                "accuracy": f"{correct/total*100:.0f}%" if total else "N/A",
            })
        return results

    def suggest_prompt_improvement(self) -> list:
        """
        根据反馈中的错误样本, 建议 prompt 改进方向
        """
        bad = self.store.data["bad"]
        if not bad:
            return ["暂无反馈数据, 请先进行审查并添加反馈"]

        suggestions = set()
        for b in bad:
            fix = b.get("suggested_fix", "")
            if fix:
                suggestions.add(f"- 修复 \"{b.get('question_id','?')}\": {fix}")
            note = b.get("human_note", "")
            if "误判" in note or "错误" in note:
                suggestions.add(f"- 检查 \"{b.get('check_dimension','?')}\" 维度的判断逻辑")
        
        return list(suggestions) if suggestions else ["暂无明确改进方向"]

    # ----------------------------------------------------------
    # 阶段2: 对比优化
    # ----------------------------------------------------------

    def run_phase2_comparison(self, review_results: list[dict],
                               human_labels: list[dict]) -> dict:
        """
        对比 AI 审查结果与人工标注, 统计准确率
        
        Args:
            review_results: [{"idx": 1, "passed": True, "reason": "..."}, ...]
            human_labels: [{"idx": 1, "passed": True, "note": "..."}, ...]

        Returns:
            {"accuracy": "85%", "confusions": [...], "errors": [...]}
        """
        # 构建映射
        human_map = {h["idx"]: h for h in human_labels}

        correct = 0
        total = len(review_results)
        errors = []

        for r in review_results:
            idx = r.get("idx")
            if idx in human_map:
                h = human_map[idx]
                ai_pass = r.get("passed")
                human_pass = h.get("passed")
                if ai_pass == human_pass:
                    correct += 1
                else:
                    errors.append({
                        "idx": idx,
                        "ai_judgment": "通过" if ai_pass else "不通过",
                        "human_judgment": "通过" if human_pass else "不通过",
                        "ai_reason": r.get("reason", "")[:100],
                        "human_note": h.get("note", ""),
                    })
                    # 自动添加反馈
                    self.store.add_from_review(
                        question_id=f"U{r.get('unit','?')}-Q{idx:02d}",
                        check_dimension=r.get("dimension", "unknown"),
                        human_judgment="通过" if human_pass else "不通过",
                        ai_judgment="通过" if ai_pass else "不通过",
                        ai_reason=r.get("reason", ""),
                        human_note=h.get("note", ""),
                    )

        accuracy = f"{correct/total*100:.1f}%" if total else "N/A"
        return {
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
            "errors": errors,
        }

    # ----------------------------------------------------------
    # 阶段3: 反馈闭环
    # ----------------------------------------------------------

    def build_enhanced_prompt(self, base_prompt: str, dim_filter: str = None) -> str:
        """
        构建增强版审查 prompt: 基础 prompt + few-shot 示例 + 规则
        
        Args:
            base_prompt: 基础的审查 prompt
            dim_filter: 维度过滤

        Returns: str (增强后的完整 prompt)
        """
        fewshot = self.store.build_fewshot_prompt(max_samples=3, dim_filter=dim_filter)
        rules = self.store.build_rules()
        stats = self.store.get_stats()

        parts = [base_prompt]
        
        if fewshot:
            parts.append(f"\n\n【参考信息】\n{fewshot}")

        if rules:
            parts.append(f"\n\n【审查规则】\n{rules}")

        if stats.get("total", 0) > 0:
            parts.append(
                f"\n\n反馈数据: 共{stats['total']}条, "
                f"准确率{stats['accuracy']}"
            )

        return "\n".join(parts)

    def export_report(self) -> str:
        """导出训练报告"""
        stats = self.store.get_stats()
        bad_patterns = self.store.get_bad_patterns()
        dim_acc = self.store.get_dimension_accuracy()
        suggestions = self.suggest_prompt_improvement()

        lines = [
            "=" * 60,
            "审查智能体训练报告",
            "=" * 60,
            f"生成时间: {datetime.now().isoformat()}",
            "",
            f"【总览】",
            f"总样本: {stats.get('total', 0)}",
            f"准确率: {stats.get('accuracy', 'N/A')}",
            f"正确样本: {stats.get('good_samples', 0)}",
            f"错误样本: {stats.get('bad_samples', 0)}",
            "",
            f"【各维度准确率】",
        ]
        for dim, acc in sorted(dim_acc.items()):
            lines.append(f"  {dim}: {acc.get('accuracy', 'N/A')} ({acc.get('correct',0)}/{acc.get('total',0)})")

        lines.extend([
            "",
            "【高频错误模式】",
        ])
        for p in bad_patterns:
            lines.append(f"  {p}")

        lines.extend([
            "",
            "【Prompt 改进建议】",
        ])
        for s in suggestions:
            lines.append(f"  {s}")

        lines.extend([
            "",
            "=" * 60,
        ])
        return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--add", nargs=5, metavar=("QID","DIM","HUMAN","AI","NOTE"),
                   help="添加反馈: QID 维度 人工判断 AI判断 备注")
    p.add_argument("--stats", action="store_true", help="查看统计")
    p.add_argument("--report", action="store_true", help="导出训练报告")
    p.add_argument("--dim-acc", action="store_true", help="各维度准确率")
    p.add_argument("--patterns", action="store_true", help="错误模式分析")
    p.add_argument("--fewshot", type=int, nargs="?", const=3, default=0,
                   help="生成 few-shot prompt (可选数量)")
    args = p.parse_args()

    store = FeedbackStore()

    if args.add:
        s = FeedbackSample(
            question_id=args.add[0],
            check_dimension=args.add[1],
            human_judgment=args.add[2],
            ai_judgment=args.add[3],
            human_note=args.add[4],
        )
        store.add(s)
        print(f"✅ 添加反馈: {s.question_id} [{s.check_dimension}]")

    if args.stats:
        import json as _json
        print(_json.dumps(store.get_stats(), ensure_ascii=False, indent=2))

    if args.dim_acc:
        dim = store.get_dimension_accuracy()
        for d, v in dim.items():
            print(f"  {d}: {v.get('accuracy','N/A')} ({v.get('correct',0)}/{v.get('total',0)})")

    if args.patterns:
        for p in store.get_bad_patterns():
            print(f"  {p}")

    if args.fewshot > 0:
        print(store.build_fewshot_prompt(max_samples=args.fewshot))

    if args.report:
        trainer = ThreeStageTrainer(store=store)
        print(trainer.export_report())
