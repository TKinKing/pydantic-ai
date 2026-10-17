param(
    [ValidateSet('run', 'test', 'debug', 'mcp-server')]
    [string]$Task = 'run'
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path $PSScriptRoot -Parent
$pythonExe = if ($env:HARNESS_PYTHON) { $env:HARNESS_PYTHON } else { Join-Path $repoDir '.venv\Scripts\python.exe' }
$pythonArgs = switch ($Task) {
    'run' { @('-X', 'utf8', '-u', '-m', 'harness_example.main') }
    'mcp-server' { @('-X', 'utf8', '-u', '-m', 'harness_example.main', '--mcp-server') }
    'test' { @('-X', 'utf8', '-m', 'pytest', 'harness_example', '-q', '-p', 'no:cacheprovider') }
    'debug' { @('-X', 'utf8', '-Xfrozen_modules=off', '-u', '-m', 'debugpy', '--listen', '127.0.0.1:5678', '--wait-for-client', '-m', 'harness_example.main') }
}
Push-Location -LiteralPath $repoDir
try {
    & $pythonExe @pythonArgs
    $runExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $runExitCode
