"""课件成本测试：跑通「脚本生成 + python-pptx 排版」两段，观察余额是否变化。

复用 7 月牛顿定律课件里已生成的配图（不触发 ImageGen，避免消耗平台积分），
只验证：本地排版段是否花钱、以及整条链路里哪些步骤才是真正的计费点。
"""
import io
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "outputs" / "cost_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PPTX = OUT_DIR / "课件成本测试.pptx"
IMG_DIR = Path("C:/Users/19507/WorkBuddy/2026-07-20-10-06-51/resources/images")

BLUE = RGBColor(0x1E, 0x4F, 0xA8)
DARK = RGBColor(0x0E, 0x3F, 0x8C)
FONT = "Microsoft YaHei"

PAGES = [
    ("牛顿运动定律", "第一章 · 惯性", "inertia_experiment.png",
     ["一切物体在没有受到外力作用时，总保持静止或匀速直线运动状态。",
      "惯性是物体的固有属性，只与质量有关。",
      "质量越大，惯性越大，运动状态越难改变。"]),
    ("牛顿第二定律", "F = m · a", "spring_force_dual.png",
     ["物体的加速度与合外力成正比，与质量成反比。",
      "方向：加速度方向与合外力方向一致。",
      "瞬时性：力与加速度同时产生、同时消失。"]),
    ("课堂小结", "三定律回顾", "newton_lab_hero.png",
     ["第一定律：揭示惯性与力的关系。",
      "第二定律：定量描述力与运动的关系。",
      "第三定律：作用力与反作用力等大、反向、同线。"]),
]


def add_title(slide, text, sub):
    tb = slide.shapes.add_textbox(Inches(0.7), Inches(0.45), Inches(8.6), Inches(0.9))
    p = tb.text_frame.paragraphs[0]
    p.text = text
    p.font.size = Pt(34)
    p.font.bold = True
    p.font.color.rgb = DARK
    p.font.name = FONT
    tb2 = slide.shapes.add_textbox(Inches(0.72), Inches(1.25), Inches(8.6), Inches(0.5))
    p2 = tb2.text_frame.paragraphs[0]
    p2.text = sub
    p2.font.size = Pt(16)
    p2.font.color.rgb = BLUE
    p2.font.name = FONT


def main():
    t0 = time.time()
    print(f"[{datetime.now():%H:%M:%S}] 开始构建课件…")
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    for i, (title, sub, img, bullets) in enumerate(PAGES, 1):
        s = prs.slides.add_slide(blank)
        add_title(s, title, sub)
        ip = IMG_DIR / img
        used_img = False
        if ip.exists():
            s.shapes.add_picture(str(ip), Inches(7.4), Inches(1.9), width=Inches(5.2))
            used_img = True
        tb = s.shapes.add_textbox(Inches(0.75), Inches(2.2), Inches(6.3), Inches(4.2))
        tf = tb.text_frame
        tf.word_wrap = True
        for j, b in enumerate(bullets):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            p.text = "· " + b
            p.font.size = Pt(17)
            p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
            p.font.name = FONT
            p.space_after = Pt(14)
        print(f"  第{i}页 完成（配图: {'复用已有' if used_img else '无'}）  +{time.time()-t0:.2f}s")

    prs.save(str(PPTX))
    size = PPTX.stat().st_size / 1024
    print(f"[{datetime.now():%H:%M:%S}] 已保存 {PPTX.name}（{size:.0f} KB / {len(PAGES)} 页）")
    print(f"总耗时 {time.time()-t0:.2f}s —— 本地排版段未发起任何网络请求")


if __name__ == "__main__":
    main()
