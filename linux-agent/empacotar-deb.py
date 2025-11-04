#!/usr/bin/env python3
"""Cria o pacote .deb do agente Linux (não precisa de dpkg)."""

import gzip
import hashlib
import io
import os
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "2.6.0"
NAME = "adm-kiosk-agente"
ROOT = os.path.dirname(HERE)

DESKTOP = """[Desktop Entry]
Type=Application
Name=ADM Kiosk Agente
Comment=Aeroportos de Moçambique - desenvolvido por Harmonico Lucas
Exec=/usr/bin/adm-kiosk-agente
X-GNOME-Autostart-enabled=true
Terminal=false
Categories=Utility;
"""

BIN = """#!/bin/sh
exec /usr/bin/python3 /opt/adm-kiosk-agent/adm-agent.py "$@"
"""

CONTROL = f"""Package: {NAME}
Version: {VERSION}
Section: misc
Priority: optional
Architecture: all
Depends: python3 (>= 3.6)
Recommends: iproute2
Maintainer: Harmonico Lucas <harmonico.lucas@localhost>
Description: ADM Kiosk - agente de ecrãs
 Abre a página configurada em modo kiosk, liga-se ao servidor de
 administração na rede local (sem precisar de Internet) e volta ao
 ambiente de trabalho com Ctrl+X e, em seguida, S.
"""

POSTINST = """#!/bin/sh
set -e
if [ -d /usr/share/adm-kiosk-agent/pacotes ]; then
    dpkg -i /usr/share/adm-kiosk-agent/pacotes/*.deb || true
    dpkg --configure -a || true
fi
chmod 755 /opt/adm-kiosk-agent /usr/bin/adm-kiosk-agente /opt/adm-kiosk-agent/adm-agent.py
chmod 1777 /opt/adm-kiosk-agent
if [ ! -f /opt/adm-kiosk-agent/agent.json ]; then
    printf '%s\\n' '{"serverUrl":"","url":"","browser":"","zoom":100}' > /opt/adm-kiosk-agent/agent.json
    chmod 666 /opt/adm-kiosk-agent/agent.json
fi
cat > /etc/sudoers.d/adm-kiosk-agent <<'EOF'
ALL ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot, /sbin/shutdown, /usr/sbin/shutdown, /bin/systemctl reboot, /bin/systemctl reboot -f, /usr/bin/systemctl reboot, /usr/bin/systemctl reboot -f
EOF
chmod 440 /etc/sudoers.d/adm-kiosk-agent
if command -v visudo >/dev/null 2>&1 && ! visudo -cf /etc/sudoers.d/adm-kiosk-agent >/dev/null 2>&1; then
    rm -f /etc/sudoers.d/adm-kiosk-agent
fi
exit 0
"""

PRERM = """#!/bin/sh
set -e
pkill -f /opt/adm-kiosk-agent/adm-agent.py 2>/dev/null || true
rm -f /etc/sudoers.d/adm-kiosk-agent
exit 0
"""


def lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def tar_bytes(entries):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data, mode, is_dir in entries:
            info = tarfile.TarInfo(name)
            info.mtime = int(time.time())
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mode = mode
            if is_dir:
                info.type = tarfile.DIRTYPE
            else:
                info.size = len(data)
            tf.addfile(info, None if is_dir else io.BytesIO(data))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        g.write(raw.getvalue())
    return gz.getvalue()


def ar(path, members):
    with open(path, "wb") as f:
        f.write(b"!<arch>\n")
        for name, data in members:
            header = name.ljust(16)[:16]
            header += str(int(time.time())).ljust(12)[:12]
            header += "0".ljust(6) + "0".ljust(6) + "100644".ljust(8)
            header += str(len(data)).ljust(10)[:10]
            header += "`\n"
            if len(header) != 60:
                raise SystemExit("cabeçalho ar com %s bytes" % len(header))
            f.write(header.encode("ascii"))
            f.write(data)
            if len(data) % 2:
                f.write(b"\n")


def main():
    agent = lf(open(os.path.join(HERE, "adm-agent.py"), encoding="utf-8").read())
    if not agent.startswith(b"#!"):
        agent = b"#!/usr/bin/env python3\n" + agent
    readme = lf(open(os.path.join(HERE, "LEIA-ME.txt"), encoding="utf-8").read())
    files = [
        ("./opt/adm-kiosk-agent/adm-agent.py", agent, 0o755),
        ("./opt/adm-kiosk-agent/LEIA-ME.txt", readme, 0o644),
        ("./usr/bin/adm-kiosk-agente", lf(BIN), 0o755),
        ("./usr/share/applications/adm-kiosk-agente.desktop", lf(DESKTOP), 0o644),
        ("./etc/xdg/autostart/adm-kiosk-agente.desktop", lf(DESKTOP), 0o644),
    ]
    deb_dir = os.path.join(HERE, "pacotes", "amd64")
    if os.path.isdir(deb_dir):
        for name in sorted(os.listdir(deb_dir)):
            if name.endswith(".deb"):
                with open(os.path.join(deb_dir, name), "rb") as handle:
                    files.append(("./usr/share/adm-kiosk-agent/pacotes/" + name, handle.read(), 0o644))
    md5 = "".join(hashlib.md5(data).hexdigest() + "  " + name[2:] + "\n" for name, data, _mode in files)
    dirs = []
    seen = set()
    for name, _data, _mode in files:
        parts = name.strip("./").split("/")[:-1]
        acc = "."
        for part in parts:
            acc += "/" + part
            if acc not in seen:
                seen.add(acc)
                mode = 0o1777 if acc.endswith("adm-kiosk-agent") else 0o755
                dirs.append((acc + "/", b"", mode, True))
    data_entries = dirs + [(name, data, mode, False) for name, data, mode in files]
    control_entries = [
        ("./control", lf(CONTROL), 0o644, False),
        ("./postinst", lf(POSTINST), 0o755, False),
        ("./prerm", lf(PRERM), 0o755, False),
        ("./md5sums", lf(md5), 0o644, False),
    ]
    deb_name = "%s_%s_all.deb" % (NAME, VERSION)
    targets = [
        os.path.join(ROOT, "Final", "Agente-Linux", deb_name),
        os.path.join(ROOT, "APK", "ADM-Kiosk-Final", "5-Agente-Linux", deb_name),
        os.path.join(ROOT, "APK", "Final2", "5-Agente-Linux", deb_name),
    ]
    blob_control = tar_bytes(control_entries)
    blob_data = tar_bytes(data_entries)
    for dest in targets:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        ar(dest, [("debian-binary", b"2.0\n"), ("control.tar.gz", blob_control), ("data.tar.gz", blob_data)])
        print(dest, os.path.getsize(dest))


if __name__ == "__main__":
    main()
