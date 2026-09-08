@echo off
chcp 65001 >nul
REM ============================================================
REM  英语宝自动化检测 - 一键启动（Windows）
REM  放在 web_server.py 同级目录，双击即可；无需关心本机路径
REM ============================================================

REM 切到本脚本所在目录（=项目根目录），解决项目路径写死问题
cd /d "%~dp0"

REM 探测 Python 解释器（不写死路径，优先 python，其次 py 启动器）
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)
if not defined PY (
  echo [错误] 未找到 Python。请先安装 Python 3.10+ 并勾选 "Add to PATH"。
  pause
  exit /b 1
)

echo 使用 Python: %PY%
echo 项目目录: %CD%
echo.

REM 依赖自检：缺关键包则提示安装
%PY% -c "import flask, uiautomator2, docx, yaml" >nul 2>nul
if errorlevel 1 (
  echo [提示] 检测到缺少依赖，正在尝试安装 requirements.txt ...
  %PY% -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请手动执行：%PY% -m pip install -r requirements.txt
    pause
    exit /b 1
  )
)

echo ============================================================
echo  正在启动 web_server.py ...
echo  启动后浏览器打开: http://localhost:5000
echo  关闭此窗口即可停止服务
echo ============================================================
echo.

%PY% web_server.py
pause
