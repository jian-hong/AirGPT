# Colibri prepare — engine is vendored at third_party/colibri
# GLM-5.2 int4 weights are ~370GB. Requires ~25GB RAM resident at runtime.
# This script does NOT auto-download weights unless -DownloadWeights is passed.

param(
  [switch]$DownloadWeights,
  [string]$ModelDir = "d:\AirGPT\data\models\glm-5.2-colibri",
  [string]$HfId = "mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp",
  [int]$Port = 8002
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Colibri = Join-Path $Root "third_party\colibri"

Write-Host "=== AirGPT Colibri prepare ==="
Write-Host "Engine: $Colibri"

if (-not (Test-Path $Colibri)) {
  Write-Host "Cloning Colibri..."
  New-Item -ItemType Directory -Force -Path (Join-Path $Root "third_party") | Out-Null
  git clone --depth 1 https://github.com/JustVugg/colibri.git $Colibri
}

$ramBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$ramGb = [math]::Round($ramBytes / 1GB, 1)
Write-Host "Detected RAM: ${ramGb} GB (Colibri GLM needs ~25 GB resident)"

if ($ramGb -lt 24) {
  Write-Warning "This machine likely cannot RUN GLM-5.2 Colibri interactively ($ramGb GB < 25 GB)."
  Write-Warning "You can still prepare weights on a large disk and serve from a stronger host."
}

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null

if ($DownloadWeights) {
  Write-Host "Downloading $HfId -> $ModelDir (this is ~370GB)..."
  python -m pip install -U huggingface_hub
  huggingface-cli download $HfId --local-dir $ModelDir --local-dir-use-symlinks False
} else {
  Write-Host "Skip download. To pull weights later:"
  Write-Host "  .\scripts\colibri_prepare.ps1 -DownloadWeights"
  Write-Host "  HF: $HfId"
  Write-Host "  Dir: $ModelDir"
}

Write-Host ""
Write-Host "Serve (after weights exist):"
Write-Host "  cd $Colibri"
Write-Host "  `$env:COLI_API_KEY='local-secret'"
Write-Host "  python coli serve --model `"$ModelDir`" --host 127.0.0.1 --port $Port --model-id glm-5.2-colibri"
Write-Host ""
Write-Host "Then in AirGPT env.local / Marketplace → Serve Colibri:"
Write-Host "  COLIBRI_BASE_URL=http://127.0.0.1:$Port"
Write-Host "  COLIBRI_API_KEY=local-secret"
Write-Host "  COLIBRI_MODEL=glm-5.2-colibri"
Write-Host "Phones/weak clients join the host chat; inference stays on this machine."
