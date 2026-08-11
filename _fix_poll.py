# -*- coding: utf-8 -*-
"""替换废弃 pollStatus 段（451-530）为正确版本"""
lines = open('templates/index.html', encoding='utf-8').read().split('\n')

start = None
for i, l in enumerate(lines):
    if l.strip() == 'async function pollStatus(){':
        start = i
        break

end = None
for j in range(start + 1, len(lines)):
    if '// ====== 文件上传' in lines[j]:
        end = j
        break

new_block = [
'async function pollStatus(){',
'  try{',
"    const s=await(await fetch('/api/status')).json()",
'    const on=s.device_connected',
"    $('devDot').className='w-2.5 h-2.5 rounded-full '+(on?'bg-green-400':'bg-amber-400')",
"    $('devStatus').textContent=on?(s.device_serial||'已连接'):'离线'",
"    $('devMeta').textContent=(s.model||'')+(s.current_version?' · v'+s.current_version:'')",
'    const now=Date.now()',
'    if(now-_devListTs>8000){',
'      _devListTs=now',
"      const dl=await(await fetch('/api/devices')).json()",
"      refreshDevSelect(dl.devices||[], s.device_serial||'')",
'    }',
'    const ts=s.task_status||{}',
'    updateStopBtn(ts.running)',
'    const busy=!!ts.running',
"    $('runBtn').disabled=busy; $('quickBtn').disabled=busy; $('stopBtn2').disabled=!busy",
'    if(ts.running){',
"      $('kitchenPulse').className='w-2.5 h-2.5 rounded-full bg-red-500'",
"      $('kitchenMsg').textContent='检测中… '+(ts.current_task||'')",
'    }else if(!ts.current_task){',
"      $('kitchenPulse').className='w-2.5 h-2.5 rounded-full bg-[#9aa5a0]'",
"      $('kitchenMsg').textContent='就绪，等待开始…'",
"      $('kitchenSub').textContent=''",
'    }',
"    $('taskBadge').textContent=ts.current_task||'空闲'",
'  }catch(e){}',
'  setTimeout(pollStatus,2000)',
'}',
]

lines[start:end] = new_block
open('templates/index.html', 'w', encoding='utf-8').write('\n'.join(lines))
print(f'替换完成: 行{start+1}~{end} → 正确 pollStatus')
