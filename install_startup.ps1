$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = "python" }

$action = New-ScheduledTaskAction -Execute $python -Argument "clipdrop.py" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "ClipDrop" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "ClipDrop will start automatically at login."
Write-Host "Open http://127.0.0.1:8765 on this PC."
