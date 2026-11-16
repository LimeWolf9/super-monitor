#!/bin/bash
# Liga ou desliga o monitor a sério (o hub chama-o no botão ⏻ do comando, ver config.local.json do hub).
# Uso: ecra.sh off | on
set -u
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${WAYLAND_DISPLAY:-}" ]; then       # o hub corre como serviço: procura o ecrã do cage
    WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR" 2>/dev/null | grep -E '^wayland-[0-9]+$' | head -1)
    export WAYLAND_DISPLAY
fi
case "${1:-}" in
    off|on) ;;
    *) echo "Uso: $0 off|on"; exit 2 ;;
esac
[ -n "$WAYLAND_DISPLAY" ] || { echo "ecra.sh: o kiosk não está a correr"; exit 1; }

# 1.º o modo de poupança (DPMS): o monitor dorme e o cage nem dá por isso
wlopm --"$1" '*' 2>/dev/null && exit 0

# Plano B: tirar a saída e voltar a pô-la (com a mesma rotação do kiosk)
ROTACAO=90; SAIDA=""
CONF="$HOME/.config/supermonitor/kiosk.conf"
[ -f "$CONF" ] && . "$CONF"
[ -n "$SAIDA" ] || SAIDA=$(wlr-randr | awk 'NR==1 {print $1}')
if [ "$1" = off ]; then
    wlr-randr --output "$SAIDA" --off
else
    wlr-randr --output "$SAIDA" --on ${ROTACAO:+--transform "$ROTACAO"}
fi
