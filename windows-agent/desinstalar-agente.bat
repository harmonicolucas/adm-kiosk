@echo off
chcp 65001 >nul
net session >nul 2>nul
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
copy /y "%~dp0desinstalar.ps1" "%TEMP%\adm-desinstalar.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\adm-desinstalar.ps1"
pause
