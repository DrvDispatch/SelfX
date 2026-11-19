[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int] $Port,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string] $Distro = 'Ubuntu-24.04'
)

$ErrorActionPreference = 'Stop'

function Test-SelfXHealth {
    try {
        $health = Invoke-RestMethod -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:$Port/api/v1/healthz"
        return $health.status -eq 'ok' -and $health.service -eq 'selfx'
    } catch {
        return $false
    }
}

$wsl = Get-Command wsl.exe -CommandType Application -ErrorAction SilentlyContinue
if (-not $wsl) {
    throw "Install WSL2 and Ubuntu first with 'wsl --install -d Ubuntu-24.04'."
}

$init = & $wsl.Source --distribution $Distro --exec /usr/bin/ps -p 1 -o comm=
if ($LASTEXITCODE -ne 0) {
    throw "Start '$Distro' in WSL2 and finish its first-launch setup. For a new install run 'wsl --install -d Ubuntu-24.04'."
}
if (($init -join '').Replace([string][char]0, '').Trim() -ne 'systemd') {
    throw "Enable systemd in '$Distro' before installing SelfX. See docs/SELF_HOSTING.md."
}

$readPort = 'if [ -r /etc/selfx/selfx.env ]; then sed -n s/^SELFX_PORT=//p /etc/selfx/selfx.env; fi'
$portOutput = & $wsl.Source --distribution $Distro --user root --exec /bin/sh -c $readPort
$previousPort = (($portOutput | Select-Object -Last 1) -join '').Replace([string][char]0, '').Trim()
if (-not $PSBoundParameters.ContainsKey('Port')) {
    if ($previousPort -match '^[1-9][0-9]{3,4}$' -and [int]$previousPort -ge 1024 -and [int]$previousPort -le 65535) {
        $Port = [int]$previousPort
    } else {
        $Port = 8800
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener -and ($previousPort -ne "$Port" -or -not (Test-SelfXHealth))) {
    throw "Windows already has a listener on port $Port. Pick another port with -Port."
}

$installArguments = @()
if ($PSBoundParameters.ContainsKey('Port')) {
    $installArguments = @('--port', $Port)
}
& $wsl.Source --distribution $Distro --user root --cd $PSScriptRoot --exec /bin/bash ./install.sh @installArguments
if ($LASTEXITCODE -ne 0) {
    throw "SelfX installation failed inside '$Distro' with exit code $LASTEXITCODE."
}

$taskDirectory = Join-Path (Join-Path $env:LOCALAPPDATA 'SelfX') $Distro
New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
$taskScript = Join-Path $taskDirectory 'keepalive.vbs'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'selfx-wsl-keepalive.vbs') -Destination $taskScript -Force

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskName = "SelfX WSL - $Distro"
$scriptHost = Join-Path ([Environment]::SystemDirectory) 'wscript.exe'
$action = New-ScheduledTaskAction -Execute $scriptHost -Argument ('//B //Nologo "{0}" "{1}"' -f $taskScript, $Distro)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settingsOptions = @{
    StartWhenAvailable = $true
    AllowStartIfOnBatteries = $true
    DontStopIfGoingOnBatteries = $true
    MultipleInstances = 'IgnoreNew'
    ExecutionTimeLimit = [TimeSpan]::Zero
    RestartCount = 3
    RestartInterval = (New-TimeSpan -Minutes 1)
}
$taskSettings = New-ScheduledTaskSettingsSet @settingsOptions
$registration = @{
    TaskName = $taskName
    Description = "Keeps $Distro running for SelfX. Linux systemd starts and supervises SelfX."
    Action = $action
    Trigger = $trigger
    Principal = $principal
    Settings = $taskSettings
    Force = $true
}
Register-ScheduledTask @registration | Out-Null
Start-ScheduledTask -TaskName $taskName

$deadline = [DateTime]::UtcNow.AddSeconds(45)
do {
    if (Test-SelfXHealth) {
        Write-Host "SelfX is ready at http://127.0.0.1:$Port and will start when you sign in."
        return
    }
    Start-Sleep -Seconds 1
} while ([DateTime]::UtcNow -lt $deadline)

throw "Windows could not reach SelfX on port $Port. Check WSL localhost forwarding and the selfx-api service logs. See docs/SELF_HOSTING.md."
