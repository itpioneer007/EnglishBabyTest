import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reviewer_text import TextReviewer
from src.reviewer_common import Question


class StubLLM:
    def __init__(self):
        self.calls = []

    def ask(self, prompt, image_path=None):
        self.calls.append((prompt, image_path))
        if "知识性" in prompt:
            return "通过"
        if "逻辑" in prompt:
            return "通过"
        return "通过"


def test_text_reviewer_supports_global_idx_and_script_content(tmp_path):
    screenshot = tmp_path / "q001.png"
    screenshot.write_bytes(b"fake")

    script_q = SimpleNamespace(
        idx=1,
        global_idx=1,
        stem="What is your name?",
        content="A. Tom\nB. Jack\nC. Lily",
        correct_answer="Tom",
        knowledge_points=["name"],
        question_type="选择题",
    )

    question = SimpleNamespace(
        idx=1,
        global_idx=1,
        stem="What is your name?",
        content="A. Tom\nB. Jack\nC. Lily",
        correct_answer="Tom",
        question_type="选择题",
        knowledge_points=["name"],
    )

    reviewer = TextReviewer(StubLLM(), [script_q])
    stem_result = reviewer.check_stem(question, str(screenshot), ocr_text="What is your name?")
    content_result = reviewer.check_content(question, str(screenshot), all_text="A. Tom\nB. Jack\nC. Lily")

    assert stem_result.passed is True
    assert content_result.passed is True
    assert any("脚本相符" in detail for detail in content_result.details)
    assert any("显示完整" in detail for detail in content_result.details)
