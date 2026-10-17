$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    foreach ($container in @('telescope-m3-qdrant', 'telescope-m3-qdrant-gateway')) {
        $state = docker inspect --format '{{.State.Status}}' $container 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "Missing local container: $container. See docs/LOCAL_MVP.md."
        }
        if ($state -ne 'running') {
            docker start $container | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not start $container." }
        }
    }
    $uvExecutable = Join-Path $PSScriptRoot '.tools/uv/bin/uv.exe'
    if (-not (Test-Path -LiteralPath $uvExecutable)) {
        $uvExecutable = (Get-Command uv -ErrorAction Stop).Source
    }
    Write-Host 'Local chat: http://127.0.0.1:8000/  |  API docs: http://127.0.0.1:8000/docs'
    Write-Host 'Each question uses the project OpenRouter key. Ctrl+C stops the API.'
    & $uvExecutable run --locked python -m telescope_rag.api.local
    if ($LASTEXITCODE -ne 0) { throw 'The local MVP could not start. Check its safe error above.' }
}
finally {
    Pop-Location
}
