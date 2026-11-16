# The holdings monitor's day (task RS2-Monitor-Daily, 05:55 local): one gather (SEC, closes, news through SearXNG), then one
# run pass on the GPU. Paper only; monitoring never sells.
#
# The gather needs SearXNG, which is up only in the Docker window (05:40 start, stop from 06:20). The marker file
# cache\monitor_gather.running tells docker_window.ps1 -Stop to leave Docker up until this gather is over. The gather waits for
# the B2 news gather (06:00, about an hour) to end, so the two never query SearXNG together.
#
# The run pass starts no new read after -MaxMinutes (default 150: the spec's estimate of a day's reads; the operator sets the
# real cap after the first live days), yields to a formation, and does not start while another job holds the card.
# Log: cache\monitor_daily.log in this repository.
param([double]$MaxMinutes = 150)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$cache = Join-Path $root "cache"
$log = Join-Path $cache "monitor_daily.log"
$marker = Join-Path $cache "monitor_gather.running"
$py = "C:\Program Files\Python312\python.exe"
$env:PYTHONIOENCODING = "utf-8"
function Log($m) { "$((Get-Date).ToUniversalTime().ToString('s'))Z $m" | Out-File -FilePath $log -Append -Encoding utf8 }
function Py($arguments) { cmd /c "`"$py`" -u `"$here\monitor.py`" $arguments >> `"$log`" 2>&1"; return $LASTEXITCODE }

if (-not (Test-Path $cache)) { New-Item -ItemType Directory $cache | Out-Null }
Set-Content -Path $marker -Value "$PID $((Get-Date).ToString('s'))" -Encoding utf8
try {
    # B2 starts at 06:00; wait until 06:05 has passed and no b2_day.py is running (at most 100 minutes)
    for ($i = 0; $i -lt 200; $i++) {
        $b2 = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "b2_day\.py" }
        if (-not $b2 -and (Get-Date).TimeOfDay -ge [TimeSpan]"06:05:00") { break }
        Start-Sleep 30
    }
    Log "gather start"
    $rc = Py "gather"
    Log "gather exit $rc"
} finally {
    Remove-Item $marker -ErrorAction SilentlyContinue
}
Log "run start (max $MaxMinutes minutes)"
$rc = Py "run --max-minutes $MaxMinutes"
Log "run exit $rc"
