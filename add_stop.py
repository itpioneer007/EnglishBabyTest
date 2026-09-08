# -*- coding: utf-8 -*-
import io

def patch(path, loop_anchor, indent=4):
    """在 loop_anchor 后插入停止检查"""
    with io.open(path, encoding='utf-8') as f:
        c = f.read()
    # 1. 导入 should_stop
    if 'should_stop' not in c:
        if 'from common.logger import step_log' in c:
            c = c.replace('from common.logger import step_log',
                          'from common.logger import step_log, should_stop')
        else:
            c = c.replace('from common.tools import (',
                          'from common.logger import should_stop\nfrom common.tools import (')
    # 2. 在循环锚点后插入停止检查
    stop_code = (' ' * indent + '# \u2605 \u505c\u6b62\u68c0\u67e5\uff1aweb_server \u6536\u5230\u505c\u6b62\u8bf7\u6c42 \u2192 \u4e2d\u65ad\n'
                 + ' ' * indent + 'if should_stop():\n'
                 + ' ' * (indent+4) + 'step_log("\u23f9 \u6536\u5230\u505c\u6b62\u8bf7\u6c42\uff0c\u4e2d\u65ad\u5f53\u524d\u6a21\u5757", "warning")\n'
                 + ' ' * (indent+4) + 'return q if "q" in dir() else 0\n')
    idx = c.find(loop_anchor)
    if idx == -1:
        print('  ! %s: not found %r' % (path, loop_anchor))
        return
    line_end = c.find('\n', idx)
    c = c[:line_end+1] + stop_code + c[line_end+1:]
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(c)
    print('  ok %s' % path)

patch('scripts/modules/\u53e3\u8bed\u8bad\u7ec3.py', 'for _ in range(15):  # \u6700\u591a15\u5c0f\u9898', indent=4)
patch('scripts/modules/\u5de7\u8bb0\u5355\u8bcd.py', '    while True:', indent=4)

with io.open('scripts/modules/\u8bed\u97f3\u8bc4\u6d4b.py', encoding='utf-8') as f:
    vc = f.read()
for anchor in ['while True:', 'for _ in range(', 'for i in range(']:
    if anchor in vc:
        print('  voice anchor: %r' % anchor)
        patch('scripts/modules/\u8bed\u97f3\u8bc4\u6d4b.py', anchor, indent=4)
        break
