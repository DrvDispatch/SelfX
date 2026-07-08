# SelfX port-proxy refresher.
# Makes the WSL2 SelfX services reachable at STABLE Windows localhost URLs by
# forwarding 127.0.0.1:<listen> -> <current WSL IP>:<connect>. The WSL IP changes
# on every boot, so this is registered as a logon Scheduled Task (highest
# privileges) to re-point the proxy each time. Run elevated.
#
# Bookmark:  http://localhost:8800   (SelfX app; WSL 8000 is used by another
#            Windows app, so the app is exposed on 8800 instead.)

$ErrorActionPreference = 'SilentlyContinue'

# Windows-side listen port -> WSL service port.
$map = @{ 8800 = 8000; 8091 = 8091; 8092 = 8092; 8093 = 8093 }

# Current WSL IP (also starts WSL if it isn't running yet).
$wslIp = (wsl hostname -I).Trim().Split(' ')[0]
if (-not $wslIp) { Write-Output "WSL IP not found; is WSL installed?"; exit 1 }

foreach ($listen in $map.Keys) {
    $connect = $map[$listen]
    netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$listen 2>$null | Out-Null
    netsh interface portproxy add    v4tov4 listenaddress=127.0.0.1 listenport=$listen connectaddress=$wslIp connectport=$connect | Out-Null
}
# Clean up the old direct 8000 rule (blocked by the other Windows app on 8000).
netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8000 2>$null | Out-Null
Write-Output "SelfX port-proxy -> $wslIp  (localhost:8800->8000, 8091/8092/8093 direct)"