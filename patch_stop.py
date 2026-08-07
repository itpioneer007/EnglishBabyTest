# -*- coding: utf-8 -*-
import io

p = 'web_server.py'
with io.open(p, encoding='utf-8') as f:
    lines = f.readlines()

# 需要处理的 def _run 行号（从定位结果）
run_lines = [2483, 2543, 2593, 2643, 2688, 2737, 2797]
# 1-based 行号 → 0-based 索引
targets = {ln - 1 for ln in run_lines}

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    if i in targets and line.strip() == 'def _run():':
        # 在 def _run(): 下一行插入线程注册（若还没有）
        if 'register_task_thread' not in ''.join(new_lines[-3:]):
            # 找到函数体缩进
            indent = '    '
            # 找下一行非空确定缩进
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            body_indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())] if j < len(lines) else indent
            new_lines.append(body_indent + '_register_task_thread()  # 记录线程 id，供"立即停止"注入异常\n')

# 在所有 "except Exception as e:" 前插入 "except SystemExit:"（只处理任务线程里的）
out = []
prev_was_run_def = False
for i, line in enumerate(lines):
    out.append(line)
# 重新遍历做 except 插入：查找 except Exception 但前面出现过 _run 定义
# 简化：对所有 "        except Exception as e:"（8空格，函数体内）在其前插 SystemExit
result = []
run_zone = False
for i, line in enumerate(lines):
    if i in targets:
        run_zone = True
    if line.strip().startswith('def ') and not line.strip().startswith('def _run()'):
        # 新函数开始（非_run），退出 run 区
        if run_zone and line.strip() != 'def _run():':
            pass  # 保持 run_zone，直到看到 Thread 启动
    # 简化策略：直接对所有 'except Exception as e:' 前面插 SystemExit（重复无害，但避免重复插）
    if line.strip() == 'except Exception as e:' and not any('except SystemExit:' in x for x in result[-3:]):
        # 插入 SystemExit 捕获（缩进与 except 相同）
        indent = line[:len(line) - len(line.lstrip())]
        result.append(indent + 'except SystemExit:\n')
        result.append(indent + '    log_msg("\u23f9 \u4efb\u52a1\u5df2\u88ab\u7acb\u5373\u505c\u6b62", "warning")\n')
    result.append(line)

with io.open(p, 'w', encoding='utf-8') as f:
    f.writelines(result)
print('done')
