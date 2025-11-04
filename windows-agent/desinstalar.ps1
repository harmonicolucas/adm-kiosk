$ErrorActionPreference = 'SilentlyContinue'
Unregister-ScheduledTask -TaskName 'ADM Kiosk Agent' -Confirm:$false
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*adm-agent.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$profileDir = 'C:\ADM-Kiosk-Agent\browser-profile'
Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe' OR Name='firefox.exe'" |
    Where-Object { $_.CommandLine -like "*$profileDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 1
Set-Location $env:TEMP
Remove-Item -Recurse -Force 'C:\ADM-Kiosk-Agent'
Write-Host 'Agente ADM Kiosk removido.' -ForegroundColor Green
