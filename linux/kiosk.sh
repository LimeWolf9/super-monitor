#!/bin/bash
# Ecrã da parede: o browser em ecrã inteiro, rodado na vertical, a mostrar o hub.
# Corre sozinho no login automático do ecrã (tty1, ver instalar.sh); se o browser fechar, o login volta a abri-lo.
#   kiosk.sh          espera pelo hub e abre o cage (um "ecrã" que só mostra uma janela)
#   kiosk.sh dentro   já dentro do cage: roda o monitor e abre o browser
# Afinações em ~/.config/supermonitor/kiosk.conf (ROTACAO, SAIDA, URL).
set -u
ROTACAO=90          # 90 ou 270, conforme o lado para onde o monitor está rodado; vazio = não rodar
SAIDA=""            # vazio = a primeira que o wlr-randr mostrar (ex.: HDMI-A-1, DP-1)
URL="http://127.0.0.1:8080/"
CONF="$HOME/.config/supermonitor/kiosk.conf"
[ -f "$CONF" ] && . "$CONF"

if [ "${1:-}" != "dentro" ]; then
    for _ in $(seq 60); do                     # o hub arranca em paralelo: espera até 60 s por ele
        curl -fs -o /dev/null "${URL}api/estado" && break
        sleep 1
    done
    cage -d -s -- "$0" dentro
    sleep 3                                    # se o cage falhar logo, não entrar num ciclo rápido
    exit 0
fi

[ -n "$SAIDA" ] || SAIDA=$(wlr-randr | awk 'NR==1 {print $1}')
[ -n "$ROTACAO" ] && [ -n "$SAIDA" ] && wlr-randr --output "$SAIDA" --transform "$ROTACAO"

BROWSER=$(command -v chromium || command -v chromium-browser || command -v google-chrome-stable)
exec "$BROWSER" --kiosk --ozone-platform=wayland --no-first-run --noerrdialogs --disable-infobars \
    --disable-session-crashed-bubble --disable-features=Translate,TranslateUI --lang=pt-PT --password-store=basic \
    --autoplay-policy=no-user-gesture-required "$URL"
