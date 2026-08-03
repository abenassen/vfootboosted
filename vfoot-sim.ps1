<#
  Gemello Windows di ./vfoot-sim. Stesso contratto, stessi argomenti:

    .\vfoot-sim.ps1              avvia (scenario predefinito, g22-live)
    .\vfoot-sim.ps1 g22-pre      avvia su un altro scenario
    .\vfoot-sim.ps1 --at 2027-01-31T21:15:00+01:00
    .\vfoot-sim.ps1 status       che cosa gira, con che orologio
    .\vfoot-sim.ps1 stop         ferma tutto quello che ha avviato
    .\vfoot-sim.ps1 build        ricostruisce lo stato dello scenario, poi avvia
    .\vfoot-sim.ps1 reset        riporta all'istante iniziale in pochi secondi

  Perche' esiste, visto che ./vfoot-sim gira gia' su Windows: gira in GIT BASH.
  Windows non onora lo shebang, quindi da PowerShell un file senza estensione non
  e' un eseguibile -- si apre la finestra "come vuoi aprire questo file". E non
  basta anteporre `bash`: l'installazione di Git per Windows mette sul PATH solo
  cmd\git.exe, non bin\bash.exe.

  Qui dentro non c'e' logica: la trova ed esegue lo script bash. Duplicare la
  logica in PowerShell -- che e' cio' che vfoot-dev.ps1 ha dovuto fare, perche'
  vfoot-dev usa ss, setsid e /proc -- avrebbe voluto dire due implementazioni da
  tenere allineate. vfoot-sim e' stato scritto apposta senza quegli strumenti,
  proprio per non dover avere un secondo cervello.
#>

$ErrorActionPreference = 'Stop'

$Repo   = $PSScriptRoot
$Script = Join-Path $Repo 'vfoot-sim'

if (-not (Test-Path $Script)) { Write-Host "errore: non trovo $Script" -ForegroundColor Red; exit 1 }

function Resolve-Bash {
    $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # Posizioni note di Git per Windows, per macchina e per utente (l'installazione
    # senza amministratore finisce sotto LOCALAPPDATA).
    $candidates = @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

$Bash = Resolve-Bash
if (-not $Bash) {
    Write-Host "errore: bash non trovato (serve Git per Windows)." -ForegroundColor Red
    Write-Host "  cercato sul PATH e in:" -ForegroundColor DarkGray
    Write-Host "    $env:ProgramFiles\Git\bin\bash.exe" -ForegroundColor DarkGray
    Write-Host "    $env:LOCALAPPDATA\Programs\Git\bin\bash.exe" -ForegroundColor DarkGray
    exit 1
}

# Il percorso dello script passa RELATIVO, dopo essersi spostati nel repo: bash di
# MSYS accetta anche un percorso Windows, ma la conversione automatica dei
# parametri e' una fonte di sorprese e questo modo non la coinvolge.
Push-Location $Repo
try {
    & $Bash 'vfoot-sim' @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
