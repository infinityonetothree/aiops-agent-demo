param(
    [switch]$KeepRunning,
    [int]$ObserveSeconds = 25
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project .venv is missing. Create it before running the Agent demo.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$reportDir = Join-Path $projectRoot "reports\agent-$stamp"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
Push-Location $projectRoot

try {
    docker compose --profile local-agent up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

    $healthy = $false
    for ($i = 0; $i -lt 20; $i++) {
        curl.exe -fsS http://127.0.0.1:8088/healthz 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $healthy = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) { throw 'recommendation did not become healthy' }

    $ollamaReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-RestMethod -Uri http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null
            $ollamaReady = $true
            break
        }
        catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ollamaReady) { throw 'Ollama did not become ready' }

    Write-Host 'Ensure the local qwen3:4b model is available.'
    docker exec aiops-ollama ollama pull qwen3:4b
    if ($LASTEXITCODE -ne 0) { throw 'Ollama model pull failed' }
    Start-Sleep -Seconds $ObserveSeconds

    $reportPath = Join-Path $reportDir 'agent.json'
    & $python -m aiops.run alerts/s4.json --mode ollama --report $reportPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Agent command failed' }

    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.note -or -not $report.agent_run.tool_called) {
        throw "Agent diagnosis was not verified. Inspect $reportPath"
    }
    Write-Host "route=$($report.route)"
    Write-Host "provider=$($report.agent_run.provider)"
    Write-Host "model=$($report.agent_run.model)"
    Write-Host "tool_called=$($report.agent_run.tool_called)"
    Write-Host "num_turns=$($report.agent_run.num_turns)"
    Write-Host "total_duration_ms=$($report.agent_run.total_duration_ms)"
    Write-Host "Evidence saved to: $reportPath"
}
finally {
    if (-not $KeepRunning) {
        docker compose --profile local-agent stop | Out-Null
    }
    Pop-Location
}
