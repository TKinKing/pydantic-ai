$ErrorActionPreference = 'Stop'
$wslExe = Join-Path $env:WINDIR 'System32\wsl.exe'
$repoDir = Split-Path $PSScriptRoot -Parent
$pythonExe = '/home/tk/.cache/pydantic-ai-harness-learning-venv/bin/python'
$modelName = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { 'qwen2.5:14b-instruct-q4_K_M' }
$baseUrl = $env:OLLAMA_BASE_URL
if (-not $baseUrl) {
    # WSL NAT 模式下，通过默认网关访问 Windows 的 Ollama。
    $route = & $wslExe -- ip -4 route show default
    if ($LASTEXITCODE -ne 0 -or "$route" -notmatch 'default via (\S+)') {
        throw '无法确定 Windows 地址，请设置 OLLAMA_BASE_URL（包含 /v1）。'
    }
    $baseUrl = "http://$($Matches[1]):11434/v1"
}
& $wslExe --cd $repoDir -- env "OLLAMA_MODEL=$modelName" "OLLAMA_BASE_URL=$baseUrl" $pythonExe -u harness_example/main.py
exit $LASTEXITCODE
