# Launch Jarvis from source (with venv + Chatterbox unlock + fast-path patch).
# Usage: From PowerShell in this folder:  .\run_source.ps1

$ErrorActionPreference = 'Stop'
$REPO = $PSScriptRoot
Set-Location $REPO

$env:PYTHONPATH = Join-Path $REPO 'src'
$env:PYTHONIOENCODING = 'utf-8'
# Ollama keep_alive (already set system-wide but harmless to repeat)
if (-not $env:OLLAMA_KEEP_ALIVE) { $env:OLLAMA_KEEP_ALIVE = '-1' }
# CTranslate2 stability on Blackwell GPUs: force FP32 accumulation in FP16
# GEMM ops to prevent transformer layer underflow on quiet dynamic-mic
# input (root cause of Greek-detected-as-French failures). Safe on all GPUs.
$env:CT2_CUDA_TRUE_FP16_GEMM = '0'

$venvPython = Join-Path $REPO '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: venv not found at $venvPython"
    Write-Host "Run setup first: see Phase 4 install steps."
    exit 1
}

Write-Host "[jarvis-src] Starting Jarvis from source..." -ForegroundColor Cyan
Write-Host "[jarvis-src] Python: $venvPython"
Write-Host "[jarvis-src] PYTHONPATH: $env:PYTHONPATH"
Write-Host ""

& $venvPython -m desktop_app
exit $LASTEXITCODE
