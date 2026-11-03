# Docker Desktop is kept off (operator 2026-11-01, to save memory for another project) and started only for the jobs that
# need SearXNG (port 8888): the 06:00 KST RS2-B2-Gather-P6 news gather. -Start starts Docker Desktop and waits for SearXNG;
# -Stop stops it once no b2_day.py gather is running (waits up to 2 hours). Log: cache/docker_window.log in this repository.
param([switch]$Start, [switch]$Stop)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) "cache\docker_window.log"
function Log($m) { "$((Get-Date).ToUniversalTime().ToString('s'))Z $m" | Out-File -FilePath $log -Append -Encoding utf8 }

if ($Start) {
    docker desktop start 2>&1 | Out-Null
    # review 2026-11-03: "docker desktop stop" leaves searxng explicitly stopped, so its unless-stopped policy never restarts it
    for ($i = 0; $i -lt 30; $i++) { docker info 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 10 }
    docker start searxng 2>&1 | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest -Uri "http://localhost:8888/" -UseBasicParsing -TimeoutSec 5 | Out-Null; Log "started; SearXNG up"; exit 0 } catch {}
        Start-Sleep 10
    }
    Log "started; SearXNG NOT up after 10 min"
    exit 1
}
if ($Stop) {
    for ($i = 0; $i -lt 240; $i++) {
        $busy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "b2_day\.py|followup_gather" }
        if (-not $busy) { docker desktop stop 2>&1 | Out-Null; Log "stopped"; exit 0 }
        Start-Sleep 30
    }
    Log "not stopped: gather still running after 2 h"
    exit 1
}
