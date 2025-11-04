#!/usr/bin/env python3
"""
ADM Kiosk - Agente para computadores / netboxes Linux
Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas

- Abre o navegador em modo kiosk (ecrã inteiro) com a página configurada logo que
  a sessão gráfica arranca e volta a abri-lo se for fechado.
- Recarrega a página quando a rede ou o servidor da página volta.
- Regista-se no servidor central de administração (descoberta automática na rede)
  e aplica a configuração e os comandos remotos.
- Permite ver o ecrã em tempo real e controlar o rato e o teclado a partir do
  navegador do administrador.

Requer Python 3.6+ (só biblioteca padrão). Para ver o ecrã: ffmpeg (recomendado)
ou ImageMagick/scrot/grim. Para controlar rato e teclado: xdotool (sessão X11).
"""

import ctypes
import fcntl
import glob
import hashlib
import http.client
import importlib.util
import json
import os
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from collections import deque

AGENT_VERSION = "2.6.0"
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(AGENT_DIR, "agent.json")
STATE_PATH = os.path.join(AGENT_DIR, "state.json")
LOG_PATH = os.path.join(AGENT_DIR, "agent.log")
DISCOVERY_PORT = 47800
AGENT_PORT = 47801
DISCOVER_MSG = b"ADM-KIOSK-DISCOVER"
ANNOUNCE_PREFIX = b"ADM-KIOSK-ANNOUNCE "
HEARTBEAT_S = 10
CHECK_S = 5

os.environ.setdefault("DISPLAY", ":0")
# Sem proxy: um proxy de sistema, sem Internet, impediria as páginas da rede local.
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"
for _proxy in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_proxy, None)
WAYLAND = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
LOG_LINES = deque(maxlen=200)
kiosk_paused = False
APP = None


# --------------------------------------------------------------------------- utilitários

def log(msg):
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        LOG_LINES.append(line)
    except OSError:
        pass


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def run(cmd, timeout=10, data=None):
    """Executa um comando e devolve (código, stdout em bytes)."""
    try:
        p = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, b""


def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def has(tool):
    return shutil.which(tool) is not None


# --------------------------------------------------------------------------- configuração e estado

cfg = read_json(CONFIG_PATH)
_state = read_json(STATE_PATH)
st = {
    "id": _state.get("id", ""),
    "configVersion": int(_state.get("configVersion", 0)),
    "name": _state.get("name", ""),
    "terminal": _state.get("terminal", ""),
    "screenType": _state.get("screenType", ""),
    "gate": _state.get("gate", ""),
    "url": _state.get("url", cfg.get("url", "")),
    "browser": _state.get("browser", cfg.get("browser", "")),
    "zoom": int(_state.get("zoom", cfg.get("zoom", 100))),
    "refreshSeconds": int(_state.get("refreshSeconds", 0)),
    "kioskEnabled": bool(_state.get("kioskEnabled", True)),
    "reloadOnError": bool(_state.get("reloadOnError", True)),
    "retryDelaySeconds": int(_state.get("retryDelaySeconds", 10)),
}
def normalize_server(url):
    """Aceita "192.168.1.3", "192.168.1.3:8080" ou "http://..."; sem porta assume a 8080 do servidor."""
    url = str(url or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    try:
        u = urllib.parse.urlsplit(url)
        if u.port is None and u.scheme.lower() == "http":
            return f"http://{u.hostname}:8080"
        return f"{u.scheme}://{u.netloc}"
    except ValueError:
        return url


SERVER_URL = normalize_server(cfg.get("serverUrl", ""))


def save_state():
    save_json(STATE_PATH, st)


def device_id():
    if st["id"]:
        return st["id"]
    machine = read_text("/etc/machine-id") or read_text("/var/lib/dbus/machine-id")
    net = net_info()
    if not machine:
        machine = hashlib.sha1(os.urandom(16)).hexdigest()
    # Inclui o MAC para distinguir equipamentos clonados a partir da mesma imagem.
    st["id"] = "l" + hashlib.sha1((machine + "|" + net["mac"]).encode()).hexdigest()[:23]
    save_state()
    return st["id"]


# --------------------------------------------------------------------------- informação do equipamento

def net_info():
    info = {"ip": "", "prefix": 0, "mask": "", "gateway": "", "dns": [], "mac": "", "iface": "", "transport": ""}
    _, out = run(["ip", "-4", "route", "show", "default"])
    m = re.search(r"default via (\S+) dev (\S+)", out.decode(errors="replace"))
    iface = ""
    if m:
        info["gateway"], iface = m.group(1), m.group(2)
    _, out = run(["ip", "-4", "-o", "addr", "show"] + (["dev", iface] if iface else []))
    for line in out.decode(errors="replace").splitlines():
        m = re.search(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if m and m.group(1) != "lo":
            iface, info["ip"], info["prefix"] = m.group(1), m.group(2), int(m.group(3))
            break
    if info["prefix"]:
        bits = (0xFFFFFFFF << (32 - info["prefix"])) & 0xFFFFFFFF
        info["mask"] = ".".join(str((bits >> s) & 255) for s in (24, 16, 8, 0))
    info["dns"] = re.findall(r"^nameserver\s+(\S+)", read_text("/etc/resolv.conf"), re.M)
    if iface:
        info["iface"] = iface
        info["mac"] = read_text(f"/sys/class/net/{iface}/address").upper()
        info["transport"] = "Wi-Fi" if os.path.exists(f"/sys/class/net/{iface}/wireless") else "Ethernet"
    return info


def os_name():
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)', read_text("/etc/os-release"), re.M)
    return (m.group(1) if m else "Linux") + " (" + os.uname().release + ")"


def screen_size():
    _, out = run(["xrandr", "--current"], timeout=5)
    m = re.search(r"current (\d+) x (\d+)", out.decode(errors="replace"))
    if m:
        return int(m.group(1)), int(m.group(2))
    _, out = run(["xdpyinfo"], timeout=5)
    m = re.search(r"dimensions:\s+(\d+)x(\d+)", out.decode(errors="replace"))
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1920, 1080


def device_info():
    w, h = screen_size()
    b = find_browser()
    try:
        uptime = int(float(read_text("/proc/uptime", "0").split()[0]))
    except (ValueError, IndexError):
        uptime = 0
    return {
        "manufacturer": read_text("/sys/class/dmi/id/sys_vendor"),
        "model": read_text("/sys/class/dmi/id/product_name"),
        "os": os_name(),
        "hostname": socket.gethostname(),
        "user": os.environ.get("USER") or os.environ.get("LOGNAME", ""),
        "resolution": f"{w}x{h}",
        "uptimeSec": uptime,
        "appVersion": f"Agente Linux {AGENT_VERSION}",
        "isLauncher": True,
        "browserName": b["label"] if b else "não encontrado",
        "session": "Wayland" if WAYLAND else "X11",
        "capture": Capturer.method_name(),
        "control": "xdotool" if has("xdotool") and not WAYLAND else ("ydotool" if has("ydotool") else "indisponível"),
    }


# --------------------------------------------------------------------------- navegador em modo kiosk

BROWSERS = [
    ("chromium", "Chromium", ["chromium", "chromium-browser"]),
    ("chrome", "Google Chrome", ["google-chrome", "google-chrome-stable"]),
    ("edge", "Microsoft Edge", ["microsoft-edge", "microsoft-edge-stable"]),
    ("firefox", "Mozilla Firefox", ["firefox", "firefox-esr"]),
]


def find_browser():
    ordered = [b for b in BROWSERS if b[0] == st["browser"]] + [b for b in BROWSERS if b[0] != st["browser"]]
    for kind, label, names in ordered:
        for n in names:
            path = shutil.which(n)
            if path:
                return {"kind": kind, "label": label, "path": path}
    return None


def is_snap(path):
    real = os.path.realpath(path)
    if path.startswith("/snap/") or real.startswith("/snap/") or os.path.basename(real) == "snap":
        return True
    try:
        with open(path, "rb") as f:
            return b"/snap/bin/" in f.read(4096)  # ex.: /usr/bin/chromium-browser no Ubuntu
    except OSError:
        return False


def profile_dir(b):
    # Navegadores em snap só acedem à sua própria pasta (as pastas escondidas da home estão vedadas).
    if b and is_snap(b["path"]):
        base = os.path.expanduser(f"~/snap/{'firefox' if b['kind'] == 'firefox' else 'chromium'}/common")
    else:
        base = os.path.expanduser("~/.local/share/adm-kiosk-agent")
    return os.path.join(base, "adm-kiosk-profile")


def browser_pids():
    needle = b"adm-kiosk-profile"
    pids = []
    for path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(path, "rb") as f:
                if needle in f.read():
                    pids.append(int(path.split("/")[2]))
        except (OSError, ValueError):
            pass
    return [p for p in pids if p != os.getpid()]


def stop_kiosk():
    pids = browser_pids()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in pids:
            try:
                os.kill(p, sig)
            except OSError:
                pass
        if not pids:
            break
        time.sleep(1.0)
        pids = browser_pids()


_last_reload = time.time()


def start_kiosk():
    global _last_reload
    if kiosk_paused or not st["url"]:
        return
    b = find_browser()
    if not b:
        log("Nenhum navegador encontrado (Chromium, Chrome, Edge ou Firefox).")
        return
    prof = profile_dir(b)
    os.makedirs(prof, exist_ok=True)
    scale = round(st["zoom"] / 100.0, 2)
    if b["kind"] == "firefox":
        with open(os.path.join(prof, "user.js"), "w") as f:
            f.write(f'user_pref("layout.css.devPixelsPerPx", "{scale}");\n')
            f.write('user_pref("browser.sessionstore.resume_from_crash", false);\n')
            f.write('user_pref("browser.shell.checkDefaultBrowser", false);\n')
            f.write('user_pref("network.captive-portal-service.enabled", false);\n')
            f.write('user_pref("network.connectivity-service.enabled", false);\n')
            f.write('user_pref("network.proxy.type", 0);\n')
        args = [b["path"], "--no-remote", "--profile", prof]
        args += ["--kiosk", st["url"]] if st["kioskEnabled"] else [st["url"]]
    else:
        # direct:// evita um proxy de sistema que, sem Internet, impediria a página da LAN.
        args = [b["path"], f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
                "--disable-session-crashed-bubble", "--noerrdialogs", "--disable-infobars",
                "--disable-sync", "--disable-background-networking", "--disable-component-update",
                "--disable-domain-reliability", "--no-pings", "--proxy-server=direct://",
                "--proxy-bypass-list=*", "--password-store=basic",
                "--disable-features=Translate,DnsOverHttps,MediaRouter,OptimizationHints,DialMediaRouteProvider",
                "--autoplay-policy=no-user-gesture-required", f"--force-device-scale-factor={scale}"]
        args += ["--kiosk", st["url"]] if st["kioskEnabled"] else ["--start-fullscreen", f"--app={st['url']}"]
    log(f"A abrir {b['label']}: {st['url']}")
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        log(f"Falha ao abrir o navegador: {e}")
    _last_reload = time.time()


def restart_kiosk():
    stop_kiosk()
    start_kiosk()


def browser_windows():
    if WAYLAND or not has("xdotool"):
        return []
    wids = []
    for p in browser_pids():
        _, out = run(["xdotool", "search", "--onlyvisible", "--pid", str(p)], timeout=5)
        wids += out.decode().split()
    return wids


def reload_page():
    global _last_reload
    if not browser_pids():
        start_kiosk()
        return
    wids = browser_windows()
    if wids:
        run(["xdotool", "windowactivate", "--sync", wids[-1], "key", "F5"], timeout=5)
    else:
        restart_kiosk()
    _last_reload = time.time()


def page_host_ok():
    if not st["url"]:
        return False
    try:
        u = urllib.parse.urlsplit(st["url"])
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((u.hostname, port), timeout=2.5):
            return True
    except (OSError, ValueError):
        return False


def keep_screen_on():
    if not WAYLAND and has("xset"):
        run(["xset", "s", "off"])
        run(["xset", "s", "noblank"])
        run(["xset", "-dpms"])


# --------------------------------------------------------------------------- captura do ecrã

QUALITY = {"high": (1920, 70, 3), "normal": (1366, 55, 6), "low": (1024, 40, 11)}  # largura, jpeg %, ffmpeg -q:v


class Capturer:
    """Fluxo contínuo com ffmpeg (x11grab) ou, em alternativa, uma captura por imagem."""

    def __init__(self):
        self.proc = None
        self.key = None
        self.frame = None
        self.seq = 0
        self.lock = threading.Lock()

    ffmpeg_broken = False

    @staticmethod
    def method_name():
        if not WAYLAND and has("ffmpeg") and not Capturer.ffmpeg_broken:
            return "ffmpeg"
        for tool in (("import",) if not WAYLAND else ()) + ("scrot", "grim", "gnome-screenshot"):
            if has(tool):
                return tool
        return "indisponível"

    def stop(self):
        proc, self.proc = self.proc, None
        if proc:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        self.key = None
        with self.lock:
            self.frame = None

    @staticmethod
    def _scale_filter(width):
        # Dimensões pares: o JPEG 4:2:0 não aceita larguras/alturas ímpares (frequentes em máquinas virtuais).
        return f"scale='trunc(min({width},iw)/2)*2':-2"

    def _start_ffmpeg(self, quality, fps):
        width, _, q = QUALITY.get(quality, QUALITY["normal"])
        w, h = screen_size()
        cmd = ["ffmpeg", "-loglevel", "error", "-nostdin", "-f", "x11grab", "-draw_mouse", "1",
               "-framerate", str(fps), "-video_size", f"{w}x{h}", "-i", os.environ["DISPLAY"],
               "-vf", self._scale_filter(width), "-pix_fmt", "yuvj420p", "-q:v", str(q), "-f", "mjpeg", "-"]
        self.started = time.time()
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._read_mjpeg, args=(self.proc,), daemon=True).start()

    def _read_mjpeg(self, proc):
        buf = b""
        frames = 0
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                err = b""
                try:
                    err = proc.stderr.read(2000)
                except (OSError, ValueError):
                    pass
                if proc is self.proc and frames == 0:
                    log("Captura com ffmpeg falhou: " + (err.decode(errors="replace").strip()[-300:] or "sem imagem")
                        + ". A usar outro método de captura.")
                    Capturer.ffmpeg_broken = True
                return
            frames += chunk.count(b"\xff\xd9")
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if start < 0 or end < 0:
                    if start > 0:
                        buf = buf[start:]
                    break
                with self.lock:
                    self.frame = buf[start:end + 2]
                    self.seq += 1
                buf = buf[end + 2:]

    def grab(self, quality, fps):
        """Devolve a imagem JPEG mais recente (ou None)."""
        method = self.method_name()
        if method == "ffmpeg":
            key = (quality, fps)
            if self.key != key or self.proc is None or self.proc.poll() is not None:
                self.stop()
                self.key = key
                self._start_ffmpeg(quality, fps)
                time.sleep(0.3)
            with self.lock:
                return self.frame
        return self.single(quality)

    def single(self, quality):
        width, jq, q = QUALITY.get(quality, QUALITY["normal"])
        method = self.method_name()
        if method == "ffmpeg":
            w, h = screen_size()
            code, out = run(["ffmpeg", "-loglevel", "error", "-nostdin", "-f", "x11grab", "-video_size", f"{w}x{h}",
                             "-i", os.environ["DISPLAY"], "-frames:v", "1",
                             "-vf", self._scale_filter(width), "-pix_fmt", "yuvj420p", "-q:v", str(q),
                             "-f", "mjpeg", "-"], timeout=10)
            return out if code == 0 and out.startswith(b"\xff\xd8") else None
        if method == "import":
            code, out = run(["import", "-silent", "-window", "root", "-resize", f"{width}x>", "-quality", str(jq), "jpeg:-"])
            return out if code == 0 and out.startswith(b"\xff\xd8") else None
        if method == "grim":
            code, out = run(["grim", "-t", "jpeg", "-q", str(jq), "-"])
            return out if code == 0 and out.startswith(b"\xff\xd8") else None
        if method in ("scrot", "gnome-screenshot"):
            path = os.path.join(tempfile.gettempdir(), f"adm-shot-{os.getpid()}.jpg")
            cmd = ["scrot", "-o", "-q", str(jq), path] if method == "scrot" else ["gnome-screenshot", "-f", path]
            code, _ = run(cmd)
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                return None
        return None


capturer = Capturer()


# --------------------------------------------------------------------------- rato e teclado

KEYS = {
    "Enter": "Return", "Escape": "Escape", "Backspace": "BackSpace", "Tab": "Tab", "Space": "space", " ": "space",
    "ArrowLeft": "Left", "ArrowUp": "Up", "ArrowRight": "Right", "ArrowDown": "Down", "Delete": "Delete",
    "Insert": "Insert", "Home": "Home", "End": "End", "PageUp": "Prior", "PageDown": "Next",
    "Meta": "super", "Win": "super", "ContextMenu": "Menu", "PrintScreen": "Print", "CapsLock": "Caps_Lock",
}
KEYS.update({f"F{i}": f"F{i}" for i in range(1, 13)})


def run_input(ev, size):
    if WAYLAND or not has("xdotool"):
        return
    w, h = size
    x = str(int(max(0.0, min(1.0, float(ev.get("x", 0.5)))) * (w - 1)))
    y = str(int(max(0.0, min(1.0, float(ev.get("y", 0.5)))) * (h - 1)))
    btn = "3" if ev.get("button") == "right" else "1"
    t = ev.get("type")
    if t == "move":
        cmd = ["mousemove", x, y]
    elif t == "down":
        cmd = ["mousemove", x, y, "mousedown", btn]
    elif t == "up":
        cmd = ["mousemove", x, y, "mouseup", btn]
    elif t == "click":
        cmd = ["mousemove", x, y, "click", "1"]
    elif t == "dblclick":
        cmd = ["mousemove", x, y, "click", "--repeat", "2", "1"]
    elif t == "rightclick":
        cmd = ["mousemove", x, y, "click", "3"]
    elif t == "scroll":
        dy = int(ev.get("dy", 1))
        cmd = ["mousemove", x, y, "click", "--repeat", str(max(1, min(20, abs(dy)))), "5" if dy > 0 else "4"]
    elif t == "key":
        name = str(ev.get("key", ""))
        key = KEYS.get(name) or (name if len(name) == 1 else None)
        if not key:
            return
        mods = [m for m in ("ctrl", "alt", "shift") if ev.get(m)]
        if len(name) == 1 and not ("ctrl" in mods or "alt" in mods):
            cmd = ["type", "--", name]
        else:
            cmd = ["key", "--clearmodifiers", "+".join(mods + [key])]
    elif t == "text":
        cmd = ["type", "--delay", "5", "--", str(ev.get("text", ""))]
    else:
        return
    run(["xdotool"] + cmd, timeout=10)


# --------------------------------------------------------------------------- HTTP / descoberta

class Http:
    """Ligação HTTP persistente (keep-alive) ao servidor; uma por thread."""

    def __init__(self):
        self.conn = None
        self.base = None

    def post(self, url, body, ctype, timeout=10):
        u = urllib.parse.urlsplit(url)
        base = (u.scheme, u.netloc)
        if self.conn is None or self.base != base:
            self.close()
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            self.conn = cls(u.netloc, timeout=timeout)
            self.base = base
        self.conn.timeout = timeout
        if self.conn.sock:
            self.conn.sock.settimeout(timeout)
        path = u.path + ("?" + u.query if u.query else "")
        try:
            self.conn.request("POST", path, body=body, headers={"Content-Type": ctype, "Content-Length": str(len(body))})
            res = self.conn.getresponse()
            data = res.read()
        except Exception:
            self.close()
            raise
        if res.status >= 300:
            raise IOError(f"HTTP {res.status}")
        return json.loads(data.decode("utf-8")) if data.strip() else {}

    def post_json(self, url, obj, timeout=10):
        return self.post(url, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", timeout)

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        self.conn = None


_discovered = ""


def _broadcast_targets():
    """Broadcast de cada interface IPv4, mais o broadcast global."""
    targets = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for name in os.listdir("/sys/class/net"):
            ifreq = struct.pack("256s", name.encode()[:15])
            try:
                flags = struct.unpack("H", fcntl.ioctl(sock.fileno(), 0x8913, ifreq)[16:18])[0]
                if not (flags & 1):
                    continue
                ip = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8915, ifreq)[20:24])
                bc = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8919, ifreq)[20:24])
            except OSError:
                continue
            if not ip.startswith("127.") and not ip.startswith("169.254.") and bc not in targets:
                targets.append(bc)
    except OSError:
        pass
    finally:
        sock.close()
    if "255.255.255.255" not in targets:
        targets.append("255.255.255.255")
    return targets


def _server_from_packet(data):
    raw = data.strip()
    if raw.startswith(ANNOUNCE_PREFIX):
        raw = raw[len(ANNOUNCE_PREFIX):]
    try:
        url = json.loads(raw.decode("utf-8")).get("server", "").rstrip("/")
    except (ValueError, UnicodeDecodeError):
        return ""
    return url if url.startswith("http") else ""


def find_server():
    global _discovered
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", AGENT_PORT))
        except OSError:
            s.bind(("", 0))
        s.settimeout(0.6)
        for _attempt in range(3):
            for target in _broadcast_targets():
                try:
                    s.sendto(DISCOVER_MSG, (target, DISCOVERY_PORT))
                except OSError:
                    pass
            deadline = time.time() + 1.2
            while time.time() < deadline:
                try:
                    data, _addr = s.recvfrom(2048)
                except socket.timeout:
                    break
                url = _server_from_packet(data)
                if url:
                    _discovered = url
                    return url
    finally:
        s.close()
    return ""


skip_configured = False


def get_server():
    # O endereço gravado é usado enquanto responder. Se falhar, procura-se o servidor na rede.
    if SERVER_URL and not skip_configured and failures < 2:
        return SERVER_URL
    return _discovered or find_server() or SERVER_URL


# --------------------------------------------------------------------------- heartbeat / configuração

page_state, page_error = "loading", ""
host_ok = False
failures = 0
wake_event = threading.Event()
connected_server = ""
hb_http = Http()


def update_page_state():
    global page_state, page_error
    if kiosk_paused:
        page_state, page_error = "paused", "Modo kiosk em pausa — ambiente de trabalho"
        return
    if not st["url"]:
        page_state, page_error = "nolinks", ""
    elif not find_browser():
        page_state, page_error = "error", "Navegador não encontrado"
    elif not host_ok:
        page_state, page_error = "offline", "Página inacessível na rede"
    elif not browser_pids():
        page_state, page_error = "loading", ""
    else:
        page_state, page_error = "ok", ""


def heartbeat():
    global failures, _discovered, connected_server, skip_configured
    server = get_server()
    if not server:
        if failures % 6 == 0:
            log("Servidor de administração não encontrado na rede. Indique o endereço em agent.json (serverUrl).")
        failures += 1
        return
    body = {
        "id": device_id(),
        "platform": "linux",
        "configVersion": st["configVersion"],
        "device": device_info(),
        "network": net_info(),
        "state": {"url": st["url"], "page": page_state, "error": page_error},
        "settings": {
            "name": st["name"], "terminal": st["terminal"], "screenType": st["screenType"], "gate": st["gate"],
            "url": st["url"], "zoom": st["zoom"], "refreshSeconds": st["refreshSeconds"], "autoScroll": False,
            "autoScrollSeconds": 10, "kioskEnabled": st["kioskEnabled"], "reloadOnError": st["reloadOnError"],
            "retryDelaySeconds": st["retryDelaySeconds"], "browser": st["browser"],
        },
    }
    try:
        r = hb_http.post_json(server + "/api/device/heartbeat", body)
        if connected_server != server:
            log(f"Ligado ao servidor de administração {server}")
        failures = 0
        connected_server = server
        if SERVER_URL and server == SERVER_URL:
            skip_configured = False
    except Exception as e:
        failures += 1
        connected_server = ""
        log(f"Sem contacto com o servidor {server}: {e}")
        if failures >= 2:
            skip_configured = True
            _discovered = ""
        return
    if r.get("config"):
        apply_config(r["config"])
    for c in r.get("commands") or []:
        try:
            run_command(server, c)
        except Exception as e:
            send_result(server, c.get("id"), False, f"Erro: {e}")
    live = r.get("live") or {}
    if live.get("active"):
        start_live(server, live)


def apply_config(c):
    version = int(c.get("version") or 0)
    if version <= 0 or version == st["configVersion"]:
        return
    # URL vazio no servidor = volta à página definida localmente no agent.json.
    new_url = c.get("url") or cfg.get("url", st["url"])
    restart = (st["url"] != new_url or st["browser"] != (c.get("browser") or "") or
               st["zoom"] != int(c.get("zoom") or 100) or st["kioskEnabled"] != bool(c.get("kioskEnabled", True)))
    st.update({
        "configVersion": version, "name": c.get("name", ""), "terminal": c.get("terminal", ""),
        "screenType": c.get("screenType", ""), "gate": c.get("gate", ""), "url": new_url,
        "browser": c.get("browser") or "", "zoom": int(c.get("zoom") or 100),
        "refreshSeconds": int(c.get("refreshSeconds") or 0), "kioskEnabled": bool(c.get("kioskEnabled", True)),
        "reloadOnError": bool(c.get("reloadOnError", True)), "retryDelaySeconds": int(c.get("retryDelaySeconds") or 10),
    })
    save_state()
    log(f"Configuração remota v{version} aplicada")
    if APP is not None:
        try:
            APP.after(0, APP.load_fields)
        except Exception:
            pass
    if restart and not kiosk_paused:
        restart_kiosk()


def send_result(server, cid, ok, message):
    try:
        Http().post_json(server + "/api/device/command-result",
                         {"id": device_id(), "commandId": cid, "ok": ok, "message": message})
    except Exception:
        pass


BANNER_PY = r"""
import sys, tkinter as tk
r = tk.Tk(); r.attributes('-fullscreen', True); r.attributes('-topmost', True); r.configure(bg='#111111')
try: r.attributes('-alpha', 0.92)
except Exception: pass
tk.Label(r, text=sys.argv[1], fg='#efe21a', bg='#111111', font=('DejaVu Sans', 40, 'bold'), justify='center').pack(expand=True)
r.after(int(sys.argv[2]) * 1000, r.destroy); r.mainloop()
"""


def show_banner(text, seconds):
    if importlib.util.find_spec("tkinter") is not None:
        try:
            subprocess.Popen([sys.executable, "-c", BANNER_PY, text, str(seconds)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            pass
    if has("zenity"):
        subprocess.Popen(["zenity", "--info", "--no-wrap", f"--timeout={seconds}", "--text", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if has("notify-send"):
        run(["notify-send", "-t", str(seconds * 1000), "ADM Kiosk", text])
        return True
    return False


def resume_kiosk():
    global kiosk_paused
    kiosk_paused = False
    if APP is not None:
        try:
            APP.after(0, APP.reflect_running)
        except Exception:
            pass
    restart_kiosk()


def leave_kiosk(reason="Atalho Ctrl+X, S"):
    global kiosk_paused, _show_when_ready
    kiosk_paused = True
    log(reason + " — a voltar ao ambiente de trabalho.")
    stop_kiosk()
    update_page_state()
    if APP is not None:
        try:
            APP.after(0, APP.show_front)
        except Exception:
            pass
    else:
        _show_when_ready = True


def save_local_settings(server, url, browser, zoom):
    global SERVER_URL, failures, _discovered
    SERVER_URL = normalize_server(server)
    cfg["serverUrl"] = SERVER_URL
    cfg["url"] = (url or "").strip()
    cfg["browser"] = browser or ""
    cfg["zoom"] = int(zoom)
    save_json(CONFIG_PATH, cfg)
    st["url"] = cfg["url"]
    st["browser"] = cfg["browser"]
    st["zoom"] = cfg["zoom"]
    save_state()
    failures = 0
    _discovered = ""
    log("Configuração local guardada.")


def run_command(server, c):
    global kiosk_paused
    t, cid = c.get("type"), c.get("id")
    log(f"Comando remoto: {t}")
    if t == "reload":
        if kiosk_paused or not browser_pids():
            resume_kiosk()
        else:
            reload_page()
        send_result(server, cid, True, "Página recarregada")
    elif t == "clear_cache":
        kiosk_paused = False
        stop_kiosk()
        b = find_browser()
        if b:
            shutil.rmtree(profile_dir(b), ignore_errors=True)
        start_kiosk()
        send_result(server, cid, True, "Cache limpa e navegador reaberto")
    elif t == "restart_app":
        resume_kiosk()
        send_result(server, cid, True, "Navegador reiniciado")
    elif t == "identify":
        seconds = int((c.get("payload") or {}).get("seconds", 20))
        net = net_info()
        kind = [x for x in ({"DPT": "DPT Doméstico", "IPT": "IPT Internacional"}.get(st["terminal"]),
                            {"FIDS_DEP": "FIDS Partidas", "FIDS_ARR": "FIDS Chegadas", "GATE": "Gate"}.get(st["screenType"])) if x]
        title = st["name"] or socket.gethostname()
        text = (f"{title}\n{' - '.join(kind)}{' ' + st['gate'] if st['gate'] else ''}\n"
                f"IP {net['ip']}   Gateway {net['gateway']}\nID {device_id()[16:].upper()}")
        ok = show_banner(text, seconds)
        send_result(server, cid, ok, f"Identificação mostrada {seconds}s" if ok else "Sem forma de mostrar a mensagem")
    elif t == "screenshot":
        jpeg = capturer.single("normal")
        if jpeg:
            Http().post(f"{server}/api/device/screenshot?id={device_id()}&cmd={cid}", jpeg, "image/jpeg", 15)
        else:
            send_result(server, cid, False, "Captura indisponível (instale ffmpeg ou ImageMagick; sessão X11)")
    elif t == "reboot":
        send_result(server, cid, True, "A forçar o reinício do computador")
        for cmd in (
            ["sudo", "-n", "/sbin/reboot", "-f"],
            ["sudo", "-n", "/usr/sbin/reboot", "-f"],
            ["sudo", "-n", "/sbin/shutdown", "-r", "now"],
            ["sudo", "-n", "/usr/sbin/shutdown", "-r", "now"],
            ["sudo", "-n", "/bin/systemctl", "reboot", "-f"],
            ["sudo", "-n", "/usr/bin/systemctl", "reboot", "-f"],
            ["sudo", "-n", "/sbin/reboot"],
            ["sudo", "-n", "/usr/sbin/reboot"],
        ):
            if run(cmd)[0] == 0:
                break
    else:
        send_result(server, cid, False, f"Comando não suportado: {t}")


# --------------------------------------------------------------------------- sessão ao vivo

live_lock = threading.Lock()
live_thread = None


def start_live(server, live):
    global live_thread
    with live_lock:
        if live_thread and live_thread.is_alive():
            return
        live_thread = threading.Thread(target=stream, args=(server, live), daemon=True)
        live_thread.start()


def stream(server, live):
    http_ = Http()
    last = None
    fails = 0
    size = screen_size()
    log("Sessão ao vivo iniciada")
    try:
        while live and live.get("active"):
            started = time.time()
            interval = max(50, min(5000, int(live.get("intervalMs") or 100))) / 1000.0
            quality = live.get("quality") or "normal"
            fps = max(1, min(15, int(round(1.0 / interval))))
            frame = capturer.grab(quality, fps)
            status = "" if frame else "capture"
            same = frame is None or frame == last
            try:
                r = http_.post(f"{server}/api/device/frame?id={device_id()}&status={status}",
                               b"" if same else frame, "image/jpeg", 10)
                fails = 0
            except Exception as e:
                fails += 1
                if fails >= 3:
                    log(f"Sessão ao vivo interrompida: {e}")
                    return
                time.sleep(0.5)
                continue
            if not same:
                last = frame
            live = r.get("live")
            for ev in r.get("inputs") or []:
                try:
                    run_input(ev, size)
                except Exception as e:
                    log(f"Controlo remoto: {e}")
            rest = interval - (time.time() - started)
            if rest > 0:
                time.sleep(rest)
    finally:
        capturer.stop()
        http_.close()
        log("Sessão ao vivo terminada")


def wait_loop():
    """Pedido de espera aberto: o servidor responde logo que há sessão, comando ou configuração."""
    gen = -1
    http_ = Http()
    while True:
        server = connected_server
        if not server:
            time.sleep(2)
            continue
        try:
            r = http_.post(f"{server}/api/device/wait?id={device_id()}&gen={gen}", b"", "application/json", 35)
            gen = int(r.get("gen", gen))
            if r.get("wake"):
                wake_event.set()
            live = r.get("live") or {}
            if live.get("active"):
                start_live(server, live)
        except Exception:
            time.sleep(3)


# --------------------------------------------------------------------------- atalho Ctrl+X, depois S

_show_when_ready = False


def agent_loop():
    global host_ok
    if WAYLAND:
        log("Sessão Wayland: o controlo remoto do rato/teclado exige uma sessão X11 (Xorg).")
    time.sleep(5)  # dá tempo à rede e ao ambiente de trabalho para arrancarem
    keep_screen_on()
    host_ok = page_host_ok()
    start_kiosk()
    threading.Thread(target=wait_loop, daemon=True).start()
    next_check = next_hb = 0.0
    while True:
        try:
            now = time.time()
            if now >= next_check:
                next_check = now + CHECK_S
                was_ok = host_ok
                host_ok = page_host_ok()
                running = bool(browser_pids())
                if kiosk_paused:
                    pass
                elif st["url"] and not running:
                    start_kiosk()
                elif host_ok and not was_ok and st["reloadOnError"]:
                    log("Ligação à página restabelecida: a recarregar.")
                    reload_page()
                elif st["refreshSeconds"] > 0 and host_ok and now - _last_reload >= st["refreshSeconds"]:
                    reload_page()
                update_page_state()
            if wake_event.is_set() or now >= next_hb:
                wake_event.clear()
                next_hb = now + HEARTBEAT_S
                heartbeat()
            wake_event.wait(0.25)
        except Exception as e:
            log(f"Erro: {e}")
            time.sleep(2)


def x11_hotkey_loop():
    try:
        lib = ctypes.cdll.LoadLibrary("libX11.so.6")
    except OSError:
        evdev_hotkey_loop()
        return
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XDefaultRootWindow.restype = ctypes.c_ulong
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    lib.XKeysymToKeycode.restype = ctypes.c_ubyte
    lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
    lib.XPending.restype = ctypes.c_int
    lib.XPending.argtypes = [ctypes.c_void_p]
    lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    lib.XConnectionNumber.restype = ctypes.c_int
    lib.XConnectionNumber.argtypes = [ctypes.c_void_p]
    dpy = lib.XOpenDisplay(None)
    if not dpy:
        evdev_hotkey_loop()
        return
    # Um grab recusado não pode terminar o processo (o X termina a aplicação por omissão).
    x_error = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    error_fn = x_error(lambda d, e: 0)
    x11_hotkey_loop.handler = error_fn
    lib.XSetErrorHandler.argtypes = [x_error]
    lib.XSetErrorHandler.restype = ctypes.c_void_p
    lib.XSetErrorHandler(error_fn)
    root = lib.XDefaultRootWindow(dpy)
    key_x = lib.XKeysymToKeycode(dpy, 0x78)
    key_s = lib.XKeysymToKeycode(dpy, 0x73)
    grab = 1
    control = 4
    for extra in (0, 2, 16, 18):
        lib.XGrabKey(dpy, key_x, control | extra, root, 0, grab, grab)
    lib.XFlush(dpy)
    s_grabbed = False

    def grab_s():
        nonlocal s_grabbed
        if s_grabbed:
            return
        lib.XGrabKey(dpy, key_s, 32768, root, 0, grab, grab)
        lib.XFlush(dpy)
        s_grabbed = True

    def ungrab_s():
        nonlocal s_grabbed
        if not s_grabbed:
            return
        lib.XUngrabKey(dpy, key_s, 32768, root)
        lib.XFlush(dpy)
        s_grabbed = False

    class XKeyEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
            ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
            ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong), ("x", ctypes.c_int),
            ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
            ("state", ctypes.c_uint), ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int),
        ]

    buf = ctypes.create_string_buffer(256)
    fd = lib.XConnectionNumber(dpy)
    armed_until = 0.0
    log("Atalho ativo: Ctrl+X, depois S, sai do modo kiosk.")
    while True:
        if s_grabbed and time.time() > armed_until:
            ungrab_s()
        lib.XFlush(dpy)
        ready, _, _ = select.select([fd], [], [], 0.25)
        if not ready:
            continue
        while lib.XPending(dpy):
            lib.XNextEvent(dpy, buf)
            ev = XKeyEvent.from_buffer_copy(buf)
            if ev.type != 2 or ev.send_event:
                continue
            if ev.keycode == key_x and (ev.state & control):
                armed_until = time.time() + 2.5
                grab_s()
            elif s_grabbed and ev.keycode == key_s and time.time() <= armed_until:
                ungrab_s()
                armed_until = 0
                leave_kiosk("Atalho Ctrl+X, S")


def evdev_hotkey_loop():
    fmt = "llHHi" if struct.calcsize("l") == 8 else "iiHHi"
    size = struct.calcsize(fmt)
    fds = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass
    if not fds:
        log("Atalho Ctrl+X, S indisponível nesta sessão (sem X11 nem acesso a /dev/input).")
        return
    log("Atalho ativo: Ctrl+X, depois S, sai do modo kiosk.")
    ctrl = False
    armed_until = 0.0
    while True:
        ready, _, _ = select.select(fds, [], [], 0.3)
        now = time.time()
        for fd in ready:
            try:
                data = os.read(fd, size * 16)
            except OSError:
                continue
            for off in range(0, len(data) - size + 1, size):
                _sec, _usec, typ, code, value = struct.unpack_from(fmt, data, off)
                if typ != 1:
                    continue
                if code in (29, 97):
                    ctrl = value != 0
                elif code == 45 and value == 1 and ctrl:
                    armed_until = now + 2.5
                elif code == 31 and value == 1 and now <= armed_until:
                    armed_until = 0
                    leave_kiosk("Atalho Ctrl+X, S")


def start_hotkey():
    target = evdev_hotkey_loop if WAYLAND or not os.environ.get("DISPLAY") else x11_hotkey_loop
    threading.Thread(target=target, daemon=True).start()


# --------------------------------------------------------------------------- janela

YELLOW = "#efe21a"
BLACK = "#121417"
INK = "#1c1f24"
DIM = "#6b7079"
FAINT = "#9aa0a8"
BG = "#f4f5f7"
SURFACE = "#ffffff"
BORDER = "#e5e7eb"
GREEN = "#0a8a4f"
RED = "#d21034"
PAGE_LABEL = {
    "ok": "Página apresentada", "loading": "A carregar", "error": "Erro na página",
    "offline": "Página inacessível na rede", "nolinks": "Sem página",
    "paused": "No ambiente de trabalho",
}


def build_window(tk):
    """Devolve a classe da janela, já com o módulo tkinter fechado."""

    class AgentApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("ADM Kiosk Agente")
            self.configure(bg=BG)
            self.geometry("820x700")
            self.minsize(720, 620)
            self._shown_log = ""
            self._hint_until = 0
            self._build()
            self.load_fields()
            self.protocol("WM_DELETE_WINDOW", self.iconify)
            self.after(400, self.tick)
            self.after(200, self._maybe_show)

        def _maybe_show(self):
            if _show_when_ready or kiosk_paused:
                self.show_front()

        def _build(self):
            head = tk.Frame(self, bg=BLACK, height=78)
            head.pack(fill="x")
            head.pack_propagate(False)
            tk.Label(head, text="ADM Kiosk Agente", bg=BLACK, fg="white",
                     font=("DejaVu Sans", 16, "bold")).place(x=22, y=12)
            tk.Label(head, text="Computador / netbox   ·   Aeroportos de Moçambique, E.P.",
                     bg=BLACK, fg=FAINT, font=("DejaVu Sans", 9)).place(x=22, y=46)
            tk.Frame(self, bg=YELLOW, height=4).pack(fill="x")

            foot = tk.Frame(self, bg=BG)
            foot.pack(side="bottom", fill="x", padx=22, pady=(0, 8))
            tk.Label(foot, text="Desenvolvido por Harmonico Lucas", bg=BG, fg=FAINT,
                     font=("DejaVu Sans", 9)).pack(anchor="w")
            self.hint = tk.Label(foot, text="Para sair do modo kiosk: Ctrl+X e, em seguida, S. "
                                  "A janela do agente volta ao ambiente de trabalho.",
                                  bg=BG, fg=DIM, font=("DejaVu Sans", 9))
            self.hint.pack(anchor="w")

            body = tk.Frame(self, bg=BG)
            body.pack(fill="both", expand=True, padx=18, pady=12)

            card = tk.Frame(body, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            card.pack(fill="x", pady=(0, 10))
            row = tk.Frame(card, bg=SURFACE)
            row.pack(fill="x", padx=14, pady=12)
            self.dot = tk.Canvas(row, width=14, height=14, bg=SURFACE, highlightthickness=0)
            self.dot.pack(side="left", padx=(0, 10))
            self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill=FAINT, outline="")
            text = tk.Frame(row, bg=SURFACE)
            text.pack(side="left", fill="x", expand=True)
            self.status_var = tk.StringVar(value="A procurar o servidor na rede…")
            self.detail_var = tk.StringVar(value="")
            tk.Label(text, textvariable=self.status_var, bg=SURFACE, fg=INK,
                     font=("DejaVu Sans", 11, "bold")).pack(anchor="w")
            tk.Label(text, textvariable=self.detail_var, bg=SURFACE, fg=DIM,
                     font=("DejaVu Sans", 9)).pack(anchor="w")

            cfg = tk.Frame(body, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            cfg.pack(fill="x", pady=(0, 10))
            inner = tk.Frame(cfg, bg=SURFACE)
            inner.pack(fill="x", padx=14, pady=12)
            tk.Label(inner, text="Este ecrã", bg=SURFACE, fg=INK,
                     font=("DejaVu Sans", 10, "bold")).pack(anchor="w")
            tk.Label(inner, text="Servidor de administração", bg=SURFACE, fg=DIM,
                     font=("DejaVu Sans", 8)).pack(anchor="w", pady=(8, 0))
            self.server_box = tk.Entry(inner, font=("DejaVu Sans", 10))
            self.server_box.pack(fill="x")
            tk.Label(inner, text="Página a apresentar", bg=SURFACE, fg=DIM,
                     font=("DejaVu Sans", 8)).pack(anchor="w", pady=(8, 0))
            self.url_box = tk.Entry(inner, font=("DejaVu Sans", 10))
            self.url_box.pack(fill="x")
            line = tk.Frame(inner, bg=SURFACE)
            line.pack(fill="x", pady=(8, 0))
            tk.Label(line, text="Navegador", bg=SURFACE, fg=DIM, font=("DejaVu Sans", 8)).pack(side="left")
            self.browser = tk.StringVar()
            names = ["Automático", "Chromium", "Google Chrome", "Microsoft Edge", "Mozilla Firefox"]
            self._browser_kinds = ["", "chromium", "chrome", "edge", "firefox"]
            tk.OptionMenu(line, self.browser, names[0], *names).pack(side="left", padx=(8, 18))
            tk.Label(line, text="Zoom %", bg=SURFACE, fg=DIM, font=("DejaVu Sans", 8)).pack(side="left")
            self.zoom = tk.Spinbox(line, from_=50, to=300, width=6, font=("DejaVu Sans", 10))
            self.zoom.pack(side="left", padx=(8, 0))

            actions = tk.Frame(body, bg=BG)
            actions.pack(fill="x", pady=(0, 10))
            self._button(actions, "Guardar", self.on_save, False).pack(side="left", padx=(0, 8))
            self._button(actions, "Entrar no modo kiosk", self.on_enter, True).pack(side="left", padx=(0, 8))
            self._button(actions, "Sair do modo kiosk", self.on_leave, False).pack(side="left", padx=(0, 8))
            self._button(actions, "Recarregar página", self.on_reload, False).pack(side="left", padx=(0, 8))
            self._button(actions, "Terminar agente", self.on_quit, False).pack(side="right")

            log_card = tk.Frame(body, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            log_card.pack(fill="both", expand=True)
            tk.Label(log_card, text="Atividade", bg=SURFACE, fg=INK,
                     font=("DejaVu Sans", 10, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
            self.log = tk.Text(log_card, height=8, bg=SURFACE, fg=INK, relief="flat",
                               font=("DejaVu Sans Mono", 8), wrap="word", highlightthickness=0)
            self.log.pack(fill="both", expand=True, padx=14, pady=(4, 10))
            self.log.configure(state="disabled")

        def _button(self, parent, text, command, primary):
            btn = tk.Button(parent, text=text, command=command, relief="flat", padx=12, pady=6,
                            bg=YELLOW if primary else SURFACE, fg=BLACK if primary else INK,
                            activebackground="#d8cb0c" if primary else "#eef0f2",
                            font=("DejaVu Sans", 9, "bold" if primary else "normal"),
                            highlightthickness=1, highlightbackground=BORDER)
            return btn

        def load_fields(self):
            if self.focus_get() is not self.server_box:
                self.server_box.delete(0, "end")
                self.server_box.insert(0, SERVER_URL)
            if self.focus_get() is not self.url_box:
                self.url_box.delete(0, "end")
                self.url_box.insert(0, st.get("url", ""))
            kind = st.get("browser") or ""
            try:
                self.browser.set(["Automático", "Chromium", "Google Chrome", "Microsoft Edge",
                                  "Mozilla Firefox"][self._browser_kinds.index(kind)])
            except ValueError:
                self.browser.set("Automático")
            if self.focus_get() is not self.zoom:
                self.zoom.delete(0, "end")
                self.zoom.insert(0, str(st.get("zoom", 100)))

        def _read(self):
            names = ["Automático", "Chromium", "Google Chrome", "Microsoft Edge", "Mozilla Firefox"]
            try:
                kind = self._browser_kinds[names.index(self.browser.get())]
            except ValueError:
                kind = ""
            try:
                zoom = max(50, min(300, int(self.zoom.get())))
            except ValueError:
                zoom = 100
            return self.server_box.get().strip(), self.url_box.get().strip(), kind, zoom

        def on_save(self):
            save_local_settings(*self._read())

        def on_enter(self):
            server, url, kind, zoom = self._read()
            if not url:
                import tkinter.messagebox as mb
                mb.showinfo("ADM Kiosk Agente", "Indique a página a apresentar neste ecrã.")
                return
            save_local_settings(server, url, kind, zoom)
            resume_kiosk()

        def on_leave(self):
            leave_kiosk("Saída pedida na janela do agente")

        def on_reload(self):
            threading.Thread(target=reload_page, daemon=True).start()

        def on_quit(self):
            import tkinter.messagebox as mb
            if mb.askokcancel("ADM Kiosk Agente", "O agente deixa de controlar este ecrã. Terminar?"):
                self.destroy()

        def show_front(self):
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(700, lambda: self.attributes("-topmost", False))
            try:
                self.focus_force()
            except Exception:
                pass

        def reflect_running(self):
            try:
                self.attributes("-topmost", False)
                self.lower()
            except Exception:
                pass

        def tick(self):
            if connected_server:
                self.status_var.set("Ligado a " + connected_server)
                color = GREEN
            elif failures:
                self.status_var.set("Sem contacto com o servidor")
                color = RED
            else:
                self.status_var.set("A procurar o servidor na rede…")
                color = FAINT
            self.dot.itemconfig(self.dot_id, fill=color)
            net = {}
            try:
                net = net_info()
            except Exception:
                pass
            mode = "No ambiente de trabalho." if kiosk_paused else "Modo kiosk activo."
            self.detail_var.set(mode + "   IP " + (net.get("ip") or "—") +
                                "   ·   " + PAGE_LABEL.get(page_state, page_state))
            text = "\n".join(LOG_LINES)
            if text != self._shown_log:
                self._shown_log = text
                self.log.configure(state="normal")
                self.log.delete("1.0", "end")
                self.log.insert("1.0", text)
                self.log.see("end")
                self.log.configure(state="disabled")
            self.after(1000, self.tick)

    return AgentApp


def main():
    global APP
    lock = open(os.path.join(tempfile.gettempdir(), f"adm-kiosk-agent-{os.getuid()}.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    log(f"Agente Linux {AGENT_VERSION} iniciado (ID {device_id()}, sessão {'Wayland' if WAYLAND else 'X11'}, "
        f"servidor {SERVER_URL or 'descoberta automática'})")
    threading.Thread(target=agent_loop, daemon=True).start()
    start_hotkey()
    if os.environ.get("DISPLAY") and importlib.util.find_spec("tkinter"):
        import tkinter as tk
        APP = build_window(tk)()
        APP.mainloop()
    else:
        log("Sem ambiente gráfico: o agente continua em segundo plano.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
