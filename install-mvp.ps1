#requires -Version 5.1
param(
    [ValidateSet('Install', 'Start', 'Stop', 'Status', 'Rollback')][string]$Action = 'Install',
    [ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version,
    [string]$ReleaseDirectory,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'TelescopeRag'),
    [ValidatePattern('^telescope-portable(?:-[a-z0-9-]{1,30})?$')][string]$Instance = 'telescope-portable',
    [ValidateRange(1024,65535)][int]$Port = 8000,
    [string]$OpenRouterKeyFile,
    [string]$EnvFile
)
$ErrorActionPreference = 'Stop'
$compose = Join-Path $PSScriptRoot 'deploy/compose.portable.yaml'
$interpolation = Join-Path $PSScriptRoot 'deploy/local-mvp.env'
$root = [IO.Path]::GetFullPath($InstallRoot)
$baseUrl = "https://github.com/RetajMelhem/telescope-chatbot-agentic-rag/releases/download/$Version/"
function Run-Docker {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Portable Docker operation failed. Existing knowledge is preserved.' }
}
function Read-Json([string]$Path) {
    if ((Get-Item -LiteralPath $Path).Length -gt 1000000) { throw 'Manifest exceeds its limit.' }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function Safe-Directory([string]$Path) {
    $candidate = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $candidate)) { $candidate = [IO.Path]::GetDirectoryName($candidate) }
    $item = Get-Item -LiteralPath $candidate
    while ($item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse installation paths are refused.' }
        $item = $item.Parent
    }
}
function Save-Json($Value, [string]$Path) {
    $text = $Value | ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText($Path, $text, (New-Object Text.UTF8Encoding($false)))
}
function Asset-File($Asset) {
    if ($Asset.name -cnotmatch '^[a-z0-9][a-z0-9._-]{0,100}$' -or
        $Asset.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $Asset.bytes -le 0 -or $Asset.bytes -ge 2147483648) {
        throw 'Invalid release asset.'
    }
    $destination = Join-Path $cache $Asset.name
    Safe-Directory $destination
    if (Test-Path -LiteralPath $destination) {
        if ((Get-Item -LiteralPath $destination).Length -eq $Asset.bytes -and
            (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Asset.sha256) { return $destination }
        throw 'Cached asset does not match this release. Refusing to overwrite it.'
    }
    $temporary = "$destination.download-$([guid]::NewGuid().ToString('N'))"
    if ($ReleaseDirectory) {
        Copy-Item -LiteralPath (Join-Path $ReleaseDirectory $Asset.name) -Destination $temporary
    } else {
        Invoke-WebRequest -Uri ($baseUrl + $Asset.name) -OutFile $temporary -UseBasicParsing -TimeoutSec 180
    }
    if ((Get-Item -LiteralPath $temporary).Length -ne $Asset.bytes -or
        (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Asset.sha256) {
        throw 'Downloaded asset verification failed. It has not been installed.'
    }
    Move-Item -LiteralPath $temporary -Destination $destination
    return $destination
}
function Ensure-Image([string]$Category) {
    $image = $manifest.images.$Category
    $reference = $image.reference
    $allowed = switch ($Category) {
        'api' { "telescope-rag-mvp:$Version" }
        'qdrant' { 'qdrant/qdrant@sha256:b7b0444c4c351c970b98e90a6f89c2ee4287c65b44e52b4cb503fa5b2aa927ad' }
    }
    if ($reference -cne $allowed -or $image.image_id -cnotmatch '^sha256:[0-9a-f]{64}$') { throw 'Release image binding is invalid.' }
    # Docker save/load need not preserve repository digests; the image ID is exact.
    $probe = if ($Category -eq 'qdrant') { $image.image_id } else { $reference }
    $actual = Probe-Docker -Arguments @('image','inspect','--format','{{.Id}}',$probe)
    if ($actual -ceq $image.image_id) { return }
    $file = Asset-File $manifest.assets.$Category
    Run-Docker -Arguments @('image','load','--input',$file)
    $actual = & docker image inspect --format '{{.Id}}' $probe
    if ($LASTEXITCODE -ne 0 -or $actual -cne $image.image_id) { throw 'Loaded image differs from the release.' }
}
function Private-Directory([string]$Path) {
    Safe-Directory $Path
    [void][IO.Directory]::CreateDirectory($Path)
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    $ids = @([Security.Principal.WindowsIdentity]::GetCurrent().User,
        (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')),
        (New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach ($id in $ids) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($id, 'FullControl', $inheritance, 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
function New-Key {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
}
function Prepare-Secrets {
    Private-Directory $secretDir
    foreach ($name in @('admin.key','read.key')) {
        $path = Join-Path $secretDir $name
        if (-not (Test-Path -LiteralPath $path)) { [IO.File]::WriteAllText($path, (New-Key), [Text.Encoding]::ASCII) }
    }
    $key = $null
    if ($OpenRouterKeyFile) { $key = [IO.File]::ReadAllText([IO.Path]::GetFullPath($OpenRouterKeyFile)).Trim() }
    elseif ($EnvFile -or (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
        if (-not $EnvFile) { $EnvFile = Join-Path $PSScriptRoot '.env' }
        $lines = @([IO.File]::ReadAllLines([IO.Path]::GetFullPath($EnvFile)) | Where-Object { $_ -match '^\s*OPENROUTER_API_KEY\s*=' })
        if ($lines.Count -ne 1) { throw 'The selected dotenv must have exactly one project OpenRouter key.' }
        $key = ($lines[0] -split '=',2)[1].Trim().Trim('"').Trim("'")
    } elseif (Test-Path -LiteralPath (Join-Path $secretDir 'openrouter.key')) {
        $key = [IO.File]::ReadAllText((Join-Path $secretDir 'openrouter.key')).Trim()
    } else {
        $secure = Read-Host 'Enter your OpenRouter API key (hidden)' -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
    if ($key -cnotmatch '^sk-or-v1-[A-Za-z0-9_-]{30,}$') { throw 'A valid-format project OpenRouter key is required; its value is hidden.' }
    [IO.File]::WriteAllText((Join-Path $secretDir 'openrouter.key'), $key, [Text.Encoding]::ASCII)
    $admin = [IO.File]::ReadAllText((Join-Path $secretDir 'admin.key'))
    $read = [IO.File]::ReadAllText((Join-Path $secretDir 'read.key'))
    $config = "telemetry_disabled: true`nlog_level: WARN`nservice:`n  enable_cors: false`n  api_key: $admin`n  read_only_api_key: $read`n"
    [IO.File]::WriteAllText((Join-Path $secretDir 'qdrant.yaml'), $config, [Text.Encoding]::ASCII)
}
function Compose-Settings($State) {
    $values = @{
        PORTABLE_PROJECT=$Instance; PORTABLE_INSTALLATION_ID=$owner.id
        PORTABLE_SECRET_DIR=$secretDir; PORTABLE_DATA_DIR=$State.data_root
        PORTABLE_SNAPSHOT=$State.snapshot; PORTABLE_VOLUME=$State.volume
        PORTABLE_API_IMAGE=$State.api_image; PORTABLE_PORT=[string]$State.port
        PORTABLE_QDRANT_IMAGE=$State.qdrant_image
    }
    foreach ($pair in $values.GetEnumerator()) { [Environment]::SetEnvironmentVariable($pair.Key, $pair.Value, 'Process') }
}
function Compose {
    param([string[]]$Arguments)
    Run-Docker -Arguments (@('compose','--env-file',$interpolation,'-f',$compose,'--project-name',$Instance) + $Arguments)
}
function Helper([string]$Operation, [string]$Data, [string]$Target='installed', [string]$Archive='') {
    $argsList = @('run','--rm','--read-only','--user','10001:10001')
    $argsList += @('--network', $(if ($Operation -eq 'verify-db') { "$Instance-knowledge" } else { 'none' }))
    $argsList += @('--mount',"type=bind,source=$manifestPath,target=/input/release.json,readonly")
    $argsList += @('--mount',"type=bind,source=$Data,target=/runtime" + $(if ($Operation -eq 'extract') { '' } else { ',readonly' }))
    if ($Operation -eq 'verify-db') { $argsList += @('--mount',"type=bind,source=$secretDir/read.key,target=/run/secrets/qdrant_read_key,readonly") }
    if ($Archive) { $argsList += @('--mount',"type=bind,source=$Archive,target=/input/knowledge.zip,readonly") }
    $argsList += @('--entrypoint','python',$manifest.images.api.reference,'-m','telescope_rag.operations.release',$Operation,'--manifest','/input/release.json','--root','/runtime')
    if ($Archive) { $argsList += @('--archive','/input/knowledge.zip') }
    if ($Operation -eq 'verify-db') { $argsList += @('--target',$Target) }
    Run-Docker -Arguments $argsList
}
function Start-State($State) {
    Compose-Settings $State
    Compose -Arguments @('up','-d','--force-recreate','--wait','--wait-timeout','100','qdrant','api')
}
function Probe-Docker {
    param([string[]]$Arguments)
    $saved = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & docker @Arguments 2>$null
        if ($LASTEXITCODE -eq 0) { return $result }
        return $null
    } finally { $ErrorActionPreference = $saved }
}

# All managed state is separate from a development checkout and its database.
Safe-Directory $root
if ($root.Contains(',') -or $root.Contains("`n") -or $root.Contains("`r")) { throw 'InstallRoot contains unsupported mount characters.' }
[void][IO.Directory]::CreateDirectory($root)
$ownerPath = Join-Path $root 'installation.json'
if (-not (Test-Path -LiteralPath $ownerPath)) {
    if (@(Get-ChildItem -LiteralPath $root -Force).Count) { throw 'InstallRoot must be empty or an existing portable installation.' }
    Save-Json @{schema_version='portable-installation-v1';instance=$Instance;id=[guid]::NewGuid().ToString('N')} $ownerPath
}
$owner = Read-Json $ownerPath
if ($owner.schema_version -ne 'portable-installation-v1' -or $owner.instance -cne $Instance -or $owner.id -cnotmatch '^[0-9a-f]{32}$') { throw 'Installation identity mismatch.' }
Private-Directory $root
foreach ($name in @('api','qdrant','restore')) {
    $existing = Probe-Docker -Arguments @('inspect',"$Instance-$name")
    if ($existing) {
        $container = ($existing | ConvertFrom-Json)[0]
        if ($container.Config.Labels.'telescope.installation_id' -cne $owner.id) { throw 'Container belongs to another installation.' }
    }
}
$secretDir = Join-Path $root 'secrets'
$statePath = Join-Path $root 'current.json'
$previousPath = Join-Path $root 'previous.json'
$current = if (Test-Path -LiteralPath $statePath) { Read-Json $statePath } else { $null }
if ($Action -ne 'Install') {
    if (-not $current) { throw 'No successful portable installation exists here.' }
    if ($Action -eq 'Rollback') {
        $previous = Read-Json $previousPath
        Start-State $previous
        Save-Json $current $previousPath
        Save-Json $previous $statePath
    } else {
        Compose-Settings $current
        switch ($Action) {
            'Start' { Start-State $current }
            'Stop' { Compose -Arguments @('stop','api','qdrant') }
            'Status' { Compose -Arguments @('ps') }
        }
    }
    return
}
if (-not $Version) { throw 'Install requires -Version vX.Y.Z.' }
if ($ReleaseDirectory) { $ReleaseDirectory = [IO.Path]::GetFullPath($ReleaseDirectory) }
$releaseRoot = Join-Path $root "releases/$Version"
Safe-Directory $releaseRoot
[void][IO.Directory]::CreateDirectory($releaseRoot)
$cache = Join-Path $root 'downloads'
Safe-Directory $cache
[void][IO.Directory]::CreateDirectory($cache)
$manifestPath = Join-Path $releaseRoot 'release.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    if ($ReleaseDirectory) { Copy-Item -LiteralPath (Join-Path $ReleaseDirectory 'release.json') -Destination $manifestPath }
    else { Invoke-WebRequest -Uri ($baseUrl+'release.json') -OutFile $manifestPath -UseBasicParsing -TimeoutSec 30 }
}
$manifest = Read-Json $manifestPath
if ($manifest.schema_version -cne 'portable-mvp-release-v1' -or $manifest.version -cne $Version -or
    $manifest.platform -cne 'linux/amd64' -or $manifest.knowledge_id -cnotmatch '^[0-9a-f]{64}$') { throw 'Unsupported release manifest.' }
foreach ($category in @('api','qdrant')) { Ensure-Image $category }
$dataRoot = Join-Path $root "knowledge/$($manifest.knowledge_id)"
Safe-Directory $dataRoot
if (Test-Path -LiteralPath $dataRoot) {
    Helper 'verify-files' $dataRoot
} else {
    $knowledgeZip = Asset-File $manifest.assets.knowledge
    $stage = Join-Path $root "knowledge/stage-$([guid]::NewGuid().ToString('N'))"
    [void][IO.Directory]::CreateDirectory($stage)
    Helper 'extract' $stage 'installed' $knowledgeZip
    Move-Item -LiteralPath $stage -Destination $dataRoot
}
Prepare-Secrets
$reuse = $current -and $current.knowledge_id -ceq $manifest.knowledge_id
if ($reuse) {
    $volume = $current.volume
    $snapshotFile = $current.snapshot
} else {
    $snapshotFile = Asset-File $manifest.assets.database
    $volume = "$Instance-knowledge-$($manifest.knowledge_id.Substring(0,24))"
    $existingVolume = Probe-Docker -Arguments @('volume','inspect',$volume)
    if ($existingVolume) { throw 'A target volume already exists. Refusing to restore over it.' }
    Run-Docker -Arguments @('volume','create','--label',"telescope.installation_id=$($owner.id)",'--label',"telescope.knowledge_id=$($manifest.knowledge_id)",$volume)
}
if ($current -and -not $PSBoundParameters.ContainsKey('Port')) { $Port = $current.port }
$next = [PSCustomObject]@{version=$Version;knowledge_id=$manifest.knowledge_id;data_root=$dataRoot;snapshot=$snapshotFile;volume=$volume;api_image=$manifest.images.api.reference;qdrant_image=$manifest.images.qdrant.image_id;port=$Port}
Compose-Settings $next
if (-not $reuse) {
    Compose -Arguments @('--profile','restore','up','-d','qdrant_restore')
    Helper 'verify-db' $dataRoot 'restore'
    Compose -Arguments @('--profile','restore','stop','qdrant_restore')
    Compose -Arguments @('--profile','restore','rm','-f','qdrant_restore')
}
try {
    Start-State $next
    Helper 'verify-db' $dataRoot
} catch {
    if ($current) { Start-State $current }
    throw 'Release startup/verification failed. The successful installation record was preserved.'
}
if ($current -and $current.version -cne $Version) { Save-Json $current $previousPath }
Save-Json $next $statePath
Write-Host "Portable MVP ready: http://127.0.0.1:$Port/"
Write-Host "Knowledge reused: $reuse. Installation made no model calls. New questions can spend OpenRouter credit."
