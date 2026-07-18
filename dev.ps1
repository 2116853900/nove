# Nove one-click local debug launcher
# Usage: .\dev.ps1 [-SkipInstall] [-ApiOnly] [-WebOnly] [-NoKill] [-ApiPort 8000]

param(
    [switch]$SkipInstall,
    [switch]$ApiOnly,
    [switch]$WebOnly,
    [switch]$NoKill,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$ApiDir = Join-Path $Root "apps\api"
$WebDir = Join-Path $Root "apps\web"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-PortListeners([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -and $_ -gt 0 }
}

function Free-Port([int]$Port, [string]$ParamName) {
    $pids = @(Get-PortListeners $Port)
    if ($pids.Count -eq 0) {
        return
    }

    foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { "pid=$procId" }
        Write-Host "Port $Port is in use by $name ($procId)" -ForegroundColor Yellow

        if ($NoKill) {
            throw "Port $Port is busy. Re-run without -NoKill, or use -$ParamName <other>."
        }

        Write-Host "Stopping $name ($procId)..." -ForegroundColor Yellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Milliseconds 500
    $left = @(Get-PortListeners $Port)
    if ($left.Count -gt 0) {
        throw "Failed to free port $Port. Close the process manually and retry."
    }
    Write-Host "Port $Port is free" -ForegroundColor Green
}

function Ensure-ApiDeps {
    if ($SkipInstall) { return }
    Write-Step "Checking API dependencies"
    Push-Location $ApiDir
    try {
        python -c "import fastapi, uvicorn, sqlalchemy" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Installing API packages..."
            python -m pip install -r requirements.txt
        } else {
            Write-Host "API packages already available"
        }
    } finally {
        Pop-Location
    }
}

function Ensure-WebDeps {
    if ($SkipInstall) { return }
    Write-Step "Checking Web dependencies"
    $nodeModules = Join-Path $WebDir "node_modules"
    if (-not (Test-Path -LiteralPath $nodeModules)) {
        Write-Host "Installing Web packages..."
        Push-Location $WebDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "Web packages already available"
    }
}

function Start-Api {
    Write-Step "Starting API on http://127.0.0.1:$ApiPort"
    Free-Port -Port $ApiPort -ParamName "ApiPort"
    $cmd = @"
Set-Location -LiteralPath '$ApiDir'
Write-Host 'Nove API  http://127.0.0.1:$ApiPort' -ForegroundColor Green
Write-Host 'OpenAPI   http://127.0.0.1:$ApiPort/docs' -ForegroundColor DarkGray
Write-Host 'Ctrl+C to stop' -ForegroundColor DarkGray
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port $ApiPort
"@
    Start-Process -FilePath "pwsh" -ArgumentList @("-NoExit", "-Command", $cmd) | Out-Null
}

function Start-Web {
    Write-Step "Starting Web on http://127.0.0.1:$WebPort"
    Free-Port -Port $WebPort -ParamName "WebPort"
    $cmd = @"
Set-Location -LiteralPath '$WebDir'
`$env:VITE_PROXY_TARGET = 'http://127.0.0.1:$ApiPort'
Write-Host 'Nove Web  http://127.0.0.1:$WebPort' -ForegroundColor Green
Write-Host 'Proxy     http://127.0.0.1:$ApiPort' -ForegroundColor DarkGray
Write-Host 'Ctrl+C to stop' -ForegroundColor DarkGray
npm run dev -- --host 127.0.0.1 --port $WebPort
"@
    Start-Process -FilePath "pwsh" -ArgumentList @("-NoExit", "-Command", $cmd) | Out-Null
}

Write-Host "Nove debug launcher" -ForegroundColor Green
Write-Host "Root: $Root"

if (-not $WebOnly) { Ensure-Command "python" }
if (-not $ApiOnly) { Ensure-Command "npm" }

if (-not $WebOnly) { Ensure-ApiDeps }
if (-not $ApiOnly) { Ensure-WebDeps }

if (-not $WebOnly) { Start-Api }
if (-not $ApiOnly) {
    Start-Sleep -Seconds 1
    Start-Web
}

Write-Host ""
Write-Host "Launched in separate terminals." -ForegroundColor Green
if (-not $WebOnly) {
    Write-Host "  API  http://127.0.0.1:$ApiPort"
    Write-Host "  Docs http://127.0.0.1:$ApiPort/docs"
}
if (-not $ApiOnly) {
    Write-Host "  Web  http://127.0.0.1:$WebPort"
}
Write-Host ""
Write-Host "Tips:"
Write-Host "  .\dev.ps1                   # free busy ports then start (default)"
Write-Host "  .\dev.ps1 -NoKill           # fail if ports are busy"
Write-Host "  .\dev.ps1 -SkipInstall      # skip dependency checks"
Write-Host "  .\dev.ps1 -ApiOnly          # API only"
Write-Host "  .\dev.ps1 -WebOnly          # Web only"
Write-Host "  .\dev.ps1 -ApiPort 8001     # custom API port"
