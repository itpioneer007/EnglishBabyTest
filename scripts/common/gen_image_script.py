"""gen_image_script.py — 从图片题截图直接生成脚本（命令行工具）

用途：听力专项/口语训练等图片题模块的脚本生成——
     遍历答题时保存的 screenshots/script_imgs/ 截图，
     用视觉模型识别每题图片内容 → 生成含完整选项描述的 DOCX 脚本。

用法：
  python scripts/common/gen_image_script.py --img-dir screenshots/script_imgs \\
      --module 听力专项 --version 湘少版 --grade 五年级上册 --unit 6

  # 或指定单张截图
  python scripts/common/gen_image_script.py --img a.png --unit 6

输出：gen_scripts/ 下规范命名 docx（日期+版本+年级+模块+U单元）
"""
import os
import sys
import argparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))


def main():
    ap = argparse.ArgumentParser(description="从图片题截图生成脚本（视觉识别）")
    ap.add_argument("--img-dir", default="screenshots/script_imgs",
                    help="图片题截图目录（默认 screenshots/script_imgs）")
    ap.add_argument("--img", default="", help="单张截图路径（与 --img-dir 二选一）")
    ap.add_argument("--module", default="听力专项", help="模块名（默认听力专项）")
    ap.add_argument("--version", default="湘少版", help="教材版本")
    ap.add_argument("--grade", default="五年级上册", help="年级")
    ap.add_argument("--unit", type=int, default=6, help="单元号")
    ap.add_argument("--qtype", default="听音选择图片", help="题型提示（默认听音选择图片）")
    args = ap.parse_args()

    imgs = []
    if args.img:
        if not os.path.exists(args.img):
            print(f"❌ 截图不存在: {args.img}")
            sys.exit(1)
        imgs = [(1, args.img)]
    else:
        img_dir = args.img_dir
        if not os.path.isabs(img_dir):
            img_dir = os.path.join(_PROJECT_ROOT, img_dir)
        if not os.path.exists(img_dir):
            print(f"❌ 截图目录不存在: {img_dir}\n（请先跑答题遍历生成图片题截图，或 --img 指定单张）")
            sys.exit(1)
        files = sorted(f for f in os.listdir(img_dir)
                       if f.lower().endswith((".png", ".jpg", ".jpeg")))
        if not files:
            print(f"❌ 截图目录为空: {img_dir}")
            sys.exit(1)
        for i, f in enumerate(files, 1):
            imgs.append((i, os.path.join(img_dir, f)))

    print(f"🖼 找到 {len(imgs)} 张图片题截图，开始视觉识别…")

    # 用 QuestionCollector 收集 + finish_unit 生成（内含视觉识别补全+LLM知识点）
    from common.gen_script import QuestionCollector
    coll = QuestionCollector(module=args.module, version=args.version,
                             grade=args.grade)
    coll.gen_allowed = True  # 听力专项等默认不在白名单，此处命令行显式允许

    for qno, img in imgs:
        coll.add(qno=qno, stem="", options=[], answer="", qtype=args.qtype,
                 unit=args.unit, image_path=img)

    if not coll.questions:
        print("❌ 无有效题目可生成（截图可能不是题目画面）")
        sys.exit(1)

    path = coll.finish_unit(unit=args.unit)
    if path:
        print(f"\n✅ 脚本生成: {path}")
    else:
        print("\n❌ 脚本生成失败")


if __name__ == "__main__":
    main()
