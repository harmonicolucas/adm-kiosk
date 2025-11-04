#!/usr/bin/env python3
"""
ADM Kiosk - Servidor central de administração remota dos televisores.

Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas.

Funções:
  * Registo automático dos equipamentos: smart TVs / boxes Android com o launcher
    ADM Kiosk e computadores / netboxes Windows com o agente ADM Kiosk.
  * Visualização ao vivo do ecrã e controlo remoto (rato/teclado) a partir do navegador.
  * Inventário de rede (IP, máscara, gateway, DNS, MAC) e do equipamento.
  * Classificação: DPT (doméstico) / IPT (internacional) e tipo de ecrã
    (FIDS Partidas, FIDS Chegadas, Gate).
  * Configuração remota (página, zoom, atualização, rotação dos voos, kiosk).
  * Comandos remotos (recarregar, identificar, captura de ecrã, limpar cache,
    reiniciar aplicação, alterar código, reiniciar televisor).
  * Descoberta automática na rede (UDP broadcast, porta 47800).

Usa apenas a biblioteca padrão do Python 3.8+ (sem instalações adicionais).
Execução:  python adm_kiosk_server.py [--port 8080]
"""

import argparse
import csv
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.4.2"
if getattr(sys, "frozen", False):
    # Executável (PyInstaller): o painel vem embutido; os dados ficam ao lado do .exe.
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    STATIC_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "static")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
SHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
DB_PATH = os.path.join(DATA_DIR, "adm_kiosk.db")

DISCOVERY_PORT = 47800
AGENT_PORT = 47801          # os agentes escutam aqui os anúncios do servidor
DISCOVER_MSG = b"ADM-KIOSK-DISCOVER"
ANNOUNCE_PREFIX = b"ADM-KIOSK-ANNOUNCE "
ONLINE_WINDOW_S = 35          # sem heartbeat há mais de 35 s = offline
COMMAND_EXPIRY_S = 600        # comandos pendentes expiram ao fim de 10 min
SESSION_TTL_S = 12 * 3600
DEFAULT_PASSWORD = "admin"

TERMINALS = {"DPT": "DPT - Doméstico", "IPT": "IPT - Internacional"}
SCREEN_TYPES = {"FIDS_DEP": "FIDS Partidas", "FIDS_ARR": "FIDS Chegadas", "GATE": "Gate"}
PLATFORMS = {
    "android": "Smart TV / Android",
    "windows": "Computador / Netbox (Windows)",
    "linux": "Computador / Netbox (Linux)",
}
# Comandos aplicáveis a cada plataforma (nome apresentado no painel).
COMMANDS = {
    "reload": "Recarregar página",
    "identify": "Identificar no ecrã",
    "screenshot": "Captura de ecrã",
    "clear_cache": "Limpar cache",
    "restart_app": "Reiniciar aplicação/navegador",
    "set_pin": "Alterar código de acesso",
    "reboot": "Forçar reinício",
}
COMMANDS_BY_PLATFORM = {
    "android": ["reload", "identify", "screenshot", "clear_cache", "restart_app", "set_pin", "reboot"],
    "windows": ["reload", "identify", "screenshot", "clear_cache", "restart_app", "reboot"],
    "linux": ["reload", "identify", "screenshot", "clear_cache", "restart_app", "reboot"],
}
LIVE_MAX_S = 600              # uma sessão ao vivo dura no máximo 10 min sem renovação
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

CONFIG_FIELDS = {
    # campo: (tipo, mínimo, máximo)
    "name": (str, 0, 80),
    "location": (str, 0, 120),
    "notes": (str, 0, 500),
    "terminal": (str, 0, 8),
    "screen_type": (str, 0, 16),
    "gate": (str, 0, 16),
    "url": (str, 0, 1000),
    "zoom": (int, 25, 400),
    "refresh_seconds": (int, 0, 86400),
    "auto_scroll": (bool, 0, 1),
    "auto_scroll_seconds": (int, 3, 300),
    "kiosk_enabled": (bool, 0, 1),
    "reload_on_error": (bool, 0, 1),
    "retry_delay_seconds": (int, 3, 300),
    "browser": (str, 0, 16),
}
BROWSERS = {
    "": "Automático", "edge": "Microsoft Edge", "chrome": "Google Chrome",
    "chromium": "Chromium", "firefox": "Mozilla Firefox",
}


# --------------------------------------------------------------------------- #
# Base de dados
# --------------------------------------------------------------------------- #

class Database:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self):
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices(
                    id TEXT PRIMARY KEY,
                    name TEXT DEFAULT '', location TEXT DEFAULT '', notes TEXT DEFAULT '',
                    terminal TEXT DEFAULT '', screen_type TEXT DEFAULT '', gate TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    zoom INTEGER DEFAULT 100, refresh_seconds INTEGER DEFAULT 0,
                    auto_scroll INTEGER DEFAULT 1, auto_scroll_seconds INTEGER DEFAULT 10,
                    kiosk_enabled INTEGER DEFAULT 1, reload_on_error INTEGER DEFAULT 1,
                    retry_delay_seconds INTEGER DEFAULT 10,
                    config_version INTEGER DEFAULT 0, applied_version INTEGER DEFAULT 0,
                    info TEXT DEFAULT '{}', seen_ip TEXT DEFAULT '',
                    first_seen REAL DEFAULT 0, last_seen REAL DEFAULT 0, shot_ts REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS profiles(
                    terminal TEXT, screen_type TEXT, url TEXT DEFAULT '',
                    PRIMARY KEY(terminal, screen_type)
                );
                CREATE TABLE IF NOT EXISTS commands(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT, type TEXT, payload TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'pending', message TEXT DEFAULT '',
                    created REAL, updated REAL
                );
                CREATE INDEX IF NOT EXISTS ix_cmd_dev ON commands(device_id, status);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, device_id TEXT DEFAULT '', level TEXT DEFAULT 'info', message TEXT
                );
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
                """
            )
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(devices)")}
            for name, ddl in (
                ("platform", "TEXT DEFAULT 'android'"),
                ("browser", "TEXT DEFAULT ''"),
                ("live_until", "REAL DEFAULT 0"),
                ("live_interval", "INTEGER DEFAULT 100"),
                ("live_quality", "TEXT DEFAULT 'normal'"),
            ):
                if name not in cols:
                    self.conn.execute(f"ALTER TABLE devices ADD COLUMN {name} {ddl}")
            for t in TERMINALS:
                for s in SCREEN_TYPES:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO profiles(terminal, screen_type, url) VALUES(?,?,'')",
                        (t, s),
                    )

    def query(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def execute(self, sql, args=()):
        with self.lock, self.conn:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid

    def get_setting(self, key, default=None):
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    def set_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, value))

    def event(self, message, device_id="", level="info"):
        self.execute(
            "INSERT INTO events(ts, device_id, level, message) VALUES(?,?,?,?)",
            (time.time(), device_id, level, message),
        )


DB = None  # type: Database


# --------------------------------------------------------------------------- #
# Autenticação do administrador
# --------------------------------------------------------------------------- #

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


def ensure_admin_password():
    if DB.get_setting("admin_hash") is None:
        salt, digest = hash_password(DEFAULT_PASSWORD)
        DB.set_setting("admin_salt", salt)
        DB.set_setting("admin_hash", digest)
        DB.set_setting("must_change", "1")


def verify_password(password):
    salt = DB.get_setting("admin_salt")
    expected = DB.get_setting("admin_hash")
    if not salt or not expected:
        return False
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, expected)


SESSIONS = {}
SESSIONS_LOCK = threading.Lock()

# Eventos de controlo remoto (rato/teclado) à espera de serem recolhidos pelo equipamento.
INPUTS = {}
INPUTS_LOCK = threading.Lock()
INPUT_TYPES = {"click", "dblclick", "rightclick", "move", "down", "up", "scroll", "key", "text"}
LIVE_QUALITIES = {"low", "normal", "high"}

# Últimas imagens da sessão ao vivo, mantidas em memória e enviadas em fluxo (MJPEG) ao navegador.
FRAMES = {}                   # dev_id -> {"seq", "data", "ts", "stamps"}
FRAMES_COND = threading.Condition()
FRAME_DISK_EVERY_S = 3        # a imagem em disco (mural/captura) é atualizada no máximo a cada 3 s
# Último contacto do equipamento durante a sessão ao vivo e o motivo indicado quando não há imagem
# (ex.: "noscreen" = o ecrã ADM Kiosk não está à frente na TV; "capture" = falha a capturar).
LIVE_CONTACT = {}             # dev_id -> {"ts", "status"}

# Canal de espera: o equipamento mantém um pedido aberto e é acordado de imediato quando há
# sessão ao vivo, comando ou configuração nova (sem esperar pelo próximo heartbeat).
WAKE_GEN = {}
WAKE_COND = threading.Condition()
WAIT_TIMEOUT_S = 25


def wake(dev_id):
    with WAKE_COND:
        WAKE_GEN[dev_id] = WAKE_GEN.get(dev_id, 0) + 1
        WAKE_COND.notify_all()


def wait_wake(dev_id, known_gen, timeout):
    with WAKE_COND:
        WAKE_COND.wait_for(lambda: WAKE_GEN.get(dev_id, 0) != known_gen, timeout)
        return WAKE_GEN.get(dev_id, 0)


def store_frame(dev_id, data):
    now = time.time()
    with FRAMES_COND:
        f = FRAMES.setdefault(dev_id, {"seq": 0, "data": b"", "ts": 0.0, "stamps": [], "disk": 0.0})
        f["seq"] += 1
        f["data"] = data
        f["ts"] = now
        f["stamps"] = [t for t in f["stamps"] if now - t < 2.0] + [now]
        write_disk = now - f["disk"] >= FRAME_DISK_EVERY_S
        if write_disk:
            f["disk"] = now
        FRAMES_COND.notify_all()
    if write_disk:
        with open(os.path.join(SHOTS_DIR, dev_id + ".jpg"), "wb") as fh:
            fh.write(data)
        DB.execute("UPDATE devices SET shot_ts=?, last_seen=? WHERE id=?", (now, now, dev_id))


def live_fps(dev_id):
    with FRAMES_COND:
        f = FRAMES.get(dev_id)
        if not f:
            return 0.0
        now = time.time()
        recent = [t for t in f["stamps"] if now - t < 2.0]
        return round(len(recent) / 2.0, 1)
LOGIN_FAILS = {}  # ip -> (falhas, bloqueado_até)


def new_session():
    token = secrets.token_urlsafe(32)
    with SESSIONS_LOCK:
        SESSIONS[token] = time.time() + SESSION_TTL_S
    return token


def valid_session(token):
    if not token:
        return False
    with SESSIONS_LOCK:
        exp = SESSIONS.get(token)
        if exp is None:
            return False
        if exp < time.time():
            SESSIONS.pop(token, None)
            return False
        SESSIONS[token] = time.time() + SESSION_TTL_S
        return True


# --------------------------------------------------------------------------- #
# Lógica dos televisores
# --------------------------------------------------------------------------- #

def profiles_map():
    return {(p["terminal"], p["screen_type"]): p["url"] for p in DB.query("SELECT * FROM profiles")}


def effective_url(dev, profiles=None):
    if dev.get("url"):
        return dev["url"]
    profiles = profiles if profiles is not None else profiles_map()
    url = profiles.get((dev.get("terminal", ""), dev.get("screen_type", "")), "")
    if not url:
        return ""
    return url.replace("{gate}", dev.get("gate") or "").replace("{name}", dev.get("name") or "")


def build_config(dev, profiles=None):
    return {
        "version": dev["config_version"],
        "name": dev["name"],
        "terminal": dev["terminal"],
        "screenType": dev["screen_type"],
        "gate": dev["gate"],
        "url": effective_url(dev, profiles),
        "zoom": dev["zoom"],
        "refreshSeconds": dev["refresh_seconds"],
        "autoScroll": bool(dev["auto_scroll"]),
        "autoScrollSeconds": dev["auto_scroll_seconds"],
        "kioskEnabled": bool(dev["kiosk_enabled"]),
        "reloadOnError": bool(dev["reload_on_error"]),
        "retryDelaySeconds": dev["retry_delay_seconds"],
        "browser": dev.get("browser") or "",
    }


def live_info(dev, now=None):
    now = now or time.time()
    active = (dev.get("live_until") or 0) > now
    return {
        "active": active,
        "intervalMs": int(dev.get("live_interval") or 100),
        "quality": dev.get("live_quality") or "normal",
    }


def is_online(dev, now=None):
    return (now or time.time()) - (dev.get("last_seen") or 0) <= ONLINE_WINDOW_S


def device_label(dev):
    if dev.get("name"):
        return dev["name"]
    prefix = "TV" if (dev.get("platform") or "android") == "android" else "PC"
    return f"{prefix} {dev['id'][-8:].upper()}"


def live_support(platform, device):
    """'full' = tempo real; 'slow' = versão antiga (cerca de 1 imagem/s, sem arrastar); 'none' = sem ao vivo."""
    if platform == "android":
        code = int(device.get("appVersionCode") or 0)
        return "full" if code >= 13 else "slow" if code == 12 else "none"
    if platform == "windows":
        m = re.search(r"(\d+)\.(\d+)", str(device.get("appVersion") or ""))
        return "full" if m and (int(m.group(1)), int(m.group(2))) >= (2, 2) else "slow"
    return "full"


def device_public(dev, profiles=None, detail=False):
    info = json.loads(dev.get("info") or "{}")
    now = time.time()
    d = {k: dev[k] for k in (
        "id", "name", "location", "notes", "terminal", "screen_type", "gate", "url", "zoom",
        "refresh_seconds", "auto_scroll", "auto_scroll_seconds", "kiosk_enabled",
        "reload_on_error", "retry_delay_seconds", "config_version", "applied_version",
        "seen_ip", "first_seen", "last_seen", "shot_ts", "platform", "browser",
        "live_until", "live_interval",
    )}
    d["platform"] = d["platform"] or "android"
    d["live"] = live_info(dev, now)["active"]
    d["live_fps"] = live_fps(dev["id"]) if d["live"] else 0.0
    d["live_quality"] = dev.get("live_quality") or "normal"
    d["live_support"] = live_support(d["platform"], info.get("device", {}))
    contact = LIVE_CONTACT.get(dev["id"]) or {}
    d["live_contact_age"] = round(now - contact["ts"], 1) if contact else None
    d["live_status"] = contact.get("status", "")
    d["allowed_commands"] = COMMANDS_BY_PLATFORM.get(d["platform"], list(COMMANDS))
    for b in ("auto_scroll", "kiosk_enabled", "reload_on_error"):
        d[b] = bool(d[b])
    d["label"] = device_label(dev)
    d["online"] = is_online(dev, now)
    d["effective_url"] = effective_url(dev, profiles)
    d["config_applied"] = dev["config_version"] == 0 or dev["applied_version"] == dev["config_version"]
    d["device"] = info.get("device", {})
    d["network"] = info.get("network", {})
    d["state"] = info.get("state", {})
    if detail:
        d["commands"] = DB.query(
            "SELECT * FROM commands WHERE device_id=? ORDER BY id DESC LIMIT 30", (dev["id"],)
        )
    return d


def bump_version(dev_id):
    DB.execute(
        "UPDATE devices SET config_version = MAX(config_version, applied_version) + 1 WHERE id=?",
        (dev_id,),
    )
    wake(dev_id)


def clean_config(fields):
    """Valida os campos de configuração recebidos do administrador."""
    out = {}
    for key, value in fields.items():
        if key not in CONFIG_FIELDS:
            continue
        kind, lo, hi = CONFIG_FIELDS[key]
        if kind is str:
            v = str(value or "").strip()[:hi]
            if key == "terminal" and v and v not in TERMINALS:
                raise ValueError("Terminal inválido")
            if key == "screen_type" and v and v not in SCREEN_TYPES:
                raise ValueError("Tipo de ecrã inválido")
            if key == "browser" and v not in BROWSERS:
                raise ValueError("Navegador inválido")
            if key == "url" and v and not re.match(r"^https?://", v, re.I):
                v = "http://" + v
            out[key] = v
        elif kind is bool:
            out[key] = 1 if value in (True, 1, "1", "true", "on") else 0
        else:
            try:
                v = int(value)
            except (TypeError, ValueError):
                raise ValueError("Valor inválido para " + key)
            out[key] = max(lo, min(hi, v))
    return out


def update_device_config(dev_id, fields):
    data = clean_config(fields)
    if not data:
        return False
    sets = ", ".join(f"{k}=?" for k in data)
    DB.execute(f"UPDATE devices SET {sets} WHERE id=?", (*data.values(), dev_id))
    bump_version(dev_id)
    return True


def queue_command(dev_id, ctype, payload):
    if ctype not in COMMANDS:
        raise ValueError("Comando inválido")
    dev = DB.one("SELECT platform FROM devices WHERE id=?", (dev_id,))
    platform = (dev or {}).get("platform") or "android"
    if ctype not in COMMANDS_BY_PLATFORM.get(platform, []):
        raise ValueError(f"'{COMMANDS[ctype]}' não está disponível para {PLATFORMS.get(platform, platform)}")
    if ctype == "set_pin":
        pin = str(payload.get("pin", ""))
        if not re.fullmatch(r"\d{4}", pin):
            raise ValueError("O código deve ter 4 dígitos")
    now = time.time()
    cid = DB.execute(
        "INSERT INTO commands(device_id, type, payload, status, created, updated) VALUES(?,?,?,?,?,?)",
        (dev_id, ctype, json.dumps(payload or {}), "pending", now, now),
    )
    wake(dev_id)
    return cid


def handle_heartbeat(body, client_ip):
    dev_id = str(body.get("id", "")).strip()
    if not ID_RE.match(dev_id):
        raise ValueError("ID inválido")
    now = time.time()
    s = body.get("settings") or {}
    info = json.dumps({
        "device": body.get("device") or {},
        "network": body.get("network") or {},
        "state": body.get("state") or {},
        "settings": s,
    })
    applied = int(body.get("configVersion") or 0)
    platform = body.get("platform") if body.get("platform") in PLATFORMS else "android"
    dev = DB.one("SELECT * FROM devices WHERE id=?", (dev_id,))
    if dev is None:
        terminal = s.get("terminal") if s.get("terminal") in TERMINALS else ""
        stype = s.get("screenType") if s.get("screenType") in SCREEN_TYPES else ""
        DB.execute(
            """INSERT INTO devices(id, name, terminal, screen_type, gate, zoom, refresh_seconds,
                   auto_scroll, auto_scroll_seconds, kiosk_enabled, reload_on_error,
                   retry_delay_seconds, config_version, applied_version, info, seen_ip,
                   first_seen, last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
            (
                dev_id, str(s.get("name", ""))[:80], terminal, stype, str(s.get("gate", ""))[:16],
                int(s.get("zoom", 100) or 100), int(s.get("refreshSeconds", 0) or 0),
                1 if s.get("autoScroll", True) else 0, int(s.get("autoScrollSeconds", 10) or 10),
                1 if s.get("kioskEnabled", True) else 0, 1 if s.get("reloadOnError", True) else 0,
                int(s.get("retryDelaySeconds", 10) or 10), applied, info, client_ip, now, now,
            ),
        )
        DB.execute(
            "UPDATE devices SET platform=?, browser=? WHERE id=?",
            (platform, str(s.get("browser", ""))[:16] if s.get("browser", "") in BROWSERS else "", dev_id),
        )
        net = (body.get("network") or {}).get("ip") or client_ip
        DB.event(f"Novo equipamento registado: {PLATFORMS[platform]} (IP {net})", dev_id)
    else:
        if not is_online(dev, now):
            DB.event(f"{device_label(dev)} voltou a comunicar", dev_id)
        if applied and applied == dev["config_version"] and dev["applied_version"] != applied:
            DB.event(f"{device_label(dev)} aplicou a configuração v{applied}", dev_id)
        DB.execute(
            "UPDATE devices SET info=?, seen_ip=?, last_seen=?, applied_version=?, platform=? WHERE id=?",
            (info, client_ip, now, applied, platform, dev_id),
        )
    dev = DB.one("SELECT * FROM devices WHERE id=?", (dev_id,))

    with DB.lock:
        pending = DB.query(
            "SELECT id, type, payload FROM commands WHERE device_id=? AND status='pending' ORDER BY id",
            (dev_id,),
        )
        for c in pending:
            DB.execute("UPDATE commands SET status='sent', updated=? WHERE id=?", (now, c["id"]))
    commands = [{"id": c["id"], "type": c["type"], "payload": json.loads(c["payload"] or "{}")}
                for c in pending]
    return {"config": build_config(dev), "commands": commands, "live": live_info(dev, now), "serverTime": now}


def handle_command_result(body):
    dev_id = str(body.get("id", ""))
    cid = int(body.get("commandId") or 0)
    ok = bool(body.get("ok"))
    msg = str(body.get("message", ""))[:300]
    DB.execute(
        "UPDATE commands SET status=?, message=?, updated=? WHERE id=? AND device_id=?",
        ("ok" if ok else "failed", msg, time.time(), cid, dev_id),
    )


def watchdog_loop():
    """Regista quedas de comunicação e expira comandos antigos."""
    known_online = set()
    while True:
        try:
            now = time.time()
            for dev in DB.query("SELECT id, name, platform, last_seen FROM devices"):
                online = is_online(dev, now)
                if online:
                    known_online.add(dev["id"])
                elif dev["id"] in known_online:
                    known_online.discard(dev["id"])
                    DB.event(f"{device_label(dev)} deixou de comunicar", dev["id"], "warn")
            DB.execute(
                "UPDATE commands SET status='expired', updated=? WHERE status IN ('pending','sent') AND created < ?",
                (now, now - COMMAND_EXPIRY_S),
            )
        except Exception as exc:  # pragma: no cover - nunca deixar a thread morrer
            print("watchdog:", exc, file=sys.stderr)
        time.sleep(10)


# --------------------------------------------------------------------------- #
# Descoberta automática (UDP)
# --------------------------------------------------------------------------- #

def local_ip_for(peer):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((peer, 9))
            return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def local_addresses():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    # Sem Internet, a rota para 8.8.8.8 pode não existir. Uma ligação UDP
    # (sem enviar dados) a um endereço da própria rede revela o IP local.
    for probe in ("8.8.8.8", "10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            ips.add(local_ip_for(probe))
        except OSError:
            pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


class Net:
    """
    Estado da rede do servidor; alterável no painel (Definições > Endereço do servidor).
    Portas acrescentadas no painel somam-se às anteriores, que continuam ativas.
    """
    host = "0.0.0.0"
    servers = {}          # porta -> servidor HTTP ativo
    main_port = 0         # porta anunciada aos equipamentos
    cli_public_url = ""
    lock = threading.Lock()

    @classmethod
    def port(cls):
        return cls.main_port

    @classmethod
    def ports(cls):
        return sorted(cls.servers, key=lambda p: (p != cls.main_port, p))


def public_address():
    """Endereço anunciado aos equipamentos: '' = automático, IP/nome ou URL completo."""
    return DB.get_setting("public_address", "") or Net.cli_public_url


def announced_url(peer_ip):
    addr = public_address().strip().rstrip("/")
    if re.match(r"^https?://", addr, re.I):
        return addr
    return f"http://{addr or local_ip_for(peer_ip)}:{Net.port()}"


def discovery_enabled():
    return DB.get_setting("discovery", "1") != "0"


def ipv4_networks():
    """Cada interface IPv4 activa: (endereço, broadcast da sub-rede)."""
    if os.name == "nt":
        return _windows_networks()
    return _posix_networks()


def _windows_networks():
    import ctypes
    import struct
    size = ctypes.c_ulong(0)
    ctypes.windll.iphlpapi.GetIpAddrTable(None, ctypes.byref(size), False)
    buf = ctypes.create_string_buffer(size.value or 1)
    if ctypes.windll.iphlpapi.GetIpAddrTable(buf, ctypes.byref(size), False) != 0:
        return []
    count = struct.unpack_from("I", buf.raw, 0)[0]
    found = []
    for i in range(count):
        addr, _index, mask, _bcast, _reasm, _u1, _u2 = struct.unpack_from("IIIIIHH", buf.raw, 4 + i * 24)
        ip = socket.inet_ntoa(struct.pack("<I", addr))
        mk = socket.inet_ntoa(struct.pack("<I", mask))
        if ip.startswith("127.") or ip.startswith("169.254.") or mk in ("0.0.0.0", "255.255.255.255"):
            continue
        ip_n = struct.unpack("!I", socket.inet_aton(ip))[0]
        mk_n = struct.unpack("!I", socket.inet_aton(mk))[0]
        bc = socket.inet_ntoa(struct.pack("!I", (ip_n | (~mk_n & 0xFFFFFFFF)) & 0xFFFFFFFF))
        found.append((ip, bc))
    return found


def _posix_networks():
    import fcntl
    import struct
    found = []
    try:
        names = os.listdir("/sys/class/net")
    except OSError:
        return found
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in names:
            ifreq = struct.pack("256s", name.encode()[:15])
            try:
                flags = struct.unpack("H", fcntl.ioctl(sock.fileno(), 0x8913, ifreq)[16:18])[0]
                if not (flags & 1):
                    continue
                ip = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8915, ifreq)[20:24])
                bc = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8919, ifreq)[20:24])
            except OSError:
                continue
            if ip.startswith("127.") or bc.startswith("127."):
                continue
            found.append((ip, bc))
    finally:
        sock.close()
    return found


def _url_on(local_ip):
    addr = public_address().strip().rstrip("/")
    if re.match(r"^https?://", addr, re.I):
        return addr
    if addr:
        return f"http://{addr}:{Net.port()}"
    return f"http://{local_ip}:{Net.port()}"


def _send_announce(local_ip, dest, packet):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind((local_ip, 0))
        except OSError:
            pass
        sock.sendto(packet, (dest, AGENT_PORT))
    except OSError:
        pass
    finally:
        sock.close()


def announce_once():
    """Diz a todos os agentes da rede onde está o painel, em cada interface."""
    if not discovery_enabled() or not Net.port():
        return
    sent_global = False
    for local_ip, broadcast in ipv4_networks():
        packet = ANNOUNCE_PREFIX + json.dumps({
            "server": _url_on(local_ip), "name": "ADM Kiosk Admin", "version": VERSION,
        }).encode("utf-8")
        _send_announce(local_ip, broadcast, packet)
        if not sent_global:
            _send_announce(local_ip, "255.255.255.255", packet)
            sent_global = True


def announce_loop():
    while True:
        try:
            announce_once()
        except Exception as exc:  # pragma: no cover
            print("[descoberta]", exc, file=sys.stderr)
        time.sleep(4)


def allow_udp_firewall(port):
    if os.name != "nt":
        return
    import subprocess
    name = f"ADM Kiosk Servidor (Descoberta UDP {port})"
    try:
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                       capture_output=True, creationflags=0x08000000, timeout=15)
        subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in",
                        "action=allow", "protocol=UDP", f"localport={port}", "profile=any"],
                       capture_output=True, creationflags=0x08000000, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def start_http(port):
    httpd = ThreadingHTTPServer((Net.host, port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    Net.servers[port] = httpd
    allow_port_in_firewall(port)
    return httpd


def all_addresses():
    ips = local_addresses()
    return [f"http://{a}:{p}" for p in Net.ports() for a in ips]


def saved_extra_ports():
    return [int(p) for p in DB.get_setting("extra_ports", "").split(",") if p.strip().isdigit()]


def change_port(new_port):
    """Passa a anunciar a nova porta, sem reiniciar e sem desligar as portas anteriores."""
    with Net.lock:
        if new_port not in Net.servers:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                if probe.connect_ex(("127.0.0.1", new_port)) == 0:
                    raise ApiError(400, f"A porta {new_port} já está a ser usada por outro programa")
            try:
                start_http(new_port)
            except OSError as exc:
                raise ApiError(400, f"Não foi possível usar a porta {new_port}: {exc.strerror or exc}")
            extra = saved_extra_ports()
            if new_port not in extra:
                DB.set_setting("extra_ports", ",".join(str(p) for p in extra + [new_port]))
        Net.main_port = new_port


def allow_port_in_firewall(port):
    """No Windows, com privilégios (servidor instalado), abre a nova porta na firewall."""
    if os.name != "nt":
        return
    import subprocess
    name = f"ADM Kiosk Servidor (HTTP {port})"
    try:
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                       capture_output=True, creationflags=0x08000000, timeout=15)
        subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in",
                        "action=allow", "protocol=TCP", f"localport={port}", "profile=any"],
                       capture_output=True, creationflags=0x08000000, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def discovery_loop():
    allow_udp_firewall(DISCOVERY_PORT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_PORT))
    except OSError as exc:
        print(f"[descoberta] porta UDP {DISCOVERY_PORT} indisponível: {exc}", file=sys.stderr)
        return
    threading.Thread(target=announce_loop, daemon=True).start()
    print(f"[descoberta] a responder em UDP {DISCOVERY_PORT} e a anunciar em UDP {AGENT_PORT}")
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if data.strip() != DISCOVER_MSG or not discovery_enabled():
                continue
            reply = json.dumps({"server": announced_url(addr[0]), "name": "ADM Kiosk Admin", "version": VERSION})
            sock.sendto(reply.encode("utf-8"), addr)
        except Exception as exc:  # pragma: no cover
            print("[descoberta]", exc, file=sys.stderr)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "ADMKioskAdmin/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencia os heartbeats no terminal
        # No pythonw.exe (sem consola) stderr é None. send_response regista o
        # pedido antes de escrever a página; se isto falhar, o navegador fica
        # com "não enviou quaisquer dados" (ERR_EMPTY_RESPONSE).
        if "/api/device/" in (args[0] if args else ""):
            return
        err = sys.stderr
        if err is None:
            return
        try:
            err.write("%s - %s\n" % (self.address_string(), fmt % args))
        except Exception:
            pass

    # ---- utilitários ----

    def send_json(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data, ctype, status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def read_body(self, limit=1_000_000):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ApiError(413, "Pedido demasiado grande")
        return self.rfile.read(length) if length else b""

    def read_json(self):
        raw = self.read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "JSON inválido")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON inválido")
        return data

    def session_token(self):
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "adm_session":
                return v
        return None

    def require_admin(self):
        if not valid_session(self.session_token()):
            raise ApiError(401, "Sessão expirada. Inicie sessão novamente.")

    # ---- encaminhamento ----

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/device/"):
                return self.device_api(method, path, query)
            if path.startswith("/api/"):
                return self.admin_api(method, path, query)
            if method == "GET":
                return self.static(path)
            raise ApiError(404, "Não encontrado")
        except ApiError as e:
            self.send_json({"error": e.message}, e.status)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # pragma: no cover
            print("erro:", repr(e), file=sys.stderr)
            self.send_json({"error": "Erro interno do servidor"}, 500)

    def static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "Não encontrado")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self.send_bytes(f.read(), ctype, headers={"Cache-Control": "no-cache"})

    # ---- API dos televisores ----

    def device_api(self, method, path, query):
        if method != "POST":
            raise ApiError(405, "Método não permitido")
        if path == "/api/device/heartbeat":
            return self.send_json(handle_heartbeat(self.read_json(), self.client_address[0]))
        if path == "/api/device/command-result":
            handle_command_result(self.read_json())
            return self.send_json({"ok": True})
        if path == "/api/device/frame":
            # Imagem da sessão ao vivo; a resposta devolve os eventos de rato/teclado pendentes.
            dev_id = (query.get("id") or [""])[0]
            dev = DB.one("SELECT * FROM devices WHERE id=?", (dev_id,)) if ID_RE.match(dev_id) else None
            if not dev:
                raise ApiError(404, "Equipamento desconhecido")
            data = self.read_body(limit=8_000_000)
            # Corpo vazio = ecrã sem alterações (o equipamento só recolhe os eventos de controlo).
            if data.startswith(b"\xff\xd8"):
                store_frame(dev_id, data)
            status = re.sub(r"[^a-z_]", "", (query.get("status") or [""])[0])[:20]
            LIVE_CONTACT[dev_id] = {"ts": time.time(), "status": status}
            with INPUTS_LOCK:
                events = INPUTS.pop(dev_id, [])
            return self.send_json({"live": live_info(dev), "inputs": events})
        if path == "/api/device/wait":
            dev_id = (query.get("id") or [""])[0]
            if not ID_RE.match(dev_id):
                raise ApiError(404, "Equipamento desconhecido")
            self.read_body()
            known = int((query.get("gen") or ["-1"])[0] or -1)
            gen = wait_wake(dev_id, known, WAIT_TIMEOUT_S)
            dev = DB.one("SELECT * FROM devices WHERE id=?", (dev_id,))
            live = live_info(dev) if dev else {"active": False, "intervalMs": 100, "quality": "normal"}
            return self.send_json({"gen": gen, "wake": gen != known, "live": live})
        if path == "/api/device/screenshot":
            dev_id = (query.get("id") or [""])[0]
            cid = int((query.get("cmd") or ["0"])[0] or 0)
            if not ID_RE.match(dev_id) or not DB.one("SELECT id FROM devices WHERE id=?", (dev_id,)):
                raise ApiError(404, "Equipamento desconhecido")
            data = self.read_body(limit=8_000_000)
            if not data.startswith(b"\xff\xd8"):
                raise ApiError(400, "Imagem inválida")
            with open(os.path.join(SHOTS_DIR, dev_id + ".jpg"), "wb") as f:
                f.write(data)
            now = time.time()
            DB.execute("UPDATE devices SET shot_ts=? WHERE id=?", (now, dev_id))
            if cid:
                DB.execute(
                    "UPDATE commands SET status='ok', message='Captura recebida', updated=? WHERE id=?",
                    (now, cid),
                )
            return self.send_json({"ok": True})
        raise ApiError(404, "Não encontrado")

    # ---- API do administrador ----

    def admin_api(self, method, path, query):
        ip = self.client_address[0]

        if path == "/api/login" and method == "POST":
            fails, until = LOGIN_FAILS.get(ip, (0, 0))
            if until > time.time():
                raise ApiError(429, "Demasiadas tentativas. Aguarde 1 minuto.")
            body = self.read_json()
            if not verify_password(str(body.get("password", ""))):
                fails += 1
                LOGIN_FAILS[ip] = (0, time.time() + 60) if fails >= 5 else (fails, 0)
                DB.event(f"Tentativa de acesso falhada ({ip})", level="warn")
                raise ApiError(401, "Palavra-passe incorreta")
            LOGIN_FAILS.pop(ip, None)
            token = new_session()
            DB.event(f"Sessão iniciada ({ip})")
            return self.send_json(
                {"ok": True, "mustChange": DB.get_setting("must_change") == "1"},
                headers={"Set-Cookie": f"adm_session={token}; HttpOnly; SameSite=Strict; Path=/"},
            )

        if path == "/api/logout" and method == "POST":
            with SESSIONS_LOCK:
                SESSIONS.pop(self.session_token() or "", None)
            return self.send_json(
                {"ok": True},
                headers={"Set-Cookie": "adm_session=; Max-Age=0; Path=/"},
            )

        if path == "/api/me" and method == "GET":
            ok = valid_session(self.session_token())
            return self.send_json({
                "authenticated": ok,
                "mustChange": ok and DB.get_setting("must_change") == "1",
            })

        self.require_admin()

        if path == "/api/password" and method == "POST":
            body = self.read_json()
            if not verify_password(str(body.get("current", ""))):
                raise ApiError(400, "Palavra-passe atual incorreta")
            new = str(body.get("new", ""))
            if len(new) < 6:
                raise ApiError(400, "A nova palavra-passe deve ter pelo menos 6 caracteres")
            salt, digest = hash_password(new)
            DB.set_setting("admin_salt", salt)
            DB.set_setting("admin_hash", digest)
            DB.set_setting("must_change", "0")
            DB.event("Palavra-passe do administrador alterada")
            return self.send_json({"ok": True})

        if path == "/api/meta" and method == "GET":
            port = self.server.server_address[1]
            return self.send_json({
                "version": VERSION,
                "terminals": TERMINALS,
                "screenTypes": SCREEN_TYPES,
                "platforms": PLATFORMS,
                "browsers": BROWSERS,
                "commands": COMMANDS,
                "addresses": all_addresses() or [f"http://{a}:{port}" for a in local_addresses()],
                "discoveryPort": DISCOVERY_PORT,
                "onlineWindow": ONLINE_WINDOW_S,
            })

        if path == "/api/server-settings":
            if method == "PUT":
                body = self.read_json()
                addr = str(body.get("publicAddress", "")).strip().rstrip("/")[:200]
                if addr and not re.fullmatch(r"(https?://)?[A-Za-z0-9._\-\[\]:]+(/[^\s]*)?", addr):
                    raise ApiError(400, "Endereço inválido (ex.: 192.168.1.7 ou http://servidor:8080)")
                try:
                    port = int(body.get("port") or Net.port())
                except (TypeError, ValueError):
                    raise ApiError(400, "Porta inválida")
                if not 1 <= port <= 65535:
                    raise ApiError(400, "A porta deve estar entre 1 e 65535")
                old_port = Net.port()
                change_port(port)
                DB.set_setting("public_address", addr)
                DB.set_setting("discovery", "1" if body.get("discovery", True) else "0")
                DB.set_setting("http_port", str(port))
                changes = [f"endereço anunciado: {addr or 'automático'}",
                           f"descoberta {'ativa' if discovery_enabled() else 'desativada'}"]
                if port != old_port:
                    changes.append(f"porta principal {old_port} → {port} (a {old_port} continua ativa)")
                DB.event("Endereço do servidor alterado (" + ", ".join(changes) + ")")
            return self.send_json({
                "publicAddress": DB.get_setting("public_address", ""),
                "cliPublicUrl": Net.cli_public_url,
                "port": Net.port(),
                "discovery": discovery_enabled(),
                "os": "windows" if os.name == "nt" else "linux",
                "addresses": all_addresses(),
                "ports": Net.ports(),
                "localIps": local_addresses(),
            })

        if path == "/api/devices" and method == "GET":
            profiles = profiles_map()
            devs = DB.query("SELECT * FROM devices ORDER BY terminal, screen_type, gate, name, id")
            return self.send_json({"devices": [device_public(d, profiles) for d in devs], "now": time.time()})

        if path == "/api/devices/bulk-config" and method == "POST":
            body = self.read_json()
            ids = [i for i in body.get("ids", []) if ID_RE.match(str(i))]
            fields = body.get("fields") or {}
            for dev_id in ids:
                update_device_config(dev_id, fields)
            DB.event(f"Configuração em massa aplicada a {len(ids)} equipamento(s)")
            return self.send_json({"ok": True, "count": len(ids)})

        if path == "/api/commands/bulk" and method == "POST":
            body = self.read_json()
            ids = [i for i in body.get("ids", []) if ID_RE.match(str(i))]
            ctype = str(body.get("type", ""))
            sent = skipped = 0
            for dev_id in ids:
                try:
                    queue_command(dev_id, ctype, body.get("payload") or {})
                    sent += 1
                except ValueError:
                    skipped += 1
            DB.event(f"Comando '{COMMANDS.get(ctype, ctype)}' enviado a {sent} equipamento(s)")
            return self.send_json({"ok": True, "count": sent, "skipped": skipped})

        m = re.fullmatch(r"/api/devices/([A-Za-z0-9_-]{1,64})(/commands|/live|/input)?", path)
        if m:
            dev_id, sub = m.group(1), m.group(2)
            dev = DB.one("SELECT * FROM devices WHERE id=?", (dev_id,))
            if not dev:
                raise ApiError(404, "Equipamento não encontrado")
            if sub == "/live" and method == "POST":
                body = self.read_json()
                seconds = max(0, min(LIVE_MAX_S, int(body.get("seconds") or 0)))
                interval = max(50, min(5000, int(body.get("intervalMs") or 100)))
                quality = body.get("quality") if body.get("quality") in LIVE_QUALITIES else "normal"
                was_live = live_info(dev)["active"]
                DB.execute(
                    "UPDATE devices SET live_until=?, live_interval=?, live_quality=? WHERE id=?",
                    (time.time() + seconds if seconds else 0, interval, quality, dev_id),
                )
                wake(dev_id)
                if seconds and not was_live:
                    LIVE_CONTACT.pop(dev_id, None)
                    DB.event(f"Sessão ao vivo iniciada em {device_label(dev)} ({ip})", dev_id)
                elif not seconds and was_live:
                    DB.event(f"Sessão ao vivo terminada em {device_label(dev)}", dev_id)
                    with INPUTS_LOCK:
                        INPUTS.pop(dev_id, None)
                return self.send_json({"ok": True, "live": seconds > 0})
            if sub == "/input" and method == "POST":
                if not live_info(dev)["active"]:
                    raise ApiError(409, "Inicie primeiro a sessão ao vivo")
                events = []
                for ev in (self.read_json().get("events") or [])[:100]:
                    if not isinstance(ev, dict) or ev.get("type") not in INPUT_TYPES:
                        continue
                    clean = {"type": ev["type"]}
                    for k in ("x", "y"):
                        if k in ev:
                            clean[k] = max(0.0, min(1.0, float(ev[k])))
                    if "dy" in ev:
                        clean["dy"] = max(-20, min(20, int(ev["dy"])))
                    if "key" in ev:
                        clean["key"] = str(ev["key"])[:32]
                    if "text" in ev:
                        clean["text"] = str(ev["text"])[:500]
                    if ev.get("button") == "right":
                        clean["button"] = "right"
                    for k in ("ctrl", "alt", "shift"):
                        if ev.get(k):
                            clean[k] = True
                    events.append(clean)
                with INPUTS_LOCK:
                    queue = INPUTS.setdefault(dev_id, [])
                    queue.extend(events)
                    del queue[:-200]
                return self.send_json({"ok": True, "queued": len(events)})
            if sub in ("/live", "/input"):
                raise ApiError(405, "Método não permitido")
            if sub and method == "POST":
                body = self.read_json()
                ctype = str(body.get("type", ""))
                cid = queue_command(dev_id, ctype, body.get("payload") or {})
                DB.event(f"Comando '{COMMANDS.get(ctype, ctype)}' enviado a {device_label(dev)}", dev_id)
                return self.send_json({"ok": True, "id": cid})
            if sub:
                raise ApiError(405, "Método não permitido")
            if method == "GET":
                return self.send_json(device_public(dev, detail=True))
            if method == "PUT":
                update_device_config(dev_id, self.read_json())
                dev = DB.one("SELECT * FROM devices WHERE id=?", (dev_id,))
                DB.event(f"Configuração de {device_label(dev)} alterada (v{dev['config_version']})", dev_id)
                return self.send_json(device_public(dev, detail=True))
            if method == "DELETE":
                DB.execute("DELETE FROM devices WHERE id=?", (dev_id,))
                DB.execute("DELETE FROM commands WHERE device_id=?", (dev_id,))
                shot = os.path.join(SHOTS_DIR, dev_id + ".jpg")
                if os.path.exists(shot):
                    os.remove(shot)
                DB.event(f"{device_label(dev)} removido do inventário", dev_id, "warn")
                return self.send_json({"ok": True})

        m = re.fullmatch(r"/api/live/([A-Za-z0-9_-]{1,64})\.mjpg", path)
        if m and method == "GET":
            return self.stream_mjpeg(m.group(1))

        m = re.fullmatch(r"/api/screenshots/([A-Za-z0-9_-]{1,64})\.jpg", path)
        if m and method == "GET":
            full = os.path.join(SHOTS_DIR, m.group(1) + ".jpg")
            if not os.path.isfile(full):
                raise ApiError(404, "Sem captura")
            with open(full, "rb") as f:
                return self.send_bytes(f.read(), "image/jpeg", headers={"Cache-Control": "no-store"})

        if path == "/api/profiles":
            if method == "GET":
                profiles = DB.query("SELECT * FROM profiles ORDER BY terminal, screen_type")
                for p in profiles:
                    p["devices"] = DB.one(
                        "SELECT COUNT(*) AS n FROM devices WHERE terminal=? AND screen_type=? AND url=''",
                        (p["terminal"], p["screen_type"]),
                    )["n"]
                return self.send_json({"profiles": profiles})
            if method == "PUT":
                body = self.read_json()
                changed = 0
                for item in body.get("profiles", []):
                    t, s = item.get("terminal"), item.get("screen_type")
                    if t not in TERMINALS or s not in SCREEN_TYPES:
                        continue
                    url = str(item.get("url", "")).strip()[:1000]
                    if url and not re.match(r"^https?://", url, re.I):
                        url = "http://" + url
                    old = DB.one("SELECT url FROM profiles WHERE terminal=? AND screen_type=?", (t, s))
                    if old and old["url"] == url:
                        continue
                    DB.execute("UPDATE profiles SET url=? WHERE terminal=? AND screen_type=?", (url, t, s))
                    for d in DB.query(
                        "SELECT id FROM devices WHERE terminal=? AND screen_type=? AND url=''", (t, s)
                    ):
                        bump_version(d["id"])
                        changed += 1
                DB.event(f"Páginas por tipo de ecrã atualizadas ({changed} equipamento(s) afetados)")
                return self.send_json({"ok": True, "devices": changed})

        if path == "/api/events" and method == "GET":
            limit = max(1, min(1000, int((query.get("limit") or ["200"])[0])))
            dev = (query.get("device") or [""])[0]
            if dev:
                rows = DB.query("SELECT * FROM events WHERE device_id=? ORDER BY id DESC LIMIT ?", (dev, limit))
            else:
                rows = DB.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
            names = {d["id"]: device_label(d) for d in DB.query("SELECT id, name, platform FROM devices")}
            for r in rows:
                r["device"] = names.get(r["device_id"], "")
            return self.send_json({"events": rows})

        if path == "/api/export.csv" and method == "GET":
            return self.export_csv()

        raise ApiError(404, "Não encontrado")

    def stream_mjpeg(self, dev_id):
        """Fluxo contínuo (multipart/x-mixed-replace): cada imagem nova segue de imediato para o navegador."""
        token = self.session_token()
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=admframe")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        last = -1
        started = time.time()
        try:
            while time.time() - started < LIVE_MAX_S + 60:
                with FRAMES_COND:
                    FRAMES_COND.wait_for(lambda: FRAMES.get(dev_id, {}).get("seq", 0) != last, timeout=5)
                    f = FRAMES.get(dev_id)
                    seq, data = (f["seq"], f["data"]) if f else (0, b"")
                if not valid_session(token):
                    break
                if not data:
                    continue
                last = seq
                # Repetir a última imagem quando o ecrã está parado também deteta quem já fechou a janela.
                self.wfile.write(
                    b"--admframe\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(data)
                    + data + b"\r\n"
                )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def export_csv(self):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow([
            "Nome", "Plataforma", "Terminal", "Tipo de ecrã", "Gate", "Localização", "Estado", "IP", "Máscara",
            "Gateway", "DNS", "MAC", "Ligação", "Fabricante", "Modelo", "Android", "Versão app",
            "Resolução", "Página", "Última comunicação", "ID",
        ])
        profiles = profiles_map()
        for d in DB.query("SELECT * FROM devices ORDER BY terminal, screen_type, gate, name"):
            p = device_public(d, profiles)
            n, dv = p["network"], p["device"]
            w.writerow([
                p["label"], PLATFORMS.get(p["platform"], p["platform"]),
                TERMINALS.get(p["terminal"], ""), SCREEN_TYPES.get(p["screen_type"], ""),
                p["gate"], p["location"], "Online" if p["online"] else "Offline",
                n.get("ip", ""), n.get("mask", ""), n.get("gateway", ""), ", ".join(n.get("dns", [])),
                n.get("mac", ""), n.get("transport", ""), dv.get("manufacturer", ""), dv.get("model", ""),
                dv.get("android", ""), dv.get("appVersion", ""), dv.get("resolution", ""),
                p["effective_url"] or p["state"].get("url", ""),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p["last_seen"])) if p["last_seen"] else "",
                p["id"],
            ])
        data = ("\ufeff" + buf.getvalue()).encode("utf-8")
        self.send_bytes(data, "text/csv; charset=utf-8", headers={
            "Content-Disposition": 'attachment; filename="inventario_televisores.csv"',
        })


# --------------------------------------------------------------------------- #

def main(argv=None):
    global DB, DATA_DIR, SHOTS_DIR, DB_PATH
    # pythonw.exe (sem consola) deixa stdout/stderr a None; um print fechava o processo
    # e o navegador recebia a página vazia (ERR_EMPTY_RESPONSE).
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    parser = argparse.ArgumentParser(description="ADM Kiosk - servidor de administração remota")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--public-url", default="", help="URL anunciado aos televisores (opcional)")
    parser.add_argument("--data", default="", help="pasta dos dados (base de dados e capturas)")
    args = parser.parse_args(argv)

    if args.data:
        DATA_DIR = os.path.abspath(args.data)
        SHOTS_DIR = os.path.join(DATA_DIR, "screenshots")
        DB_PATH = os.path.join(DATA_DIR, "adm_kiosk.db")
    os.makedirs(SHOTS_DIR, exist_ok=True)
    DB = Database(DB_PATH)
    ensure_admin_password()

    Net.host = args.host
    Net.cli_public_url = args.public_url.strip().rstrip("/")
    # A porta de arranque fica sempre ativa; as acrescentadas no painel somam-se a ela.
    start_http(args.port)
    for extra in saved_extra_ports():
        if extra not in Net.servers:
            try:
                start_http(extra)
            except OSError as exc:
                print(f" Porta {extra} (acrescentada no painel) indisponível: {exc}", file=sys.stderr)
    saved = DB.get_setting("http_port", "")
    Net.main_port = int(saved) if saved.isdigit() and int(saved) in Net.servers else args.port

    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=discovery_loop, daemon=True).start()

    print("=" * 64)
    print(" ADM Kiosk - Servidor de administração remota v" + VERSION)
    print(" Aeroportos de Moçambique, E.P.  |  Harmonico Lucas")
    print("=" * 64)
    for url in all_addresses():
        print(f" Administração web: {url}")
    print(f" Dados: {DATA_DIR}")
    if DB.get_setting("must_change") == "1":
        print(f" Primeiro acesso: palavra-passe '{DEFAULT_PASSWORD}' (altere-a em Definições)")
    print(" Ctrl+C para terminar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nA terminar…")
    finally:
        for httpd in Net.servers.values():
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    main()
