#!/bin/sh
# ADM Kiosk - Servidor de administração: desinstalação em Linux.
# Uso:  sudo sh desinstalar-servidor.sh

APP_DIR=/opt/adm-kiosk-servidor
DATA_DIR=/var/lib/adm-kiosk-servidor
SERVICE=adm-kiosk-servidor
SVC_USER=admkiosk
DISCOVERY_PORT=47800
UNIT="/etc/systemd/system/$SERVICE.service"

say() { printf '%s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    say "Execute com sudo:  sudo sh desinstalar-servidor.sh"
    exit 1
fi

PORT="$(sed -n 's/.*--port \([0-9]*\).*/\1/p' "$UNIT" 2>/dev/null | head -n 1)"
PORT="${PORT:-8080}"

say "A parar e a remover o serviço $SERVICE..."
systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
rm -f "$UNIT"
systemctl daemon-reload 2>/dev/null || true

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw delete allow "$PORT/tcp" >/dev/null 2>&1 || true
    ufw delete allow "$DISCOVERY_PORT/udp" >/dev/null 2>&1 || true
elif systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --quiet --permanent --remove-port="$PORT/tcp" --remove-port="$DISCOVERY_PORT/udp" 2>/dev/null || true
    firewall-cmd --quiet --reload 2>/dev/null || true
fi

rm -rf "$APP_DIR"

if [ -d "$DATA_DIR" ]; then
    printf 'Apagar também os dados (equipamentos registados, configurações e palavra-passe)? [s/N]: '
    read -r ans || ans=""
    case "$ans" in
        s|S|sim|Sim|SIM) rm -rf "$DATA_DIR"; say "Dados apagados." ;;
        *) say "Os dados foram mantidos em $DATA_DIR" ;;
    esac
fi
if [ ! -d "$DATA_DIR" ] && id "$SVC_USER" >/dev/null 2>&1; then
    userdel "$SVC_USER" 2>/dev/null || true
fi

say "O servidor ADM Kiosk foi desinstalado."
