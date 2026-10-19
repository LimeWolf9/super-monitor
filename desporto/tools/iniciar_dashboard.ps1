# Liga o dashboard: arranca o servidor (que atualiza os dados) e abre o Edge em ecrã inteiro no monitor vertical.
# Ao fechar o dashboard (Alt+F4), o servidor também para: assim só está ligado quando queres.
# Uso: duplo clique em Dashboard.bat, na raiz do projeto.

$raiz = Split-Path -Parent $PSScriptRoot
$python = Join-Path $raiz ".venv\Scripts\python.exe"
$url = "http://127.0.0.1:8000/"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { Write-Host "Não encontrei o Microsoft Edge."; Read-Host "Enter para sair"; exit 1 }

# Monitor do dashboard: o que está na vertical (mais alto do que largo); se nenhum estiver, o que não é o principal.
Add-Type -AssemblyName System.Windows.Forms
$ecras = [System.Windows.Forms.Screen]::AllScreens
$alvo = $ecras | Where-Object { $_.Bounds.Height -gt $_.Bounds.Width } | Select-Object -First 1
if (-not $alvo) {
    $alvo = $ecras | Where-Object { -not $_.Primary } | Select-Object -First 1
    Write-Host "Aviso: nenhum monitor está na vertical (Definições > Ecrã > Orientação: Retrato)."
}
if (-not $alvo) { $alvo = $ecras[0] }

# Servidor (só se ainda não estiver a correr)
$servidor = $null
try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null }
catch {
    $servidor = Start-Process $python -ArgumentList "serve.py", "--no-browser" -WorkingDirectory $raiz -WindowStyle Minimized -PassThru
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch {}
    }
}

# Edge em modo quiosque, com um perfil próprio (não mexe nas tuas janelas do Edge) e posto no monitor certo
$perfil = Join-Path $env:LOCALAPPDATA "dashboard-desportivo\edge"
$b = $alvo.Bounds
$edgeProc = Start-Process $edge -PassThru -ArgumentList @(
    "--kiosk", $url, "--edge-kiosk-type=fullscreen", "--no-first-run",
    "--user-data-dir=`"$perfil`"", "--window-position=$($b.X),$($b.Y)", "--window-size=$($b.Width),$($b.Height)")
$edgeProc.WaitForExit()

# Fechou o dashboard: para o servidor que este script arrancou
# taskkill /T: o python do .venv lança um segundo processo, que também tem de parar
if ($servidor -and -not $servidor.HasExited) { taskkill /PID $servidor.Id /T /F | Out-Null }
