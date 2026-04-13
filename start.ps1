# nanobot 启动脚本 (PowerShell)
# 解决 UTF-8 编码问题

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

$python = ".venv\Scripts\python.exe"

# 构建参数列表：如果没有参数，默认执行 agent
if ($args.Count -eq 0) {
    $args = @("agent")
}

# 将 PowerShell 数组转为 JSON 字符串，安全传递给 Python
$argsJson = ($args | ForEach-Object { "'$_'" }) -join ","
$script = "from nanobot.cli.commands import app; app([$argsJson])"

& $python -c "import os,sys; os.environ['PYTHONUTF8']='1'; sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); $script"
