[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Pause', 'Resume', 'Status')]
    [string]$Mode,

    [string]$StatePath = (Join-Path $PSScriptRoot '..\cache\rs2_outage_state.json'),

    [datetime]$ResumeAt,

    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = 'C:\Program Files\Python312\python.exe'
$ScreenerRepository = 'riperdy-tech/stock-screener'
$Rs2Repository = 'riperdy-tech/rs2-local'
$TemporaryTasks = @(
    'RS2-Depth-Orchestrator',
    'RS2-Control-Agent',
    'RS2-SDF-Dispatch',
    'RS2-KIS-Dispatch'
)
$RetiredTask = 'RS2-Orchestrator'
$WorkflowTargets = @(
    [pscustomobject]@{ repository = $ScreenerRepository; path = '.github/workflows/schedule-data-fetch.yml' },
    [pscustomobject]@{ repository = $ScreenerRepository; path = '.github/workflows/kis-sync.yml' },
    [pscustomobject]@{ repository = $ScreenerRepository; path = '.github/workflows/price-refresh.yml' },
    [pscustomobject]@{ repository = $ScreenerRepository; path = '.github/workflows/factor-recalibration.yml' },
    [pscustomobject]@{ repository = $ScreenerRepository; path = '.github/workflows/paradigm-weekly-analyst.yml' },
    [pscustomobject]@{ repository = $ScreenerRepository; path = '.github/workflows/ai-worker.yml' },
    [pscustomobject]@{ repository = $Rs2Repository; path = '.github/workflows/depth-cloud-backstop.yml' }
)

function Write-AtomicJson([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.$PID.tmp"
    [System.IO.File]::WriteAllText(
        $temporary,
        ($Value | ConvertTo-Json -Depth 8),
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Read-State([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Get-WorkflowStates {
    $result = @()
    foreach ($target in $WorkflowTargets) {
        $raw = & gh workflow list -R $target.repository --all --json name,path,state
        if ($LASTEXITCODE -ne 0) {
            throw "Could not read GitHub workflow state from $($target.repository)."
        }
        $all = $raw | ConvertFrom-Json
        $match = @($all | Where-Object { $_.path -eq $target.path })
        if ($match.Count -ne 1) {
            throw "Expected exactly one GitHub workflow at $($target.repository):$($target.path)."
        }
        $result += [pscustomobject]@{ repository = $target.repository; path = $target.path; state = [string]$match[0].state }
    }
    return $result
}

function Set-WorkflowState([string]$Repository, [string]$Path, [string]$Action) {
    if ($WhatIf) {
        Write-Host "WHATIF GitHub workflow ${Action}: ${Repository}:$Path"
        return
    }
    & gh workflow $Action $Path -R $Repository
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub workflow $Action failed: $Path"
    }
}

function Set-TaskEnabled([string]$Name, [bool]$Enabled) {
    if ($WhatIf) {
        Write-Host "WHATIF scheduled task enabled=${Enabled}: $Name"
        return
    }
    if ($Enabled) {
        Enable-ScheduledTask -TaskName $Name -ErrorAction Stop | Out-Null
    } else {
        Disable-ScheduledTask -TaskName $Name -ErrorAction Stop | Out-Null
    }
}

function New-RecoveryTask([datetime]$At, [string]$StateFile) {
    $taskName = 'RS2-Shadow-Outage-Recovery'
    $argument = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Mode Resume -StatePath "{1}"' -f $PSCommandPath, $StateFile
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $argument
    $trigger = New-ScheduledTaskTrigger -Once -At $At `
        -RepetitionInterval (New-TimeSpan -Minutes 30) `
        -RepetitionDuration (New-TimeSpan -Days 1)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    if ($WhatIf) {
        Write-Host "WHATIF recovery task $taskName at $($At.ToString('o'))"
        return $taskName
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop | Out-Null
    return $taskName
}

function Invoke-Pause {
    if ($ResumeAt -eq [datetime]::MinValue) {
        throw 'Pause requires -ResumeAt.'
    }
    if ($ResumeAt -le (Get-Date)) {
        throw 'ResumeAt must be in the future.'
    }
    $existing = Read-State $StatePath
    if ($null -ne $existing -and $existing.phase -eq 'paused') {
        Write-Host "Already paused. Recovery remains scheduled for $($existing.resume_at)."
        return
    }

    $taskState = @()
    foreach ($name in $TemporaryTasks) {
        $task = Get-ScheduledTask -TaskName $name
        $taskState += [pscustomobject]@{ name = $name; was_enabled = [bool]$task.Settings.Enabled }
    }
    $workflows = Get-WorkflowStates
    $state = [ordered]@{
        schema_version = 'rs2-outage/v1'
        phase = 'pausing'
        created_at = (Get-Date).ToString('o')
        resume_at = $ResumeAt.ToString('o')
        temporary_tasks = $taskState
        workflows = $workflows
        retired_task = $RetiredTask
        depth_pause_was_present = (Test-Path -LiteralPath (Join-Path $Root 'cache\DEPTH_PAUSED'))
        recovery_task = $null
        last_error = $null
    }
    if (-not $WhatIf) {
        Write-AtomicJson $StatePath $state
        & $Python (Join-Path $Root 'status.py') stop
        if ($LASTEXITCODE -ne 0) {
            throw 'Graceful depth stop failed.'
        }
    }

    foreach ($task in $taskState) {
        if ($task.was_enabled) {
            Set-TaskEnabled $task.name $false
        }
    }
    Set-TaskEnabled $RetiredTask $false
        foreach ($workflow in $workflows) {
        if ($workflow.state -eq 'active') {
            Set-WorkflowState $workflow.repository $workflow.path 'disable'
        }
    }

    $state.phase = 'paused'
    $state.paused_at = (Get-Date).ToString('o')
    $state.recovery_task = New-RecoveryTask $ResumeAt $StatePath
    if (-not $WhatIf) {
        Write-AtomicJson $StatePath $state
    }
    Write-Host "OUTAGE PAUSED until $($state.resume_at). Telegram remains untouched."
}

function Invoke-Resume {
    $state = Read-State $StatePath
    if ($null -eq $state) {
        throw "Outage state is missing: $StatePath"
    }
    if ($state.phase -eq 'resumed') {
        Write-Host 'Outage recovery already completed.'
        return
    }
    try {
        foreach ($task in $state.temporary_tasks) {
            if ([bool]$task.was_enabled) {
                Set-TaskEnabled ([string]$task.name) $true
            }
        }
        foreach ($workflow in $state.workflows) {
            if ([string]$workflow.state -eq 'active') {
                $workflowRepository = if ($null -ne $workflow.PSObject.Properties['repository']) { [string]$workflow.repository } else { $ScreenerRepository }
                Set-WorkflowState $workflowRepository ([string]$workflow.path) 'enable'
            }
        }
        $state.phase = 'resumed'
        $resumedAt = (Get-Date).ToString('o')
        if ($null -eq $state.PSObject.Properties['resumed_at']) {
            $state | Add-Member -NotePropertyName resumed_at -NotePropertyValue $resumedAt
        } else {
            $state.resumed_at = $resumedAt
        }
        $state.last_error = $null
        if (-not $WhatIf) {
            Write-AtomicJson $StatePath $state
            Disable-ScheduledTask -TaskName ([string]$state.recovery_task) -ErrorAction Stop | Out-Null
        }
        Write-Host 'OUTAGE RECOVERED. Depth pause marker was preserved; no sweep was launched.'
    } catch {
        $state.last_error = $_.Exception.Message
        if (-not $WhatIf) {
            Write-AtomicJson $StatePath $state
        }
        throw
    }
}

switch ($Mode) {
    'Pause' { Invoke-Pause }
    'Resume' { Invoke-Resume }
    'Status' {
        $state = Read-State $StatePath
        if ($null -eq $state) {
            Write-Host "No outage state at $StatePath"
        } else {
            $state | ConvertTo-Json -Depth 8
        }
    }
}
