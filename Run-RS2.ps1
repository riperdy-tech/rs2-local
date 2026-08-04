<#
================================================================
 Run-RS2.ps1  —  Staged RS2 v2.0 analysis runner
 Drives the rs2-analyst Ollama model layer-group by layer-group,
 feeding each stage the previous stages' output so a 3B-active
 MoE holds the full 17-layer chain the way a frontier model would.
================================================================

 USAGE:
   .\Run-RS2.ps1 -Ticker TSLA
   .\Run-RS2.ps1 -Ticker TSLA -DataFile .\data\TSLA.md
   .\Run-RS2.ps1 -Ticker TSLA -Model rs2-analyst -NoThink

 Output: reports\<TICKER>_<timestamp>\  (one .md per stage + FINAL.md)
#>

param(
  [Parameter(Mandatory=$true)][string]$Ticker,
  [string]$DataFile = "",
  [string]$Model    = "rs2-analyst",
  [string]$Endpoint = "http://localhost:11434/api/chat",
  [int]$StageCtx    = 16384,   # per-stage: 100% GPU, ~36% faster
  [int]$FinalCtx    = 24576,   # final assembly needs room for all prior stages
  [switch]$NoThink            # disable thinking (faster, lower quality)
)

$ErrorActionPreference = "Stop"
$think = -not $NoThink

# ---- load optional analyst-supplied data -------------------------------
$data = ""
if ($DataFile -ne "" -and (Test-Path $DataFile)) {
  $data = Get-Content $DataFile -Raw
  Write-Host "[data] loaded $DataFile ($($data.Length) chars)" -ForegroundColor Cyan
} else {
  Write-Host "[data] none provided -> model must tag gaps [Unconfirmed]/[Assumption]" -ForegroundColor Yellow
}

# ---- stage definitions (layer groups) ----------------------------------
# Keep each stage small so the active-3B expert stays on-rails.
$stages = @(
  @{ id="S1_macro_classify"; title="Layers 0, 1, 1.5 — Classification / Macro / Base Rate";
     task="Execute LAYER 0, LAYER 1, and LAYER 1.5 ONLY. Determine archetype + valuation engine (Step 0-1..0-4), full macro context with the 4-regime probability distribution (must sum 100%) and sensitivity matrix, and the base-rate / historical-pattern check. STOP after Layer 1.5." }
  @{ id="S2_quality"; title="Layers 2, 2.5 — Business Quality / Adjusted Financials";
     task="Execute LAYER 2 and LAYER 2.5 ONLY. Business understanding, 7-type moat score + direction, Lynch classification, financial strength scorecard, capital-allocation scorecard, and intangibles-adjusted (R&D cap, SBC, leases, adjusted ROIC, owner earnings). STOP after Layer 2.5." }
  @{ id="S3_valuation"; title="Layers 3, 3.5 — Valuation Engine / Second-Order";
     task="Execute LAYER 3 and LAYER 3.5 ONLY. Run the valuation using the engine selected in Stage 1 (show the math, Point + 50% CI + 80% CI on core variables, Tornado top-3 KPIs). Then second-order effects (competitive response, reflexivity, customer evolution). STOP after Layer 3.5." }
  @{ id="S4_scenarios"; title="Layers 4, 4.5 — Scenarios (Bayesian) / Horizon Arbitrage";
     task="Execute LAYER 4 and LAYER 4.5 ONLY. Build Bear/Base/Bull scenarios (probabilities sum 100%, base = highest), Bayesian update from the Stage-1 base rates, expected price + 50%/80% CI, Margin of Safety, then market-implied vs my-horizon arbitrage. STOP after Layer 4.5." }
  @{ id="S5_conviction"; title="Layers 5, 5.5, 6, 6.5 — Conviction / Behavioral / Portfolio / Kelly";
     task="Execute LAYER 5, LAYER 5.5, LAYER 6 (portfolio fit) and LAYER 6.5 (Kelly sizing) ONLY. Conviction score /15, decay note, sizing guideline; behavioral & positioning (short interest, ownership, insider, options skew, sentiment, crowding /15); portfolio fit; Kelly-based size. If Layer 5 vs 6.5 sizing gap > 20 percentage points, flag for re-analysis. STOP after Layer 6.5." }
  @{ id="S6_redteam_audit"; title="Layers 7, 7.5, 8, 9 — Monitoring / Correlation / Audit / Red Team";
     task="Execute LAYER 7, LAYER 7.5, LAYER 8 and LAYER 9 ONLY. Thesis-integrity KPIs + thresholds, pre-mortem (3 failure modes + early-warning indicators), decision-journal entry; correlation-adjusted risk (common bear triggers, tail correlation, CVaR); the 37-point audit (state pass/fail per group A-G); and the Red Team (short thesis 5-7 bullets, long-vs-short logic combat, adversarial data, killed arguments). STOP after Layer 9." }
)

# ---- final assembly stage ----------------------------------------------
$finalTask = "You now have the complete worked analysis from all prior stages (provided above). Assemble the FINAL REPORT exactly per 'FINAL OUTPUT STRUCTURE (v2.0)': SECTION 0 through SECTION 12, in fixed order, in a SINGLE code block. Do not re-derive — consolidate the numbers already produced. Enforce all 14 FINAL MANDATORY RULES. End with SECTION 12 Final Execution Opinion (Action, Conviction, Weight %, Strategy). Output in English."

# ---- helper: one model call --------------------------------------------
function Invoke-RS2Stage {
  param([string]$UserContent, [int]$Ctx = 16384)
  $body = @{
    model    = $Model
    stream   = $false
    think    = $think
    messages = @(@{ role = "user"; content = $UserContent })
    options  = @{ num_ctx = $Ctx }
  } | ConvertTo-Json -Depth 6
  $resp = Invoke-RestMethod -Uri $Endpoint -Method Post -Body $body -ContentType "application/json" -TimeoutSec 1800
  return $resp.message.content
}

# ---- run pipeline ------------------------------------------------------
$stamp   = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir  = Join-Path "reports" "$($Ticker)_$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Write-Host "[out] $outDir`n" -ForegroundColor Green

$accum = ""   # rolling context of prior stage outputs
foreach ($s in $stages) {
  Write-Host ">> $($s.title)" -ForegroundColor Magenta
  $sw = [Diagnostics.Stopwatch]::StartNew()

  if ([string]::IsNullOrWhiteSpace($data))  { $dataBlock  = "(none provided — tag all unverified inputs [Unconfirmed]/[Assumption])" } else { $dataBlock  = $data }
  if ([string]::IsNullOrWhiteSpace($accum)) { $accumBlock = "(this is the first stage)" } else { $accumBlock = $accum }

  $prompt = @"
TICKER UNDER ANALYSIS: $Ticker

=== ANALYST-SUPPLIED DATA (use as [Actual]; tag missing items) ===
$dataBlock

=== PRIOR-STAGE RESULTS (already completed, build on these — do not contradict) ===
$accumBlock

=== YOUR TASK FOR THIS STAGE ===
$($s.task)
"@

  $out  = Invoke-RS2Stage -UserContent $prompt -Ctx $StageCtx
  $sw.Stop()
  $file = Join-Path $outDir "$($s.id).md"
  Set-Content -Path $file -Value $out -Encoding utf8
  Write-Host ("   done in {0:n1}s -> {1}`n" -f $sw.Elapsed.TotalSeconds, $file) -ForegroundColor DarkGray

  # carry forward a trimmed summary so context doesn't explode
  $accum += "`n`n----- $($s.title) -----`n$out"
}

# ---- final assembly ----------------------------------------------------
Write-Host ">> FINAL ASSEMBLY (Sections 0-12) [ctx $FinalCtx]" -ForegroundColor Magenta
$finalPrompt = @"
TICKER: $Ticker

=== COMPLETE WORKED ANALYSIS (all stages) ===
$accum

=== TASK ===
$finalTask
"@
$final = Invoke-RS2Stage -UserContent $finalPrompt -Ctx $FinalCtx
$finalFile = Join-Path $outDir "FINAL.md"
Set-Content -Path $finalFile -Value $final -Encoding utf8

Write-Host "`n[DONE] Final report -> $finalFile" -ForegroundColor Green
