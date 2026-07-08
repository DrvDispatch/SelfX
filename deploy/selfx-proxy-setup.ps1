# One-time elevated setup: register a logon Scheduled Task that refreshes the SelfX
# port-proxy (so localhost:8000 always reaches the WSL app), and apply it now.
$log = "C:\SelfX\deploy\portproxy_setup.log"
try {
    $arg = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\SelfX\deploy\selfx-portproxy.ps1"'
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "SelfX Port Proxy" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $out = & "C:\SelfX\deploy\selfx-portproxy.ps1"
    "OK TASK_REGISTERED :: $out" | Set-Content $log
} catch {
    "ERROR: $($_.Exception.Message)" | Set-Content $log
}