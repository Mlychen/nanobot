@echo off
REM nanobot 启动脚本 (Windows)
REM 解决 GBK 编码问题，强制使用 UTF-8

setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

if "%1"=="gateway" (
    .venv\Scripts\python.exe -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['gateway'])"
) else if "%1"=="serve" (
    .venv\Scripts\python.exe -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['serve'])"
) else if "%1"=="status" (
    .venv\Scripts\python.exe -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['status'])"
) else (
    .venv\Scripts\python.exe -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['agent'])"
)

endlocal
