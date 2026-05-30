# kill-jarvis.ps1
# Stops any running Jarvis processes (desktop_app, the jarvis.main daemon, and
# its MCP children) so the launcher can start exactly ONE clean instance.
# Called by Start-Jarvis.vbs before launching. Safe to run when nothing is up.
#
# Matches by command line (not just image name) so unrelated python processes
# are never touched.
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'desktop_app|jarvis\.main|Jarvis-src\\mcps' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
