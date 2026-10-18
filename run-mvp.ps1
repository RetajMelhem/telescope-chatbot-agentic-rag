param(
    [ValidateSet('Start', 'Stop', 'Status', 'Restart')][string]$Action = 'Start',
    [ValidateRange(1024, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$previousPort = $env:TELESCOPE_MVP_PORT
try {
    $env:TELESCOPE_MVP_PORT = "$Port"
    $composeArgs = @('compose', '--env-file', 'deploy/local-mvp.env', '-f',
        'deploy/compose.local-mvp.yaml', '--project-name', 'telescope-local-mvp')
    if ($Action -eq 'Stop') {
        & docker @composeArgs stop api
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the local API.' }
        Write-Host 'Local API stopped. Database and knowledge remain intact.'
        return
    }
    if ($Action -eq 'Status') {
        & docker @composeArgs ps
        if ($LASTEXITCODE -ne 0) { throw 'Could not read local API status.' }
        return
    }
    foreach ($container in @('telescope-m3-qdrant', 'telescope-m3-qdrant-gateway')) {
        $state = docker inspect --format '{{.State.Status}}' $container 2>$null
        if ($LASTEXITCODE -ne 0) { throw "Missing required local container: $container." }
        if ($state -ne 'running') {
            docker start $container | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not start $container." }
        }
    }
    $uvExecutable = Join-Path $PSScriptRoot '.tools/uv/bin/uv.exe'
    if (-not (Test-Path -LiteralPath $uvExecutable)) {
        $uvExecutable = (Get-Command uv -ErrorAction Stop).Source
    }
    & $uvExecutable run --locked python scripts/prepare_local_mvp_runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Local runtime preparation failed.' }
    & docker @composeArgs config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Local Compose configuration is invalid.' }
    if ($Action -eq 'Start') {
        & docker @composeArgs up -d --build --force-recreate --wait --wait-timeout 90 api
    }
    else {
        & docker @composeArgs up -d --force-recreate --wait --wait-timeout 90 api
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Local API failed to start. Check Docker logs and whether the selected port is free.'
    }
    Write-Host "Local chat: http://127.0.0.1:$Port/ | API docs: http://127.0.0.1:$Port/docs"
    Write-Host 'Each question uses the project OpenRouter key. Stop with .\run-mvp.ps1 -Action Stop.'
}
finally {
    $env:TELESCOPE_MVP_PORT = $previousPort
    Pop-Location
}
