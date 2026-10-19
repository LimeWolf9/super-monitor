# Liga o MonitorHub: arranca o hub e abre o Edge em ecrã inteiro no monitor vertical.
# Ao fechar (Alt+F4), fecha a app que estiver aberta e para o hub.
# Uso: duplo clique em MonitorHub.bat.

$raiz = $PSScriptRoot
$url = "http://127.0.0.1:8080/"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { Write-Host "Não encontrei o Microsoft Edge."; Read-Host "Enter para sair"; exit 1 }

# Python: o hub só usa a biblioteca standard, por isso serve qualquer Python 3
$python = $null; $argsPy = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $python = "py"; $argsPy = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = "python" }
if (-not $python) { Write-Host "Não encontrei o Python."; Read-Host "Enter para sair"; exit 1 }

# Monitor da parede: o que está na vertical; se nenhum estiver, o que não é o principal.
Add-Type -AssemblyName System.Windows.Forms
$ecras = [System.Windows.Forms.Screen]::AllScreens
$alvo = $ecras | Where-Object { $_.Bounds.Height -gt $_.Bounds.Width } | Select-Object -First 1
if (-not $alvo) { $alvo = $ecras | Where-Object { -not $_.Primary } | Select-Object -First 1 }
if (-not $alvo) { $alvo = $ecras[0] }

# Hub (só se ainda não estiver a correr)
$hub = $null
try { Invoke-WebRequest "$($url)api/estado" -UseBasicParsing -TimeoutSec 2 | Out-Null }
catch {
    $hub = Start-Process $python -ArgumentList ($argsPy + @("hub.py")) -WorkingDirectory $raiz -WindowStyle Minimized -PassThru
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try { Invoke-WebRequest "$($url)api/estado" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch {}
    }
}

$perfil = Join-Path $env:LOCALAPPDATA "monitorhub\edge"
$b = $alvo.Bounds
$edgeProc = Start-Process $edge -PassThru -ArgumentList @(
    "--kiosk", $url, "--edge-kiosk-type=fullscreen", "--no-first-run",
    "--user-data-dir=`"$perfil`"", "--window-position=$($b.X),$($b.Y)", "--window-size=$($b.Width),$($b.Height)")
$edgeProc.WaitForExit()

# Fechou o ecrã: volta ao menu (o hub para a app que arrancou) e depois para o hub
try { Invoke-RestMethod "$($url)api/comando" -Method Post -ContentType "application/json" -Body '{"acao":"menu"}' -TimeoutSec 15 | Out-Null } catch {}
if ($hub -and -not $hub.HasExited) { taskkill /PID $hub.Id /T /F | Out-Null }
