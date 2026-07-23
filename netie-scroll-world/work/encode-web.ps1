# Encode approved masters → assets/vid (H.264, CRF 20, GOP 8, no audio, faststart)
# Usage: .\encode-web.ps1
# Place masters as work/masters/{desk,bridge,vault,agents,tower,hero,conn1..conn5}.mp4

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$masters = Join-Path $root 'work\masters'
$out = Join-Path $root 'assets\vid'
New-Item -ItemType Directory -Force -Path $out | Out-Null

$names = @('desk','bridge','vault','agents','tower','hero','conn1','conn2','conn3','conn4','conn5')
foreach ($n in $names) {
  $src = Join-Path $masters "$n.mp4"
  if (-not (Test-Path $src)) {
    Write-Warning "Missing master: $src"
    continue
  }
  $dst = Join-Path $out "$n.mp4"
  & ffmpeg -y -i $src -c:v libx264 -pix_fmt yuv420p -crf 20 -g 8 -keyint_min 8 -sc_threshold 0 -an -movflags +faststart $dst
  Write-Host "Encoded $dst"
}

$landingVid = 'C:\Users\user\Landing\netie-agent\public\airgpt\assets\vid'
if (Test-Path $landingVid) {
  Copy-Item (Join-Path $out '*.mp4') $landingVid -Force
  Write-Host "Copied encodes to $landingVid"
}
