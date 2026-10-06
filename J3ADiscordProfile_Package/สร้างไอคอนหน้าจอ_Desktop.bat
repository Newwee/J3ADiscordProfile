@echo off
chcp 65001 >nul
echo กำลังสร้างไอคอนทางลัด J3A Discord Profile บนหน้าจอ Desktop...

set "CURRENT_DIR=%~dp0"
set "TARGET_EXE=%CURRENT_DIR%J3ADiscordProfile.exe"
set "DESKTOP_DIR=%USERPROFILE%\Desktop"
set "SHORTCUT_PATH=%DESKTOP_DIR%\J3A Discord Profile.lnk"

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT_PATH%'); $sc.TargetPath = '%TARGET_EXE%'; $sc.WorkingDirectory = '%CURRENT_DIR%'; $sc.Description = 'J3A Discord Profile'; $sc.Save()"

if exist "%SHORTCUT_PATH%" (
    echo สร้างไอคอนบนหน้าจอ Desktop สำเร็จเรียบร้อยแล้ว!
) else (
    echo เกิดข้อผิดพลาดในการสร้างไอคอน
)

pause
