#!/bin/sh
# ADM Kiosk - remoção do agente Linux.  Uso:  sudo sh desinstalar.sh
if [ "$(id -u)" -ne 0 ]; then
    echo "Execute com permissões de administrador:  sudo sh desinstalar.sh"
    exit 1
fi
DEST=/opt/adm-kiosk-agent
pkill -f "$DEST/adm-agent.py" 2>/dev/null || true
for F in /home/*/.config/autostart/adm-kiosk-agent.desktop /root/.config/autostart/adm-kiosk-agent.desktop; do
    [ -f "$F" ] && rm -f "$F"
done
rm -f /etc/sudoers.d/adm-kiosk-agent
rm -rf "$DEST"
echo "Agente ADM Kiosk removido. O navegador em modo kiosk já não abre automaticamente."
