# -*- coding: utf-8 -*-
"""重构 index.html 下半区：左审查结果 + 右截图横向布局"""
lines = open('templates/index.html', encoding='utf-8').read().split('\n')

start = None
for i, l in enumerate(lines):
    if '<!-- 下半：审查结果 + 截图 -->' in l:
        start = i
        break

main_pos = None
for j in range(start, len(lines)):
    if '  </main>' in lines[j]:
        main_pos = j
        break

end = None
for j in range(main_pos - 1, start, -1):
    if lines[j].startswith('    </div>'):
        end = j
        break

# 下半区内容 = lines[start .. end-1]（保留 end 的 4空格 </div>）
new_block = [
'      <!-- 下半：左审查结果 + 右截图（横向利用宽度） -->',
'      <div class="flex-1 flex min-h-0 border-t border-[#e6dfd4] bg-[#fbfaf6]">',
'        <!-- 左：审查结果 -->',
'        <div class="flex-1 flex flex-col min-w-0 min-h-0 border-r border-[#e6dfd4]">',
'          <div class="flex items-center gap-2 px-4 pt-2">',
'            <h3 class="font-bold text-[13px] text-[#1b4332]">题目审查结果（六维）</h3>',
'            <span class="text-[10.5px] text-[#9aa5a0]">AI 判断 + 人工复核</span>',
'            <span id="qBadge" class="ml-auto bg-white border border-[#e6dfd4] rounded-full px-2.5 py-0.5 text-[10.5px] text-[#6b7280]">待启动</span>',
'          </div>',
'          <div id="qStatsBar" class="hidden md:flex gap-4 px-4 py-1.5 text-[12px] text-[#6b7280] flex-wrap">',
'            <span>总题数 <b class="text-[15px] text-[#2d6a4f]" id="sTotal">0</b></span>',
'            <span>AI通过 <b class="text-[15px] text-[#1d6f3c]" id="sPassed">0</b></span>',
'            <span>AI不通过 <b class="text-[15px] text-[#bc4742]" id="sFailed">0</b></span>',
'            <span class="ml-auto">已人工标注 <b class="text-[15px] text-[#2d6a4f]" id="sLabeled">0</b></span>',
'          </div>',
'          <div id="questionList" class="flex-1 overflow-y-auto px-4 py-2">',
'            <div class="text-center py-8 text-[#9aa5a0]">',
'              <div class="text-[13.5px] font-medium text-[#6b7280] mb-1">尚未开始审查</div>',
'              <div class="text-[11px]">点「快速检查」从手机当前页开查，或随自动化检测同步展示</div>',
'            </div>',
'          </div>',
'        </div>',
'        <!-- 右：截图（手机相框 + 缩略图） -->',
'        <div class="w-[310px] shrink-0 overflow-y-auto px-3 py-2 flex flex-col gap-1.5">',
'          <div class="flex items-center gap-2">',
'            <h3 class="font-bold text-[12px] text-[#1b4332]">手机画面</h3>',
'            <span class="text-[10px] text-[#9aa5a0]">实时 · 点图放大</span>',
'          </div>',
'          <div class="phone-frame">',
'            <div class="screenshot-box" id="screenshotArea"><div class="ph">等待巡检截图…</div></div>',
'          </div>',
'          <div class="text-[11px] font-semibold text-[#475569] mt-0.5">最近截图（点开放大）</div>',
'          <div id="shotThumbs" class="grid grid-cols-3 gap-1.5">',
'            <div class="text-[10px] text-[#9aa5a0] text-center py-4 bg-[#faf8f3] rounded-lg col-span-3">暂无</div>',
'          </div>',
'          <div class="shot-hint">手机屏 1080×2400 竖屏 · 完整显示每题画面</div>',
'        </div>',
'      </div>',
]

lines[start:end] = new_block
open('templates/index.html', 'w', encoding='utf-8').write('\n'.join(lines))
print(f'重构完成: {start}~{end} → 新布局')
