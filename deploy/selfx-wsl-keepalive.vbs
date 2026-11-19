Option Explicit

' Systemd services alone do not keep a WSL distribution running.
If WScript.Arguments.Count <> 1 Then WScript.Quit 2
Dim shell, command, distro, quote
Set shell = CreateObject("WScript.Shell")
quote = Chr(34)
distro = WScript.Arguments(0)
command = quote & shell.ExpandEnvironmentStrings("%SystemRoot%") & _
    "\System32\wsl.exe" & quote & " --distribution " & quote & distro & quote & _
    " --exec /usr/bin/sleep infinity"
WScript.Quit shell.Run(command, 0, True)
