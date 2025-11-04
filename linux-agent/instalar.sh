#!/bin/sh
# ADM Kiosk - instalação do agente para computadores / netboxes Linux
# Uso:  sudo sh instalar.sh [endereço-do-servidor] [url-da-página]
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Execute com permissões de administrador:  sudo sh instalar.sh"
    exit 1
fi

USER_NAME="${SUDO_USER:-}"
if [ -z "$USER_NAME" ] || [ "$USER_NAME" = "root" ]; then
    printf "Utilizador que inicia a sessão gráfica neste ecrã: "
    read -r USER_NAME
fi
if ! id "$USER_NAME" >/dev/null 2>&1; then
    echo "O utilizador '$USER_NAME' não existe."
    exit 1
fi
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=/opt/adm-kiosk-agent

SERVER="${1:-}"
URL="${2:-}"
if [ -z "$SERVER" ]; then
    echo "Endereço do servidor de administração, ex.: 192.168.1.3:8080"
    printf "(Enter = procurar automaticamente na rede): "
    read -r SERVER
fi
while :; do
    if [ -z "$URL" ]; then
        echo "Página a apresentar neste ecrã (endereço do site, NÃO é a palavra-passe)."
        printf "Ex.: http://10.10.5.20/fids  (Enter = definir depois no painel web): "
        read -r URL
    fi
    HOST_PART=$(echo "$URL" | sed -e 's#^https\?://##' -e 's#[/?\#].*$##')
    # Um nome sem ponto nem porta (ex.: "admin") quase sempre é um engano.
    case "$HOST_PART" in
        ""|*.*|*:*|localhost) break ;;
    esac
    printf "'%s' não parece um endereço de página (ex.: http://10.10.5.20/fids). Usar mesmo assim? (s/N) " "$URL"
    read -r ANSWER
    case "$ANSWER" in s*|S*) break ;; esac
    URL=""
done

echo
echo "== A instalar os pacotes incluídos (sem precisar de Internet) =="
ARCH=$(dpkg --print-architecture 2>/dev/null || echo amd64)
if ls "$SRC/pacotes/$ARCH/"*.deb >/dev/null 2>&1; then
    dpkg -i "$SRC/pacotes/$ARCH/"*.deb || true
elif ls "$SRC/pacotes/"*.deb >/dev/null 2>&1; then
    dpkg -i "$SRC/pacotes/"*.deb || true
fi

echo
echo "== A completar dependências, se houver Internet =="
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-tk ffmpeg xdotool \
        x11-xserver-utils x11-utils iproute2 || true
    if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1 &&
       ! command -v google-chrome >/dev/null 2>&1 && ! command -v firefox >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chromium ||
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chromium-browser || true
    fi
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-tkinter ffmpeg xdotool xset xrandr xdpyinfo iproute || true
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install python3 python3-tk ffmpeg xdotool xset xrandr xdpyinfo iproute2 || true
elif command -v pacman >/dev/null 2>&1; then
    pacman -S --noconfirm --needed python tk ffmpeg xdotool xorg-xset xorg-xrandr xorg-xdpyinfo iproute2 || true
else
    echo "Gestor de pacotes não reconhecido: instale manualmente python3, ffmpeg e xdotool."
fi

# Sessão Wayland (ex.: Ubuntu 25.10 / 26.04 com GNOME, que já não tem Xorg): não permite ver nem
# controlar o ecrã remotamente. Propõe instalar a sessão XFCE (X11) com início de sessão automático.
SESSION_TYPE=""
for P in $(pgrep -u "$USER_NAME" 2>/dev/null); do
    T=$(tr '\0' '\n' < "/proc/$P/environ" 2>/dev/null | sed -n 's/^XDG_SESSION_TYPE=//p' | head -n 1)
    if [ -n "$T" ]; then SESSION_TYPE="$T"; break; fi
done
NEED_REBOOT=0
if [ "$SESSION_TYPE" = "wayland" ] && command -v apt-get >/dev/null 2>&1; then
    echo
    echo "ATENÇÃO: a sessão gráfica de '$USER_NAME' é Wayland. Nela o sistema não permite ver nem"
    echo "controlar o ecrã a partir do painel. Recomenda-se a sessão XFCE (X11), leve e própria para ecrãs."
    printf "Instalar a sessão XFCE com início de sessão automático de '%s'? (S/n) " "$USER_NAME"
    read -r ANSWER
    case "$ANSWER" in
        n*|N*) echo "Sessão mantida. Ver o ecrã ao vivo não vai funcionar nesta sessão." ;;
        *)
            echo "== A instalar XFCE + LightDM (pode demorar alguns minutos) =="
            echo "lightdm shared/default-x-display-manager select lightdm" | debconf-set-selections || true
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xfce4 lightdm lightdm-gtk-greeter || true
            if [ -f /usr/share/xsessions/xfce.desktop ] && command -v lightdm >/dev/null 2>&1; then
                command -v lightdm > /etc/X11/default-display-manager
                ln -sf /lib/systemd/system/lightdm.service /etc/systemd/system/display-manager.service
                groupadd -f autologin
                usermod -aG autologin "$USER_NAME" || true
                mkdir -p /etc/lightdm/lightdm.conf.d
                printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\nautologin-session=xfce\nuser-session=xfce\n' \
                    "$USER_NAME" > /etc/lightdm/lightdm.conf.d/50-adm-kiosk.conf
                NEED_REBOOT=1
            else
                echo "Não foi possível instalar o XFCE/LightDM. Verifique a ligação à Internet e repita."
            fi
            ;;
    esac
fi

echo
echo "== A copiar o agente para $DEST =="
mkdir -p "$DEST"
cp "$SRC/adm-agent.py" "$DEST/adm-agent.py"
cp "$SRC/desinstalar.sh" "$DEST/desinstalar.sh" 2>/dev/null || true
chmod 755 "$DEST/adm-agent.py"
python3 - "$SERVER" "$URL" "$DEST/agent.json" <<'EOF'
import json, re, sys, urllib.parse, urllib.request
server = sys.argv[1].strip().rstrip("/")
if server:
    if not re.match(r"^https?://", server, re.I):
        server = "http://" + server
    u = urllib.parse.urlsplit(server)
    server = f"http://{u.hostname}:8080" if u.port is None and u.scheme.lower() == "http" else f"{u.scheme}://{u.netloc}"
with open(sys.argv[3], "w", encoding="utf-8") as f:
    json.dump({"serverUrl": server, "url": sys.argv[2], "browser": "", "zoom": 100}, f, indent=2)
print()
if not server:
    print("Servidor: descoberta automática na rede.")
    sys.exit(0)
print(f"A testar a ligação ao servidor {server} ...")
try:
    urllib.request.urlopen(server + "/", timeout=5).read(64)
    print("  OK - o servidor de administração respondeu.")
except Exception as e:
    print(f"  ATENÇÃO: o servidor não respondeu ({e}).")
    print("  - Confirme o endereço em Definições > Endereço do servidor, no painel web")
    print("    (use o endereço da mesma rede deste computador, com a porta, ex.: 192.168.1.3:8080).")
    print("  - No PC do servidor, execute configurar-firewall.bat como administrador.")
    print("  - Numa máquina virtual (VirtualBox/VMware), use a placa de rede em modo 'Bridge'.")
    print(f"  Pode corrigir depois em {sys.argv[3]} (serverUrl) e voltar a iniciar a sessão.")
EOF
chown -R "$USER_NAME": "$DEST"

echo "== Arranque automático ao iniciar a sessão gráfica =="
AUTOSTART="$USER_HOME/.config/autostart"
mkdir -p "$AUTOSTART"
cat > "$AUTOSTART/adm-kiosk-agent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ADM Kiosk Agente
Comment=Aeroportos de Moçambique - desenvolvido por Harmonico Lucas
Exec=/usr/bin/env python3 $DEST/adm-agent.py
X-GNOME-Autostart-enabled=true
NoDisplay=false
Terminal=false
EOF
chown -R "$USER_NAME": "$USER_HOME/.config"

echo "== Permissão para reiniciar o computador a partir do painel =="
SUDOERS=/etc/sudoers.d/adm-kiosk-agent
echo "$USER_NAME ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, /usr/sbin/shutdown, /bin/systemctl reboot, /bin/systemctl reboot -f, /usr/bin/systemctl reboot, /usr/bin/systemctl reboot -f" > "$SUDOERS"
chmod 440 "$SUDOERS"
if command -v visudo >/dev/null 2>&1 && ! visudo -cf "$SUDOERS" >/dev/null 2>&1; then
    rm -f "$SUDOERS"
fi

# Arranca já, se o utilizador tiver uma sessão gráfica aberta.
pkill -f "$DEST/adm-agent.py" 2>/dev/null || true
STARTED=0
for P in $(pgrep -u "$USER_NAME" 2>/dev/null); do
    ENV_VARS=$(tr '\0' '\n' < "/proc/$P/environ" 2>/dev/null |
        grep -E '^(DISPLAY|XAUTHORITY|XDG_SESSION_TYPE|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|WAYLAND_DISPLAY)=' || true)
    if echo "$ENV_VARS" | grep -q '^DISPLAY='; then
        # shellcheck disable=SC2086
        sudo -u "$USER_NAME" env $ENV_VARS HOME="$USER_HOME" nohup python3 "$DEST/adm-agent.py" >/dev/null 2>&1 &
        STARTED=1
        break
    fi
done

echo
echo "Instalação concluída."
if [ "$NEED_REBOOT" = "1" ]; then
    echo "Reinicie o computador (sudo reboot): entra sozinho na sessão XFCE e o agente arranca com ela."
elif [ "$STARTED" = "1" ]; then
    echo "O agente já está a correr. O navegador abre em ecrã inteiro dentro de alguns segundos."
else
    echo "O agente arranca no próximo início de sessão gráfica de '$USER_NAME'."
fi
echo "Recomendações: ative o início de sessão automático de '$USER_NAME' e use uma sessão X11 (Xorg)"
echo "para permitir o controlo remoto do rato e do teclado. Registo: $DEST/agent.log"
