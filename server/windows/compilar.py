"""
Gera ADM-Kiosk-Servidor-Setup.exe (não precisa de Python no computador de destino):
janela para instalar, iniciar o servidor, abrir o painel e desinstalar.

Requisitos (só no computador onde se compila):  pip install pyinstaller pillow
Uso:  python server/windows/compilar.py [pasta_de_saida]
"""

import os
import re
import sys

from PIL import Image

# Num venv o Tcl/Tk não é encontrado e o PyInstaller excluiria o tkinter (a janela).
for var, sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    path = os.path.join(sys.base_prefix, "tcl", sub)
    if not os.environ.get(var) and os.path.isdir(path):
        os.environ[var] = path

import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
DIST = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "dist")

with open(os.path.join(SERVER, "adm_kiosk_server.py"), encoding="utf-8") as f:
    version = re.search(r'^VERSION = "([\d.]+)"', f.read(), re.M).group(1)
parts = (version.split(".") + ["0"] * 4)[:4]

os.makedirs(BUILD, exist_ok=True)
icon = os.path.join(BUILD, "adm.ico")
logo = Image.open(os.path.join(SERVER, "static", "logo.png")).convert("RGBA")
side = max(logo.size)
square = Image.new("RGBA", (side, side), (255, 255, 255, 0))
square.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))
square.save(icon, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

version_file = os.path.join(BUILD, "version.txt")
with open(version_file, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({', '.join(parts)}), prodvers=({', '.join(parts)}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('081604B0', [
      StringStruct('CompanyName', 'Harmonico Lucas'),
      StringStruct('FileDescription', 'ADM Kiosk - Servidor de administração'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'ADM-Kiosk-Servidor'),
      StringStruct('LegalCopyright', 'Aeroportos de Moçambique, E.P. - Harmonico Lucas'),
      StringStruct('OriginalFilename', 'ADM-Kiosk-Servidor.exe'),
      StringStruct('ProductName', 'ADM Kiosk'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x0816, 1200])])
  ]
)
""")

PyInstaller.__main__.run([
    os.path.join(HERE, "adm_kiosk_servidor_win.py"),
    "--name", "ADM-Kiosk-Servidor-Setup",
    "--onefile",
    "--noconsole",
    "--clean",
    "--noconfirm",
    "--icon", icon,
    "--version-file", version_file,
    "--paths", SERVER,
    "--paths", HERE,
    "--hidden-import", "adm_kiosk_gui",
    "--add-data", f"{os.path.join(SERVER, 'static')}{os.pathsep}static",
    "--distpath", DIST,
    "--workpath", os.path.join(BUILD, "work"),
    "--specpath", BUILD,
])
print("\nInstalador:", os.path.join(DIST, "ADM-Kiosk-Servidor-Setup.exe"))
