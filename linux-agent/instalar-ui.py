#!/usr/bin/env python3
"""Instalador com janela do agente ADM Kiosk para Ubuntu 24.04.

Instala os pacotes .deb que vêm na pasta pacotes (python3-tk, ffmpeg, xdotool)
e depois o agente. Não precisa de Internet.

Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas.
"""

import glob
import json
import os
import pwd
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = "/opt/adm-kiosk-agent"
VERSION = "2.6.0"


def arch():
    try:
        out = subprocess.check_output(["dpkg", "--print-architecture"], text=True, stderr=subprocess.DEVNULL)
        return out.strip() or "amd64"
    except (OSError, subprocess.SubprocessError):
        return "amd64"


def deb_files():
    folder = os.path.join(HERE, "pacotes", arch())
    if not os.path.isdir(folder):
        folder = os.path.join(HERE, "pacotes")
    found = sorted(glob.glob(os.path.join(folder, "*.deb")))
    preferred = []
    rest = []
    for path in found:
        name = os.path.basename(path)
        if any(part in name for part in ("python3-tk", "libtcl", "libtk", "tk8.6", "blt_", "xdotool", "libxdo", "x11-")):
            preferred.append(path)
        else:
            rest.append(path)
    return preferred, rest


def have_tk():
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def desktop_user():
    for key in ("--user",):
        if key in sys.argv:
            value = sys.argv[sys.argv.index(key) + 1]
            if value and value != "root":
                return value
    for env in ("PKEXEC_UID", "SUDO_UID"):
        if os.environ.get(env, "").isdigit():
            try:
                return pwd.getpwuid(int(os.environ[env])).pw_name
            except KeyError:
                pass
    try:
        for entry in pwd.getpwall():
            if entry.pw_uid >= 1000 and entry.pw_dir.startswith("/home/"):
                return entry.pw_name
    except Exception:
        pass
    return ""


def elevate():
    if os.geteuid() == 0:
        return
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    display = os.environ.get("DISPLAY") or ":0"
    xauth = os.environ.get("XAUTHORITY") or ""
    script = os.path.abspath(__file__)
    cmd = ["pkexec", sys.executable, script, "--user", user, "--display", display, "--xauth", xauth]
    os.execvp(cmd[0], cmd)


def arg_value(flag, default=""):
    if flag in sys.argv:
        index = sys.argv.index(flag)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def install_debs(log):
    preferred, rest = deb_files()
    if not preferred and not rest:
        log("Não foram encontrados pacotes em pacotes/. Copie a pasta completa.")
        return False

    def apply(group):
        if not group:
            return True
        proc = subprocess.run(["dpkg", "-i", *group], capture_output=True, text=True)
        if proc.stdout:
            log(proc.stdout.strip())
        if proc.stderr:
            log(proc.stderr.strip())
        return proc.returncode == 0

    ok = apply(preferred)
    apply(rest)
    subprocess.run(["dpkg", "--configure", "-a"], capture_output=True, text=True)
    return ok or have_tk()


def install_agent(user, server, page, log):
    os.makedirs(DEST, exist_ok=True)
    shutil.copy(os.path.join(HERE, "adm-agent.py"), os.path.join(DEST, "adm-agent.py"))
    os.chmod(os.path.join(DEST, "adm-agent.py"), 0o755)
    extra = os.path.join(HERE, "desinstalar.sh")
    if os.path.isfile(extra):
        shutil.copy(extra, os.path.join(DEST, "desinstalar.sh"))
    server = server.strip().rstrip("/")
    if server and "://" not in server:
        server = "http://" + server
    with open(os.path.join(DEST, "agent.json"), "w", encoding="utf-8") as handle:
        json.dump({"serverUrl": server, "url": page.strip(), "browser": "", "zoom": 100}, handle, indent=2)
    os.chmod(os.path.join(DEST, "agent.json"), 0o666)
    wrapper = "#!/bin/sh\nexec /usr/bin/python3 /opt/adm-kiosk-agent/adm-agent.py \"$@\"\n"
    with open("/usr/bin/adm-kiosk-agente", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(wrapper)
    os.chmod("/usr/bin/adm-kiosk-agente", 0o755)
    desktop = (
        "[Desktop Entry]\nType=Application\nName=ADM Kiosk Agente\n"
        "Comment=Aeroportos de Moçambique - desenvolvido por Harmonico Lucas\n"
        "Exec=/usr/bin/adm-kiosk-agente\nX-GNOME-Autostart-enabled=true\n"
        "Terminal=false\nCategories=Utility;\n"
    )
    for folder in ("/usr/share/applications", "/etc/xdg/autostart"):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "adm-kiosk-agente.desktop"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(desktop)
    sudoers = (
        "ALL ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, "
        "/usr/sbin/shutdown, /bin/systemctl reboot, /bin/systemctl reboot -f, "
        "/usr/bin/systemctl reboot, /usr/bin/systemctl reboot -f\n"
    )
    path = "/etc/sudoers.d/adm-kiosk-agent"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(sudoers)
    os.chmod(path, 0o440)
    check = subprocess.run(["visudo", "-cf", path], capture_output=True)
    if check.returncode != 0:
        os.remove(path)
        log("A permissão de reinício não ficou ativa.")
    info = pwd.getpwnam(user) if user else None
    if info:
        os.chown(DEST, info.pw_uid, info.pw_gid)
        for name in os.listdir(DEST):
            try:
                os.chown(os.path.join(DEST, name), info.pw_uid, info.pw_gid)
            except OSError:
                pass
        auto = os.path.join(info.pw_dir, ".config", "autostart")
        os.makedirs(auto, exist_ok=True)
        with open(os.path.join(auto, "adm-kiosk-agente.desktop"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(desktop)
        os.chown(auto, info.pw_uid, info.pw_gid)
        os.chown(os.path.join(auto, "adm-kiosk-agente.desktop"), info.pw_uid, info.pw_gid)
    log("Agente " + VERSION + " instalado em " + DEST)
    return info


def launch_agent(info):
    if not info:
        return False
    display = arg_value("--display", os.environ.get("DISPLAY", ":0"))
    xauth = arg_value("--xauth", os.environ.get("XAUTHORITY", ""))
    env = os.environ.copy()
    env["HOME"] = info.pw_dir
    env["USER"] = info.pw_name
    env["LOGNAME"] = info.pw_name
    env["DISPLAY"] = display or ":0"
    if xauth:
        env["XAUTHORITY"] = xauth
    subprocess.Popen(
        ["sudo", "-u", info.pw_name, "--", sys.executable, os.path.join(DEST, "adm-agent.py")],
        env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True


def main():
    elevate()
    if not have_tk():
        install_debs(lambda text: print(text, flush=True))
        if not have_tk():
            sys.stderr.write("Não foi possível instalar o python3-tk a partir dos pacotes incluídos.\n")
            return 1
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), *sys.argv[1:]])

    import tkinter as tk
    from tkinter import messagebox, ttk

    user = desktop_user()
    root = tk.Tk()
    root.title("ADM Kiosk - Instalar agente")
    root.configure(bg="#f4f5f7")
    root.geometry("640x520")
    root.minsize(560, 460)

    head = tk.Frame(root, bg="#121417", height=72)
    head.pack(fill="x")
    head.pack_propagate(False)
    tk.Label(head, text="ADM Kiosk", bg="#121417", fg="#efe21a", font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(12, 0))
    tk.Label(head, text="Instalação do agente  " + VERSION + "  ·  Ubuntu 24.04", bg="#121417", fg="#d0d4da", font=("Segoe UI", 9)).pack(anchor="w", padx=18)

    body = tk.Frame(root, bg="#f4f5f7")
    body.pack(fill="both", expand=True, padx=18, pady=14)
    tk.Label(body, text="Os pacotes necessários vêm nesta pasta (Python Tk, ffmpeg e xdotool). Não é preciso Internet.",
             bg="#f4f5f7", fg="#1c1f24", wraplength=580, justify="left").pack(anchor="w")
    tk.Label(body, text="Servidor (vazio = descobrir na rede)", bg="#f4f5f7", fg="#1c1f24").pack(anchor="w", pady=(12, 2))
    server = ttk.Entry(body)
    server.pack(fill="x")
    tk.Label(body, text="Página deste ecrã (pode ficar vazia e definir depois no painel)", bg="#f4f5f7", fg="#1c1f24").pack(anchor="w", pady=(10, 2))
    page = ttk.Entry(body)
    page.pack(fill="x")
    log = tk.Text(body, height=12, bg="#ffffff", fg="#1c1f24", relief="flat", font=("Consolas", 9))
    log.pack(fill="both", expand=True, pady=(12, 8))

    def write(text):
        if not text:
            return
        log.insert("end", text.rstrip() + "\n")
        log.see("end")
        root.update_idletasks()

    def go():
        button.configure(state="disabled")
        write("A instalar os pacotes incluídos…")
        install_debs(write)
        if not have_tk():
            messagebox.showerror("ADM Kiosk", "O pacote python3-tk não ficou instalado. Veja o registo nesta janela.")
            button.configure(state="normal")
            return
        if not user:
            messagebox.showerror("ADM Kiosk", "Não foi encontrado o utilizador da sessão gráfica.")
            button.configure(state="normal")
            return
        write("A instalar o agente para " + user + "…")
        info = install_agent(user, server.get(), page.get(), write)
        launch_agent(info)
        write("Instalação concluída. O agente abre nesta sessão e nos próximos arranques.")
        messagebox.showinfo("ADM Kiosk", "O agente ficou instalado.\n\nPara sair do ecrã inteiro: Ctrl+X e, em seguida, S.")
        button.configure(state="normal")

    button = tk.Button(body, text="Instalar", command=go, bg="#efe21a", fg="#121417",
                       font=("Segoe UI", 11, "bold"), relief="flat", padx=18, pady=6)
    button.pack(anchor="e")
    tk.Label(root, text="Desenvolvido por Harmonico Lucas", bg="#f4f5f7", fg="#9aa0a8").pack(anchor="w", padx=18, pady=(0, 8))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
