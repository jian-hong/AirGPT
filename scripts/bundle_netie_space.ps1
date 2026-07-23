# Bundle Netie Space into AirGPT installer
#
# 1) Publish Netie Space:  powershell -File "C:\Users\OoiJianHong\Netie Space\scripts\publish.ps1"
# 2) Run this script to copy into dist\bundle\NetieSpace
# 3) build_exe.bat for AirGPT
# 4) ISCC installer\AirGPT.iss

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$SrcCandidates = @(
  "C:\Users\OoiJianHong\Netie Space\dist\NetieSpace",
  "D:\Netie Space\dist\NetieSpace"
)
$Dest = Join-Path $Root "dist\bundle\NetieSpace"

$Src = $SrcCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Src) {
  Write-Warning "Netie Space publish folder not found. Installer will skip Space files (skipifsourcedoesntexist)."
  Write-Host "Looked in:`n - $($SrcCandidates -join "`n - ")"
  exit 0
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
robocopy $Src $Dest /MIR /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }
Write-Host "Bundled Netie Space from $Src -> $Dest"
