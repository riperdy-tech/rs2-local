# Docker Desktop is kept off (operator 2026-11-01, to save memory for another project) and started only for the jobs that
# need SearXNG (port 8888): the 06:00 KST RS2-B2-Gather-P6 news gather and, after it, the holdings monitor's daily gather
# (RS2-Monitor-Daily, tools/holdings_monitor/monitor_daily.ps1, which waits for the B2 gather to end). -Start starts Docker Desktop
# and waits for SearXNG; -Stop stops it once neither gather is running or waiting (waits up to 3 hours). Log: cache/docker_window.log.
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
    for ($i = 0; $i -lt 360; $i++) {
        # monitor_daily.ps1 deletes its marker when its gather is over (or failed); a marker older than 3 hours is a dead run's
        $marker = Join-Path (Split-Path -Parent $log) "monitor_gather.running"
        $waiting = (Test-Path $marker) -and (((Get-Date) - (Get-Item $marker).LastWriteTime).TotalHours -lt 3)
        $busy = $waiting -or (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "b2_day\.py|followup_gather|monitor\.py`"? gather" })
        if (-not $busy) { docker desktop stop 2>&1 | Out-Null; Log "stopped"; exit 0 }
        Start-Sleep 30
    }
    Log "not stopped: a gather still running after 3 h"
    exit 1
}
