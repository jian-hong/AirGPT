# AirGPT LAN setup — run as Administrator (or via restart.bat UAC prompt)
param([switch]$Quiet)

$ErrorActionPreference = "SilentlyContinue"
$rules = @(
    @{ Name = "AirGPT LAN Inbound 8765";  Dir = "in";  Proto = "TCP"; Port = "8765" },
    @{ Name = "AirGPT LAN Outbound 8765"; Dir = "out"; Proto = "TCP"; Port = "8765" },
    @{ Name = "ClipDrop LAN Port 8765";   Dir = "in";  Proto = "TCP"; Port = "8765" },
    @{ Name = "ClipDrop 8765";            Dir = "in";  Proto = "TCP"; Port = "8765" }
)

function Add-PortRule($r) {
    $exists = netsh advfirewall firewall show rule name="$($r.Name)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        if (-not $Quiet) { Write-Host "  [exists] $($r.Name)" }
        return
    }
    netsh advfirewall firewall add rule name="$($r.Name)" dir=$($r.Dir) action=allow protocol=$($r.Proto) localport=$($r.Port) profile=private,public,domain | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [added]  $($r.Name)"
    } else {
        Write-Host "  [FAIL]   $($r.Name) — need Administrator"
    }
}

# Allow python.exe through firewall (program rule)
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($python) {
    $progRule = "AirGPT Python"
    $exists = netsh advfirewall firewall show rule name="$progRule" 2>$null
    if ($LASTEXITCODE -ne 0) {
        netsh advfirewall firewall add rule name="$progRule" dir=in action=allow program="$python" enable=yes profile=private,public,domain | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "  [added]  $progRule ($python)" }
    } elseif (-not $Quiet) { Write-Host "  [exists] $progRule" }
}

Write-Host ""
Write-Host "=== AirGPT LAN firewall setup ==="
foreach ($r in $rules) { Add-PortRule $r }

# Set active WiFi/Ethernet to Private (critical for home LAN access)
Write-Host ""
Write-Host "=== Network profile (Public blocks LAN) ==="
$profiles = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -eq "Internet" -or $_.IPv4Connectivity -eq "LocalNetwork" }
foreach ($p in $profiles) {
    if ($p.NetworkCategory -ne "Private") {
        Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private
        Write-Host "  [fixed]  $($p.InterfaceAlias): Public -> Private"
    } else {
        Write-Host "  [ok]     $($p.InterfaceAlias): already Private"
    }
}

Write-Host ""
Write-Host "=== Your LAN URLs (scan QR or type on phone) ==="
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown"
} | Select-Object -First 1).IPAddress
if ($ip) {
    Write-Host "  http://${ip}:8765"
} else {
    ipconfig | Select-String "IPv4"
    Write-Host "  http://YOUR_IP_ABOVE:8765"
}
Write-Host "  http://127.0.0.1:8765  (this PC only)"
Write-Host ""

if (-not $Quiet) { Read-Host "Press Enter" }
