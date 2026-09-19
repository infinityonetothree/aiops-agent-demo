param([switch]$KeepRunning)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project .venv is missing. Create it before running the repair demo.'
}
Push-Location $projectRoot

try {
    docker compose --profile local-agent up -d ollama
    if ($LASTEXITCODE -ne 0) { throw 'Ollama container failed to start' }
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-RestMethod -Uri http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        }
        catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Ollama did not become ready' }
    docker exec aiops-ollama ollama pull qwen3:4b
    if ($LASTEXITCODE -ne 0) { throw 'qwen3:4b is unavailable' }

    & $python -m aiops.repair
    if ($LASTEXITCODE -ne 0) { throw 'Repair workflow failed' }
}
finally {
    if (-not $KeepRunning) {
        docker compose --profile local-agent stop ollama | Out-Null
    }
    Pop-Location
}
