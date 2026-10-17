param(
    [ValidateSet('run', 'test', 'debug')]
    [string]$Task = 'run'
)

$ErrorActionPreference = 'Stop'
$wslExe = Join-Path $env:WINDIR 'System32\wsl.exe'
$repoDir = Split-Path $PSScriptRoot -Parent
$pythonExe = if ($env:HARNESS_PYTHON) { $env:HARNESS_PYTHON } else { '/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python' }
$modelName = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { 'qwen2.5-harness:14b-16k' }
$baseUrl = $env:OLLAMA_BASE_URL
if (-not $baseUrl -and ($Task -eq 'test' -or -not [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY))) {
    $baseUrl = 'http://localhost:11434/v1'
}
if ($Task -ne 'test' -and -not $baseUrl -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    # WSL NAT 模式下，通过默认网关访问 Windows 的 Ollama。
    $route = & $wslExe -- ip -4 route show default
    if ($LASTEXITCODE -ne 0 -or "$route" -notmatch 'default via (\S+)') {
        throw '无法确定 Windows 地址，请设置 OLLAMA_BASE_URL（包含 /v1）。'
    }
    $baseUrl = "http://$($Matches[1]):11434/v1"
}
$pythonArgs = switch ($Task) {
    'run' { @('-u', '-m', 'harness_example.main') }
    'test' { @('-m', 'pytest', 'harness_example', '-q', '-p', 'no:cacheprovider') }
    'debug' { @('-Xfrozen_modules=off', '-u', '-m', 'debugpy', '--listen', '127.0.0.1:5678', '--wait-for-client', '-m', 'harness_example.main') }
}
$originalWslEnv = $env:WSLENV
try {
    # 仅传递变量名，不把 API Key 放入进程命令行。
    $sharedVariables = @($originalWslEnv -split ':' | Where-Object { $_ -and ($_ -split '/')[0] -ne 'DEEPSEEK_API_KEY' })
    $env:WSLENV = ($sharedVariables + 'DEEPSEEK_API_KEY/u') -join ':'
    & $wslExe --cd $repoDir --exec env "OLLAMA_MODEL=$modelName" "OLLAMA_BASE_URL=$baseUrl" $pythonExe @pythonArgs
    $runExitCode = $LASTEXITCODE
}
finally {
    $env:WSLENV = $originalWslEnv
}
exit $runExitCode
