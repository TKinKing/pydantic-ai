# Harness learning example. Every task uses the current machine's Python environment.

set dotenv-load := true
set windows-shell := [x"${WINDIR:-C:/Windows}/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

venv_python := if os() == 'windows' { justfile_directory() / '.venv/Scripts/python.exe' } else { justfile_directory() / '.venv/bin/python' }
harness_python := env('HARNESS_PYTHON', venv_python)

default:
    @just --list

# Run the complete example with DeepSeek when a key is set, otherwise local Ollama.
[windows]
harness:
    @& ./harness_example/run_ollama.ps1; exit $LASTEXITCODE

[unix]
harness:
    @{{ quote(harness_python) }} -X utf8 -u -m harness_example.main

# Run only the MCP stdio server; no model API or Ollama service is needed.
[windows]
mcp-server:
    @& ./harness_example/run_ollama.ps1 -Task mcp-server; exit $LASTEXITCODE

[unix]
mcp-server:
    @{{ quote(harness_python) }} -X utf8 -u -m harness_example.main --mcp-server

# Run only the learning example tests; no model API or Ollama service is needed.
[windows]
harness-test:
    @& ./harness_example/run_ollama.ps1 -Task test; exit $LASTEXITCODE

[unix]
harness-test:
    @{{ quote(harness_python) }} -X utf8 -m pytest harness_example -q -p no:cacheprovider

# Start a manual debugpy listener on port 5678; use VS Code F5 for direct debugging.
[windows]
harness-debug:
    @& ./harness_example/run_ollama.ps1 -Task debug; exit $LASTEXITCODE

[unix]
harness-debug:
    @{{ quote(harness_python) }} -X utf8 -Xfrozen_modules=off -u -m debugpy --listen 127.0.0.1:5678 --wait-for-client -m harness_example.main
