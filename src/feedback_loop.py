"""
feedback_loop.py — AI 审查精准度反馈优化系统

三阶段提升机制:
  1. Prompt 迭代 — 用已知答案的题测试 → 看 AI 判断对不对 → 改 prompt
  2. 对比优化 — AI 结果 vs 人工标注 → 发现系统性错误 → 加规则
  3. 反馈闭环 — 正确/错误样本存入 Skill → 每次审查自动加载 → 持续学习
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================
# 反馈样本
# ============================================================

@dataclass
class FeedbackSample:
    """一条审查反馈"""
    question_id: str = ""             # 题目编号 (如 "U6-Q01")
    image_type: str = ""              # 配图类型: 有图/无图/纯图
    human_judgment: str = ""          # 人工判断: 通过/不通过
    ai_judgment: str = ""             # AI判断: 通过/不通过
    ai_reason: str = ""               # AI 给出的理由
    human_note: str = ""              # 人工备注（AI 哪里错了）
    screenshot: str = ""              # 截图路径
    timestamp: str = ""               # 记录时间

    def is_ai_correct(self) -> bool:
        return self.human_judgment == self.ai_judgment


class FeedbackStore:
    """
    反馈样本存储

    文件: data/feedback_samples.json
    结构:
      {
        "good": [ 正确样本... ],
        "bad": [  错误样本... ],
        "stats": { "total": 100, "ai_accuracy": 0.85 }
      }
    """

    PATH = "data/feedback_samples.json"

    def __init__(self):
        self.data = {"good": [], "bad": [], "stats": {}}
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
        self.data["stats"] = {
            "total": total,
            "good_samples": len(good),
            "bad_samples": len(bad),
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
            "image_type": sample.image_type,
            "human_judgment": sample.human_judgment,
            "ai_judgment": sample.ai_judgment,
            "ai_reason": sample.ai_reason[:200],
            "human_note": sample.human_note,
            "screenshot": sample.screenshot,
            "timestamp": sample.timestamp or datetime.now().isoformat(),
        }
        if sample.is_ai_correct():
            self.data["good"].append(entry)
        else:
            self.data["bad"].append(entry)
        self._save()

    def get_stats(self) -> dict:
        """获取当前准确率统计"""
        good = len(self.data["good"])
        bad = len(self.data["bad"])
        total = good + bad
        return {
            "total": total,
            "correct": good,
            "wrong": bad,
            "accuracy": f"{good/total*100:.1f}%" if total else "N/A",
        }

    def get_bad_patterns(self) -> list[str]:
        """分析高频错误模式"""
        patterns = {}
        for entry in self.data["bad"]:
            key = entry["image_type"] or "未分类"
            patterns[key] = patterns.get(key, 0) + 1
        return [f"{k}: {v}次" for k, v in sorted(patterns.items(), key=lambda x: -x[1])]

    def build_fewshot_prompt(self, max_samples: int = 3) -> str:
        """用反馈样本构建 few-shot prompt 前缀"""
        good = self.data["good"][-max_samples:]
        bad = self.data["bad"][-max_samples:]

        parts = []
        if good:
            parts.append("以下是之前审查通过的题目示例（供参考）:")
            for g in good:
                parts.append(f"  ✅ Q{g['question_id']}: {g['human_note'][:80]}")
        if bad:
            parts.append("\n以下是之前审查不通过的题目示例（请注意避免类似错误）:")
            for b in bad:
                parts.append(f"  ❌ Q{b['question_id']}: AI判断='{b['ai_judgment']}', 实际='{b['human_judgment']}', 原因: {b['human_note'][:80]}")

        return "\n".join(parts) + "\n" if parts else ""


# ============================================================
# Skill 注册
# ============================================================

def save_as_skill():
    """将反馈数据导出为 Skill 配置, 供审查引擎加载"""
    store = FeedbackStore()
    stats = store.get_stats()
    fewshot = store.build_fewshot_prompt(5)

    skill_content = f"""# 英语宝听力专项审查 Skill

## 审查配置

- 审查类型: 配图检查 + 作答检查
- 目标模块: APP 听力专项（基础巩固/综合进阶/难点突破）
- 脚本来源: 公司 DOCX
- 视觉模型: qwen3.7-plus

## 反馈统计

- 总样本: {stats['total']} 题
- AI 准确率: {stats['accuracy']}
- 高频错误: {', '.join(store.get_bad_patterns())}

## Few-shot 示例

{fewshot}

## 审查流程

1. 解析 DOCX → 提取 160 题的脚本数据
2. 匹配截图 (q{{global_idx}}.png)
3. 配图题: qwen3.7-plus 看图对比
4. 非配图题: 跳过视觉检查
5. 作答检查: 标注"无手机跳过"

## 注意事项

- 听音选择图片 / 听音判断图片 / 听音匹配图片 这 56 题需要配图对比
- 听音选择词汇 / 句子 / 释义 / 答语 / 判断信息 这 104 题不需要配图
- 听力专项在 APP 中通过左右滑动切换三个阶段
"""

    Path("data/review_skill.md").write_text(skill_content, encoding="utf-8")
    print(f"✅ Skill 已保存到 data/review_skill.md")
    print(f"   准确率: {stats['accuracy']}")
    print(f"   样本: {stats['total']} 条 (正确{stats['correct']}, 错误{stats['wrong']})")
    return skill_content


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--add", nargs=4, metavar=("QID","HUMAN","AI","NOTE"),
                   help="添加一条反馈: QID 人工判断 AI判断 备注")
    p.add_argument("--stats", action="store_true", help="查看统计")
    p.add_argument("--skill", action="store_true", help="生成 Skill 文件")
    args = p.parse_args()

    store = FeedbackStore()

    if args.add:
        s = FeedbackSample(
            question_id=args.add[0],
            human_judgment=args.add[1],
            ai_judgment=args.add[2],
            human_note=args.add[3],
        )
        store.add(s)
        print(f"✅ 添加反馈: {s.question_id}")

    if args.stats:
        print(json.dumps(store.get_stats(), ensure_ascii=False, indent=2))

    if args.skill:
        save_as_skill()
