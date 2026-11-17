# Runs the local CVAT stack (labeling tool) on THIS PC.
#
#   .\labeling\cvat.ps1 up          start CVAT (first start pulls several GB of images)
#   .\labeling\cvat.ps1 down        stop it (the database and tasks are kept in docker volumes)
#   .\labeling\cvat.ps1 status|logs
#   .\labeling\cvat.ps1 superuser   create the admin account (asks for the password interactively)
#
# The Docker context is pinned to Docker Desktop on purpose: the default context of this machine points at
# the Raspberry Pi over SSH, and CVAT must never be started there.
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('up', 'down', 'status', 'logs', 'superuser')]
    [string]$Command
)
$ErrorActionPreference = 'Stop'

$CvatVersion = 'v2.79.0'
$Context = 'desktop-linux'
$Here = $PSScriptRoot
$CvatDir = Join-Path $Here 'cvat'
$SharedDir = Join-Path $Here 'batches'

cmd /c "docker --context $Context info >nul 2>nul"
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running (context '$Context'). Start it and retry." }

if (-not (Test-Path (Join-Path $CvatDir 'docker-compose.yml'))) {
    & git clone --depth 1 --branch $CvatVersion https://github.com/cvat-ai/cvat.git $CvatDir
    if ($LASTEXITCODE -ne 0) { throw 'git clone of CVAT failed' }
}
if (-not (Test-Path $SharedDir)) { New-Item -ItemType Directory -Path $SharedDir | Out-Null }

$env:CVAT_VERSION = $CvatVersion
$env:CVAT_HOST = 'localhost'
$env:CVAT_SHARE_DIR = $SharedDir -replace '\\', '/'
$compose = @('--context', $Context, 'compose', '-p', 'cvat',
    '-f', (Join-Path $CvatDir 'docker-compose.yml'), '-f', (Join-Path $Here 'compose.share.yml'))

switch ($Command) {
    'up'        { & docker @compose up -d; if ($LASTEXITCODE -eq 0) { Write-Host "CVAT: http://localhost:8080 (create the admin with: .\labeling\cvat.ps1 superuser)" } }
    'down'      { & docker @compose down }
    'status'    { & docker @compose ps }
    'logs'      { & docker @compose logs -f --tail 100 cvat_server cvat_worker_import }
    'superuser' { & docker --context $Context exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser' }
}
