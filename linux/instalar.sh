#!/bin/bash
# Prepara o mini PC (Ubuntu Server) para o Super Monitor. Corre-se uma vez, como o teu utilizador (não root):
#   bash linux/instalar.sh && sudo reboot
# Pode voltar a correr-se sem estragar nada (ex.: depois de um git pull que mude estes ficheiros).
set -euo pipefail
RAIZ=$(cd "$(dirname "$0")/.." && pwd)
UTIL=$(id -un)
[ "$UTIL" != root ] || { echo "Corre como o teu utilizador, não como root (o script usa sudo onde precisa)."; exit 1; }

echo "== Programas: cage (ecrã de uma janela), wlr-randr/wlopm (rodar e apagar o monitor), fontes, avahi (nome supermonitor.local na rede)"
sudo apt-get update -q
sudo apt-get install -y -q cage wlr-randr curl fonts-noto-core fonts-noto-color-emoji avahi-daemon
sudo apt-get install -y -q wlopm || echo "   (sem wlopm: o ⏻ usa o wlr-randr)"
command -v chromium >/dev/null || command -v google-chrome-stable >/dev/null || sudo snap install chromium

echo "== Chromium sem a janela de tradução (política, vale para o snap e para o .deb)"
for d in /var/snap/chromium/current/policies/managed /etc/chromium/policies/managed; do
    sudo mkdir -p "$d"
    echo '{"TranslateEnabled": false}' | sudo tee "$d/supermonitor.json" >/dev/null
done

echo "== Hora de Portugal (o relógio e os jogos usam a hora do sistema)"
sudo timedatectl set-timezone Europe/Lisbon

echo "== Login automático no ecrã da parede (tty1) que abre o kiosk"
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
printf '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin %s --noclear %%I $TERM\n' "$UTIL" \
    | sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null
MARCA="# super-monitor: kiosk no ecrã da parede"
touch "$HOME/.bash_profile"
grep -qF "$MARCA" "$HOME/.bash_profile" || cat >> "$HOME/.bash_profile" <<FIM

$MARCA
[ -f "\$HOME/.profile" ] && . "\$HOME/.profile"
if [ "\$(tty)" = /dev/tty1 ] && [ -z "\${WAYLAND_DISPLAY:-}" ]; then exec "$RAIZ/linux/kiosk.sh"; fi
FIM

echo "== Fonte no lugar da Segoe UI, e afinações do kiosk"
mkdir -p "$HOME/.config/fontconfig/conf.d" "$HOME/.config/supermonitor"
cp "$RAIZ/linux/fontes.conf" "$HOME/.config/fontconfig/conf.d/50-supermonitor.conf"
[ -f "$HOME/.config/supermonitor/kiosk.conf" ] || cat > "$HOME/.config/supermonitor/kiosk.conf" <<'FIM'
# Afinações do ecrã da parede (lidas pelo linux/kiosk.sh e linux/ecra.sh)
ROTACAO=90      # 90 ou 270: se a imagem ficar de pernas para o ar, troca e reinicia
SAIDA=""        # vazio = automático
URL="http://127.0.0.1:8080/"
FIM

echo "== Botão ⏻ do comando desliga o monitor a sério (hub/config.local.json)"
python3 - "$RAIZ" <<'FIM'
import json, sys
from pathlib import Path
raiz = Path(sys.argv[1])
f = raiz / "hub" / "config.local.json"
cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
ecra = str(raiz / "linux" / "ecra.sh")
cfg.setdefault("ao_desligar_ecra", [ecra, "off"])
cfg.setdefault("ao_ligar_ecra", [ecra, "on"])
f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
FIM

echo "== Serviço do hub (arranca com o PC)"
sed "s|@RAIZ@|$RAIZ|g; s|@UTIL@|$UTIL|g" "$RAIZ/linux/supermonitor-hub.service" \
    | sudo tee /etc/systemd/system/supermonitor-hub.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable supermonitor-hub
sudo systemctl restart supermonitor-hub

echo
echo "Feito. Reinicia com: sudo reboot"
echo "Depois: o monitor mostra o Início e o comando está em http://$(hostname -I | awk '{print $1}'):8080/comando"
