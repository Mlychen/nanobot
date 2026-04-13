#!/bin/bash
# nanobot 启动脚本 (Linux/macOS/WSL)
# 解决编码问题，强制使用 UTF-8

set -e

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

cd "$(dirname "$0")"

case "$1" in
    gateway)
        .venv/bin/python -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['gateway'])"
        ;;
    serve)
        .venv/bin/python -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['serve'])"
        ;;
    status)
        .venv/bin/python -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['status'])"
        ;;
    *)
        .venv/bin/python -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); from nanobot.cli.commands import app; app(['agent'])"
        ;;
esac
