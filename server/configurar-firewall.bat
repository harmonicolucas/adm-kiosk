@echo off
chcp 65001 >nul
rem Abre no Firewall do Windows as portas usadas pelo servidor (executar como Administrador).
net session >nul 2>nul
if errorlevel 1 (
    echo Execute este ficheiro como Administrador (botao direito ^> Executar como administrador).
    pause
    exit /b 1
)
netsh advfirewall firewall delete rule name="ADM Kiosk Admin (HTTP 8080)" >nul 2>nul
netsh advfirewall firewall delete rule name="ADM Kiosk Admin (Descoberta UDP 47800)" >nul 2>nul
netsh advfirewall firewall add rule name="ADM Kiosk Admin (HTTP 8080)" dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="ADM Kiosk Admin (Descoberta UDP 47800)" dir=in action=allow protocol=UDP localport=47800
echo.
echo Regras criadas. Os televisores ja podem contactar este servidor.
pause
