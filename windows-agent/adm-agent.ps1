<#
  ADM Kiosk - Agente para computadores / netboxes Windows
  Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas

  - Abre o navegador em modo kiosk (ecrã inteiro) com a página configurada, logo
    que o utilizador inicia sessão, e volta a abri-lo se for fechado.
  - Recarrega a página quando a rede ou o servidor da página volta.
  - Regista-se no servidor central de administração (descoberta automática) e
    aplica a configuração remota.
  - Permite ver o ecrã ao vivo e controlar o rato/teclado a partir do navegador.

  Requer apenas o Windows 10/11 (PowerShell 5.1 e .NET Framework incluídos).
#>

$ErrorActionPreference = 'Stop'
$AgentVersion = '2.4.0'
$AgentDir = $PSScriptRoot
$ConfigPath = Join-Path $AgentDir 'agent.json'
$StatePath = Join-Path $AgentDir 'state.json'
$LogPath = Join-Path $AgentDir 'agent.log'
$ProfileDir = Join-Path $AgentDir 'browser-profile'
$DiscoveryPort = 47800
$Invariant = [Globalization.CultureInfo]::InvariantCulture

# ---------------------------------------------------------------- instância única
$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'Global\ADMKioskAgent', [ref]$created)
if (-not $created) { exit 0 }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing, System.Web.Extensions
$jsonAsm = [System.Web.Script.Serialization.JavaScriptSerializer].Assembly.Location
Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $AgentDir 'AdmNative.cs'))) `
    -ReferencedAssemblies System.Windows.Forms, System.Drawing, $jsonAsm
[AdmNative]::Init()

# ---------------------------------------------------------------- utilitários

function Write-Log([string]$msg) {
    try {
        if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) {
            Move-Item $LogPath "$LogPath.old" -Force
        }
        Add-Content -Path $LogPath -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $msg) -Encoding UTF8
    } catch { }
}

function Read-JsonFile([string]$path) {
    if (Test-Path $path) {
        try { return [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { }
    }
    return $null
}

function Save-JsonFile($obj, [string]$path) {
    [IO.File]::WriteAllText($path, ($obj | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
}

function Get-Prop($obj, [string]$name, $default) {
    if ($null -ne $obj -and $obj.PSObject.Properties.Name -contains $name -and $null -ne $obj.$name) { return $obj.$name }
    return $default
}

# ---------------------------------------------------------------- configuração local e estado

$cfg = Read-JsonFile $ConfigPath
$state = Read-JsonFile $StatePath
$st = @{
    id                = Get-Prop $state 'id' ''
    configVersion     = [int](Get-Prop $state 'configVersion' 0)
    name              = Get-Prop $state 'name' ''
    terminal          = Get-Prop $state 'terminal' ''
    screenType        = Get-Prop $state 'screenType' ''
    gate              = Get-Prop $state 'gate' ''
    url               = Get-Prop $state 'url' (Get-Prop $cfg 'url' '')
    browser           = Get-Prop $state 'browser' (Get-Prop $cfg 'browser' '')
    zoom              = [int](Get-Prop $state 'zoom' (Get-Prop $cfg 'zoom' 100))
    refreshSeconds    = [int](Get-Prop $state 'refreshSeconds' 0)
    kioskEnabled      = [bool](Get-Prop $state 'kioskEnabled' $true)
    reloadOnError     = [bool](Get-Prop $state 'reloadOnError' $true)
    retryDelaySeconds = [int](Get-Prop $state 'retryDelaySeconds' 10)
}
$ServerUrl = ([string](Get-Prop $cfg 'serverUrl' '')).TrimEnd('/')
if ($ServerUrl -and $ServerUrl -notmatch '^https?://') { $ServerUrl = "http://$ServerUrl" }
# Sem porta (ex.: "192.168.1.3") assume a 8080 do servidor de administração.
if ($ServerUrl -match '^http://[^/:]+$') { $ServerUrl = "${ServerUrl}:8080" }

function Save-State { Save-JsonFile ([pscustomobject]$st) $StatePath }

function Get-DeviceId {
    if ($st.id) { return $st.id }
    $guid = ''
    try { $guid = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid } catch { }
    $mac = ''
    try {
        $mac = (Get-CimInstance Win32_NetworkAdapter -Filter "PhysicalAdapter=True" |
            Where-Object MACAddress | Select-Object -First 1).MACAddress
    } catch { }
    if (-not $guid) { $guid = [guid]::NewGuid().ToString() }
    # Inclui o MAC para distinguir equipamentos clonados a partir da mesma imagem.
    $sha = [Security.Cryptography.SHA1]::Create()
    $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes("$guid|$mac"))
    $st.id = 'w' + (($hash | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 23)
    Save-State
    return $st.id
}

# ---------------------------------------------------------------- informação do equipamento

function Get-NetInfo {
    $info = @{ ip = ''; prefix = 0; mask = ''; gateway = ''; dns = @(); mac = ''; iface = ''; transport = '' }
    try {
        $all = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True')
        $nic = $all | Where-Object { $_.DefaultIPGateway } | Select-Object -First 1
        if (-not $nic) { $nic = $all | Select-Object -First 1 }
        if ($nic) {
            for ($i = 0; $i -lt $nic.IPAddress.Count; $i++) {
                if ($nic.IPAddress[$i] -match '^\d+\.\d+\.\d+\.\d+$') {
                    $info.ip = $nic.IPAddress[$i]
                    $info.mask = $nic.IPSubnet[$i]
                    break
                }
            }
            if ($info.mask) {
                $bits = ($info.mask.Split('.') | ForEach-Object { [Convert]::ToString([int]$_, 2) }) -join ''
                $info.prefix = ($bits.ToCharArray() | Where-Object { $_ -eq '1' }).Count
            }
            $info.gateway = @($nic.DefaultIPGateway | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })[0]
            $info.dns = @($nic.DNSServerSearchOrder | Where-Object { $_ })
            $info.mac = ([string]$nic.MACAddress).Replace('-', ':')
            $info.iface = $nic.Description
            $adapter = Get-CimInstance Win32_NetworkAdapter -Filter "Index=$($nic.Index)"
            $info.transport = if ("$($adapter.Name) $($adapter.NetConnectionID)" -match 'Wi-?Fi|Wireless|WLAN|802\.11') { 'Wi-Fi' } else { 'Ethernet' }
        }
    } catch { Write-Log "net info: $_" }
    if (-not $info.gateway) { $info.gateway = '' }
    return $info
}

$script:staticInfo = $null
function Get-DeviceInfo {
    if (-not $script:staticInfo) {
        $cs = Get-CimInstance Win32_ComputerSystem
        $os = Get-CimInstance Win32_OperatingSystem
        $script:staticInfo = @{
            manufacturer = $cs.Manufacturer
            model        = $cs.Model
            os           = "$($os.Caption) ($($os.Version))".Trim()
            hostname     = $env:COMPUTERNAME
            bootTime     = $os.LastBootUpTime
        }
    }
    $b = Find-Browser
    return @{
        manufacturer = $script:staticInfo.manufacturer
        model        = $script:staticInfo.model
        os           = $script:staticInfo.os
        hostname     = $script:staticInfo.hostname
        user         = "$env:USERDOMAIN\$env:USERNAME"
        resolution   = [AdmNative]::Resolution
        uptimeSec    = [int]((Get-Date) - $script:staticInfo.bootTime).TotalSeconds
        appVersion   = "Agente $AgentVersion"
        isLauncher   = $true
        browserName  = $(if ($b) { $b.label } else { 'não encontrado' })
    }
}

# ---------------------------------------------------------------- navegador em modo kiosk

function Find-Browser {
    $pf86 = ${env:ProgramFiles(x86)}
    $candidates = @(
        @{ kind = 'edge'; label = 'Microsoft Edge'; paths = @("$pf86\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") },
        @{ kind = 'chrome'; label = 'Google Chrome'; paths = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "$pf86\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") },
        @{ kind = 'firefox'; label = 'Mozilla Firefox'; paths = @("$env:ProgramFiles\Mozilla Firefox\firefox.exe", "$pf86\Mozilla Firefox\firefox.exe") }
    )
    $ordered = @($candidates | Where-Object { $_.kind -eq $st.browser }) + @($candidates | Where-Object { $_.kind -ne $st.browser })
    foreach ($c in $ordered) {
        foreach ($p in $c.paths) {
            if ($p -and (Test-Path $p)) { return @{ kind = $c.kind; label = $c.label; path = $p } }
        }
    }
    return $null
}

function Get-BrowserProcesses {
    $needle = $ProfileDir.ToLower()
    @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe' OR Name='firefox.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) })
}

function Stop-Kiosk {
    foreach ($p in Get-BrowserProcesses) {
        try { Stop-Process -Id $p.ProcessId -Force } catch { }
    }
    Start-Sleep -Milliseconds 800
}

function Start-Kiosk {
    if (-not $st.url) { return }
    $b = Find-Browser
    if (-not $b) { Write-Log 'Nenhum navegador encontrado (Edge, Chrome ou Firefox).'; return }
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
    $scale = ([math]::Round($st.zoom / 100.0, 2)).ToString($Invariant)
    if ($b.kind -eq 'firefox') {
        $mode = if ($st.kioskEnabled) { '-kiosk' } else { '' }
        $argLine = "$mode -no-remote -profile `"$ProfileDir`" `"$($st.url)`""
    } else {
        $mode = if ($st.kioskEnabled) { "--kiosk `"$($st.url)`"" } else { "--start-fullscreen --app=`"$($st.url)`"" }
        $argLine = "$mode --user-data-dir=`"$ProfileDir`" --no-first-run --no-default-browser-check " +
                "--disable-session-crashed-bubble --noerrdialogs --disable-infobars --disable-features=Translate " +
                "--autoplay-policy=no-user-gesture-required --force-device-scale-factor=$scale"
        if ($b.kind -eq 'edge') { $argLine += ' --edge-kiosk-type=fullscreen' }
    }
    Write-Log "A abrir $($b.label): $($st.url)"
    Start-Process -FilePath $b.path -ArgumentList $argLine | Out-Null
    $script:lastReload = Get-Date
}

function Restart-Kiosk { Stop-Kiosk; Start-Kiosk }

function Invoke-PageReload {
    $procs = Get-BrowserProcesses
    if ($procs.Count -eq 0) { Start-Kiosk; return }
    $win = Get-Process -Id ($procs | ForEach-Object { $_.ProcessId }) -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } | Select-Object -First 1
    if ($win) {
        [AdmNative]::Focus($win.MainWindowHandle)
        Start-Sleep -Milliseconds 200
        [AdmNative]::Key('F5', $false, $false, $false) | Out-Null
    } else {
        Restart-Kiosk
    }
    $script:lastReload = Get-Date
}

function Test-PageHost {
    if (-not $st.url) { return $false }
    try {
        $u = [Uri]$st.url
        $client = New-Object Net.Sockets.TcpClient
        $ar = $client.BeginConnect($u.Host, $u.Port, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne(2500) -and $client.Connected
        $client.Close()
        return $ok
    } catch { return $false }
}

# ---------------------------------------------------------------- HTTP / descoberta

function Send-Http([string]$url, [byte[]]$body, [string]$ctype, [int]$timeout = 8000) {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.Method = 'POST'
    $req.ContentType = $ctype
    $req.Timeout = $timeout
    $req.ReadWriteTimeout = $timeout
    $req.Proxy = $null
    $req.ContentLength = $body.Length
    $s = $req.GetRequestStream(); $s.Write($body, 0, $body.Length); $s.Close()
    $res = $req.GetResponse()
    try {
        $reader = New-Object IO.StreamReader($res.GetResponseStream(), [Text.Encoding]::UTF8)
        return $reader.ReadToEnd()
    } finally { $res.Close() }
}

function Send-Json([string]$url, $obj) {
    $json = $obj | ConvertTo-Json -Depth 6 -Compress
    $text = Send-Http $url ([Text.Encoding]::UTF8.GetBytes($json)) 'application/json; charset=utf-8'
    if ($text) { return $text | ConvertFrom-Json }
    return $null
}

$script:discovered = ''
function Find-Server {
    $net = Get-NetInfo
    $targets = @('255.255.255.255')
    if ($net.ip -and $net.mask) {
        $ip = ([Net.IPAddress]$net.ip).GetAddressBytes()
        $mk = ([Net.IPAddress]$net.mask).GetAddressBytes()
        $bc = for ($i = 0; $i -lt 4; $i++) { $ip[$i] -bor (255 -bxor $mk[$i]) }
        $targets = @($bc -join '.') + $targets
    }
    $udp = New-Object Net.Sockets.UdpClient
    try {
        $udp.EnableBroadcast = $true
        $udp.Client.ReceiveTimeout = 2500
        $msg = [Text.Encoding]::ASCII.GetBytes('ADM-KIOSK-DISCOVER')
        for ($try = 0; $try -lt 2; $try++) {
            foreach ($t in $targets) { try { [void]$udp.Send($msg, $msg.Length, $t, $DiscoveryPort) } catch { } }
            try {
                $remote = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0)
                $data = $udp.Receive([ref]$remote)
                $url = (([Text.Encoding]::UTF8.GetString($data)) | ConvertFrom-Json).server
                if ($url -match '^https?://') { $script:discovered = $url.TrimEnd('/'); return $script:discovered }
            } catch { }
        }
    } finally { $udp.Close() }
    return ''
}

function Get-Server {
    # Se o endereço configurado falhar repetidamente, tenta também a descoberta automática.
    if ($ServerUrl -and $script:failures -lt 3) { return $ServerUrl }
    if ($script:discovered) { return $script:discovered }
    $found = Find-Server
    if ($found) { return $found }
    return $ServerUrl
}

# ---------------------------------------------------------------- estado da página

$script:pageState = 'loading'
$script:pageError = ''

function Update-PageState {
    if (-not $st.url) { $script:pageState = 'nolinks'; $script:pageError = ''; return }
    if (-not (Find-Browser)) { $script:pageState = 'error'; $script:pageError = 'Navegador não encontrado'; return }
    if (-not $script:hostOk) { $script:pageState = 'offline'; $script:pageError = 'Página inacessível na rede'; return }
    if ((Get-BrowserProcesses).Count -eq 0) { $script:pageState = 'loading'; $script:pageError = ''; return }
    $script:pageState = 'ok'; $script:pageError = ''
}

# ---------------------------------------------------------------- heartbeat / configuração

function Invoke-Heartbeat {
    $server = Get-Server
    if (-not $server) { return }
    [AdmLive]::Configure($server, (Get-DeviceId))
    $body = @{
        id            = Get-DeviceId
        platform      = 'windows'
        configVersion = $st.configVersion
        device        = Get-DeviceInfo
        network       = Get-NetInfo
        state         = @{ url = $st.url; page = $script:pageState; error = $script:pageError }
        settings      = @{
            name = $st.name; terminal = $st.terminal; screenType = $st.screenType; gate = $st.gate
            url = $st.url; zoom = $st.zoom; refreshSeconds = $st.refreshSeconds; autoScroll = $false
            autoScrollSeconds = 10; kioskEnabled = $st.kioskEnabled; reloadOnError = $st.reloadOnError
            retryDelaySeconds = $st.retryDelaySeconds; browser = $st.browser
        }
    }
    try {
        $r = Send-Json "$server/api/device/heartbeat" $body
        $script:failures = 0
    } catch {
        $script:failures++
        Write-Log "Sem contacto com o servidor ${server}: $($_.Exception.Message)"
        if ($script:failures -ge 3) { $script:discovered = '' }
        return
    }
    if ($r.config) { Set-RemoteConfig $r.config }
    foreach ($c in @($r.commands)) { if ($c) { Invoke-RemoteCommand $server $c } }
}

function Set-RemoteConfig($c) {
    $version = [int]$c.version
    if ($version -le 0 -or $version -eq $st.configVersion) { return }
    # URL vazio no servidor = volta à página definida localmente no agent.json.
    $newUrl = if ($c.url) { [string]$c.url } else { [string](Get-Prop $cfg 'url' $st.url) }
    $restart = ($st.url -ne $newUrl) -or ($st.browser -ne [string]$c.browser) -or ($st.zoom -ne [int]$c.zoom) -or
               ($st.kioskEnabled -ne [bool]$c.kioskEnabled)
    $st.configVersion = $version
    $st.name = [string]$c.name
    $st.terminal = [string]$c.terminal
    $st.screenType = [string]$c.screenType
    $st.gate = [string]$c.gate
    $st.url = $newUrl
    $st.browser = [string]$c.browser
    $st.zoom = [int]$c.zoom
    $st.refreshSeconds = [int]$c.refreshSeconds
    $st.kioskEnabled = [bool]$c.kioskEnabled
    $st.reloadOnError = [bool]$c.reloadOnError
    $st.retryDelaySeconds = [int]$c.retryDelaySeconds
    Save-State
    Write-Log "Configuração remota v$version aplicada"
    if ($restart) { Restart-Kiosk }
}

function Send-Result([string]$server, $id, [bool]$ok, [string]$message) {
    try { Send-Json "$server/api/device/command-result" @{ id = (Get-DeviceId); commandId = $id; ok = $ok; message = $message } | Out-Null } catch { }
}

function Invoke-RemoteCommand([string]$server, $c) {
    Write-Log "Comando remoto: $($c.type)"
    switch ($c.type) {
        'reload' { Invoke-PageReload; Send-Result $server $c.id $true 'Página recarregada' }
        'clear_cache' {
            Stop-Kiosk
            try { Remove-Item -Recurse -Force $ProfileDir -ErrorAction SilentlyContinue } catch { }
            Start-Kiosk
            Send-Result $server $c.id $true 'Cache limpa e navegador reaberto'
        }
        'restart_app' { Restart-Kiosk; Send-Result $server $c.id $true 'Navegador reiniciado' }
        'identify' {
            $seconds = [int](Get-Prop $c.payload 'seconds' 20)
            $net = Get-NetInfo
            $kind = @(@{ DPT = 'DPT Doméstico'; IPT = 'IPT Internacional' }[$st.terminal],
                      @{ FIDS_DEP = 'FIDS Partidas'; FIDS_ARR = 'FIDS Chegadas'; GATE = 'Gate' }[$st.screenType]) |
                Where-Object { $_ }
            $title = if ($st.name) { $st.name } else { $env:COMPUTERNAME }
            $text = "$title`n$(($kind -join ' - ') + $(if ($st.gate) { " $($st.gate)" }))`nIP $($net.ip)   Gateway $($net.gateway)`nID $((Get-DeviceId).Substring(16).ToUpper())"
            [AdmNative]::ShowBanner($text, $seconds)
            Send-Result $server $c.id $true "Identificação mostrada ${seconds}s"
        }
        'screenshot' {
            try {
                $jpeg = [AdmNative]::Capture(1280, 70)
                Send-Http "$server/api/device/screenshot?id=$(Get-DeviceId)&cmd=$($c.id)" $jpeg 'image/jpeg' 15000 | Out-Null
            } catch { Send-Result $server $c.id $false "Falha na captura: $($_.Exception.Message)" }
        }
        'reboot' {
            Send-Result $server $c.id $true 'A reiniciar o computador'
            Start-Process -FilePath 'shutdown.exe' -ArgumentList '/r /t 5 /f' -WindowStyle Hidden
        }
        default { Send-Result $server $c.id $false "Comando não suportado: $($c.type)" }
    }
}

# ---------------------------------------------------------------- ciclo principal

Write-Log "Agente $AgentVersion iniciado (ID $(Get-DeviceId))"
$script:failures = 0
$script:hostOk = $false
$script:lastReload = Get-Date
$nextHeartbeat = Get-Date
$nextCheck = Get-Date

# Dá tempo à rede e ao ambiente de trabalho para arrancarem.
Start-Sleep -Seconds 5
$script:hostOk = Test-PageHost
Start-Kiosk
# A sessão ao vivo (ecrã, rato e teclado) corre numa thread própria; ver AdmLive em AdmNative.cs.
[AdmLive]::Start()
$lastLiveError = ''

while ($true) {
    try {
        $now = Get-Date

        if ($now -ge $nextCheck) {
            $nextCheck = $now.AddSeconds(5)
            $wasOk = $script:hostOk
            $script:hostOk = Test-PageHost
            $running = (Get-BrowserProcesses).Count -gt 0
            if ($st.url -and -not $running) {
                Start-Kiosk
            } elseif ($script:hostOk -and -not $wasOk -and $st.reloadOnError) {
                Write-Log 'Ligação à página restabelecida: a recarregar.'
                Invoke-PageReload
            } elseif ($st.refreshSeconds -gt 0 -and $script:hostOk -and
                      ($now - $script:lastReload).TotalSeconds -ge $st.refreshSeconds) {
                Invoke-PageReload
            }
            Update-PageState
        }

        if ([AdmLive]::TakeWake() -or $now -ge $nextHeartbeat) {
            $nextHeartbeat = $now.AddSeconds(10)
            Invoke-Heartbeat
        }

        if ([AdmLive]::LastError -and [AdmLive]::LastError -ne $lastLiveError) {
            $lastLiveError = [AdmLive]::LastError
            Write-Log "Sessão ao vivo / espera: $lastLiveError"
        }

        Start-Sleep -Milliseconds 250
    } catch {
        Write-Log "Erro: $($_.Exception.Message)"
        Start-Sleep -Seconds 2
    }
}
