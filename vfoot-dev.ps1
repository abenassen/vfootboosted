<#
  Equivalente Windows di ./vfoot-dev (che e' bash e usa ip/ss/setsid//proc:
  su Windows non gira). Stesso contratto:

    .\vfoot-dev.ps1 local     tutto su localhost: nessun altro dispositivo entra
    .\vfoot-dev.ps1 lan       raggiungibile dal wifi di casa (telefono, tablet)
                              sull'IP di questa macchina, RILEVATO OGNI VOLTA
    .\vfoot-dev.ps1 status    che assetto e' attivo, cosa gira, a quali indirizzi
    .\vfoot-dev.ps1 restart   riavvia senza cambiare assetto
    .\vfoot-dev.ps1 stop      ferma entrambi

  Perche' uno script e non due righe a mano: l'indirizzo compare in QUATTRO
  posti (ALLOWED_HOSTS e CORS di Django, il base URL nei link delle email, il
  VITE_API_BASE_URL del frontend) e i server lo leggono solo all'avvio.
#>

param([string]$Command = 'status')

$ErrorActionPreference = 'Stop'

$Repo      = $PSScriptRoot
$EnvBack   = Join-Path $Repo '.env'
$EnvFront  = Join-Path $Repo 'vfoot-frontend\.env.local'
$Py        = Join-Path $Repo 'vfoot-backend\.venv\Scripts\python.exe'
$LogDir    = Join-Path $env:TEMP 'vfoot-dev'
$BackPort  = 8000
$FrontPort = 5173

function Die($msg) { Write-Host "errore: $msg" -ForegroundColor Red; exit 1 }

# --- lettura/scrittura dei file env ---------------------------------------
# Confronto per prefisso letterale, non regex: la secret key contiene '=' e
# altri caratteri che una sostituzione ingenua interpreterebbe.

function Get-EnvValue($file, $key) {
    if (-not (Test-Path $file)) { return $null }
    foreach ($line in Get-Content $file) {
        if ($line.StartsWith("$key=")) { return $line.Substring($key.Length + 1) }
    }
    return $null
}

function Set-EnvValue($file, $key, $val) {
    if (-not (Test-Path $file)) { Die "manca $file" }
    $lines = @(Get-Content $file)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line.StartsWith("$key=")) { $found = $true; "$key=$val" } else { $line }
    }
    if (-not $found) { $out = @($out) + "$key=$val" }
    Set-Content -Path $file -Value $out -Encoding UTF8
}

# --- rete ------------------------------------------------------------------

function Get-LocalIp {
    # L'IP dell'interfaccia che regge la rotta di default: esclude da solo i
    # bridge virtuali e le VPN inattive.
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
                 Sort-Object RouteMetric, ifMetric | Select-Object -First 1
        if (-not $route) { return $null }
        (Get-NetIPAddress -InterfaceIndex $route.ifIndex -AddressFamily IPv4 -ErrorAction Stop |
            Select-Object -First 1).IPAddress
    } catch { return $null }
}

function Get-PidsOnPort($port) {
    try {
        @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch { @() }
}

function Test-PortBusy($port) { (Get-PidsOnPort $port).Count -gt 0 }

function Wait-Port($port, $limitSec = 40) {
    $waited = 0
    while (-not (Test-PortBusy $port)) {
        if ($waited -gt ($limitSec * 2)) { return $false }
        Start-Sleep -Milliseconds 500
        $waited++
    }
    return $true
}

# --- avvio e arresto -------------------------------------------------------

function Stop-OnPort($port, $label) {
    $pids = Get-PidsOnPort $port
    if ($pids.Count -eq 0) { Write-Host ("  {0,-9} gia fermo" -f $label) -ForegroundColor DarkGray; return }
    foreach ($procId in $pids) { try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch {} }
    for ($i = 0; $i -lt 20; $i++) { if (-not (Test-PortBusy $port)) { break }; Start-Sleep -Milliseconds 500 }
    if (Test-PortBusy $port) { Die "non riesco a liberare la porta $port ($label)" }
    Write-Host ("  {0,-9} fermato" -f $label)
}

function Start-Backend($bind) {
    New-Item -ItemType Directory -Force $LogDir | Out-Null
    # Le variabili esportate nella shell vincerebbero su quelle del .env
    # (load_dotenv non sovrascrive l'ambiente): le ripuliamo qui, ed e' cio'
    # che rende affidabile il passaggio fra i due assetti.
    foreach ($v in 'DJANGO_ALLOWED_HOSTS','DJANGO_CORS_ORIGINS','VFOOT_FRONTEND_BASE_URL') {
        Remove-Item "env:$v" -ErrorAction SilentlyContinue
    }
    $log = Join-Path $LogDir 'backend.log'
    Start-Process -FilePath $Py `
        -ArgumentList 'manage.py','runserver',$bind,'--noreload' `
        -WorkingDirectory (Join-Path $Repo 'vfoot-backend\src') `
        -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    if (-not (Wait-Port $BackPort 40)) {
        Get-Content $log,"$log.err" -Tail 20 -ErrorAction SilentlyContinue
        Die 'backend non partito'
    }
}

function Resolve-Npm {
    # Node qui e' installato come zip nella cartella utente (l'MSI vuole
    # l'amministratore): se la shell corrente non ha ancora ricaricato il PATH
    # utente, lo cerchiamo comunque nelle posizioni note invece di arrenderci.
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @()
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\node-v*-win-x64\npm.cmd" -ErrorAction SilentlyContinue
    $candidates += Get-Item "$env:ProgramFiles\nodejs\npm.cmd" -ErrorAction SilentlyContinue
    $found = $candidates | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) {
        # Vite lancia sottoprocessi node: senza questo non li troverebbe.
        $env:Path = $found.DirectoryName + ';' + $env:Path
        return $found.FullName
    }
    return $null
}

function Start-Frontend($vmHost) {
    New-Item -ItemType Directory -Force $LogDir | Out-Null
    foreach ($v in 'VITE_API_BASE_URL','VITE_API_PROVIDER') {
        Remove-Item "env:$v" -ErrorAction SilentlyContinue
    }
    $npm = Resolve-Npm
    if (-not $npm) { Die 'npm non trovato: installa Node 22+ o aggiungilo al PATH' }
    $log = Join-Path $LogDir 'frontend.log'
    Start-Process -FilePath $npm `
        -ArgumentList 'run','dev','--','--host',$vmHost,'--port',"$FrontPort" `
        -WorkingDirectory (Join-Path $Repo 'vfoot-frontend') `
        -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    if (-not (Wait-Port $FrontPort 40)) {
        Get-Content $log,"$log.err" -Tail 20 -ErrorAction SilentlyContinue
        Die 'frontend non partito'
    }
}

# --- assetti ---------------------------------------------------------------

function Set-ModeLocal {
    Set-EnvValue $EnvBack  'DJANGO_ALLOWED_HOSTS'    'localhost,127.0.0.1,testserver'
    Set-EnvValue $EnvBack  'DJANGO_CORS_ORIGINS'     "http://localhost:$FrontPort,http://127.0.0.1:$FrontPort"
    Set-EnvValue $EnvBack  'VFOOT_FRONTEND_BASE_URL' "http://localhost:$FrontPort"
    Set-EnvValue $EnvFront 'VITE_API_BASE_URL'       "http://localhost:$BackPort/api/v1"
}

function Set-ModeLan($ip) {
    Set-EnvValue $EnvBack  'DJANGO_ALLOWED_HOSTS'    "localhost,127.0.0.1,testserver,$ip"
    Set-EnvValue $EnvBack  'DJANGO_CORS_ORIGINS'     "http://localhost:$FrontPort,http://127.0.0.1:$FrontPort,http://${ip}:$FrontPort"
    Set-EnvValue $EnvBack  'VFOOT_FRONTEND_BASE_URL' "http://${ip}:$FrontPort"
    Set-EnvValue $EnvFront 'VITE_API_BASE_URL'       "http://${ip}:$BackPort/api/v1"
}

function Get-CurrentMode {
    # L'assetto e' desumibile dal .env: se fra gli host ammessi c'e' un IP,
    # siamo in lan. Nessun file di stato a parte, che potrebbe mentire.
    $hosts = Get-EnvValue $EnvBack 'DJANGO_ALLOWED_HOSTS'
    if ($hosts) {
        $ip = ($hosts -split ',' | Where-Object { $_ -match '^\d+(\.\d+){3}$' -and $_ -notlike '127.*' } | Select-Object -First 1)
        if ($ip) { return @{ mode = 'lan'; ip = $ip } }
    }
    return @{ mode = 'local'; ip = $null }
}

function Restart-For($mode, $ip) {
    Write-Host 'Arresto:' -ForegroundColor White
    Stop-OnPort $FrontPort 'frontend'
    Stop-OnPort $BackPort  'backend'
    Write-Host "Avvio ($mode):" -ForegroundColor White
    if ($mode -eq 'lan') {
        Start-Backend  "0.0.0.0:$BackPort"; Write-Host '  backend   ok'
        Start-Frontend '0.0.0.0';           Write-Host '  frontend  ok'
    } else {
        Start-Backend  "localhost:$BackPort"; Write-Host '  backend   ok'
        Start-Frontend 'localhost';           Write-Host '  frontend  ok'
    }
}

# --- comandi ---------------------------------------------------------------

function Cmd-Status {
    $cur = Get-CurrentMode
    Write-Host -NoNewline 'Assetto configurato: ' -ForegroundColor White
    Write-Host ($cur.mode + $(if ($cur.ip) { " ($($cur.ip))" } else { '' }))

    $now = Get-LocalIp
    if (-not $now) {
        Write-Host 'attenzione: nessuna rotta di default: IP non rilevabile (wifi spento?)' -ForegroundColor Yellow
    } else {
        Write-Host -NoNewline "IP attuale sulla rete:  $now"
        if ($cur.mode -eq 'lan' -and $now -ne $cur.ip) {
            Write-Host '  <- diverso da quello configurato: rilancia .\vfoot-dev.ps1 lan' -ForegroundColor Yellow
        } else { Write-Host '' }
    }

    Write-Host "`nServer:" -ForegroundColor White
    foreach ($spec in @(@{l='backend';p=$BackPort}, @{l='frontend';p=$FrontPort})) {
        $pids = Get-PidsOnPort $spec.p
        if ($pids.Count -gt 0) {
            Write-Host ("  {0,-9} attivo   porta {1}  (pid {2})" -f $spec.l, $spec.p, ($pids -join ' ')) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-9} fermo    porta {1}" -f $spec.l, $spec.p) -ForegroundColor Red
        }
    }

    Write-Host "`nIndirizzi:" -ForegroundColor White
    $api = Get-EnvValue $EnvFront 'VITE_API_BASE_URL'
    if ($api) {
        Write-Host ('  frontend  ' + ($api -replace '/api/v1','' -replace ":$BackPort", ":$FrontPort"))
        Write-Host "  API       $api"
    }
    Write-Host "  log: $LogDir" -ForegroundColor DarkGray
}

function Cmd-Lan {
    $ip = Get-LocalIp
    if (-not $ip) { Die "nessuna rotta di default: la rete e' spenta? (serve un IP da annunciare)" }
    Write-Host "IP rilevato: $ip" -ForegroundColor White
    Set-ModeLan $ip
    Restart-For 'lan' $ip
    Write-Host "`nPronto. Dal telefono: http://${ip}:$FrontPort/" -ForegroundColor Green
    Write-Host "Se il telefono non si connette, apri le porte nel firewall di Windows:" -ForegroundColor DarkGray
    Write-Host "  New-NetFirewallRule -DisplayName 'vfoot dev' -Direction Inbound -Protocol TCP -LocalPort $FrontPort,$BackPort -Action Allow" -ForegroundColor DarkGray
}

function Cmd-Local {
    Set-ModeLocal
    Restart-For 'local' $null
    Write-Host "`nPronto. Solo da questa macchina: http://localhost:$FrontPort/" -ForegroundColor Green
}

function Cmd-Restart {
    $cur = Get-CurrentMode
    if ($cur.mode -eq 'lan') {
        # Un riavvio e' anche l'occasione in cui ci si accorge che il router
        # ha assegnato un altro IP.
        $now = Get-LocalIp
        $ip = $cur.ip
        if ($now -and $now -ne $ip) {
            Write-Host "IP cambiato: $ip -> $now, aggiorno" -ForegroundColor Yellow
            Set-ModeLan $now; $ip = $now
        }
        Restart-For 'lan' $ip
        Write-Host "`nPronto. Dal telefono: http://${ip}:$FrontPort/" -ForegroundColor Green
    } else {
        Restart-For 'local' $null
        Write-Host "`nPronto. http://localhost:$FrontPort/" -ForegroundColor Green
    }
}

function Cmd-Stop {
    Write-Host 'Arresto:' -ForegroundColor White
    Stop-OnPort $FrontPort 'frontend'
    Stop-OnPort $BackPort  'backend'
}

if (-not (Test-Path $EnvBack))  { Die "manca $EnvBack (copia .env.example)" }
if (-not (Test-Path $EnvFront)) { Die "manca $EnvFront (copia vfoot-frontend\.env.example)" }
if (-not (Test-Path $Py))       { Die "manca il venv del backend: $Py" }
if (-not (Test-Path (Join-Path $Repo 'vfoot-frontend\node_modules'))) { Die 'manca node_modules: npm install in vfoot-frontend' }

switch ($Command) {
    'lan'     { Cmd-Lan }
    'local'   { Cmd-Local }
    'status'  { Cmd-Status }
    'restart' { Cmd-Restart }
    'stop'    { Cmd-Stop }
    default   { Write-Host "comando sconosciuto: $Command`n"; Write-Host 'usa: local | lan | status | restart | stop'; exit 1 }
}
