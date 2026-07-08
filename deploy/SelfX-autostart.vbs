' SelfX autostart ? launches the WSL2 stack hidden at logon
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl -d Ubuntu -u root -e bash /root/selfx-start.sh", 0, False
