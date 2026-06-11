# stop-jarvis.ps1
# FULL shutdown: kills every Jarvis process (like kill-jarvis.ps1) AND tells
# Ollama to release the models Jarvis loaded. Without the second step the
# models sit in VRAM "Forever" (their keep_alive), pinning ~10 GB long after
# Jarvis is gone — exactly what Task Manager shows after an End Task.
#
# Use this when you want Jarvis GONE and the GPU back.
# Plain restarts should keep using Start-Jarvis.vbs (warm models = fast boot).
$ErrorActionPreference = 'SilentlyContinue'

Write-Output 'Stopping Jarvis processes...'
& "$PSScriptRoot\kill-jarvis.ps1"

Write-Output 'Releasing models from VRAM...'
try {
    $ps = Invoke-RestMethod -Uri 'http://localhost:11434/api/ps' -TimeoutSec 3
    $names = @($ps.models | ForEach-Object { $_.name } | Where-Object { $_ })
    if ($names.Count -eq 0) {
        Write-Output '  (nothing loaded)'
    }
    foreach ($name in $names) {
        $body = @{ model = $name; keep_alive = 0 } | ConvertTo-Json
        Invoke-RestMethod -Uri 'http://localhost:11434/api/generate' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 15 | Out-Null
        Write-Output "  Unloaded $name"
    }
} catch {
    Write-Output '  Ollama not reachable - nothing to unload.'
}

Write-Output 'Done. Jarvis stopped and VRAM released.'
