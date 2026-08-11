with open('modules/知识过关.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 增强录音题处理：所有点击包 try/except，录音/结束多轮重试
old = '''        # 1. 录音题：检测"原音"按钮（跟读单词题）
        if d(text="原音").exists(timeout=0.3):
            print(f"    🎤 录音题")
            d(text="原音").click()
            time.sleep(2)
            if d(text="点击录音").exists(timeout=0.8):
                d(text="点击录音").click()
                time.sleep(1.5)
            if d(text="点击结束").exists(timeout=0.8):
                d(text="点击结束").click()
                time.sleep(2)
            # 点检测
            if d(text="检测").exists(timeout=1.5):
                d(text="检测").click()
                time.sleep(1.5)
            q += 1
            continue'''

new = '''        # 1. 录音题：检测"原音"按钮（跟读单词题）
        if d(text="原音").exists(timeout=0.3):
            print(f"    🎤 录音题")
            try:
                d(text="原音").click()
            except Exception:
                pass
            time.sleep(2)
            # 点录音（多轮重试，点击结束后等待自动跳转）
            try:
                if d(text="点击录音").exists(timeout=1):
                    d(text="点击录音").click()
                    time.sleep(1.5)
            except Exception:
                pass
            try:
                if d(text="点击结束").exists(timeout=1):
                    d(text="点击结束").click()
                    time.sleep(2)
                else:
                    # 点完录音后可能直接出下一题/检测
                    time.sleep(2)
            except Exception:
                pass
            # 点检测
            try:
                if d(text="检测").exists(timeout=1.5):
                    d(text="检测").click()
                    time.sleep(1.5)
            except Exception:
                pass
            q += 1
            continue'''

if old in content:
    content = content.replace(old, new)
    with open('modules/知识过关.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK 录音题增强')
else:
    print('NOT FOUND')
