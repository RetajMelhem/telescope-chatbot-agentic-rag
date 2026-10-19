#requires -Version 5.1
<#
Tests public GitHub main and release assets in an empty, disposable Docker engine.
The Windows installer runs unchanged. A Docker command adapter maps only this
test's Windows paths to /cold and forwards commands into the isolated engine.
No existing installation, application image, volume or private key is supplied.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version = 'v0.2.0',
    [string]$OutputDirectory,
    [string]$DockerContext = 'desktop-linux'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$dockerExe = @(Get-Command docker.exe -CommandType Application)[0].Source
$gitExe = @(Get-Command git.exe -CommandType Application)[0].Source
$testId = [guid]::NewGuid().ToString('N').Substring(0,12)
$engineName = "telescope-cold-engine-$testId"
$instance = "telescope-portable-cold-$testId"
$engineImage = 'docker@sha256:3e5756e2b6dad6a5f1f5deacf0a19f9eaa2581b76ae092b2d4a118162e1d4d4e'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) "artifacts/portable-cold-install-$testId"
}
$testRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $testRoot) { throw 'The test output directory must not exist yet.' }
[void][IO.Directory]::CreateDirectory($testRoot)
$source = Join-Path $testRoot 'source'
$installRoot = Join-Path $testRoot 'install'
$reportPath = Join-Path $testRoot 'report.json'
$report = [ordered]@{
    schema_version='portable-cold-install-test-v1'; started_utc=[DateTime]::UtcNow.ToString('o')
    status='running'; source_url='https://github.com/RetajMelhem/telescope-chatbot-agentic-rag.git'
    source_branch='main'; version=$Version; engine_image=$engineImage
    synthetic_openrouter_key=$true; model_calls=0; instance=$instance
    limitation='Same Windows/Docker Desktop host and kernel; Docker path adapter, not a second physical machine.'
}
$coldCalls = New-Object Collections.ArrayList
$engineStarted = $false
$originalContainers = @()
function Save-Report {
    [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 30), (New-Object Text.UTF8Encoding($false)))
}
function Host-Docker {
    param([string[]]$Arguments)
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & $dockerExe --context $DockerContext @Arguments
        if ($LASTEXITCODE -ne 0) { throw 'A test Docker operation failed.' }
        return $result
    } finally { $ErrorActionPreference = $savedPreference }
}
function Inner-Docker {
    param([string[]]$Arguments)
    Host-Docker -Arguments (@('exec',$engineName,'docker','--host','unix:///var/run/docker.sock') + $Arguments)
}
try {
    $originalContainers = @(Host-Docker -Arguments @('ps','-aq','--no-trunc'))
    $originalStarted = @{}
    foreach ($id in $originalContainers) {
        $originalStarted[$id] = Host-Docker -Arguments @('inspect','--format','{{.State.StartedAt}}',$id)
    }
    $report.original_container_count = $originalContainers.Count
    & $gitExe clone --branch main --single-branch $report.source_url $source
    if ($LASTEXITCODE -ne 0) { throw 'The public GitHub clone failed.' }
    $report.source_revision = & $gitExe -C $source rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'The source revision could not be read.' }
    if (@(& $gitExe -C $source status --porcelain).Count -or
        (Test-Path -LiteralPath (Join-Path $source '.env')) -or
        (Test-Path -LiteralPath (Join-Path $source '.venv')) -or
        (Test-Path -LiteralPath $installRoot)) { throw 'The clone/install directory is not clean.' }
    $report.fresh_clone_and_install_root = $true
    Host-Docker -Arguments @('pull',$engineImage)
    $containerId = Host-Docker -Arguments @('run','-d','--privileged','--name',$engineName,
        '--label',"telescope.cold_test=$testId",'--env','DOCKER_TLS_CERTDIR=',
        '--mount',"type=bind,source=$testRoot,target=/cold",$engineImage)
    $engineStarted = $true
    $report.engine_container_id = $containerId
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        $savedPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $engineVersion = & $dockerExe --context $DockerContext exec $engineName docker --host unix:///var/run/docker.sock info --format '{{.ServerVersion}}' 2>$null
        $probeCode = $LASTEXITCODE
        $ErrorActionPreference = $savedPreference
        if ($probeCode -eq 0) { break }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'The isolated Docker engine did not become ready.' }
        Start-Sleep -Milliseconds 500
    } while ($true)
    $report.engine_version = $engineVersion
    $empty = [ordered]@{
        images=@(Inner-Docker -Arguments @('image','ls','-aq'))
        containers=@(Inner-Docker -Arguments @('ps','-aq'))
        volumes=@(Inner-Docker -Arguments @('volume','ls','-q'))
    }
    $report.engine_before_install = $empty
    if ($empty.images.Count -or $empty.containers.Count -or $empty.volumes.Count) {
        throw 'The isolated Docker engine was not empty.'
    }
    Write-Host 'Verified: isolated engine has zero images, containers and volumes.'
    foreach ($entry in @(Get-ChildItem Env: | Where-Object {
        $_.Name -like 'PORTABLE_*' -or $_.Name -in @('OPENROUTER_API_KEY','OPENAI_API_KEY')
    })) { Remove-Item -LiteralPath "Env:$($entry.Name)" }
    $syntheticKey = Join-Path $testRoot 'synthetic-openrouter.key'
    [IO.File]::WriteAllText($syntheticKey, ('sk-or-v1-' + ('x' * 40)), [Text.Encoding]::ASCII)

    # Only command transport/mount paths differ for the nested Linux daemon.
    # The cloned installer, Compose file and release assets remain unchanged.
    $adapter = {
        $arguments = @($args | ForEach-Object { [string]$_ })
        [void]$coldCalls.Add($arguments)
        $mapPath = {
            param([string]$Value)
            if ($Value.IndexOf($testRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
                return ([regex]::Replace($Value,[regex]::Escape($testRoot),'/cold','IgnoreCase')).Replace('\','/')
            }
            return $Value
        }
        $forward = @('exec')
        foreach ($setting in @(Get-ChildItem Env: | Where-Object { $_.Name -like 'PORTABLE_*' })) {
            $forward += @('--env',($setting.Name + '=' + (& $mapPath $setting.Value)))
        }
        $forward += @($engineName,'docker','--host','unix:///var/run/docker.sock')
        $forward += @($arguments | ForEach-Object { & $mapPath $_ })
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $dockerExe --context $DockerContext @forward
        } finally { $ErrorActionPreference = $savedPreference }
    }.GetNewClosure()
    Set-Item -Path Function:docker -Value $adapter
    & (Join-Path $source 'install-mvp.ps1') -Version $Version -InstallRoot $installRoot -Instance $instance -Port 8000 -OpenRouterKeyFile $syntheticKey
    if (-not (Test-Path -LiteralPath (Join-Path $installRoot 'current.json'))) {
        throw 'The installer did not record a successful installation.'
    }
    $state = Get-Content -LiteralPath (Join-Path $installRoot 'current.json') -Raw | ConvertFrom-Json
    $manifest = Get-Content -LiteralPath (Join-Path $installRoot "releases/$Version/release.json") -Raw | ConvertFrom-Json
    $assetChecks = @()
    foreach ($asset in $manifest.assets.PSObject.Properties) {
        $path = Join-Path $installRoot ('downloads/' + $asset.Value.name)
        $matches = (Test-Path -LiteralPath $path) -and
            (Get-Item -LiteralPath $path).Length -eq $asset.Value.bytes -and
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $asset.Value.sha256
        $assetChecks += [PSCustomObject]@{category=$asset.Name;name=$asset.Value.name;verified=$matches}
        if (-not $matches) { throw 'A downloaded release asset is absent or differs from the manifest.' }
    }
    $loads = @($coldCalls | Where-Object { $_[0] -eq 'image' -and $_[1] -eq 'load' })
    if ($loads.Count -ne 2) { throw 'Both application image archives must be downloaded and loaded.' }
    $report.assets = $assetChecks
    $report.image_archive_loads = $loads.Count
    $report.knowledge_id = $state.knowledge_id
    $report.runtime_files = $manifest.knowledge.files.Count
    $report.database_points = $manifest.knowledge.database.points
    $report.database_fingerprint = $manifest.knowledge.database.points_sha256
    $report.database_verified_by_installer_before_and_after_start = $true
    $apiName = "$instance-api"
    $inspection = (Inner-Docker -Arguments @('inspect',$apiName) | ConvertFrom-Json)[0]
    $mounts = @($inspection.Mounts | Select-Object Source,Destination,RW)
    foreach ($mount in $mounts) {
        if (-not $mount.Source.StartsWith('/cold/install/') -or $mount.RW) {
            throw 'The API used an unexpected or writable host mount.'
        }
    }
    $report.api_mounts = $mounts
    $report.api_user = $inspection.Config.User
    $report.api_read_only_root = $inspection.HostConfig.ReadonlyRootfs
    $report.api_health = $inspection.State.Health.Status
    if ($report.api_health -cne 'healthy') { throw 'The isolated API is not healthy.' }
    $databaseInspection = (Inner-Docker -Arguments @('inspect',"$instance-qdrant") | ConvertFrom-Json)[0]
    $bindings = @($databaseInspection.HostConfig.PortBindings.'6333/tcp')
    if ($bindings.Count -ne 1 -or $bindings[0].HostIp -cne '127.0.0.1' -or
        $bindings[0].HostPort -cne '6333' -or $databaseInspection.HostConfig.PortBindings.'6334/tcp') {
        throw 'The dashboard must publish only the REST port on localhost.'
    }
    $published = @($databaseInspection.NetworkSettings.Ports.'6333/tcp')
    if ($published.Count -ne 1 -or $published[0].HostIp -cne '127.0.0.1' -or
        $published[0].HostPort -cne '6333') { throw 'The dashboard port was not actually published.' }
    $report.qdrant_dashboard_loopback_binding = $true
    $httpCheck = @'
import json, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
results = {}
for route in ('/', '/health/live', '/health/ready', '/docs', '/openapi.json'):
    with opener.open('http://127.0.0.1:8000' + route, timeout=10) as response:
        results[route] = response.status
assert all(code == 200 for code in results.values())
with opener.open('http://telescope-m3-qdrant:6333/dashboard/', timeout=10) as response:
    assert response.status == 200 and b'<html' in response.read().lower()
results['qdrant_dashboard'] = 200
from pathlib import Path
key = Path('/run/secrets/qdrant_read_key').read_text().strip()
request = urllib.request.Request('http://telescope-m3-qdrant:6333/collections', headers={'api-key': key})
with opener.open(request, timeout=10) as response:
    assert len(json.load(response)['result']['collections']) == 1
results['qdrant_read_only_collections'] = 200
print(json.dumps(results))
'@
    $report.http_endpoints = Inner-Docker -Arguments @('exec',$apiName,'python','-c',$httpCheck) | ConvertFrom-Json
    $report.status = 'passed'
    Write-Host 'Verified: public release installs, restores and serves five healthy HTTP endpoints without existing application resources.'
} catch {
    $report.status = 'failed'
    $report.error = $_.Exception.Message
    throw
} finally {
    [IO.File]::WriteAllText((Join-Path $testRoot 'docker-commands.json'),
        (ConvertTo-Json -InputObject @($coldCalls) -Depth 10), (New-Object Text.UTF8Encoding($false)))
    try {
        if ($engineStarted) {
            $labels = Host-Docker -Arguments @('inspect','--format','{{json .Config.Labels}}',$engineName) | ConvertFrom-Json
            if ($labels.'telescope.cold_test' -cne $testId) { throw 'Test engine ownership mismatch; cleanup refused.' }
            Host-Docker -Arguments @('rm','-f','-v',$engineName)
            $report.test_engine_removed = $true
        }
        $preserved = $true
        foreach ($id in $originalContainers) {
            $started = Host-Docker -Arguments @('inspect','--format','{{.State.StartedAt}}',$id)
            if ($started -cne $originalStarted[$id]) { $preserved = $false }
        }
        $report.original_containers_preserved = $preserved
        if (-not $preserved) { throw 'An original container changed during the test.' }
    } catch {
        $report.status='failed'
        $report.cleanup_error=$_.Exception.Message
        throw
    } finally {
        $report.finished_utc = [DateTime]::UtcNow.ToString('o')
        Save-Report
        Write-Host "Cold-install report: $reportPath"
    }
}
