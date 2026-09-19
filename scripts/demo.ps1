param(
    [switch]$KeepRunning,
    [int]$ObserveSeconds = 25
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$reportDir = Join-Path $projectRoot "reports\demo-$stamp"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
Push-Location $projectRoot

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'docker command not found. Start Docker Desktop and open a new PowerShell window.'
    }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'py command not found. Install Python 3.10+ for this Windows demo.'
    }

    Write-Host '[1/5] Start the isolated Docker demo.'
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

    $healthy = $false
    for ($i = 0; $i -lt 20; $i++) {
        curl.exe -fsS http://127.0.0.1:8088/healthz 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $healthy = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) { throw 'recommendation did not become healthy' }
    Write-Host "[2/5] Collect Prometheus samples for $ObserveSeconds seconds."
    Start-Sleep -Seconds $ObserveSeconds

    $preMetrics = curl.exe -fsS http://127.0.0.1:8088/metrics
    if ($LASTEXITCODE -ne 0) { throw 'metrics endpoint failed' }
    $preMetrics | Set-Content -LiteralPath (Join-Path $reportDir 'before.metrics.txt') -Encoding UTF8
    docker stats aiops-recommendation --no-stream --format 'MemUsage={{.MemUsage}}' |
        Set-Content -LiteralPath (Join-Path $reportDir 'before.stats.txt') -Encoding UTF8

    Write-Host '[3/5] Run read-only diagnosis.'
    $readonlyPath = Join-Path $reportDir 'readonly.json'
    py -m aiops.run alerts/s4.json --mode heuristic --report $readonlyPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'read-only diagnosis failed' }
    $readonly = Get-Content -LiteralPath $readonlyPath -Raw | ConvertFrom-Json
    Write-Host "  route=$($readonly.route)"
    Write-Host "  evidence=$($readonly.diagnosis.evidence -join ' | ')"
    if ($readonly.route -ne 'human_review_online_op_code_fix_pending') {
        throw 'expected growth diagnosis was not produced; inspect readonly.json'
    }

    Write-Host '[4/5] Permit one authorized restart of this demo container.'
    $restartPath = Join-Path $reportDir 'restart.json'
    py -m aiops.run alerts/s4.json --mode heuristic --apply-low-risk --report $restartPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'restart diagnosis failed' }
    $restart = Get-Content -LiteralPath $restartPath -Raw | ConvertFrom-Json
    Write-Host "  route=$($restart.route)"
    Write-Host "  health_verified=$($restart.executed_actions[0].health_verified)"
    if ($restart.route -ne 'auto_remediated_code_fix_pending' -or
        -not $restart.executed_actions[0].health_verified) {
        throw 'restart was not verified; inspect restart.json'
    }

    Write-Host '[5/5] Capture after-restart metrics and save evidence.'
    $postMetrics = curl.exe -fsS http://127.0.0.1:8088/metrics
    if ($LASTEXITCODE -ne 0) { throw 'post-restart metrics endpoint failed' }
    $postMetrics | Set-Content -LiteralPath (Join-Path $reportDir 'after.metrics.txt') -Encoding UTF8
    docker stats aiops-recommendation --no-stream --format 'MemUsage={{.MemUsage}}' |
        Set-Content -LiteralPath (Join-Path $reportDir 'after.stats.txt') -Encoding UTF8
    Write-Host "Evidence saved to: $reportDir"
    Write-Host 'Restart is temporary containment; the planted code leak remains.'
}
finally {
    if (-not $KeepRunning) {
        Write-Host 'Stopping demo containers.'
        docker compose stop | Out-Null
    }
    Pop-Location
}
