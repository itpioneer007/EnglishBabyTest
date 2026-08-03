# A同学功能测试脚本
import sys
sys.path.insert(0, '.')

print("=" * 60)
print("  A4 — 脚本生成测试")
print("=" * 60)

from src.script_generator import ScriptGenerator
g = ScriptGenerator()
qs = g.generate('新湘鲁六上', 6, '基础巩固')
print(f'\n生成 {len(qs)} 题:\n')
for q in qs[:5]:
    print(f"  Q{q['global_idx']:02d} [{q['type_2']}]")
    print(f"    录音: {q['recording'][:60]}")
    print(f"    答案: {q['answer']}  选项: {q['options']}")
    print()

print("=" * 60)
print("  A1 — 答错后检查测试")
print("=" * 60)

from src.post_error_check import PostErrorChecker
from pathlib import Path

shot = 'screenshots/test_question.png'
if not Path(shot).exists():
    shot = 'screenshots/test_result.png'
if not Path(shot).exists():
    shot = 'screenshots/test.png'
if not Path(shot).exists():
    print(f'\n  ⚠ 截图不存在，请把答错后的截图放到 screenshots/ 目录下')
else:
    mock_q = {
        'qid': 'U6-Q01', 'answer': 'B',
        'recording': 'The star is in the sky.',
        'stem': '英语课上，老师在播放一段录音...',
        'type_2': '听音选择词汇',
        'options': ['A. car', 'B. star'],
    }
    c = PostErrorChecker()
    r = c.check(shot, mock_q)
    print(f'\n  passed={r.passed}')
    print(f'  score={r.score}')
    print(f'  details={r.details}')
    print(f'  error={r.error}')

print("\n完成!")
