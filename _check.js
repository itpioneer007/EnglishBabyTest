

const $=id=>document.getElementById(id)
function escHtml(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
let logLast=0,_devListTs=0,_lastLogs=0

/* ========== 截图放大 ========== */
function openShotLightbox(src){
  const img=$('shotLbImg')
  if(src) img.src=src
  else{
    const cur=$('screenshotArea').querySelector('img')
    if(cur) img.src=cur.src
  }
  $('shotLightbox').classList.add('open')
}
function closeShotLightbox(){$('shotLightbox').classList.remove('open')}

/* ========== 使用指南 ========== */
function openGuide(){document.getElementById('guideMask').classList.add('open');try{localStorage.setItem('yyb_guide_seen','1')}catch(e){}}
function closeGuide(){document.getElementById('guideMask').classList.remove('open')}

/* ========== Tab 切换（每个 Tab 一屏，避免页面内嵌滚动条） ========== */
function switchTab(n){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active', parseInt(b.dataset.tab)===n))
  const aside=$('tabAside'), main=$('tabMain')
  const on1=(n===1), on2=(n===2), on3=(n===3)
  // Tab1 任务配置：aside 显示（内部两栏布局由 HTML 定义）；其余隐藏
  aside.style.display=on1?'':'none'
  // Tab2/3：main 显示
  main.style.display=on1?'none':''
  // Tab2 运行日志·手机画面：状态条/流程条/日志+截图左右分栏显示；审查结果隐藏
  $('statusSec').style.display=on2?'':'none'
  $('flowStrip').style.display=on2?'':'none'
  $('logShotSec').style.display=on2?'':'none'
  // Tab3 审查结果：全宽显示
  $('revSec').style.display=on3?'':'none'
}

/* ========== 设备轮询 ========== */
async function pollStatus(){
  try{
    const s=await(await fetch('/api/status')).json()
    const on=s.device_connected
    $('devDot').className='w-2.5 h-2.5 rounded-full '+(on?'bg-green-400':'bg-amber-400')
    $('devStatus').textContent=on?(s.device_serial||'已连接'):'离线'
    $('devMeta').textContent=(s.model||'')
    const _selVer=$('setupVersion')?$('setupVersion').value:''
    if(_selVer) $('devMeta').textContent+=($('devMeta').textContent?' · ':'')+'目标: '+_selVer
    const now=Date.now()
    if(now-_devListTs>8000){
      _devListTs=now
      const dl=await(await fetch('/api/devices')).json()
      refreshDevSelect(dl.devices||[], s.device_serial||'')
    }
    const ts=s.task_status||{}
    updateStopBtn(ts.running)
    const busy=!!ts.running
    $('runBtn').disabled=busy; $('quickBtn').disabled=busy; $('stopBtn2').disabled=!busy
    if(ts.running){
      $('kitchenPulse').className='w-2.5 h-2.5 rounded-full bg-red-500'
      $('kitchenMsg').textContent='检测中… '+(ts.current_task||'')
      $('taskBadge').textContent=ts.current_task||'检测中'
    }else{
      // ★ 关键修复：running=False 时一律显示"空闲"，不再残留上一次任务的 current_task
      //   （旧逻辑 else if(!ts.current_task) 在 set_done 未清空 current_task 时会导致
      //   界面停留在旧任务名、既无"运行中"也无"空闲"、停止按钮又隐藏，用户以为卡死）
      $('kitchenPulse').className='w-2.5 h-2.5 rounded-full bg-[#9aa5a0]'
      $('kitchenMsg').textContent='空闲，等待开始…'
      $('kitchenSub').textContent=''
      $('taskBadge').textContent='空闲'
    }
  }catch(e){}
  setTimeout(pollStatus,2000)
}
// ====== 文件上传 ======
async function uploadFile(){
  const f=$('uploadInput').files[0]; if(!f) return
  const fd=new FormData(); fd.append('file',f)
  await fetch('/api/upload',{method:'POST',body:fd})
  loadUploadList()
}


async function uploadViaFileInput(){
  const f=$('fileInput').files[0]; if(!f) return
  const fd=new FormData(); fd.append('file',f)
  try{
    const r=await fetch('/api/upload',{method:'POST',body:fd})
    const j=await r.json().catch(()=>({}))
    if(!r.ok){alert(j.error||'上传失败 ('+r.status+')');$('fileInput').value='';return}
    if(typeof addLog==='function')addLog('success','📤 已上传脚本: '+f.name)
    alert('✅ 上传成功: '+f.name)
  }catch(e){alert('上传失败: '+e.message)}
  $('fileInput').value=''
  loadUploadList()
}

async function loadUploadList(){
  const d=await(await fetch('/api/upload/list')).json()
  $('planDocx').innerHTML=(d.files||[]).map(f=>`<option>${f.name}</option>`).join('')
  $('uploadList').innerHTML=(d.files||[]).length
    ? d.files.map(f=>`<div>${f.name} (${(f.size/1024).toFixed(0)}KB)</div>`).join('')
    : '<span>暂无上传 — 可跳过，AI将自动生成答案</span>'
}

function refreshDevSelect(devs,cur){
  const sel=$('devSelect'),focus=cur||sel.value
  sel.innerHTML='<option value="">选择设备…</option>'+
    devs.map(d=>`<option value="${d.serial}" ${d.serial===focus?'selected':''}>${d.serial}</option>`).join('')
}
async function selectDevice(serial){
  try{
    const r=await fetch('/api/device/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({serial})})
    const j=await r.json()
    if(j.error){alert('设备选择失败: '+j.error);return}
    addLog('info',j.serial?'已切换设备: '+j.serial+'':'已恢复默认设备')
  }catch(e){alert('设备选择失败: '+e.message)}
}

/* ========== 模块标签 ========== */
function refreshModuleSel(){
  const boxes=[...document.querySelectorAll('.mod-sel')]
  const n=boxes.filter(b=>b.checked).length
  $('moduleSelCount').textContent=n
  boxes.forEach(b=>{
    const lb=b.closest('.mod-tag')
    if(lb){
      const on=b.checked
      lb.classList.toggle('bg-[#e8f5ee]',on);lb.classList.toggle('border-[#2d6a4f]',on);lb.classList.toggle('text-[#1b4332]',on);lb.classList.toggle('font-semibold',on)
      lb.classList.toggle('bg-white',!on);lb.classList.toggle('border-[#e6dfd4]',!on);lb.classList.toggle('text-[#3d3226]',!on)
    }
  })
}

/* ========== 单元范围输入（空格/横线/逗号分隔 → 规范范围串） ========== */
/* 输入 "1-5" / "1,3,5" / "1 3 5" / "1-3,5" → "1-5" / "1,3,5" / "1-3,5"；空 → ""（不限） */
function normalizeUnits(str){
  const tokens=String(str||'').split(/[\s,，]+/).filter(Boolean)
  const vals=[]
  const kws=[]
  const KEYWORDS=['期中评价','期末评价','AI检测','期中','期末']
  tokens.forEach(t=>{
    const raw=String(t).trim()
    // ★ 先识别特殊关键词（期中/期末/AI检测等），直接透传给后端
    const hit=KEYWORDS.find(k=>raw===k||raw.includes(k))
    if(hit){ kws.push(hit); return }
    // ★ 兼容 U 前缀（U3/U3-5/U1-U2/第5单元/单元3），剥离后按纯数字解析
    const ts=raw.replace(/[Uu]nit|[Uu]|第|单元/g,'')
    const m=ts.trim().match(/^(\d+)(?:-(\d+))?$/)
    if(!m) return
    const a=parseInt(m[1]),b=m[2]?parseInt(m[2]):a
    for(let u=a;u<=b;u++) vals.push(u)
  })
  const uniq=[...new Set(vals)].sort((a,b)=>a-b)
  const parts=[];let s=uniq[0],p=uniq[0]
  for(let i=1;i<=uniq.length;i++){
    const v=uniq[i]
    if(v===p+1){p=v;continue}
    parts.push(s===p?String(s):`${s}-${p}`)
    s=p=v
  }
  // 数字范围 + 关键词合并
  return [...parts,...kws].join(',')
}
/* 「清空单元」按钮：清空输入框 */
function clearUnitPicks(btn){
  const card=btn.closest('.mod-card')||btn.closest('.mod-tag')
  if(card) card.querySelectorAll('.unit-val').forEach(i=>{i.value=''; if(i.classList.contains('unit-val-t')) i.placeholder='点此选测评（留空=不测测试）'})
}

/* ========== 日志（点击 + 审查合并流） ========== */
function addLog(level,msg,evidence){
  const t=new Date().toLocaleTimeString()
  const el=$('logWrap')
  const empty=el.querySelector('.log-empty')
  if(empty) empty.style.display='none'
  let html=`<div class="log-item ${level}"><span class="t">${t}</span>${msg}</div>`
  if(evidence && Array.isArray(evidence) && evidence.length){
    html=`<div class="log-item ${level} review-log">`
    html+=`<span class="t">${t}</span>${msg}`
    html+=`<div class="review-evidence">`
    evidence.forEach(e=>{
      const fieldLabel={stem:'题干',content:'内容',answer:'答案',options:'选项',audio:'音频'}[e.field]||e.field
      html+=`<div class="evidence-row ${e.type}">`
      html+=`<span class="evidence-field">${fieldLabel}</span>`
      if(e.diff_html){html+=`<div class="evidence-diff">${e.diff_html}</div>`}
      else if(e.diff){html+=`<div class="evidence-desc">${e.diff}</div>`}
      html+=`<div class="evidence-pair"><span class="exp">预期: ${e.expected||'(无)'}</span><span class="act">实际: ${e.actual||'(无)'}</span></div>`
      html+=`</div>`
    })
    html+=`</div></div>`
  }
  el.innerHTML+=html
  el.scrollTop=el.scrollHeight
}
function checkVersion(v){
  switchTab(2);
  fetch('/api/check/version',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:v})})
    .then(r=>r.json()).then(j=>{
      if(j.error){alert(j.error);}
      else{addLog('info',`已发起检查「${v}」版本，请等待手机自动操作…`);}
    }).catch(e=>alert('启动失败: '+e.message));
}

function clearLog(){
  $('logWrap').innerHTML='<div class="log-empty"><span class="big">▦</span>日志已清空</div>'
  $('serveWrap').innerHTML='';$('serveWrap').style.display='none'
}
async function pollLog(){
  try{
    const d=await(await fetch('/api/log')).json()
    const arr = Array.isArray(d) ? d : (d.logs||[])
    const logs=arr.slice(logLast)
    if(logs.length) logLast+=logs.length
    logs.forEach(l=>addLog(l.level,l.msg,l.evidence))
  }catch(e){}
  setTimeout(pollLog,1500)
}

/* ========== 文件上传 ========== */
async function uploadOrder(e){
  const f=e.target.files[0]
  if(!f) return
  addLog('info','已选择任务清单: '+f.name+' ('+(f.size/1024).toFixed(1)+'KB)')
  const fd=new FormData()
  fd.append('file',f)
  try{
    const r=await fetch('/api/order/parse',{method:'POST',body:fd})
    const j=await r.json()
    if(j.error){
      addLog('warning','清单解析失败: '+j.error)
      alert('清单解析失败: '+j.error)
      return
    }
    $('orderInput').value=j.text
    addLog('success','已提取 '+j.text.length+' 字符，开始自动识别配置…')
    const ok=applyOrder(j.text)
    if(ok){
      addLog('success','✅ 已从清单识别出 版本/年级/模块/单元，核对后点「解析并开始检测」')
      switchTab(1)
    }else{
      addLog('warning','清单中未识别出模块/版本，已把原文填入描述框，可手动调整')
    }
    addLog('info','清单内容: '+j.text.substring(0,300)+(j.text.length>300?'…':''))
  }catch(err){
    addLog('warning','清单上传失败: '+err)
    alert('清单上传失败: '+err)
  }finally{
    e.target.value=''
  }
}

/* ========== 开始检测（多模块执行） ========== */
async function startCooking(){
  const orderText=($('orderInput').value||'').trim()
  if(orderText && /(年级[上下]册|U\d+|单元|听力专项|口语训练|单元自检|知识过关|巧记单词|语音评测)/.test(orderText)){
    applyOrder(orderText)
    addLog('info','已按描述自动配置，可直接开始')
  }
  const version=$('setupVersion').value
  const grade=$('setupGrade').value
  const moduleConfigs=[]
  document.querySelectorAll('.mod-sel:checked').forEach(cb=>{
    const name=cb.value
    const tag=cb.closest('.mod-tag')
    if(!tag) return
    if(name==='听力专项'){
      const pWrap=tag.querySelector('.unit-val-p')
      const tWrap=tag.querySelector('.unit-val-t')
      const pChk=tag.querySelector('input.tingli-part[value="practice"]')
      const tChk=tag.querySelector('input.tingli-part[value="test"]')
      // ★ 练/测 开关：勾选才测；未勾选传 'NONE' 哨兵 → 后端跳过该部分
      const pOn=pChk?pChk.checked:true
      const tOn=tChk?tChk.checked:true
      const pUnits=pOn?(pWrap?normalizeUnits(pWrap.value):''):'NONE'
      // ★ 测试输入框由弹窗生成标准选择器串（如 单元|1-5|A），直接透传给后端，不要 normalizeUnits
      const tUnits=tOn?(tWrap?tWrap.value.trim():''):'NONE'
      moduleConfigs.push({name,units:pUnits,testUnits:tUnits})
    }else{
      const v=tag.querySelector('.unit-val')
      moduleConfigs.push({name,units:v?normalizeUnits(v.value):''})
    }
  })
  if(!moduleConfigs.length){alert('请至少选择一个模块（或在清单中说明）');return}
  const modules=moduleConfigs.map(m=>m.name)
  const unitsMap={}
  moduleConfigs.forEach(m=>{
    if(m.name==='听力专项'){
      // ★ 听力专项始终传"练/测"两个键（NONE=跳过该部分），保证后端能正确判断
      unitsMap['听力专项']=m.units||'NONE'
      unitsMap['听力专项_测试']=m.testUnits||'NONE'
    }else{
      if(m.units) unitsMap[m.name]=m.units
    }
  })
  const hasUnits=Object.keys(unitsMap).length>0
  // ★ 模块 → 上传脚本 自动匹配：有脚本的模块走 LLM 知识性审查，无脚本仅基础完整性
  const docxs=getUploadedDocxs()
  const {v:matchV,g:matchG}=curVersionGrade()
  const docxMap={}
  // ★ 手动选中的脚本（reviewDocx 下拉）作为兜底：自动匹配失败时直接绑
  //   不再做"模块/版本/年级"二次校验——理由：
  //   1. 选错脚本是用户责任，运行前预览（卡片下方"无匹配脚本/有脚本+单元不匹配"）
  //      已经把每个模块的状态显示给用户了，弹窗再警告一遍是废话
  //   2. 匹配失败时静默走基础完整性即可，不需要弹窗警告
  //   3. 真要拦截脚本错配，放在跑完后端（review_agent）发现 0 题时自然告警即可
  const manualDocx=$('reviewDocx')?$('reviewDocx').value:''
  const manualOk=manualDocx&&manualDocx!=='— 尚未上传 —'&&manualDocx!==''
  moduleConfigs.forEach(m=>{
    if(m.name==='听力专项'){
      // 练习/测试分别匹配对应脚本（脚本名需含「练习/测试」字样）
      if(m.units && m.units!=='NONE'){
        let d=matchDocxForModule('听力专项',docxs,matchV,matchG,m.units,'练习')
        if(!d && manualOk && moduleConfigs.length===1) d=manualDocx
        if(d) docxMap['听力专项_练习']=d
      }
      if(m.testUnits && m.testUnits!=='NONE'){
        let d=matchDocxForModule('听力专项',docxs,matchV,matchG,m.testUnits,'测试')
        if(!d && manualOk && moduleConfigs.length===1) d=manualDocx
        if(d) docxMap['听力专项_测试']=d
      }
    }else{
      let _d=matchDocxForModule(m.name,docxs,matchV,matchG,curModuleUnits(m.name))
      if(!_d && manualOk && moduleConfigs.length===1){
        // 单模块：手动脚本直接绑（用户自选，自负责）
        _d=manualDocx
      }
      if(_d) docxMap[m.name]=_d
    }
  })
  let confirmMsg = '确认启动多模块检测？\n'
  confirmMsg += `版本: ${version} | 年级: ${grade}\n`
  confirmMsg += `模块: ${modules.join('、')} (共${modules.length}个)`
  confirmMsg += '\n审查方式: '
  confirmMsg += moduleConfigs.map(m=>{
    if(m.name==='听力专项'){
      const parts=[]
      if(docxMap['听力专项_练习']) parts.push(`练习=LLM(${docxMap['听力专项_练习']})`)
      else if(m.units && m.units!=='NONE') parts.push('练习=基础完整性')
      if(docxMap['听力专项_测试']) parts.push(`测试=LLM(${docxMap['听力专项_测试']})`)
      else if(m.testUnits && m.testUnits!=='NONE') parts.push('测试=基础完整性')
      return `${m.name}(${parts.join('；')})`
    }
    return docxMap[m.name]?`${m.name}=LLM知识性审查(脚本 ${docxMap[m.name]})`:`${m.name}=基础完整性`
  }).join('；')
  if(hasUnits){
    confirmMsg += '\n单元范围: '
    confirmMsg += moduleConfigs.filter(m=>m.units).map(m=>`${m.name}=${m.units}`).join(', ')
  }
  // ★ 弹窗警告原则（2026-08-25 用户定调）：
  //   - 自动匹配失败（本模块本年级本单元无脚本）→ 静默走基础完整性，不警告
  //   - 唯一值得提醒：同模块+同版本 但 不同年级 的脚本存在（说明该模块其他年级有脚本，
  //     当前年级没有 → 提醒用户，可能想切年级或传脚本）
  moduleConfigs.forEach(m=>{
    // 已有匹配脚本 → 不用提醒
    if(m.name==='听力专项' && (docxMap['听力专项_练习'] || docxMap['听力专项_测试'])) return
    if(m.name!=='听力专项' && docxMap[m.name]) return
    const _kws=MOD_KEYWORDS[m.name]||[m.name]
    const _verKws=matchV?(VER_KEYWORDS[matchV]||_verAliases(matchV)):[]
    const _gKws=matchG?(GRADE_KEYWORDS[matchG]||_gradeAliases(matchG)):[]
    const _hasK=d=>_kws.some(k=>d.includes(k))
    const _verOk=d=>!_verKws.length||_verKws.some(k=>d.includes(k))
    const _grOk=d=>!_gKws.length||_gKws.some(k=>d.includes(k))
    // 同模块+同版本、但年级不是当前所选 → 值得提醒
    const _other = docxs.find(d=>_hasK(d)&&_verOk(d)&&!_grOk(d))
    if(_other){
      confirmMsg += `\nℹ️ ${m.name} 当前年级(${matchG||'?'})无匹配脚本，但发现其他年级脚本「${_other}」\n` +
                    `   （如需 LLM 审查请切换年级或上传当前年级脚本，否则仅做基础完整性）`
    }
  })
  if(orderText) confirmMsg += `\n清单描述: "${orderText.substring(0,80)}${orderText.length>80?'…':''}"`
  if(!confirm(confirmMsg)) return
  const btn=$('btnCook')
  btn.disabled=true; btn.innerHTML='检测中…'
  if(orderText){addLog('step','收到清单: '+orderText.substring(0,200)+(orderText.length>200?'…':''))}
  addLog('step','开始分析清单 → 准备调用模块: '+modules.join('、'))
  addLog('info','版本/年级: '+version+' '+grade)
  if(hasUnits) addLog('info','单元范围: '+JSON.stringify(unitsMap))
  try{
    const body=hasUnits
      ? {version,grade,modules,units:unitsMap,docxMap}
      : {version,grade,modules,docxMap}
    const r=await fetch('/api/modules/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    const j=await r.json()
    if(j.error){alert(j.error);btn.disabled=false;btn.innerHTML='解析并开始检测';return}
    addLog('success','任务已启动，共 '+j.modules.length+' 个模块')
    $('serveWrap').innerHTML='';$('serveWrap').style.display='none'
    pollCookResult(modules)
  }catch(e){alert('启动失败: '+e.message);btn.disabled=false;btn.innerHTML='解析并开始检测'}
  finally{setTimeout(()=>{btn.disabled=false;btn.innerHTML='解析并开始检测'},4000)}
}

/* ========== 停止 ========== */
async function stopCooking(){
  const btn=$('btnStop'), btnLog=$('btnStopLog')
  if(btn) btn.disabled=true
  if(btnLog) btnLog.disabled=true
  try{
    const r=await(await fetch('/api/modules/stop',{method:'POST'})).json()
    if(r.message) addLog('warning','停止: '+r.message)
  }catch(e){
    addLog('error','停止请求发送失败: '+e.message)
    if(btn) btn.disabled=false
    if(btnLog) btnLog.disabled=false
  }
}
function updateStopBtn(running){
  const btn=$('btnStop'), btnLog=$('btnStopLog')
  if(btn){
    btn.style.display = running ? 'inline-block' : 'none'
    if(!running) btn.disabled = false
  }
  if(btnLog){
    btnLog.style.display = running ? 'inline-block' : 'none'
    if(!running) btnLog.disabled = false
  }
}

function pollCookResult(modules){
  pollModulesResult(modules)
}

// ====== 多模块检测：结果轮询与汇总展示 ======
async function pollModulesResult(modules){
  let tried=0
  const timer=setInterval(async()=>{
    tried++
    try{
      const r=await(await fetch('/api/modules/result')).json()
      if(r.done&&r.results){
        clearInterval(timer)
        renderServe(r)
      }else if(tried>600){
        clearInterval(timer)
        addLog('warning','任务超时（10分钟），请手动查看设备状态')
      }
    }catch(e){}
  },2000)
}

/* ========== 结果展示 ========== */
async function renderServe(data){
  const rs=data.results||{}
  const names=Object.keys(rs)
  const totalQ=names.reduce((s,n)=>s+(rs[n].q||0),0)
  const okN=names.filter(n=>rs[n].ok).length
  let html='<div class="serve-hdr">检测完成</div><div class="serve-cards">'
  names.forEach(n=>{
    const r=rs[n]; const ok=r.ok
    html+=`<div class="serve-card ${ok?'ok':'fail'}">
      <div class="sc-name">${n}</div>
      <div class="sc-stat"><span class="sc-q">${r.q||0}<small> 题</small></span></div>
      <div class="sc-detail">${ok?'完成':'失败'} · ${r.t||0}s${r.error?' · '+r.error:''}</div>
    </div>`
  })
  html+=`</div><div class="serve-summary" id="serveSummary">
    ${names.length} 个模块 · 成功 <b style="color:var(--ok-ink)">${okN}</b> 个 ·
    累计答题 <b style="color:var(--ok-ink)">${totalQ}</b> 题 · ${data.version||''} ${data.grade||''}
    <span id="errSummary"><span class="animate-pulse inline-block ml-2" style="color:var(--gray)">加载错题…</span></span>
  </div>`
  const el=$('serveWrap')
  el.innerHTML=html
  el.style.display='block'
  el.scrollIntoView({behavior:'smooth'})
  addLog('success','全部完成！'+names.length+'个模块，'+okN+'个成功，累计'+totalQ+'题')

  // 异步加载错题汇总
  try{
    const er=await(await fetch('/api/errors/summary')).json()
    const es=document.getElementById('errSummary')
    if(!es) return
    if(er.error){
      es.innerHTML='<span class="ml-2" style="color:var(--gray);font-size:11px">错题数据不可用</span>'
    }else if(er.has_errors){
      es.innerHTML=`<span class="ml-2" style="color:var(--red);font-weight:600;font-size:12px">
        不通过 <b>${er.failed_count}/${er.total_questions}</b> 题</span>
        <span class="ml-2 text-[11px] px-2 py-0.5 rounded-lg border border-[#bc4742] text-[#bc4742] cursor-pointer hover:bg-[#fce4e4]" style="font-weight:500"
          onclick="switchTab(3);document.getElementById('wrongBadge')&&document.getElementById('wrongBadge').scrollIntoView({behavior:'smooth',block:'center'})">去错题日志看 →</span>`
    }else{
      es.innerHTML=`<span class="ml-2" style="color:var(--ok-ink);font-weight:600;font-size:12px">全部通过 ✓</span>`
    }
  }catch(e){ /* 静默处理 */ }
}

/* ========== 版本×年级配置表 ========== */
let GRADE_TABLE=null, gradesLoaded=false
async function loadGradeTable(){
  try{
    const r=await fetch('/api/version-grades')
    const d=await r.json()
    if(r.ok && d.table){
      GRADE_TABLE=d.table
      const gl=document.getElementById('gradeLoading')
      if(gl) gl.textContent='配置表就绪'
      renderGrades($('setupVersion').value, true)
      return
    }
    throw new Error(d.error||'无配置表')
  }catch(e){
    addLog('warning','配置表未加载，改用动态读取: '+e.message)
    loadGrades('', true)
  }
}
function renderGrades(version, silent){
  const sel=document.getElementById('setupGrade')
  const gl=document.getElementById('gradeLoading')
  if(GRADE_TABLE && GRADE_TABLE[version]){
    const info=GRADE_TABLE[version]||{}
    const grades=info.grades||[]
    if(grades.length){
      sel.innerHTML=grades.map(g=>`<option${g===info.current?' selected':''}>${g}</option>`).join('')
      if(gl) gl.textContent=` 已同步${grades.length}个`
      sel.disabled=false
      gradesLoaded=true
      return true
    }
  }
  loadGrades(version, silent)
  return false
}
async function loadGrades(version, silent){
  const gl=document.getElementById('gradeLoading')
  const sel=document.getElementById('setupGrade')
  if(!silent && gl) gl.textContent='读取中…'
  sel.disabled=true
  try{
    const r=await fetch('/api/version-grades/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:version||''})})
    const d=await r.json()
    if(!r.ok) throw new Error(d.error||'读取失败')
    const grades=d.grades||[]
    if(!grades.length) throw new Error('App 返回空年级列表')
    sel.innerHTML=grades.map(g=>`<option${g===d.current_grade?' selected':''}>${g}</option>`).join('')
    if(gl) gl.textContent=` 已同步App（${grades.length}个）`
    gradesLoaded=true
  }catch(e){
    sel.innerHTML='<option selected>五年级上册</option><option>五年级下册</option><option>六年级上册</option><option>六年级下册</option><option>四年级下册</option><option>三年级下册</option>'
    if(gl) gl.textContent=' !读取失败，用默认'
    addLog('warning','动态年级读取失败: '+e.message)
  }finally{
    sel.disabled=false
  }
}

/* ========== 自然语言解析 ========== */
const MODULE_NAMES=['听力专项','口语训练','单元自检','知识过关','巧记单词','语音评测']
const VERSION_ALIAS={
  '湘少版(2024审定)':'湘少版(2024审定)','湘少（2024审定）':'湘少版(2024审定)','湘少(2024审定)':'湘少版(2024审定)','湘少2024审定':'湘少版(2024审定)',
  '湘少版':'湘少版','湘教':'湘少版','湘少':'湘少版',
  '人教PEP':'人教版(PEP)','人教版(PEP)':'人教版(PEP)','人教PEP版':'人教版(PEP)',
  '外研版(三起)':'外研版(三起)','外研三起':'外研版(三起)','外研版':'外研版(三起)',
  '外研版(一起)':'外研版(一起)','外研一起':'外研版(一起)',
  '人教版':'人教版','人教':'人教版',
  '湘鲁':'湘鲁版（2024审定）','湘鲁版（2024审定）':'湘鲁版（2024审定）','湘鲁（2024审定）':'湘鲁版（2024审定）','湘鲁2024审定':'湘鲁版（2024审定）','湘鲁版2024审定':'湘鲁版（2024审定）','湘鲁版(2024审定)':'湘鲁版（2024审定）',
  '冀教':'冀教版','教科':'教科版','陕旅':'陕旅版','新概念':'新概念青少版','通用':'通用'
}
function parseOrder(text){
  const res={version:'',grade:'',modules:[]}
  if(!text) return res
  let bestV='',bestLen=0
  for(const k in VERSION_ALIAS){
    if(text.includes(k) && k.length>bestLen){bestLen=k.length;bestV=VERSION_ALIAS[k]}
  }
  res.version=bestV
  const gm=text.match(/([一二三四五六]年级[上下]册)/)
  if(gm) res.grade=gm[1]
  const pos=[]
  for(const name of MODULE_NAMES){
    let p=text.indexOf(name)
    while(p!==-1){pos.push({idx:p,name});p=text.indexOf(name,p+name.length)}
  }
  pos.sort((a,b)=>a.idx-b.idx)
  const units=[]
  // ★ 中文数字单元归一化：第二单元/单元二/二单元/第2单元/单元2/2单元/unit 2/Unit2 → 统一解析
  const _cnNum={一:1,二:2,两:2,三:3,四:4,五:5,六:6,七:7,八:8,九:9,十:10}
  const _cnN2={一:1,二:2,两:2,三:3,四:4,五:5,六:6,七:7,八:8,九:9,十:10}
  // ★ 归一化：只在"单元"上下文转换，绝不误伤年级等普通文本
  //   ① 英文 unit n（词边界）→ 第n单元
  //   ② 第X单元 / X单元 / 单元X（X可为中文数字或阿拉伯数字）→ 第N单元
  const _normUnitTxt=String(text)
    .replace(/\b(?:unit|Unit|UNIT)\s*(\d+)\b/g,'第$1单元')
    .replace(/(?:第)?([一二三四五六七八九十两]+)\s*单元/g,function(_m,_a){return '第'+(_cnN2[_a[0]]||_a)+'单元'})
    .replace(/单元\s*([一二三四五六七八九十两]+)/g,function(_m,_a){return '第'+(_cnN2[_a[0]]||_a)+'单元'})
    .replace(/(?<![A-Za-z\d第])(\d+)\s*单元/g,'第$1单元')
    .replace(/单元\s*(?![A-Za-z])(\d+)/g,'第$1单元')
  const ure=/U(\d+)(?:\s*[-到至]\s*(?:U)?(\d+))?|第\s*([0-9一二三四五六七八九十两]+)\s*单元(?:\s*[-到至]\s*(?:第)?\s*([0-9一二三四五六七八九十两]+))?/gi
  let um
  while((um=ure.exec(_normUnitTxt))!==null){
    const _f=String(um[3]||'').replace(/[一二三四五六七八九十两]/g,ch=>_cnNum[ch]||ch)
    const _t=String(um[4]||'').replace(/[一二三四五六七八九十两]/g,ch=>_cnNum[ch]||ch)
    units.push({idx:um.index,from:um[1]||_f,to:um[2]||_t})
  }
  for(const p of pos){
    const m={name:p.name,units:'',testUnits:'',sub:''}
    // ★ 收集本模块与下一模块之间的所有U号(空格分隔=多个独立单元; 连字符/到/至=区间)
    const nextPos=pos.find(q=>q.idx>p.idx)
    const segEnd=nextPos?nextPos.idx:text.length
    const segUnits=units.filter(u=>u.idx>p.idx && u.idx<segEnd).sort((a,b)=>a.idx-b.idx)
    if(segUnits.length){
      m.units=segUnits.map(u=>u.to?`${u.from}-${u.to}`:`${u.from}`).join(' ')
    }
    const seg=text.slice(p.idx, segEnd)
    if(!m.units){
      for(const kw of ['期中评价','期末评价','期中','期末','AI检测']){
        if(seg.includes(kw)){m.units=kw;break}
      }
    }
    if(p.name==='听力专项'){
      const after=text.slice(p.idx)
      const hasTest=/测试|测验/.test(after), hasPractice=/练习/.test(after)
      if(hasTest && !hasPractice){m.testUnits=m.units;m.units=''}
      else if(hasTest && hasPractice){
        // ★ 练习+测试混合: 按'测试/测验'后的U归测, 之前的归练
        const tm=after.match(/测试|测验/)
        if(tm){const tIdx=tm.index;const testPart=after.slice(tIdx)
          const uu=m.units.split(' ').map(x=>parseInt(x,10)).filter(n=>!isNaN(n))
          const tU=uu.filter(n=>testPart.includes('U'+n)||testPart.includes('u'+n)||testPart.includes('第'+n+'单元')||testPart.includes('单元'+n)||testPart.includes(' '+n))
          const pU=uu.filter(n=>!tU.includes(n))
          m.testUnits=tU.join(' ');m.units=pU.join(' ')
        }
      }
      for(const s of ['基础巩固','综合进阶','难点突破']){
        if(after.includes(s)){m.sub=s;break}
      }
    }
    res.modules.push(m)
  }
  return res
}
function applyOrder(text){
  const r=parseOrder(text)
  if(!r.version && !r.grade && !r.modules.length){
    addLog('warning','未从描述中识别出版本/年级/模块，请检查表述')
    return false
  }
  if(r.version){
    const sv=$('setupVersion')
    if([...sv.options].some(o=>o.value===r.version)){
      sv.value=r.version
      renderGrades(r.version,true)
      addLog('info','识别版本: '+r.version)
    }else{
      addLog('warning','识别到版本但不在列表: '+r.version)
    }
  }
  if(r.grade){
    const sg=$('setupGrade')
    if([...sg.options].some(o=>o.value===r.grade)){
      sg.value=r.grade
      addLog('info','识别年级: '+r.grade)
    }else{
      addLog('warning','识别到年级但不在该版本列表: '+r.grade)
    }
  }
  if(r.modules.length){
    document.querySelectorAll('.mod-sel').forEach(cb=>{cb.checked=false;cb.closest('.mod-tag').classList.remove('on')})
    r.modules.forEach(m=>{
      const cb=document.querySelector(`.mod-sel[value="${m.name}"]`)
      if(!cb) return
      cb.checked=true
      cb.closest('.mod-tag').classList.add('on')
      const tag=cb.closest('.mod-tag')
      if(m.name==='听力专项' && tag){
        const pWrap=tag.querySelector('.unit-val-p')
        const tWrap=tag.querySelector('.unit-val-t')
        const pChk=tag.querySelector('input.tingli-part[value="practice"]')
        const tChk=tag.querySelector('input.tingli-part[value="test"]')
        // ★ 练/测勾选同步: 有练习单元→勾练; 有测试单元→勾测; 没有则取消(避免默认勾全)
        if(pChk) pChk.checked=!!m.units
        if(tChk) tChk.checked=!!m.testUnits
        if(pWrap && m.units) pWrap.value=m.units
        if(tWrap && m.testUnits) tWrap.value=m.testUnits
      }else{
        const v=tag?tag.querySelector('.unit-val'):null
        if(v && m.units) v.value=m.units
      }
      addLog('info','识别模块: '+m.name+(m.units?' U'+m.units:'')+(m.testUnits?' 测试U'+m.testUnits:'')+(m.sub?'（'+m.sub+'）':''))
    })
    refreshModuleSel()
  }
  return true
}
function tryParseOrder(){
  const text=($('orderInput').value||'').trim()
  if(!text){alert('请输入检测需求');return}
  const ok=applyOrder(text)
  addLog(ok?'success':'warning', ok?'已自动识别描述并配置好（版本/年级/模块/单元），确认后点「开始检测」':'未能从描述中识别出有效内容')
}

/* ========== 齿轮事件 ========== */
document.addEventListener('click', function(ev){
  const gear = ev.target.closest ? ev.target.closest('.unit-gear') : null
  if(!gear) return
  ev.preventDefault()
  ev.stopPropagation()
  const tag = gear.closest('.mod-tag')
  if(!tag) return
  const wrap = tag.querySelector('.unit-input-wrap')
  if(!wrap) return
  const show = wrap.style.display !== 'flex'
  wrap.style.display = show ? 'flex' : 'none'
  if(show) wrap.querySelector('input').focus()
}, true)

/* ============================================================
   题目审查面板
   ============================================================ */
async function pollInspect(){
  try{
    const f=await(await fetch('/api/inspect/state')).json()
    updFlowStrip(f)
    updQ(f)
    updWrong(f)
    updShot(f)
    const qs=f.questions||{}
    const ids=Object.keys(qs)
    const lb=ids.filter(id=>qs[id].human_label).length
    if(lb>0){
      const corr=ids.filter(id=>qs[id].human_label==='通过'&&qs[id].overall_passed).length
              +ids.filter(id=>qs[id].human_label==='不通过'&&!qs[id].overall_passed).length
      $('fbAccuracy').textContent=(corr/lb*100).toFixed(0)+'%'
    }else{
      $('fbAccuracy').textContent='—'
    }
  }catch(e){}
  setTimeout(pollInspect,2000)
}

function updFlowStrip(f){
  const steps=f.workflow_steps||[]
  const el=$('flowStrip')
  if(!steps.length){el.innerHTML='';return}
  el.innerHTML=steps.map(s=>{
    const st=s.status||'pending'
    return `<div class="flow-item ${st}"><span class="fd"></span>${s.step||''}${s.detail?' · '+s.detail:''}</div>`
  }).join('')
}

// ★ 题干清洗：过滤状态栏时间(21:12)/得分(77.0)/进度(3/40)/百分比(100%)等 UI 噪音
function cleanStem(s){
  s=(s||'').trim(); if(!s) return ''
  const noise=/^(?:还剩[：:]?\s*\d{1,2}:\d{2}|\d{1,2}:\d{2}|\d+\.?\d*\s*%|\d+\s*\/\s*\d+|\d+\.\d+|\d+)$/
  return s.split(/\s*(?:\/|｜|\|)\s*/).map(p=>p.trim()).filter(p=>p&&!noise.test(p)).join(' / ').slice(0,120)
}

function updQ(f){
  const qs=f.questions||{},ids=Object.keys(qs).sort(),t=ids.length
  const lb=ids.filter(id=>qs[id].human_label).length
  const aipa=ids.filter(id=>qs[id].overall_passed).length
  const aifa=t-aipa
  $('qBadge').textContent=t?t+'题':'待启动'
  const sb=$('qStatsBar')
  if(t){sb.classList.remove('hidden');$('sTotal').textContent=t;$('sPassed').textContent=aipa;$('sFailed').textContent=aifa;$('sLabeled').textContent=lb}
  else sb.classList.add('hidden')
  if(!t){
    $('questionList').innerHTML=`<div class="text-center py-8 text-[#9aa5a0]">
      <div class="text-[13.5px] font-medium text-[#6b7280] mb-1">尚未开始审查</div>
      <div class="text-[11px]">点「快速检查」从手机当前页开查，或随自动化检测同步展示</div></div>`
    return
  }
  // ★ 按模块/阶段分组渲染（每组一个标题，让用户知道题目归属哪个模块/子模块）
  const groupKey=qid=>{
    const s=String(qid),q=qs[qid]
    if(s.includes('-脚本-')){const mod=s.split('-')[0];return `${mod}${q.stage?' · '+q.stage:''} · 脚本审查${q.position?' · '+q.position:''}`}
    if(s.startsWith('auto-')){return `${String(q.question_type||'完整性检查').replace(/[（(].*?[）)]/g,'')} · 完整性检查`}
    const stage=(s.match(/(基础巩固|综合进阶|难点突破)/)||[])[1]
    const um=s.match(/U(\d+)/)
    return `${s.split('-')[0]}${um?' · U'+um[1]:''}${stage?' · '+stage:''}`
  }
  const groups={}
  ids.forEach(qid=>{const k=groupKey(qid);(groups[k]=groups[k]||[]).push(qid)})
  $('questionList').innerHTML=Object.keys(groups).map((k,gi)=>
    `<div class="q-group-title${gi?' mt-3':''}">▎${escHtml(k)}<span class="count">${groups[k].length} 题</span></div>`+
    groups[k].map(qid=>{
    const q=qs[qid],pa=q.overall_passed,unrev=(pa===null||pa===undefined)
    const dims=[
      ['题干',q.ai_stem, q.stem_reason||''],
      ['内容',q.ai_content, q.content_reason||''],
      ['配图',q.ai_image, q.image_reason||''],
      ['作答',q.ai_answer, q.answer_reason||''],
      ['音频',q.ai_audio, q.audio_reason||''],
      ['答错后',q.ai_post_error, q.post_error_reason||'']
    ]
    const dimHtml=dims.map(d=>{
      const v=d[1], stCls=(v===true)?'pass':(v===false?'fail':'skip')
      const stTxt=(v===true)?'通过':(v===false?'不通过':'未检')
      return `<div class="q-dim ${stCls}"><div class="label">${d[0]}</div><div class="st">${stTxt}</div></div>`
    }).join('')
    // ★ 生成题目内容展示区域：显示题干文字 + 选项（让检查人员知道这题是什么）
    const stemTxt=cleanStem(q.stem)
    const optTxt=(q.options||'').trim()
    let contentHtml=''
    if(stemTxt&&stemTxt!==`第${q.idx}题（${q.question_type||''}）`){
      contentHtml+=`<div class="q-stem">${escHtml(stemTxt)}</div>`
    }
    if(optTxt){
      contentHtml+=`<div class="q-opts">选项: ${escHtml(optTxt)}</div>`
    }
    if(q.score_info){
      contentHtml+=`<div class="q-opts" style="color:#92400e">分值: ${escHtml(q.score_info)}</div>`
    }
    // 简化的原因展示：只显示不通过/异常的维度原因（一屏看清）
    const failReasons=dims.filter(d=>d[1]===false||(d[1]===null&&d[2]&&!d[2].includes('无需检查')))
    const reasonHtml=failReasons.length
      ? `<div class="q-reasons">${failReasons.map(d=>`<div class="q-reason-line"><b>${d[0]}:</b> ${escHtml(d[2]||'?')}</div>`).join('')}</div>`
      : `<div class="q-reasons ok">全部通过</div>`
    const actHtml = q.human_label
      ? `<span class="done-tag">已标注: ${q.human_label}${q.human_note?' · '+q.human_note:''}</span>`
      : `<span class="action-label">人工判断</span>
         <input class="note" id="nt_${qid}" placeholder="备注(选填)" onkeydown="if(event.key==='Enter')humanLabel('${qid}','通过')">
         <button class="bg-[#2d6a4f] text-white rounded-lg px-3 py-1.5 text-[11.5px] font-semibold hover:bg-[#1b4332] transition" onclick="humanLabel('${qid}','通过')">通过</button>
         <button class="bg-[#bc4742] text-white rounded-lg px-3 py-1.5 text-[11.5px] font-semibold hover:bg-[#a33b36] transition" onclick="humanLabel('${qid}','不通过')">不通过</button>`
    return `<div class="q-card">
      <div class="q-head">
        <div class="qnum">Q${String(q.idx??qid).padStart(2,'0')}</div>
        <span class="qtype">${q.question_type||'?'}</span>
        ${q.note?`<span class="ml-auto text-[9px] px-1.5 py-px rounded bg-[#e0f2fe] text-[#0369a1] truncate max-w-[130px]" title="${escHtml(q.note)}">📖 脚本审查</span>`:''}
        <div class="qstatus">
          <span class="tag ${unrev?'pending-label':(pa?'pass':'fail')}">AI:${unrev?'未审查':(pa?'通过':'不通过')}</span>
          ${q.human_label?`<span class="tag ${q.human_label==='通过'?'human-pass':'human-fail'}">人:${q.human_label}</span>`:''}
        </div>
      </div>
      <div class="q-body">
        ${contentHtml?`<div class="q-content">${contentHtml}</div>`:''}
        <div class="q-dims">${dimHtml}</div>
        <div class="q-reasons">${reasonHtml}</div>
        <div class="q-actions">${actHtml}</div>
      </div>
    </div>`
    }).join('')
  ).join('')
}

function updShot(f){
  const qs=f.questions||{},ids=Object.keys(qs).sort()
  if(!ids.length) return
  const q=qs[ids[ids.length-1]]
  if(q.screenshot){
    $('screenshotArea').innerHTML=`<img src="/api/screenshot/${q.screenshot}" onclick="openShotLightbox('/api/screenshot/${q.screenshot}')" onerror="this.parentElement.innerHTML='<div class=ph>截图加载失败: ${q.screenshot}</div>'">`
  }
}

/* ========== 错题日志（位置 / 原因 / 修改建议，AI 检测中实时更新） ========== */
const WRONG_SUGGEST={
  题干:'按脚本核对并修正题干文字',
  内容:'核对选项内容/数量是否与脚本一致',
  配图:'核对配图与脚本是否一致',
  作答:'核对答案与脚本是否一致',
  音频:'检查听力音频控件与内容',
  答错后:'验证答错后的反馈流程'
}

function downloadDocxReport(){
  fetch('/api/export/docx',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{
      if(d.success&&d.url){
        const a=document.createElement('a');
        a.href=d.url; a.download=''; document.body.appendChild(a); a.click(); a.remove();
        const n=d.stats?`（共${d.stats.total_questions}题，错题${d.stats.error_questions}题）`:'';
        alert('✅ 错题报告 DOCX 已生成并开始下载'+n+'\n\n按模块分组：每个板块错题放一起，含在App中的位置、出错理由、改进建议、错题截图。');
      }else{
        alert('❌ 导出失败：'+(d.error||'未知错误'));
      }
    }).catch(e=>alert('❌ 请求失败：'+e));
}
// ★ 已生成解析脚本：渲染列表到「审查脚本」卡底部，点文件名下载。
//   （不再手动触发生成——脚本在检测遍历时自动生成，避免 LLM 重复做无用功）
function refreshScriptList(){
  const box=$('scriptList'); if(!box) return;
  box.innerHTML='<div class="text-[#9aa5a0] text-center py-2">加载中…</div>';
  fetch('/api/script/list').then(r=>r.json()).then(d=>{
    if(!d.success){box.innerHTML='<div class="text-[#9aa5a0] text-center py-2">加载失败</div>';return;}
    if(!d.files.length){
      box.innerHTML='<div class="text-[#9aa5a0] text-center py-2 bg-[#faf8f3] rounded-lg">暂无脚本，检测后自动生成</div>';
      return;
    }
    box.innerHTML=d.files.map(f=>{
      const kb=(f.size/1024).toFixed(1)+'KB';
      return `<div class="flex items-center gap-1.5 px-2 py-1.5 bg-[#f0f7f4] border border-[#bbf7d0] rounded">
        <span class="text-[#2d6a4f]">📄</span>
        <span class="text-[#475569] truncate flex-1" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
        <span class="text-[10px] text-[#9aa5a0] shrink-0">${kb} · ${f.mtime}</span>
        <a href="${f.url}" download class="shrink-0 text-[10.5px] px-2 py-0.5 rounded bg-[#2d6a4f] text-white hover:bg-[#1b4332]">下载</a>
      </div>`;
    }).join('');
  }).catch(e=>{box.innerHTML='<div class="text-[#9aa5a0] text-center py-2">加载失败</div>';});
}
function fmtLoc(id,q){
  // 期望格式：模块 + 单元 +（子模块）+ 题号，如「听力专项 · U6 · 基础巩固 · 第3题」
  // ★ 优先用检测时记录的 module/stage/module_qno（App 页面 9/10 的 9 就是子模块内题号）
  const parts=[]
  const mod=(q.module||'').trim(), stage=(q.stage||'').trim()
  const qno=(q.module_qno!==undefined&&q.module_qno!==null&&q.module_qno!=='')?q.module_qno:(q.idx||'?')
  if(mod||stage){
    if(mod) parts.push(mod)
    if(stage) parts.push(stage)
    parts.push('第'+qno+'题')
    return parts.join(' · ')
  }
  const s=String(id||'')
  // 模块名：auto- 前缀（来自答题循环）→ 用 question_type；否则取 qid 第一段
  if(s.startsWith('auto-')){
    parts.push(String(q.question_type||'题目').replace(/[（(].*?[）)]/g,'').replace(/测试$/,''))
  }else{
    const first=s.split('-')[0]
    parts.push(first||'题目')
  }
  // 单元 U\d+
  const um=s.match(/U(\d+)/)
  if(um) parts.push('U'+um[1])
  // 子模块（阶段）
  const sm=(s.match(/(基础巩固|综合进阶|难点突破)/)||[])[1]
  if(sm) parts.push(sm)
  // 题号
  const qm=s.match(/[Qq]0*(\d+)/)
  parts.push('第'+(qm?qm[1]:qno)+'题')
  return parts.join(' · ')
}
let _wrongSig=''  // 错题列表内容签名（防每2秒重绘导致滚动抖动）
function updWrong(f){
  const el=$('wrongList'); if(!el) return
  const qs=f.questions||{}
  const wrong=Object.keys(qs).filter(id=>{
    const q=qs[id]
    return q.overall_passed===false || q.question_type==='错题截图'
  }).sort().map(id=>({id,q:qs[id]}))
  $('wrongBadge').textContent=wrong.length
  // ★ 内容签名无变化 → 不重绘（保住滚动位置，用户能翻到底部看最后一题）
  const sig=wrong.length+':'+wrong.map(({id,q})=>
    id+'|'+q.overall_passed+'|'+(q.human_label||'')+'|'+
    (q._score?(q._score.score+'_'+q._score.checked_count):'')+'|'+(q.screenshot||q._marked||'')
  ).join(',')
  if(sig===_wrongSig) return
  _wrongSig=sig
  if(!wrong.length){
    el.innerHTML='<div class="text-center py-6 text-[#9aa5a0] bg-[#faf8f3] rounded-lg text-[11px]">暂无错题<br>（检测通过或尚未开始）</div>'
    return
  }
  const scTop=el.scrollTop  // 记录滚动位置，重绘后恢复
  const cleanR=s=>String(s||'').replace(/^\[不通过\]\s*\|\s*/,'')
  const sevLbl={high:'高',medium:'中',low:'低'}
  const sevCls={high:'bg-[#fee2e2] text-[#bc4742]',medium:'bg-[#fef3c7] text-[#92400e]',low:'bg-[#e0e7ff] text-[#3730a3]'}
  // ★ 错题也按模块/阶段分组（与六维面板一致的分组逻辑）
  const wGroupKey=(id,q)=>{
    // ★ 优先用记录的 module/stage 字段（web_server 检测时写入，定位最准）
    if(q.module) return `${q.module}${q.stage?' · '+q.stage:''}`
    const s=String(id)
    if(s.includes('-脚本-')){const mod=s.split('-')[0];return `${mod}${q.stage?' · '+q.stage:''} · 脚本审查${q.position?' · '+q.position:''}`}
    if(s.startsWith('auto-')){return `${String(q.question_type||'完整性检查').replace(/[（(].*?[）)]/g,'')} · 完整性检查`}
    const stage=(s.match(/(基础巩固|综合进阶|难点突破)/)||[])[1]
    const um=s.match(/U(\d+)/)
    return `${s.split('-')[0]}${um?' · U'+um[1]:''}${stage?' · '+stage:''}`
  }
  const wGroups={}
  wrong.forEach(({id,q})=>{const k=wGroupKey(id,q);(wGroups[k]=wGroups[k]||[]).push({id,q})})
  el.innerHTML=Object.keys(wGroups).map((k,gi)=>
    `<div class="q-group-title${gi?' mt-3':''}">▎${escHtml(k)}<span class="count">${wGroups[k].length} 题</span></div>`+
    wGroups[k].map(({id,q})=>{
    // 1) 位置
    const locHtml=`<div class="flex items-center gap-2 px-2.5 py-1.5 bg-[#fef2f2]">
      <span class="w-1.5 h-1.5 rounded-full bg-[#bc4742] shrink-0"></span>
      <span class="text-[11px] font-semibold text-[#7f1d1d] truncate" title="${escHtml(id)}">${escHtml(fmtLoc(id,q))}</span>
    </div>`

    // 来自答题流程真实答错的题（已截图，无六维判定）→ 简版卡片
    if(q.question_type==='错题截图'){
      const shot=q.screenshot
      return `<div class="border border-[#fecaca] rounded-lg overflow-hidden bg-white">
        ${locHtml}
        <div class="px-2.5 py-2 text-[11px] text-[#475569] space-y-1">
          <div><span class="font-semibold text-[#bc4742]">原因：</span>答题答错（已截图）</div>
          <div><span class="font-semibold text-[#2d6a4f]">建议：</span>人工核对错题画面，针对薄弱点重点巩固</div>
          ${shot?`<img src="/api/screenshot/${shot}" class="w-full max-h-[150px] object-contain bg-[#faf8f3] rounded-md border border-[#e6dfd4] cursor-pointer" onclick="openShotLightbox('/api/screenshot/${shot}')" onerror="this.style.display='none'">`:''}
        </div>
      </div>`
    }

    // 2) 评分 + 评分依据（透明：已检查N维·通过M维 → M/N×100）
    const sc=q._score
    let scoreHtml=''
    if(sc&&sc.checked_count>0){
      const pct=sc.score
      const barCls=pct>=80?'bg-[#2d6a4f]':(pct>=60?'bg-[#e9c46a]':'bg-[#bc4742]')
      const txtCls=pct>=60?'text-[#2d6a4f]':'text-[#bc4742]'
      scoreHtml=`<div class="bg-[#faf8f3] rounded-md px-2.5 py-2">
        <div class="flex items-center gap-2">
          <span class="text-[21px] font-bold leading-none ${txtCls}">${pct}</span>
          <span class="text-[10px] text-[#9aa5a0]">/100</span>
          <div class="flex-1 h-1.5 bg-[#e8e4da] rounded-full overflow-hidden"><div class="h-full ${barCls} rounded-full" style="width:${pct}%"></div></div>
        </div>
        <div class="text-[10px] text-[#6b7280] mt-1">评分依据：已检查 <b>${sc.checked_count}</b> 维 · 通过 <b>${sc.passed_count}</b> 维 → ${sc.formula}</div>
      </div>`
    }else if(sc){
      scoreHtml=`<div class="bg-[#faf8f3] rounded-md px-2.5 py-2 text-[10.5px] text-[#6b7280]">${sc.formula}</div>`
    }

    // 3) 错误维度溯源清单（同学C的 checks：维度/严重度/原因/建议）
    const tr=q._trace
    let dimsHtml=''
    if(tr&&tr.checks&&tr.checks.length){
      dimsHtml=`<div class="space-y-1.5">${tr.checks.map(c=>{
        const reason=cleanR(c.reason)||'未提供具体原因'
        return `<div class="border border-[#fecaca] rounded-md px-2 py-1.5 bg-[#fffbfb]">
          <div class="flex items-center gap-1.5">
            <span class="text-[11px] font-semibold text-[#7f1d1d]">${escHtml(c.dimension)}</span>
            <span class="text-[9px] px-1.5 py-px rounded ${sevCls[c.severity]||sevCls.low}">${sevLbl[c.severity]||c.severity}</span>
            <span class="ml-auto text-[9.5px] text-[#bc4742]">未通过</span>
          </div>
          <div class="text-[10.5px] text-[#475569] mt-1">原因：${escHtml(reason)}</div>
          <div class="text-[10.5px] text-[#2d6a4f] mt-0.5">建议：${escHtml(cleanR(c.suggestion)||'核对脚本修正')}</div>
        </div>`
      }).join('')}</div>`
    }else{
      // 兼容旧数据（无 trace 字段）→ 从维度 reason 提取
      const dims=[['题干',q.ai_stem,q.stem_reason],['内容',q.ai_content,q.content_reason],
        ['图片',q.ai_image,q.image_reason],['答案',q.ai_answer,q.answer_reason],
        ['音频',q.ai_audio,q.audio_reason],['答错检查',q.ai_post_error,q.post_error_reason]]
      const fails=dims.filter(d=>d[1]===false)
      dimsHtml=fails.length
        ? `<div class="space-y-1.5">${fails.map(d=>`<div class="border border-[#fecaca] rounded-md px-2 py-1.5 bg-[#fffbfb]">
            <div class="flex items-center gap-1.5"><span class="text-[11px] font-semibold text-[#7f1d1d]">${escHtml(d[0])}</span><span class="ml-auto text-[9.5px] text-[#bc4742]">未通过</span></div>
            <div class="text-[10.5px] text-[#475569] mt-1">原因：${escHtml(cleanR(d[2])||'未提供')}</div>
            <div class="text-[10.5px] text-[#2d6a4f] mt-0.5">建议：${escHtml(WRONG_SUGGEST[d[0]]||'核对脚本修正')}</div>
          </div>`).join('')}</div>`
        : '<div class="text-[10.5px] text-[#6b7280]">综合判定不通过</div>'
    }

    // 4) 题目溯源截图（红框标注图优先，其次原图）
    const shot=q._marked||q.screenshot
    const shotHtml=shot?`<img src="/api/screenshot/${shot}" class="w-full max-h-[150px] object-contain bg-[#faf8f3] rounded-md border border-[#e6dfd4] cursor-pointer" onclick="openShotLightbox('/api/screenshot/${shot}')" onerror="this.style.display='none'">`:''

    // 5) 题干 / 标准答案（script_context）
    const ctx=tr&&tr.script_context
    const ctxHtml=(ctx&&(ctx.stem||ctx.answer))
      ? `<div class="text-[10.5px] text-[#6b7280] border-t border-dashed border-[#e6dfd4] pt-1.5 space-y-0.5">
          ${ctx.stem?`<div><b>题干：</b>${escHtml(String(ctx.stem).slice(0,80))}</div>`:''}
          ${ctx.answer?`<div><b>标准答案：</b>${escHtml(ctx.answer)}</div>`:''}
        </div>`:''

    return `<div class="border border-[#fecaca] rounded-lg overflow-hidden bg-white">
      ${locHtml}
      <div class="px-2.5 py-2 space-y-2">
        ${scoreHtml}
        ${dimsHtml}
        ${shotHtml}
        ${ctxHtml}
      </div>
    </div>`
    }).join('')
  ).join('')
  el.scrollTop=scTop  // 恢复滚动位置（防重绘抖动）
}

/* ========== 模块 → 上传脚本 自动匹配 ========== */
// 模块名 → 脚本文件名关键词（顺序匹配，第一个命中即选）
const MOD_KEYWORDS={
  '听力专项':['听力专项','听力'],
  '口语训练':['口语','朗读'],
  '单元自检':['单元自检','单元检测'],
  '知识过关':['知识过关','知识','重点词汇','重点句型'],
  '巧记单词':['巧记','单词'],
  '语音评测':['语音评测','语音']
}
// ★ 子阶段关键词：听力专项脚本命名区分「练习/测试」时用于精确匹配
const STAGE_KEYWORDS={
  '练习':['练习','练'],
  '测试':['测试','测']
}
function getSelectedModules(){
  return [...document.querySelectorAll('.mod-sel')].filter(c=>c.checked).map(c=>c.value)
}
function getUploadedDocxs(){
  // 从 reviewDocx select 的 options 取当前上传脚本名（由 loadUploadList / 上传回调填充）
  const sel=$('reviewDocx'); if(!sel) return []
  return [...sel.options].map(o=>o.text||'').filter(Boolean)
}
// 版本/年级 select 值 → 脚本文件名关键词（数组：简称+全称；表外值用 _Aliases 自动推导，绝不放空）
const VER_KEYWORDS={
  '湘少版':['湘少','湘少版'],'湘少版(2024审定)':['湘少','湘少版'],'湘鲁版':['湘鲁','湘鲁版'],'新湘鲁版':['湘鲁','湘鲁版'],'湘鲁版（2024审定）':['湘鲁','湘鲁版'],
  '人教版':['人教','人教版'],'人教版(PEP)':['人教','人教版'],'外研版(三起)':['外研','外研版'],'外研版(一起)':['外研','外研版'],
  '冀教版':['冀教','冀教版'],'教科版':['教科','教科版'],'陕旅版':['陕旅','陕旅版'],'新概念青少版':['新概念']
}
const GRADE_KEYWORDS={
  '一年级上册':['一上','一年级上册'],'一年级下册':['一下','一年级下册'],
  '二年级上册':['二上','二年级上册'],'二年级下册':['二下','二年级下册'],
  '三年级上册':['三上','三年级上册'],'三年级下册':['三下','三年级下册'],
  '四年级上册':['四上','四年级上册'],'四年级下册':['四下','四年级下册'],
  '五年级上册':['五上','五年级上册'],'五年级下册':['五下','五年级下册'],
  '六年级上册':['六上','六年级上册'],'六年级下册':['六下','六年级下册']
}
/* 表外版本兜底：去括号、去“版”尾 → 如 湘鲁版(2024) → 湘鲁版/湘鲁；表外值仍用选项值本身匹配 */
function _verAliases(v){
  const base=String(v||'').replace(/（.*）|\(.*\)/g,'').replace(/版$/,'').trim()
  return [...new Set([String(v),base])].filter(Boolean)
}
/* 表外年级兜底：一年级上册 → 一上（简称推导） */
function _gradeAliases(g){
  const m=String(g||'').match(/^([一二三四五六])年级([上下])册$/)
  return m?[String(g),m[1]+m[2]]:[String(g)]
}
// ★★ 模块 → 脚本 五要素匹配：模块 + 版本 + 年级 + 单元 + 子阶段（2026-08-29 新增练习/测试）
//   unitRange：所选单元范围字符串（"2,4" / "2-4" / ""=不限制）
//   stage：子阶段，听力专项区分「练习/测试」；脚本名必须包含对应关键词
//   - 脚本无 U 信息（如"口语训练湘少五上"全单元脚本）→ 视为覆盖所有单元 → 命中
//   - 脚本 U 范围与所选单元有交集（如 U6-U10 覆盖所选 U6）→ 命中（后端按单元提取题目审查）
//   - 无交集（如选 U2 但脚本只有 U6-U10）→ 不命中 → 该模块走基础完整性（不弹窗警告）
function matchDocxForModule(mod,docxs,version,grade,unitRange,stage=''){
  const kws=MOD_KEYWORDS[mod]||[mod]
  // ★ 关键：未知版本/年级绝不允许“不限制”——表里有就用表，表外就用选项值本身推导匹配
  const verKws=(version&&version!=='通用')?(VER_KEYWORDS[version]||_verAliases(version)):[]
  const gKws=grade?(GRADE_KEYWORDS[grade]||_gradeAliases(grade)):[]
  const hasK=d=>kws.some(k=>d.includes(k))
  const verOk=d=>!verKws.length||verKws.some(k=>d.includes(k))
  const gOk=d=>!gKws.length||gKws.some(k=>d.includes(k))
  // ★ 单元维度：有单元范围时，脚本必须覆盖所选单元（有交集）才算匹配；
  //   脚本无 U 信息（全单元脚本）视为覆盖
  const uOk=d=>{
    if(!unitRange||unitRange==='NONE') return true
    const su=scriptUnitsOf(d)
    return unitCoveredBy(unitRange,su)!==false
  }
  // ★ 子阶段维度（如听力专项练习/测试）：要求脚本名包含对应关键词
  //   ★ 兼容规则：听力专项脚本若不含任何阶段关键词（「练习/测试/练/测」），
  //     默认视为「练习」脚本（历史脚本均未带阶段标识，全为练习模式）
  const stageOk=(d)=>{
    if(!stage) return true
    const skws=STAGE_KEYWORDS[stage]||[stage]
    if(skws.some(k=>d.includes(k))) return true
    // ★ 听力专项兼容：无阶段关键词 → 默认归为练习（不匹配测试）
    if(mod==='听力专项' && stage==='练习'){
      const hasAnyStage=Object.values(STAGE_KEYWORDS).flat().some(k=>d.includes(k))
      return !hasAnyStage  // 脚本没有任何阶段标记 → 当作练习脚本
    }
    return false
  }
  // ★ 严格匹配：模块 + 版本 + 年级 + 单元 + 子阶段 五者全部命中才算「有脚本」
  //   （不做降级兜底，避免版本/年级/单元/阶段不对的脚本被误用，导致 LLM 对照错误）
  return docxs.find(d=>hasK(d)&&verOk(d)&&gOk(d)&&uOk(d)&&stageOk(d))||''
}
function curVersionGrade(){
  return {v:$('setupVersion')?$('setupVersion').value:'',g:$('setupGrade')?$('setupGrade').value:''}
}
// ★ 从脚本文件名解析单元范围，兼容两种格式：
//   "U6-U10"（带U）→ {lo:6,hi:10}；"U1-5"（不带U）→ {lo:1,hi:5}
//   "U6"（单单元）→ {lo:6,hi:6}；无 U 信息 → null
function scriptUnitsOf(fname){
  const f=fname||''
  // ① 范围带U: U6-U10 / U6~U10 / U6至U10
  let m=/[Uu]\s*(\d{1,2})\s*(?:-|~|至|到)\s*[Uu]\s*(\d{1,2})/.exec(f)
  if(m){ return {lo:parseInt(m[1]), hi:parseInt(m[2])} }
  // ② 范围不带U: U1-5 / U1~5
  m=/[Uu]\s*(\d{1,2})\s*(?:-|~|至|到)\s*(\d{1,2})/.exec(f)
  if(m){ return {lo:parseInt(m[1]), hi:parseInt(m[2])} }
  // ③ 单单元: U6
  const m2=/[Uu]\s*(\d{1,2})\b/.exec(f)
  if(!m2) return null
  const lo=parseInt(m2[1])
  if(!lo||lo<1||lo>20) return null
  return {lo,hi:lo}
}
// 单元是否被脚本覆盖（unit 可能是 "6" / "1-5" / "6,8" / "1,2,3"）
function unitCoveredBy(unitStr, su){
  if(!su) return null               // 脚本无单元信息 → 未知
  if(!unitStr) return true          // 未指定单元 → 视为全部覆盖
  return String(unitStr).split(/[,，]/).some(p=>{
    const mm=/^\s*(\d+)\s*(?:-(\d+))?\s*$/.exec(p)
    if(!mm) return true
    const lo=parseInt(mm[1]); const hi=mm[2]?parseInt(mm[2]):lo
    return !(hi<su.lo||lo>su.hi)     // 有交集即覆盖
  })
}
function curModuleUnits(name,stage=''){
  const cb=document.querySelector(`.mod-sel[value="${name}"]`)
  if(!cb) return ''
  const tag=cb.closest('.mod-tag'); if(!tag) return ''
  if(name==='听力专项' && stage){
    // 练习/测试单元输入框分开取值，避免交叉
    if(stage==='练习'){ const p=tag.querySelector('.unit-val-p'); return p?p.value:'' }
    if(stage==='测试'){ const t=tag.querySelector('.unit-val-t'); return t?t.value:'' }
  }
  if(name==='听力专项'){
    const p=tag.querySelector('.unit-val-p'); const t=tag.querySelector('.unit-val-t')
    return [p&&p.value,t&&t.value].filter(v=>v&&v!=='NONE').join(',')
  }
  const v=tag.querySelector('.unit-val')
  return v?v.value:''
}
function updateModuleMatch(){
  const list=$('moduleMatchList'); if(!list) return
  const mods=getSelectedModules()
  const docxs=getUploadedDocxs()
  const {v,g}=curVersionGrade()
  if(!mods.length){
    list.innerHTML='<div class="text-[#9aa5a0] text-center py-2 bg-[#faf8f3] rounded-lg">尚未选模块</div>'
    $('matchSummary').textContent=''
    return
  }
  // 渲染一行匹配结果（stageLabel: 可选的子阶段标签，如「练习」「测试」）
  function renderRow(label,d,stageLabel){
    const badge=stageLabel?`<span class="text-[10px] font-medium px-1.5 py-0.5 rounded ${d?'bg-[#dcfce7] text-[#166534]':'bg-[#fef3c7] text-[#b45309]'}">${escHtml(stageLabel)}</span>`:''
    if(!d){
      return `<div class="flex items-center gap-1.5 px-2 py-1 bg-[#fef3c7] border border-[#fde68a] rounded">
        <span class="text-[#92400e]">—</span>
        <span class="text-[#92400e] font-semibold">${escHtml(label)}</span>
        ${badge}
        <span class="text-[#9aa5a0]">→</span>
        <span class="text-[#92400e]">无匹配脚本</span>
        <span class="ml-auto text-[10px] text-[#92400e]">仅基础</span>
      </div>`
    }
    const su=scriptUnitsOf(d)
    if(su){
      return `<div class="flex items-center gap-1.5 px-2 py-1 bg-[#f0f7f4] border border-[#bbf7d0] rounded">
        <span class="text-[#2d6a4f]">✓</span>
        <span class="text-[#2d6a4f] font-semibold">${escHtml(label)}</span>
        ${badge}
        <span class="text-[#9aa5a0]">→</span>
        <span class="text-[#475569] truncate" title="${escHtml(d)}">${escHtml(d)}</span>
        <span class="ml-auto text-[10px] text-[#2d6a4f]">LLM（U${su.lo}${su.hi>su.lo?'-'+su.hi:''}）</span>
      </div>`
    }
    return `<div class="flex items-center gap-1.5 px-2 py-1 bg-[#f0f7f4] border border-[#bbf7d0] rounded">
      <span class="text-[#2d6a4f]">✓</span>
      <span class="text-[#2d6a4f] font-semibold">${escHtml(label)}</span>
      ${badge}
      <span class="text-[#9aa5a0]">→</span>
      <span class="text-[#475569] truncate" title="${escHtml(d)}">${escHtml(d)}</span>
      <span class="ml-auto text-[10px] text-[#2d6a4f]">LLM</span>
    </div>`
  }
  // ★ 听力专项区分练习/测试，其余模块按原逻辑
  let hit=0,total=0
  list.innerHTML=mods.map(m=>{
    if(m==='听力专项'){
      const cb=document.querySelector(`.mod-sel[value="听力专项"]`)
      const tag=cb?cb.closest('.mod-tag'):null
      const pChk=tag?tag.querySelector('input.tingli-part[value="practice"]'):null
      const tChk=tag?tag.querySelector('input.tingli-part[value="test"]'):null
      const rows=[]
      if(pChk && pChk.checked){
        total++
        const d=matchDocxForModule(m,docxs,v,g,curModuleUnits(m,'练习'),'练习')
        if(d) hit++
        rows.push(renderRow('听力专项',d,'练习'))
      }
      if(tChk && tChk.checked){
        total++
        const d=matchDocxForModule(m,docxs,v,g,curModuleUnits(m,'测试'),'测试')
        if(d) hit++
        rows.push(renderRow('听力专项',d,'测试'))
      }
      if(!rows.length) rows.push(renderRow('听力专项','','未选模式'))
      return rows.join('')
    }
    total++
    const d=matchDocxForModule(m,docxs,v,g,curModuleUnits(m))
    if(d) hit++
    return renderRow(m,d)
  }).join('')
  $('matchSummary').textContent=`可审查 ${hit}/${total} 项`
}
// 监听模块勾选变化 → 重新计算匹配
document.querySelectorAll && setTimeout(()=>{
  document.querySelectorAll('.mod-sel').forEach(c=>c.addEventListener('change',updateModuleMatch))
  // ★ 单元输入变化 → 也刷新匹配预览（运行前即时看到脚本覆盖状态）
  document.querySelectorAll('.unit-val,.unit-val-p,.unit-val-t').forEach(c=>{
    c.addEventListener('change',updateModuleMatch)
    c.addEventListener('input',updateModuleMatch)
  })
},0)

/* ========== 审查动作 ========== */
function inspStageAllChange(){
  const all=$('inspStageAll')
  document.querySelectorAll('.inspStageCb').forEach(c=>c.checked=!!(all&&all.checked))
}
function getInspStages(){
  const sel=[...document.querySelectorAll('.inspStageCb')].filter(c=>c.checked).map(c=>c.value)
  // 一个都没勾 = 全部
  return sel.length?sel:['基础巩固','综合进阶','难点突破']
}
async function startInsp(){
  const v=$('inspectVersion').value,u=$('inspectUnit').value
  const stages=getInspStages()
  // ★ 按当前选中模块自动匹配上传的脚本：选中模块的第一个匹配 docx → 后端 LLM 审查
  const mods=getSelectedModules()
  const docxs=getUploadedDocxs()
  const {v:cv,g:cg}=curVersionGrade()
  const matchedMod=mods.length?mods[0]:''
  const docx=matchedMod?matchDocxForModule(matchedMod,docxs,cv,cg,curModuleUnits(matchedMod)):''
  $('runBtn').disabled=true
  addLog('info',`开始检查: ${v} U${u} ${stages.join('、')} · ${matchedMod||'未选模块'} ${docx?'(脚本 '+docx+' 启用 LLM)':'(无脚本，仅基础完整性)'}`)
  try{
    const r=await(await fetch('/api/inspect/listening-run',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({version:v,unit:parseInt(u),stages,docx})})).json()
    if(r.error){alert(r.error);$('runBtn').disabled=false;return}
    addLog('success','审查任务已启动')
  }catch(e){alert('失败:'+e);$('runBtn').disabled=false}
}
async function stopInsp(){
  try{
    const r=await(await fetch('/api/inspect/stop',{method:'POST'})).json()
    addLog('warning','停止审查: '+(r.message||'信号已发送'))
  }catch(e){addLog('error','停止失败:'+e)}
}
async function quickInsp(){
  $('quickBtn').disabled=true
  // ★ 按当前选中模块自动匹配上传的脚本（核心：模块→脚本→LLM 审查）
  const mods=getSelectedModules()
  const docxs=getUploadedDocxs()
  const {v,g}=curVersionGrade()
  const matchedMod=mods.length?mods[0]:''
  const docx=matchedMod?matchDocxForModule(matchedMod,docxs,v,g,curModuleUnits(matchedMod)):($('reviewDocx')?$('reviewDocx').value:'')
  const unit=$('reviewUnit')?$('reviewUnit').value:''
  const withAI=docx&&docx!=='— 尚未上传 —'&&docx!==''
  addLog('info',`快速检查: ${matchedMod||'未选模块'} · ${withAI?'有脚本，启用 LLM 六维审查':'无脚本，仅做基础完整性'}`)
  try{
    const r=await(await fetch('/api/inspect/quick-run',{method:'POST',
      headers:{'Content-Type': 'application/json'},
      body:JSON.stringify({docx:withAI?docx:'',unit:unit?parseInt(unit):0})})).json()
    if(r.error){alert(r.error);$('quickBtn').disabled=false;return}
    addLog('success','快速检查任务已启动')
  }catch(e){alert('失败:'+e);$('quickBtn').disabled=false}
}
async function humanLabel(qid,label){
  const n=$('nt_'+qid);const note=n?n.value:''
  try{
    const r=await(await fetch('/api/inspect/human-label',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({qid,label,note})})).json()
    if(r.success){
      addLog(label==='通过'?'success':'warning',qid+' 标注: '+label)
      const f=await(await fetch('/api/inspect/state')).json();updQ(f)
    }
  }catch(e){addLog('error','标注失败:'+e)}
}
async function runReview(){
  // ★ 优先用选中模块自动匹配的脚本，否则用 reviewDocx 手动选中的脚本
  const mods=getSelectedModules()
  const docxs=getUploadedDocxs()
  const {v,g}=curVersionGrade()
  let d=''
  if(mods.length){d=matchDocxForModule(mods[0],docxs,v,g,curModuleUnits(mods[0]))}
  if(!d)d=$('reviewDocx').value
  const u=parseInt($('reviewUnit')?.value||'0')
  if(!d||d==='— 尚未上传 —'){
    $('reviewResult').innerHTML='<span style="color:var(--red)">请先选中模块并上传匹配脚本，或在下方下拉手动选脚本</span>'
    return
  }
  $('reviewResult').innerHTML='审查中…'
  try{
    const r=await(await fetch('/api/review/run',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({docx:d,unit:u,stage:'基础巩固'})})).json()
    if(r.error){$('reviewResult').innerHTML=`<span style="color:var(--red)">失败: ${r.error}</span>`;return}
    $('reviewResult').innerHTML=`完成: ${r.total}题, 通过${r.passed}（${r.avg_score}）`
  }catch(e){$('reviewResult').innerHTML=`<span style="color:var(--red)">失败: ${e}</span>`}
}

/* ========== 上传 / 知识库 ========== */
$('fileInput').addEventListener('change',e=>up(e.target.files[0]))
const dz=$('dropZone')
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover')})
dz.addEventListener('dragleave',e=>dz.classList.remove('dragover'))
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');if(e.dataTransfer.files.length)up(e.dataTransfer.files[0])})

async function up(f){
  if(!f) return
  const fd=new FormData();fd.append('file',f)
  $('uploadStatus').textContent='上传 '+f.name+' …'
  try{
    const r=await(await fetch('/api/upload-docx',{method:'POST',body:fd})).json()
    if(r.error){$('uploadStatus').innerHTML=`<span style="color:var(--red)">失败: ${r.error}</span>`;return}
    $('uploadStatus').innerHTML=`<span style="color:var(--ok-ink)">${r.message}（${r.entries_added||0}条知识点）</span>`
    loadUL();loadKB()
  }catch(e){$('uploadStatus').innerHTML=`<span style="color:var(--red)">失败: ${e}</span>`}
}
async function loadUL(){
  try{
    const d=await(await fetch('/api/upload/list')).json(),sel=$('reviewDocx')
    if(d.files&&d.files.length){
      $('uploadList').innerHTML=d.files.map(f=>`<div class="item">${f.name} (${(f.size/1024).toFixed(0)}KB)</div>`).join('')
      sel.innerHTML=d.files.map(f=>`<option>${f.name}</option>`).join('')
    }else{
      $('uploadList').innerHTML='<div style="color:var(--gray-2);font-size:11px">暂无已上传的脚本文件</div>'
      sel.innerHTML='<option>— 尚未上传 —</option>'
    }
    updateModuleMatch()  // 脚本列表更新后刷新模块→脚本自动匹配
  }catch(e){}
}
async function loadVersions(){
  try{
    const d=await(await fetch('/api/versions/available')).json()
    const sel=$('inspectVersion')
    const cur=sel.value
    const vs=d.versions||[]
    if(vs.length){
      sel.innerHTML=vs.map(v=>`<option${v===cur?' selected':''}>${v}</option>`).join('')
      if(cur&&vs.includes(cur)) sel.value=cur
    }
  }catch(e){}
}
async function loadKB(){
  try{
    const d=await(await fetch('/api/knowledge/status')).json()
    if(d.total_entries>0){
      $('kbTotal').textContent=d.total_entries+'条'
      $('kbGrades').textContent=d.grades.join(', ')
    }else{
      $('kbTotal').textContent='空'
    }
  }catch(e){}
}

/* ========== 启动 ========== */
document.querySelectorAll('.mod-sel').forEach(b=>b.addEventListener('change',refreshModuleSel))
pollStatus()
pollLog()
pollInspect()
refreshModuleSel()
loadGradeTable()
loadUL()
loadKB()
loadVersions()
refreshScriptList()  // ★ 初始加载已生成的解析脚本（下载区）

// ====== 首次访问自动弹出使用指南（看过之后不再自动弹） ======
try{
  if(!localStorage.getItem('yyb_guide_seen')){ setTimeout(()=>openGuide(),600) }
}catch(e){}

// ====== 缓存兜底：若加载到旧版页面（缺少日志区停止按钮），强制刷新一次 ======
try{
  if(!document.getElementById('btnStopLog') && !sessionStorage.getItem('yyb_stopbtn_checked')){
    sessionStorage.setItem('yyb_stopbtn_checked','1')
    location.reload(true)
  }
}catch(e){}

// ====== 默认切到 Tab1 任务配置 ======
switchTab(1)

// ====== 截图实时预览轮询 (每2秒) ======
let _shotTimer=null
async function pollShot(){
  try{
    const t=Date.now()
    const r=await fetch('/api/screenshot/latest?t='+t)
    if(r.ok){
      const blob=await r.blob()
      const url=URL.createObjectURL(blob)
      const cur=$('screenshotArea').querySelector('img')
      if(cur&&cur.src===url) return
      $('screenshotArea').innerHTML=`<img src="${url}" alt="实时截图" onclick="openShotLightbox()">`
    }
  }catch(e){}
}
function startShotPolling(){
  if(_shotTimer) clearInterval(_shotTimer)
  _shotTimer=setInterval(pollShot,2000)
  pollShot()
}
startShotPolling()

// ===== 导出报告 =====
async function openExport(){
  try{
    const r=await(await fetch("/api/review/export",{method:"POST"})).json()
    if(!r.content){alert("无审查数据");return}
    const b=new Blob([r.content],{type:"text/plain;charset=utf-8"})
    const a=document.createElement("a")
    a.href=URL.createObjectURL(b); a.download="审查报告.txt"
    a.click(); URL.revokeObjectURL(a.href)
  }catch(e){alert("导出异常: "+e.message)}
}


let _tp={type:'全部',sub:'',nums:[],papers:'AB'};
function openTestPicker(){
  const inp=document.querySelector('.unit-val-t');
  const cur=(inp.value||'').trim();
  parseTestVal(cur);
  renderTestPicker();
  document.getElementById('testPicker').classList.remove('hidden');
  document.getElementById('testPickerMask').classList.remove('hidden');
}
function parseTestVal(cur){
  _tp={type:'全部',sub:'',nums:[],papers:'AB'};
  if(!cur) return;
  if(cur.indexOf('|')>=0){
    const bits=cur.split('|');
    _tp.type=bits[0]||'全部';
    const u=(bits[1]||'').trim();
    if(u){ if(/^\d+-\d+$/.test(u)) _tp.sub=u; else _tp.nums=u.split(',').filter(Boolean); }
    if(bits[2]&&bits[2].trim()) _tp.papers=bits[2].trim().toUpperCase();
  } else if(/^[\d,\s]+$/.test(cur)){ _tp.type='单元'; _tp.nums=cur.split(',').map(s=>s.trim()).filter(Boolean); }
  else if(cur==='all'||cur==='全部'){ _tp.type='全部'; }
  else { _tp.type=cur; }
}
function renderTestPicker(){
  document.querySelectorAll('.tp-type').forEach(b=>b.classList.toggle('on',b.dataset.t===_tp.type));
  document.getElementById('tpUnitBox').classList.toggle('hidden',_tp.type!=='单元');
  // 自定义范围输入框
  const fromEl=document.getElementById('tpFrom'), toEl=document.getElementById('tpTo');
  if(fromEl&&toEl){
    const m=_tp.sub.match(/^(\d+)-(\d+)$/);
    if(m){ fromEl.value=m[1]; toEl.value=m[2]; }
    else { fromEl.value=''; toEl.value=''; }
  }
  // "全部单元" 高亮：sub 为空且没有选单个单元号
  document.querySelectorAll('.tp-subb').forEach(b=>b.classList.toggle('on',b.dataset.s===''&&_tp.sub===''&&_tp.nums.length===0));
  const box=document.getElementById('tpUnitBtns');
  if(!box.dataset.built){box.dataset.built='1';for(let i=1;i<=9;i++){const b=document.createElement('button');b.type='button';b.textContent=i;b.className='tp-ub';b.onclick=()=>pickNum(String(i));box.appendChild(b);}}
  document.querySelectorAll('.tp-ub').forEach(b=>b.classList.toggle('on',_tp.nums.includes(b.textContent)));
  // A/B 卷
  document.querySelectorAll('.tp-paper').forEach(b=>b.classList.toggle('on',b.dataset.p===_tp.papers));
  const note=document.getElementById('tpNote');
  if(_tp.type==='单元') note.textContent='自定义范围对应六下「Units阶段评价」；单元号多选对应三下「Unit N 单元评价」（无 A/B 卷时自动忽略）';
  else if(_tp.type==='期中'||_tp.type==='期末') note.textContent='点击对应「'+_tp.type+'评价」卷；当前版本若无此分类将提示未找到并跳过';
  else if(_tp.type==='考前突破') note.textContent='考前突破 = 测该 tab 下所有卷';
  else note.textContent='全部 = 测测试页所有卷（留空同效果）';
}
function onRangeChange(){
  const fromEl=document.getElementById('tpFrom'), toEl=document.getElementById('tpTo');
  let a=parseInt(fromEl.value), b=parseInt(toEl.value);
  if(!isNaN(a)&&!isNaN(b)&&a>=1&&b>=1&&a<=b){
    _tp.sub=a+'-'+b; _tp.nums=[]; renderTestPicker();
  }
}
function pickNum(k){
  const idx=_tp.nums.indexOf(k);
  if(idx>=0)_tp.nums.splice(idx,1); else _tp.nums.push(k);
  _tp.sub=''; renderTestPicker();
}
function pickType(t){_tp.type=t;if(t!=='单元'){_tp.sub='';_tp.nums=[];}renderTestPicker();}
function pickSub(s){_tp.sub=s;_tp.nums=[];const fromEl=document.getElementById('tpFrom'),toEl=document.getElementById('tpTo');if(fromEl)fromEl.value='';if(toEl)toEl.value='';renderTestPicker();}
function pickPaper(p){_tp.papers=p;renderTestPicker();}
function closeTestPicker(){document.getElementById('testPicker').classList.add('hidden');document.getElementById('testPickerMask').classList.add('hidden');}
function clearTestPick(){const inp=document.querySelector('.unit-val-t');inp.value='';inp.placeholder='点此选测评（留空=不测测试）';closeTestPicker();}
function confirmTestPick(){
  const inp=document.querySelector('.unit-val-t');
  let v='';
  if(_tp.type==='全部'){v='全部||';}
  else if(_tp.type==='单元'){
    const u=_tp.sub||(_tp.nums.length?[...new Set(_tp.nums)].sort((a,b)=>a-b).join(','):'');
    v='单元|'+u+'|'+_tp.papers;
  } else { v=_tp.type+'||'+_tp.papers; }
  inp.value=v;
  let label=_tp.type;
  if(_tp.type==='单元'){ label='单元'+( _tp.sub?(' '+ _tp.sub.replace('-','~')+'单元') : (_tp.nums.length?(' '+_tp.nums.join(',')):'') ); }
  label+=' · '+(_tp.papers==='AB'?'AB两卷':_tp.papers+'卷');
  inp.placeholder='已选：'+label;
  closeTestPicker();
}
