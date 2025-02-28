Set WshShell = WScript.CreateObject("WScript.Shell")
strDesktop = WshShell.SpecialFolders("Desktop")
Set oShellLink = WshShell.CreateShortcut(strDesktop & "\SaMuGed.lnk")
oShellLink.TargetPath = WScript.Arguments(0) & "\dist\SaMuGed\SaMuGed.exe"
oShellLink.WorkingDirectory = WScript.Arguments(0) & "\dist\SaMuGed"
oShellLink.IconLocation = WScript.Arguments(0) & "\dist\SaMuGed\SaMuGed.exe,0"
oShellLink.Description = "SaMuGed - Similar MIDI Generator & Editor"
oShellLink.Save 