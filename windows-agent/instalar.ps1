<#
  Instalação do agente ADM Kiosk num computador / netbox Windows.
  Executado por instalar-agente.bat (com privilégios de administrador).
#>
param([string]$Server = '', [string]$Url = '', [switch]$Silent)

$ErrorActionPreference = 'Stop'
$Target = 'C:\ADM-Kiosk-Agent'
$TaskName = 'ADM Kiosk Agent'
$Source = $PSScriptRoot

Write-Host ''
Write-Host '=== ADM Kiosk - Instalação do agente Windows ===' -ForegroundColor Yellow
Write-Host 'Aeroportos de Moçambique, E.P.  |  Harmonico Lucas'
Write-Host ''

if (-not $Silent) {
    if (-not $Server) {
        $Server = Read-Host 'Endereço do servidor de administração (Enter = descoberta automática, ex.: 10.10.5.10:8080)'
    }
    while ($true) {
        if (-not $Url) {
            Write-Host 'Página a apresentar neste ecrã (endereço do site, NÃO é a palavra-passe).'
            $Url = Read-Host 'Ex.: http://10.10.5.20/fids  (Enter = definir depois no administrador web)'
        }
        $Url = $Url.Trim()
        $hostPart = ($Url -replace '^https?://', '') -replace '[/?#].*$', ''
        # Um nome sem ponto nem porta (ex.: "admin") quase sempre é um engano.
        if (-not $Url -or $hostPart -match '\.|:|^localhost$') { break }
        $answer = Read-Host "'$Url' não parece um endereço de página (ex.: http://10.10.5.20/fids). Usar mesmo assim? (s/N)"
        if ($answer -match '^[sS]') { break }
        $Url = ''
    }
}
if ($Url -and $Url -notmatch '^https?://') { $Url = "http://$Url" }

# Pára uma instância anterior.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*adm-agent.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Force -Path $Target | Out-Null
foreach ($f in 'adm-agent.ps1', 'AdmNative.cs', 'iniciar-oculto.vbs', 'desinstalar.ps1', 'desinstalar-agente.bat') {
    Copy-Item (Join-Path $Source $f) (Join-Path $Target $f) -Force
}

$configPath = Join-Path $Target 'agent.json'
$config = [ordered]@{ serverUrl = $Server.Trim(); url = $Url.Trim(); browser = ''; zoom = 100 }
[IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))

# Arranque automático ao iniciar sessão (na sessão do utilizador, para ver e controlar o ecrã).
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$Target\iniciar-oculto.vbs`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Force | Out-Null

# Ecrã sempre ligado (sinalética): sem suspensão, sem desligar o monitor.
foreach ($a in '-monitor-timeout-ac 0', '-standby-timeout-ac 0', '-hibernate-timeout-ac 0', '-disk-timeout-ac 0') {
    Start-Process powercfg.exe -ArgumentList "-change $a" -WindowStyle Hidden -Wait
}

Start-ScheduledTask -TaskName $TaskName

Write-Host ''
Write-Host "Agente instalado em $Target e iniciado." -ForegroundColor Green
Write-Host "Arranca automaticamente quando o utilizador '$user' inicia sessão."
Write-Host ''
Write-Host 'Para o navegador abrir sozinho ao ligar o computador, ative o início de sessão'
Write-Host 'automático: Win+R > netplwiz > desmarcar "Os utilizadores têm de introduzir um nome..."'
Write-Host ''
