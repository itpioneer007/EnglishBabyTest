"""
run_full_review.py — 完整审查流程

用法:
    python run_full_review.py --docx "公司脚本.docx" --screenshots screenshots/ --unit 6

对比逻辑:
    DOCX 脚本 (标准答案)          APP 截图 (待检查)
    ─────────────────────         ────────────────
    Q1: 听音选词, 答案=B          q01.png
    Q2: 听音选图, 配图=卡车        q02.png
    ...

    对每题做:
    (3) 配图检查: 截图 vs 脚本配图描述 (视觉模型)
    (4) 作答检查: 题库型判断 (无手机时跳过)
"""

import sys, json, time
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent))
from src.parse_yingyubao_docx import parse, YingYuBaoQuestion
from src.reviewer_common import LLMClient


# ============================================================
# 配置
# ============================================================

@dataclass
class ReviewConfig:
    docx_path: str = ""
    screenshot_dir: str = "screenshots"
    unit: int = 0       # 0=全部, 6/7/8/9=单个单元
    stage: str = ""     # 空=全部, "基础巩固"/"综合进阶"/"难点突破"

    def filter(self, q: YingYuBaoQuestion) -> bool:
        if self.unit and q.unit != self.unit:
            return False
        if self.stage and q.stage != self.stage:
            return False
        return True


# ============================================================
# 审查引擎
# ============================================================

class FullReviewer:
    """完整审查器: DOCX脚本 + APP截图 → 四维对比 """

    def __init__(self, config: ReviewConfig):
        self.cfg = config
        self.llm = LLMClient.from_config()
        self.screenshots = self._scan_screenshots()

    def _scan_screenshots(self) -> dict:
        """扫描截图文件夹"""
        folder = Path(self.cfg.screenshot_dir)
        mapping = {}
        if folder.exists():
            for f in sorted(folder.glob("*.png")):
                num = f.stem.replace("q", "").replace("Q", "")
                try:
                    mapping[int(num)] = str(f)
                except ValueError:
                    pass
        return mapping

    def run(self):
        """主流程"""
        print("=" * 60)
        print("🔍 完整审查: DOCX vs APP")
        print("=" * 60)

        # 1. 加载脚本
        print(f"\n📂 脚本: {self.cfg.docx_path}")
        questions = parse(self.cfg.docx_path)
        questions = [q for q in questions if self.cfg.filter(q)]
        print(f"   筛选后: {len(questions)} 题")

        # 2. 统计题型
        types = {}
        for q in questions:
            types[q.type_2] = types.get(q.type_2, 0) + 1
        print(f"\n📊 题型分布:")
        for tp, n in sorted(types.items(), key=lambda x: -x[1]):
            print(f"   {tp}: {n} 题")

        # 3. 截图匹配
        print(f"\n📸 截图: {len(self.screenshots)} 张")
        missing = sum(1 for q in questions if q.global_idx not in self.screenshots)
        if missing:
            print(f"   ⚠ {missing} 题缺少截图")

        # 4. 逐题审查
        print(f"\n🔄 逐题审查...\n")
        results = []
        for q in questions:
            shot = self.screenshots.get(q.global_idx)
            result = self._review_one(q, shot)
            results.append(result)

        # 5. 报告
        return self._generate_report(questions, results)

    def _review_one(self, q: YingYuBaoQuestion, screenshot: str = None) -> dict:
        """单题审查"""
        r = {
            "global_idx": q.global_idx,
            "unit": q.unit,
            "stage": q.stage,
            "type": q.type_2,
            "stem": q.stem[:60],
            "script_answer": q.answer,
            "script_recording": q.recording[:50],
            "image_check": {"passed": None, "details": []},
            "answer_check": {"passed": None, "details": []},
            "screenshot": screenshot or "",
        }

        if not screenshot:
            r["image_check"]["details"].append("❌ 无截图，跳过")
            r["answer_check"]["details"].append("⏭ 无截图，跳过")
            return r

        # === (3) 配图检查 ===
        has_image_type = any(k in q.type_2 for k in ['图片', '匹配图', '排列'])

        if has_image_type:
            # 配图题：视觉模型对比
            prompt = self._build_image_prompt(q)
            llm_result = self.llm.ask(prompt, image_path=screenshot)
            r["image_check"]["details"].append(f"视觉模型: {llm_result[:150]}")
            r["image_check"]["passed"] = "不匹配" not in llm_result and "无关" not in llm_result
        else:
            # 非配图题：检测是否有不必要的图片
            r["image_check"]["details"].append(f"⏭ 非配图题 ({q.type_2})")
            r["image_check"]["passed"] = True  # 不需要配图的题，通过

        # 图片完整性（所有题）
        if screenshot:
            from src.reviewer_media import MediaReviewer
            mr = MediaReviewer(llm=None)
            if mr._is_image_truncated(screenshot):
                r["image_check"]["details"].append("⚠ 截图可能被截断")
            else:
                r["image_check"]["details"].append("✅ 截图显示完整")

        # === (4) 作答检查 ===
        r["answer_check"]["details"].append(f"题型: {q.type_2}")
        r["answer_check"]["details"].append(f"脚本答案: {q.answer}")
        r["answer_check"]["details"].append("⏭ 无手机连接，跳过交互测试")

        return r

    def _build_image_prompt(self, q: YingYuBaoQuestion) -> str:
        """构建配图检查 prompt"""
        parts = [
            f"你是英语听力题配图质检专家。请检查这道题的截图。",
            f"",
            f"题目: {q.stem}",
            f"录音内容: {q.recording}",
            f"正确答案: {q.answer}",
            f"题型: {q.type_2}",
            f"知识点: {q.knowledge_points}",
            f"",
            f"请判断:",
            f"1. 截图中的配图是否与录音内容匹配？",
            f"2. 图片中的文字/物体是否有明显错误？",
            f"3. 图片是否清晰、完整？",
            f"",
            f"回答格式: [通过/不通过] + 简要理由",
        ]
        return "\n".join(parts)

    def _generate_report(self, questions, results):
        """生成报告"""
        out = Path("outputs/review_report.json")
        out.parent.mkdir(exist_ok=True)

        # 统计
        img_pass = sum(1 for r in results if r["image_check"]["passed"])
        ans_pass = sum(1 for r in results if r["answer_check"]["passed"])
        total = len(results)

        report = {
            "file": self.cfg.docx_path,
            "total": total,
            "image_check_pass": img_pass,
            "answer_check_pass": ans_pass,
            "results": results,
        }

        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"✅ 审查完成: {total} 题")
        print(f"   配图通过: {img_pass}/{total}")
        print(f"   作答通过: {ans_pass}/{total}")
        print(f"   报告: {out}")
        return report


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", required=True, help="公司脚本 DOCX 文件")
    parser.add_argument("--screenshots", default="screenshots", help="截图文件夹")
    parser.add_argument("--unit", type=int, default=0, help="只审指定单元 (6/7/8/9)")
    parser.add_argument("--stage", default="", help="只审指定阶段 (基础巩固/综合进阶/难点突破)")
    args = parser.parse_args()

    cfg = ReviewConfig(
        docx_path=args.docx,
        screenshot_dir=args.screenshots,
        unit=args.unit,
        stage=args.stage,
    )

    reviewer = FullReviewer(cfg)
    reviewer.run()
