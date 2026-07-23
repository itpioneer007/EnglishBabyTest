"""
run_review.py — 一键审查脚本

用法:
    python run_review.py

前置准备:
    1. 编辑 llm_config.json，填入你的 API key
    2. 公司题目文件放在 data/ 目录下（.json / .xlsx / .csv）
    3. 每题的截图放在 screenshots/ 目录下，命名规则:
       screenshots/
       ├── q01.png
       ├── q02.png
       ├── q03.png
       └── ...

运行后会生成:
    outputs/review_report.json   ← 审查报告
    outputs/review_report.md    ← Markdown 可读报告
"""

import json
import time
import sys
from pathlib import Path

# 加 src 路径
sys.path.insert(0, str(Path(__file__).parent))

from src.reviewer_common import LLMClient, QuestionLoader, CheckItem, Question
from src.reviewer_media import MediaReviewer


def find_screenshots(screenshot_dir: str) -> dict:
    """扫描截图文件夹，返回 {题号: 文件路径} 映射"""
    folder = Path(screenshot_dir)
    if not folder.exists():
        return {}

    mapping = {}
    for f in sorted(folder.glob("q*.png")):
        # 支持 q01.png, q1.png, q001.png 等命名
        num_part = f.stem.replace("q", "").replace("Q", "")
        try:
            num = int(num_part)
            mapping[num] = str(f)
        except ValueError:
            pass
    return mapping


def review_questions(questions_file: str, screenshot_dir: str):
    """执行审查主流程"""
    print("=" * 60)
    print("🔍 题目审查智能体")
    print("=" * 60)

    # 1. 加载题目
    print(f"\n📂 加载题目文件: {questions_file}")
    questions = QuestionLoader.load(questions_file)
    print(f"   共 {len(questions)} 道题")

    # 2. 加载截图
    screenshots = find_screenshots(screenshot_dir)
    print(f"\n📸 加载截图: {screenshot_dir}/")
    print(f"   共 {len(screenshots)} 张截图")
    for idx, path in sorted(screenshots.items())[:5]:
        print(f"   Q{idx:02d} → {Path(path).name}")
    if len(screenshots) > 5:
        print(f"   ... 还有 {len(screenshots)-5} 张")

    # 3. 连接 LLM
    print(f"\n🤖 连接 LLM...")
    try:
        llm = LLMClient.from_config()
        if not llm.api_key:
            print("   ❌ 未配置 API key！")
            print("   请编辑 llm_config.json，填入 api_key")
            return
        print(f"   ✅ 模型: {llm.model}")
        print(f"   ✅ 地址: {llm.base_url}")
    except Exception as e:
        print(f"   ❌ 配置读取失败: {e}")
        return

    # 4. 创建审查器
    reviewer = MediaReviewer(llm=llm)
    print(f"\n🔄 开始逐题审查...\n")

    # 5. 逐题审查
    results = []
    for i, q in enumerate(questions):
        qid = q.idx
        shot = screenshots.get(qid)

        img_result = CheckItem(name="(3)配图检查", passed=False, error="无截图")
        ans_result = CheckItem(name="(4)作答检查", passed=False, error="无截图")

        if shot:
            try:
                print(f"  Q{qid:02d}: ", end="", flush=True)
                img_result = reviewer.check_image(q, shot)
                ans_result = reviewer.check_answer(q, shot)
                icon = "✅" if img_result.passed and ans_result.passed else "⚠"
                print(f"{icon} 配图={'✅' if img_result.passed else '❌'} 作答={'✅' if ans_result.passed else '❌'}")
            except Exception as e:
                print(f"❌ 审查失败: {e}")
                img_result.error = str(e)
                ans_result.error = str(e)
        else:
            print(f"  Q{qid:02d}: ⚠ 无截图，跳过")

        results.append({
            "idx": qid,
            "stem": q.stem,
            "image": img_result.to_dict(),
            "answer": ans_result.to_dict(),
        })

    # 6. 保存报告
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)

    # JSON 报告
    json_path = out_dir / "review_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"total": len(results), "results": results}, f, ensure_ascii=False, indent=2)

    # Markdown 报告
    md_path = out_dir / "review_report.md"
    _write_markdown_report(md_path, results)

    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r["image"]["passed"] and r["answer"]["passed"])
    print(f"✅ 审查完成: {passed}/{len(results)} 题通过")
    print(f"📊 JSON 报告: {json_path}")
    print(f"📄 MD  报告: {md_path}")


def _write_markdown_report(path: Path, results: list):
    """生成 Markdown 可读报告"""
    lines = [
        "# 题目审查报告",
        f"\n**审查时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**审查数量**: {len(results)} 题\n",
        "---\n",
    ]

    passed_count = 0
    for r in results:
        img = r["image"]
        ans = r["answer"]
        img_ok = img["passed"]
        ans_ok = ans["passed"]
        all_ok = img_ok and ans_ok
        if all_ok:
            passed_count += 1

        icon = "✅" if all_ok else "⚠"
        lines.append(f"## Q{r['idx']:02d} {icon}\n")
        lines.append(f"**题目**: {r.get('stem', '(无)')[:60]}  \n")

        lines.append(f"### (3) 配图检查: {'✅ 通过' if img_ok else '❌ 不通过'}")
        for d in img.get("details", []):
            lines.append(f"- {d}")
        if img.get("error"):
            lines.append(f"- ❌ 错误: {img['error']}")
        lines.append("")

        lines.append(f"### (4) 作答检查: {'✅ 通过' if ans_ok else '❌ 不通过'}")
        for d in ans.get("details", []):
            lines.append(f"- {d}")
        if ans.get("error"):
            lines.append(f"- ❌ 错误: {ans['error']}")
        lines.append("\n---\n")

    lines.insert(3, f"**通过率**: {passed_count}/{len(results)} ({passed_count/len(results)*100:.0f}%)\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="题目审查智能体")
    parser.add_argument("--questions", default="data/sample_questions.json",
                        help="题目文件路径 (.json/.xlsx/.csv)")
    parser.add_argument("--screenshots", default="screenshots",
                        help="截图文件夹路径")
    args = parser.parse_args()

    review_questions(args.questions, args.screenshots)
