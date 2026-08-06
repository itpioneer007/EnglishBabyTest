"""批量给各模块答题循环加 step_log (修正版)"""
import os
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modules'))

files_updates = {
    '听力专项.py': [
        ('from common.tools import (', 'from common.logger import step_log\nfrom common.tools import ('),
        ('print(f\"      → 选 {opt}\")', 'print(f\"      → 选 {opt}\")\n            step_log(f\"  第{q}题: 选 {opt} → 检查\", \"info\")'),
        ('print(\"      → 查看报告！测试完成\")', 'print(\"      → 查看报告！测试完成\")\n            step_log(f\"📊 测试完成，共{q}题\", \"success\")'),
        ('print(\"      → 下一题(答错)\")', 'print(\"      → 下一题(答错)\")\n            step_log(f\"  答错 → 下一题\", \"warning\")'),
        ('print(\"      → 练习报告（本轮结束）\")', 'print(\"      → 练习报告（本轮结束）\")\n            step_log(f\"📊 练习报告（本轮结束，共{q}题）\", \"success\")'),
    ],
    '单元自检.py': [
        ('from engine import _handle_match_question, _handle_sort_question', 'from common.logger import step_log\nfrom engine import _handle_match_question, _handle_sort_question'),
        ('print(f\"      → 选 {opt}\")', 'print(f\"      → 选 {opt}\")\n            step_log(f\"  第{q}题: 选 {opt} → 检查\", \"info\")'),
        ('print(\"      → 查看报告！单元自检完成\")', 'print(\"      → 查看报告！单元自检完成\")\n            step_log(f\"📊 单元自检完成，共{q}题\", \"success\")'),
        ('print(\"      → 下一题(答错)\")', 'print(\"      → 下一题(答错)\")\n            step_log(f\"  答错 → 下一题\", \"warning\")'),
    ],
    '口语训练.py': [
        ('from common.tools import (', 'from common.logger import step_log\nfrom common.tools import ('),
        ('print(f\"    🎤 点录音 ({pos[0]},{pos[1]})\")', 'print(f\"    🎤 点录音 ({pos[0]},{pos[1]})\")\n        step_log(f\"🎤 点录音\", \"info\")'),
        ('print(f\"    ⏹ 点结束 ({pos[0]},{pos[1]})\")', 'print(f\"    ⏹ 点结束 ({pos[0]},{pos[1]})\")\n        step_log(f\"⏹ 点结束\", \"info\")'),
        ('print(f\"    ➡ 下一题（进入下一大题）\")', 'print(f\"    ➡ 下一题（进入下一大题）\")\n        step_log(f\"➡ 进入下一大题\", \"step\")'),
        ('print(f\"  📝 第{big}大题\")', 'print(f\"  📝 第{big}大题\")\n        step_log(f\"📝 开始第{big}大题\", \"step\")'),
        ('print(f\"    ✅ 交卷按钮出现，点击交卷\")', 'print(f\"    ✅ 交卷按钮出现，点击交卷\")\n        step_log(\"✅ 交卷\", \"success\")'),
        ('print(f\"    🔊 点小喇叭 ({pos[0]},{pos[1]})\")', 'print(f\"    🔊 点小喇叭 ({pos[0]},{pos[1]})\")\n        step_log(f\"🔊 点小喇叭\", \"info\")'),
    ],
}

for fname, updates in files_updates.items():
    with open(fname, 'r', encoding='utf-8') as f:
        content = f.read()
    for old, new in updates:
        if old in content:
            content = content.replace(old, new)
        else:
            print(f'WARN: {fname}: not found: {repr(old[:70])}...')
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'{fname} OK')

print('Done')
