<#
  start_openfree.ps1 — bring the OpenFree gateway up for AirGPT.

  OpenFree is AirGPT's bundled name for the OmniRoute OpenAI-compatible free-tier
  gateway (https://github.com/diegosouzapw/OmniRoute, MIT). We install the
  PREBUILT npm package (no monorepo build) into vendor/openfree, then serve it
  on loopback :20128. First run downloads ~739 MB once.

  Boundary: this starts a local gateway the user runs on their own machine and
  only uses providers' keyless free tiers or keys the user already holds. It does
  NOT create accounts. State is written to data/openfree/state.json for the UI.

  Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_openfree.ps1
#>
param(
  [int]$Port = 20128,
  [switch]$StopFirst
)
$ErrorActionPreference = "Stop"

$Root    = Split-Path -Parent $PSScriptRoot          # AirGPT root (parent of scripts/)
$Vendor  = Join-Path $Root "vendor\openfree"
$DataDir = Join-Path $Root "data\openfree"
$Log     = Join-Path $DataDir "openfree.log"
$StateF  = Join-Path $DataDir "state.json"
$PidF    = Join-Path $DataDir "openfree.pid"
$Bin     = Join-Path $Vendor "node_modules\omniroute\bin\omniroute.mjs"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-State([string]$phase, [string]$msg) {
  $obj = [ordered]@{ phase = $phase; msg = $msg; port = $Port; ts = [int][double]::Parse((Get-Date -UFormat %s)) }
  ($obj | ConvertTo-Json -Compress) | Set-Content -Path $StateF -Encoding utf8
  Write-Host "[openfree] $phase — $msg"
}

function Test-Port([int]$p) {
  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $p); $c.Close(); return $true }
  catch { return $false }
}

# Already serving? idempotent no-op.
if (Test-Port $Port) { Write-State "up" "gateway already listening on :$Port"; exit 0 }

# Node runtime check (OmniRoute needs >=22.22.2 <23 or >=24 <27).
try { $nodev = (& node --version) 2>$null } catch { $nodev = "" }
if (-not $nodev) { Write-State "error" "Node.js not found — install Node 22+ then retry"; exit 1 }

# One-time install of the prebuilt package into vendor/openfree.
if (-not (Test-Path $Bin)) {
  New-Item -ItemType Directory -Force -Path $Vendor | Out-Null
  Write-State "installing" "downloading OpenFree (~739 MB, one-time) via npm"
  & npm install omniroute@latest --prefix $Vendor --no-audit --no-fund --loglevel error *>> $Log
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Bin)) {
    Write-State "error" "npm install failed — see data/openfree/openfree.log"; exit 1
  }
}

Write-State "starting" "launching gateway on 127.0.0.1:$Port"
$env:PORT = "$Port"
$env:HOST = "127.0.0.1"
$env:OMNIROUTE_DATA_DIR = $DataDir
$env:OMNIROUTE_TELEMETRY = "0"

# Detached background process; logs to file. Bare `omniroute` = serve gateway.
$proc = Start-Process -FilePath "node" -ArgumentList @($Bin) `
  -WorkingDirectory $Vendor -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"
$proc.Id | Set-Content -Path $PidF -Encoding ascii

# Wait for the port to come up (build-free start is quick, but first boot provisions a key).
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 750
  if (Test-Port $Port) { Write-State "up" "OpenFree gateway live on :$Port"; exit 0 }
  if ($proc.HasExited) { Write-State "error" "gateway exited early (exit $($proc.ExitCode)) — see log"; exit 1 }
}
Write-State "starting" "gateway still booting — first run provisions storage; check status shortly"
exit 0
