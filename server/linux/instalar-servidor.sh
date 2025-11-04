#!/bin/sh
# ADM Kiosk - Servidor de administração: instalação em Linux (serviço systemd).
# Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas.
#
# Uso:  sudo sh instalar-servidor.sh [porta]      (porta por omissão: 8080)
# Também serve para atualizar: volte a executar com a nova versão dos ficheiros.

set -e

APP_DIR=/opt/adm-kiosk-servidor
DATA_DIR=/var/lib/adm-kiosk-servidor
SERVICE=adm-kiosk-servidor
SVC_USER=admkiosk
DISCOVERY_PORT=47800
PORT="${1:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"

say() { printf '%s\n' "$*"; }

say "================================================================"
say " ADM Kiosk - Servidor de administração (instalação em Linux)"
say " Aeroportos de Moçambique, E.P.  |  Desenvolvido por Harmonico Lucas"
say "================================================================"

if [ "$(id -u)" -ne 0 ]; then
    say "Execute com sudo:  sudo sh instalar-servidor.sh"
    exit 1
fi
case "$PORT" in
    ''|*[!0-9]*) say "Porta inválida: $PORT"; exit 1 ;;
esac
if [ ! -f "$HERE/adm_kiosk_server.py" ] || [ ! -d "$HERE/static" ]; then
    say "Faltam ficheiros. Execute o script dentro da pasta Servidor-Admin-Linux"
    say "(onde estão adm_kiosk_server.py e a pasta static)."
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
    say "Este sistema não usa systemd. Execute o servidor manualmente:"
    say "  python3 $HERE/adm_kiosk_server.py --port $PORT"
    exit 1
fi

install_pkgs() {
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q "$@"
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q "$@"
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install "$@"
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --noconfirm "$@"
    else
        return 1
    fi
}

port_busy() {
    python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1', $1)) == 0 else 1)"
}

say "[1/6] A verificar o Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    say "      A instalar o Python 3..."
    install_pkgs python3 || { say "Não foi possível instalar o Python 3. Instale-o e volte a executar."; exit 1; }
fi
if ! python3 -c 'import sys, sqlite3; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    say "É preciso o Python 3.8 ou mais recente (com o módulo sqlite3). Versão atual: $(python3 --version 2>&1)"
    exit 1
fi
PY="$(command -v python3)"

if [ -z "$PORT" ]; then
    FREE="$(python3 -c 'import socket
cands=[8080,8081,8082,8088,8090,8000,8888,9080,8443,80]+list(range(8083,8100))
seen=set(); free=[]
for p in cands:
    if p in seen: continue
    seen.add(p)
    s=socket.socket(); s.settimeout(0.4)
    try:
        busy=s.connect_ex(("127.0.0.1", p))==0
    finally:
        s.close()
    if not busy:
        free.append(str(p))
    if len(free)>=6: break
print(" ".join(free))')"
    set -- $FREE
    FIRST="${1:-8080}"
    if [ -c /dev/tty ]; then
        say ""
        say "Portas livres: ${FREE:-nenhuma detetada}"
        say "Sugestão: $FIRST"
        printf "Porta do painel [%s]: " "$FIRST" >/dev/tty
        read -r ANSWER </dev/tty || ANSWER=""
        PORT="${ANSWER:-$FIRST}"
    else
        PORT="$FIRST"
        say "Porta do painel: $PORT (primeira porta livre)"
    fi
    say ""
fi

say "[2/6] A parar a versão instalada (se existir)..."
systemctl stop "$SERVICE" 2>/dev/null || true
sleep 1
if port_busy "$PORT"; then
    say ""
    say "ERRO: a porta $PORT está ocupada por outro programa (talvez o servidor iniciado à mão)."
    say "      Feche-o ou escolha outra porta:  sudo sh instalar-servidor.sh 8081"
    exit 1
fi

say "[3/6] A copiar o programa para $APP_DIR..."
if ! id "$SVC_USER" >/dev/null 2>&1; then
    NOLOGIN="$(command -v nologin || echo /bin/false)"
    useradd --system --user-group --home-dir "$DATA_DIR" --no-create-home --shell "$NOLOGIN" "$SVC_USER"
fi
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/static"
cp "$HERE/adm_kiosk_server.py" "$APP_DIR/"
cp -R "$HERE/static" "$APP_DIR/"
cp "$HERE/desinstalar-servidor.sh" "$APP_DIR/" 2>/dev/null || true
chown -R root:root "$APP_DIR"
chmod -R a+rX "$APP_DIR"

say "[4/6] Dados em $DATA_DIR"
mkdir -p "$DATA_DIR"
if [ -f "$HERE/data/adm_kiosk.db" ] && [ ! -f "$DATA_DIR/adm_kiosk.db" ]; then
    cp -R "$HERE/data/." "$DATA_DIR/"
    say "      Dados existentes copiados de $HERE/data"
fi
ADM_PORT="$PORT" ADM_DATA="$DATA_DIR" python3 - <<'PY'
import os, sqlite3
data = os.environ["ADM_DATA"]
os.makedirs(data, exist_ok=True)
con = sqlite3.connect(os.path.join(data, "adm_kiosk.db"))
con.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('http_port', ?)", (os.environ["ADM_PORT"],))
con.commit()
con.close()
PY
chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

say "[5/6] A criar o serviço $SERVICE (arranca sozinho com o sistema)..."
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=ADM Kiosk - Servidor de administracao (Harmonico Lucas)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY $APP_DIR/adm_kiosk_server.py --port $PORT --data $DATA_DIR
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"

say "[6/6] A abrir as portas na firewall (se estiver ativa)..."
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$PORT/tcp" >/dev/null
    ufw allow "$DISCOVERY_PORT/udp" >/dev/null
    say "      ufw: portas $PORT/tcp e $DISCOVERY_PORT/udp abertas"
elif systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --quiet --permanent --add-port="$PORT/tcp" --add-port="$DISCOVERY_PORT/udp"
    firewall-cmd --quiet --reload
    say "      firewalld: portas $PORT/tcp e $DISCOVERY_PORT/udp abertas"
else
    say "      Nenhuma firewall ativa."
fi

i=0
while [ $i -lt 20 ] && ! port_busy "$PORT"; do
    sleep 0.5
    i=$((i + 1))
done
say ""
if port_busy "$PORT"; then
    say "Instalação concluída. O servidor arranca sozinho sempre que o sistema inicia."
    say "Painel de administração:"
    for ip in $(hostname -I 2>/dev/null); do
        case "$ip" in *:*) continue ;; esac
        say "   http://$ip:$PORT"
    done
    say "Primeiro acesso: palavra-passe 'admin' (se ainda não foi alterada)."
else
    say "ATENÇÃO: o servidor não respondeu. Veja o registo com:"
    say "   sudo journalctl -u $SERVICE -n 50"
fi
say ""
say "Comandos úteis:"
say "   Estado:      sudo systemctl status $SERVICE"
say "   Reiniciar:   sudo systemctl restart $SERVICE"
say "   Registo:     sudo journalctl -u $SERVICE -f"
say "   Desinstalar: sudo sh $APP_DIR/desinstalar-servidor.sh"
