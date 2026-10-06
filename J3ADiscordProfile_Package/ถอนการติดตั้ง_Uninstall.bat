@echo off
chcp 65001 >nul
title J3A Discord Profile - ถอนการติดตั้ง (Uninstaller)
echo ========================================================
echo   J3A Discord Profile - ระบบถอนการติดตั้ง (Uninstaller)
echo ========================================================
echo.
set /p CONFIRM="คุณต้องการถอนการติดตั้งและล้างข้อมูลของ J3A Discord Profile ใช่หรือไม่? (Y/N): "
if /I not "%CONFIRM%"=="Y" (
    echo ยกเลิกการถอนการติดตั้งแล้ว
    pause
    exit /b
)

echo.
echo [1/3] กำลังปิดการทำงานของโปรแกรมที่ค้างอยู่...
taskkill /F /IM "J3ADiscordProfile.exe" >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/3] กำลังลบไอคอนทางลัดบนหน้าจอ Desktop...
del /F /Q "%USERPROFILE%\Desktop\J3A Discord Profile.lnk" >nul 2>&1
del /F /Q "%USERPROFILE%\Desktop\J3ADiscordProfile.lnk" >nul 2>&1
del /F /Q "%USERPROFILE%\OneDrive\Desktop\J3A Discord Profile.lnk" >nul 2>&1
del /F /Q "%USERPROFILE%\OneDrive\Desktop\J3ADiscordProfile.lnk" >nul 2>&1

echo [3/3] กำลังลบไฟล์ข้อมูลการตั้งค่าในเครื่อง (%APPDATA%\J3ADiscordProfile)...
rmdir /S /Q "%APPDATA%\J3ADiscordProfile" >nul 2>&1

set "CURRENT_DIR=%~dp0"
del /F /Q "%CURRENT_DIR%J3ADiscordProfile.exe" >nul 2>&1
del /F /Q "%CURRENT_DIR%สร้างไอคอนหน้าจอ_Desktop.bat" >nul 2>&1
del /F /Q "%CURRENT_DIR%วิธีใช้งาน_คู่มือเริ่มต้น.txt" >nul 2>&1

echo.
echo ✅ ถอนการติดตั้ง J3A Discord Profile เรียบร้อยแล้ว!
pause
del "%~f0"
