# Harness learning example. Run from Windows PowerShell or a WSL/Linux/macOS terminal.

set dotenv-load := true
set windows-shell := [x"${WINDIR:-C:/Windows}/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

harness_python := env('HARNESS_PYTHON', env('HOME', '/home/tk') / '.cache/pydantic-ai-harness-learning-venv/bin/python')

default:
    @just --list

# Run the complete example with DeepSeek when a key is set, otherwise local Ollama.
[windows]
harness:
    @& ./harness_example/run_ollama.ps1

[unix]
harness:
    @"{{ harness_python }}" -u -m harness_example.main

# Run only the learning example tests; no model API or Ollama service is needed.
[windows]
harness-test:
    @& ./harness_example/run_ollama.ps1 -Task test

[unix]
harness-test:
    @"{{ harness_python }}" -m pytest harness_example -q -p no:cacheprovider

# Wait for VS Code's "Python: Harness 附加 just 调试 (WSL)" on port 5678.
[windows]
harness-debug:
    @& ./harness_example/run_ollama.ps1 -Task debug

[unix]
harness-debug:
    @"{{ harness_python }}" -Xfrozen_modules=off -u -m debugpy --listen 127.0.0.1:5678 --wait-for-client -m harness_example.main
