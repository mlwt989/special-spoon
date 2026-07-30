' Silent launcher - runs start_webapp.bat without showing a console window
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\18095\WorkBuddy\2026-07-22-16-37-18\auto_video_editor\web_app"
WshShell.Run "cmd /c ""C:\Users\18095\WorkBuddy\2026-07-22-16-37-18\auto_video_editor\web_app\start_webapp.bat""", 0, False
