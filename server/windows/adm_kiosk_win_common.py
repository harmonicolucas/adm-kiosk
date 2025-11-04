"""Caminhos e utilitários partilhados pelo instalador e pela janela do servidor (Windows)."""

import os
import socket
import sqlite3
import urllib.request

APP = "ADM Kiosk Servidor"
TASK = "ADM Kiosk Servidor"
PORT = 8080
INSTALL_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), APP)
INSTALLED_EXE = os.path.join(INSTALL_DIR, "ADM-Kiosk-Servidor.exe")
OLD_PANEL_EXE = os.path.join(INSTALL_DIR, "ADM-Kiosk-Painel.exe")
DATA_ROOT = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), APP)
DATA_DIR = os.path.join(DATA_ROOT, "data")
NO_WINDOW = 0x08000000


def _setting(key):
    db = os.path.join(DATA_DIR, "adm_kiosk.db")
    if not os.path.isfile(db):
        return ""
    try:
        con = sqlite3.connect("file:" + urllib.request.pathname2url(db) + "?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        finally:
            con.close()
        return str(row[0]) if row else ""
    except sqlite3.Error:
        return ""


def current_port():
    """Porta principal escolhida no painel (Definições > Endereço do servidor); por omissão 8080."""
    value = _setting("http_port")
    return int(value) if value.isdigit() else PORT


def active_ports():
    """Porta principal primeiro, seguida das que foram acrescentadas no painel."""
    main = current_port()
    others = {int(p) for p in _setting("extra_ports").split(",") if p.strip().isdigit()}
    return [main] + sorted(others - {main})


def port_busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def free_ports(limit=6):
    """Portas livres, com a 8080 em primeiro lugar quando está disponível."""
    candidates = [8080, 8081, 8082, 8088, 8090, 8000, 8888, 9080, 8443, 80]
    candidates += [number for number in range(8083, 8100) if number not in candidates]
    free = []
    seen = set()
    for number in candidates:
        if number in seen:
            continue
        seen.add(number)
        if not port_busy(number):
            free.append(number)
        if len(free) >= limit:
            break
    return free


def save_http_port(port):
    """Grava a porta escolhida na instalação, antes de o servidor arrancar."""
    os.makedirs(DATA_DIR, exist_ok=True)
    db = os.path.join(DATA_DIR, "adm_kiosk.db")
    con = sqlite3.connect(db, timeout=5)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('http_port', ?)", (str(int(port)),))
        con.commit()
    finally:
        con.close()
