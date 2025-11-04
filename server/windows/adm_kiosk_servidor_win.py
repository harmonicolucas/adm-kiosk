"""
ADM Kiosk - Servidor de administração: instalação e gestão no Windows.

O executável abre uma janela (adm_kiosk_gui) para instalar, iniciar o servidor, abrir o
painel e desinstalar. Argumentos:
  --install     abre a janela e instala (pede privilégios de administrador)
  --uninstall   abre a janela e desinstala (entrada em "Aplicações instaladas")
  --stop        para o servidor (sem janela; usado quando é preciso ser administrador)
  --serve ...   executa o servidor sem janela (tarefa de arranque; aceita --port e --data)

Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas.
"""

import ctypes
import http.client
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
import winreg

import adm_kiosk_server as srv
from adm_kiosk_win_common import (APP, DATA_DIR, DATA_ROOT, INSTALL_DIR, INSTALLED_EXE, NO_WINDOW, OLD_PANEL_EXE,
                                  PORT, TASK, current_port, port_busy, save_http_port)

PROGRAMS = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs")
START_MENU = os.path.join(PROGRAMS, APP)
PUBLIC_DESKTOP = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop")
DESKTOP_LINK = os.path.join(PUBLIC_DESKTOP, "ADM Kiosk Servidor.lnk")
OLD_LINKS = (os.path.join(PUBLIC_DESKTOP, "Painel ADM Kiosk.url"),
             os.path.join(START_MENU, "Painel ADM Kiosk.url"),
             os.path.join(START_MENU, "Gerir o servidor ADM Kiosk.lnk"))
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ADMKioskServidor"
OLD_FW_RULES = ("ADM Kiosk Admin (HTTP 8080)", "ADM Kiosk Admin (Descoberta UDP 47800)")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)


def q(text):
    """Texto entre plicas para PowerShell."""
    return "'" + str(text).replace("'", "''") + "'"


def ps(script):
    return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin(args):
    """Volta a abrir este programa com privilégios de administrador (janela do UAC)."""
    params = args if getattr(sys, "frozen", False) else f'"{os.path.abspath(sys.argv[0])}" {args}'
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32


APP_FILES = (
    "adm_kiosk_server.py",
    "adm_kiosk_servidor_win.py",
    "adm_kiosk_gui.py",
    "adm_kiosk_win_common.py",
)


def installed_script():
    return os.path.join(INSTALL_DIR, "adm_kiosk_servidor_win.py")


def pythonw_path():
    """pythonw do pacote de 32 bits, ou o interpretador que abriu esta janela."""
    marker = os.path.join(INSTALL_DIR, "pythonw.path")
    if os.path.isfile(marker):
        saved = open(marker, encoding="utf-8").read().strip().strip('"')
        if os.path.isfile(saved):
            return saved
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for candidate in (
        os.path.normpath(os.path.join(here, "..", "Python38", "pythonw.exe")),
        os.path.join(r"C:\ADM-Kiosk-Server", "Python38", "pythonw.exe"),
        os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


def program_command(extra):
    """Comando que abre este programa (executável único ou Python de 32 bits)."""
    if os.path.isfile(INSTALLED_EXE):
        return [INSTALLED_EXE] + extra
    script = installed_script() if os.path.isfile(installed_script()) else os.path.abspath(sys.argv[0])
    return [pythonw_path(), script] + extra


def is_installed():
    return os.path.isfile(INSTALLED_EXE) or os.path.isfile(installed_script())


def running_installed():
    if getattr(sys, "frozen", False):
        return os.path.normcase(os.path.abspath(sys.executable)).startswith(os.path.normcase(INSTALL_DIR + os.sep))
    return os.path.normcase(os.path.abspath(sys.argv[0])).startswith(os.path.normcase(INSTALL_DIR + os.sep))


def add_fw_rule(name, proto, port):
    run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"])
    run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in", "action=allow",
         f"protocol={proto}", f"localport={port}", "profile=any"])


def remove_fw_rules():
    """Remove todas as regras do ADM Kiosk (incluindo as das portas acrescentadas no painel)."""
    ps("Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'ADM Kiosk Servidor (*' } "
       "| Remove-NetFirewallRule -ErrorAction SilentlyContinue")
    for name in OLD_FW_RULES:
        run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"])


def _kill(filter_ps):
    ps("Get-CimInstance Win32_Process | Where-Object { " + filter_ps +
       f" -and $_.ProcessId -ne {os.getpid()} -and $_.ProcessId -ne {os.getppid()} }} "
       "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def stop_server():
    """Para o servidor instalado (tarefa e processos '--serve'); devolve True se ficou parado."""
    run(["schtasks", "/End", "/TN", TASK])
    _kill(f"($_.ExecutablePath -eq {q(INSTALLED_EXE)} -or $_.CommandLine -like {q('*' + installed_script() + '*')}) "
          " -and $_.CommandLine -like '*--serve*'")
    time.sleep(1)
    return not port_busy(current_port())


def stop_everything_installed():
    """Antes de atualizar ou remover: fecha o servidor e as janelas do programa instalado."""
    ps(f"Stop-ScheduledTask -TaskName {q(TASK)} -ErrorAction SilentlyContinue")
    _kill(f"($_.ExecutablePath -eq {q(INSTALLED_EXE)} -or $_.ExecutablePath -eq {q(OLD_PANEL_EXE)} "
          f"-or $_.CommandLine -like {q('*' + installed_script() + '*')})")
    time.sleep(1.5)


def start_server(wait=25):
    """Arranca o servidor instalado: 1.º a tarefa (corre como sistema), 2.º com o utilizador atual."""
    port = current_port()
    if page_ok(port):
        return True
    if port_busy(port) and not stop_broken_server(port):
        return False
    task = run(["schtasks", "/Run", "/TN", TASK])
    if task.returncode == 0 and _wait(port, 6):
        return True
    if port_busy(port) and not page_ok(port) and not stop_broken_server(port):
        return False
    subprocess.Popen(program_command(["--serve", "--port", str(current_port()), "--data", DATA_DIR]),
                     creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)
    return _wait(port, wait)


def page_ok(port):
    """True só quando o painel chega mesmo. Uma porta aberta que não envia a página
    faz o Chrome mostrar «This page isn't working»."""
    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=3)
        conn.request("GET", "/", headers={"Connection": "close", "Accept-Encoding": "identity"})
        resp = conn.getresponse()
        body = resp.read(65536)
        return resp.status == 200 and (b"login-password" in body or b"ADM Kiosk" in body)
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


def listener_pids(port):
    """Processos do servidor nesta porta. O netstat, sem privilégios, mostra às vezes o PID 0."""
    found = set()
    try:
        out = subprocess.check_output(["netstat", "-ano", "-p", "TCP"],
                                      creationflags=NO_WINDOW, text=True, errors="replace")
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() not in ("TCP", "TCPV6"):
            continue
        _host, sep, local_port = parts[1].rpartition(":")
        if sep and local_port == str(port) and parts[-1].isdigit() and int(parts[-1]) > 4:
            found.add(int(parts[-1]))
    if found:
        return sorted(found)
    result = ps("(Get-NetTCPConnection -LocalPort %d -ErrorAction SilentlyContinue).OwningProcess" % port)
    for token in re.findall(r"\d+", result.stdout or ""):
        pid = int(token)
        if pid > 4:
            found.add(pid)
    return sorted(found)


def command_line(pid):
    if pid <= 4:
        return ""
    try:
        result = run(["wmic", "process", "where", "ProcessId=%d" % pid, "get", "CommandLine", "/value"])
    except OSError:
        result = None
    if result is not None:
        for line in ((result.stdout or "") + "\n" + (result.stderr or "")).splitlines():
            if "CommandLine=" in line:
                return line.split("CommandLine=", 1)[1].strip()
    for script in (
        "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid,
        "(Get-WmiObject Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid,
    ):
        result = ps(script)
        text = (result.stdout or "").strip()
        if result.returncode == 0 and text:
            return text
    return ""


def _terminate(pid):
    handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, int(pid))
    if not handle:
        return False
    ok = bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
    ctypes.windll.kernel32.CloseHandle(handle)
    return ok


def stop_broken_server(port):
    """Fecha um servidor ADM antigo que ocupa a porta e não envia o painel."""
    me = {os.getpid()}
    parent = os.getppid()
    if parent:
        me.add(parent)
    for pid in listener_pids(port):
        if pid in me:
            continue
        cmd = command_line(pid).lower()
        if "adm_kiosk" in cmd or "adm-kiosk-servidor" in cmd:
            _terminate(pid)
    for _ in range(12):
        if not port_busy(port):
            return True
        time.sleep(0.25)
    return False


def _wait(port, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if page_ok(port):
            return True
        time.sleep(0.4)
    return False


def ensure_page(port, start_local):
    """Garante que o painel responde. Se o servidor antigo não enviar a página, fecha-o
    e arranca o servidor deste programa."""
    if page_ok(port):
        return True
    if port_busy(port):
        print("A porta %s está aberta, mas a página não chega. O navegador mostra "
              "\"This page isn't working\". A fechar o servidor antigo…" % port)
        if not stop_broken_server(port):
            print("ERRO: não foi possível fechar o programa que ocupa a porta %s." % port)
            return False
    if is_installed():
        print("A iniciar o servidor instalado…")
        if start_server() and page_ok(port):
            return True
        print("O servidor instalado não enviou a página. A usar o programa que está aberto…")
        if port_busy(port):
            stop_broken_server(port)
    print("A executar o servidor desta janela…")
    start_local()
    return _wait(port, 20)


def copy_file(src, dst):
    for attempt in range(10):
        try:
            shutil.copy2(src, dst)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(1)


def make_shortcut(path, description):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(INSTALLED_EXE):
        target, arguments, icon = INSTALLED_EXE, "", INSTALLED_EXE + ",0"
    else:
        target, arguments, icon = pythonw_path(), '"' + installed_script() + '"', pythonw_path() + ",0"
    ps("$l = (New-Object -ComObject WScript.Shell).CreateShortcut(" + q(path) + "); "
       f"$l.TargetPath = {q(target)}; $l.Arguments = {q(arguments)}; $l.WorkingDirectory = {q(INSTALL_DIR)}; "
       f"$l.IconLocation = {q(icon)}; $l.Description = {q(description)}; $l.Save()")


def install_python_files():
    """Copia os .py e a pasta static (versão de 32 bits, sem executável único)."""
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for name in APP_FILES:
        src = os.path.join(here, name)
        if not os.path.isfile(src):
            print("ERRO: falta o ficheiro", name)
            return False
        copy_file(src, os.path.join(INSTALL_DIR, name))
    static_src = os.path.join(here, "static")
    static_dst = os.path.join(INSTALL_DIR, "static")
    if os.path.isdir(static_dst):
        shutil.rmtree(static_dst, ignore_errors=True)
    shutil.copytree(static_src, static_dst)
    with open(os.path.join(INSTALL_DIR, "pythonw.path"), "w", encoding="utf-8") as handle:
        handle.write(pythonw_path())
    return True


def install(port=None):
    """Instala ou atualiza na porta escolhida na janela; as mensagens vão para print()."""
    try:
        port = int(PORT if port is None else port)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        print("ERRO: a porta tem de ser um número entre 1 e 65535.")
        return False
    print(f"[1/7] A parar a versão instalada (se existir)... Porta escolhida: {port}")
    stop_everything_installed()
    if port_busy(port):
        print(f"ERRO: a porta {port} está ocupada por outro programa.")
        print("      Escolha uma das portas livres sugeridas na janela e volte a instalar.")
        return False

    print("[2/7] A copiar o programa para", INSTALL_DIR)
    os.makedirs(INSTALL_DIR, exist_ok=True)
    src = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        if os.path.normcase(src) != os.path.normcase(INSTALLED_EXE):
            copy_file(src, INSTALLED_EXE)
    elif not install_python_files():
        return False
    if os.path.isfile(OLD_PANEL_EXE):
        os.remove(OLD_PANEL_EXE)

    print("[3/7] Dados em", DATA_DIR)
    os.makedirs(DATA_DIR, exist_ok=True)
    old_data = os.path.join(os.path.dirname(src), "data")
    if (os.path.isfile(os.path.join(old_data, "adm_kiosk.db"))
            and not os.path.isfile(os.path.join(DATA_DIR, "adm_kiosk.db"))):
        shutil.copytree(old_data, DATA_DIR, dirs_exist_ok=True)
        print("      Dados existentes copiados de", old_data)
    # A janela pode arrancar o servidor com o utilizador atual: precisa de escrever os dados.
    run(["icacls", DATA_ROOT, "/grant", "*S-1-5-32-545:(OI)(CI)M", "/T", "/Q"])
    save_http_port(port)

    print(f"[4/7] A configurar a firewall do Windows (porta {port})...")
    remove_fw_rules()
    add_fw_rule(f"ADM Kiosk Servidor (HTTP {port})", "TCP", port)
    add_fw_rule(f"ADM Kiosk Servidor (Descoberta UDP {srv.DISCOVERY_PORT})", "UDP", srv.DISCOVERY_PORT)

    print("[5/7] A configurar o arranque automático com o Windows...")
    if os.path.isfile(INSTALLED_EXE):
        task_exe, task_args = INSTALLED_EXE, f'--serve --port {port} --data "{DATA_DIR}"'
    else:
        task_exe = pythonw_path()
        task_args = f'"{installed_script()}" --serve --port {port} --data "{DATA_DIR}"'
    r = ps(
        f"$a = New-ScheduledTaskAction -Execute {q(task_exe)} -Argument {q(task_args)} -WorkingDirectory {q(INSTALL_DIR)}; "
        "$t = New-ScheduledTaskTrigger -AtStartup; "
        "$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest; "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) "
        "-StartWhenAvailable -MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName {q(TASK)} -Action $a -Trigger $t -Principal $p -Settings $s "
        "-Description 'ADM Kiosk - servidor de administracao (Harmonico Lucas)' -Force | Out-Null; "
        f"Start-ScheduledTask -TaskName {q(TASK)}"
    )
    if r.returncode != 0:
        print("ERRO ao criar a tarefa de arranque: " + (r.stderr or r.stdout).strip())
        return False

    print("[6/7] A criar o atalho no ambiente de trabalho e no menu Iniciar...")
    for old in OLD_LINKS:
        if os.path.isfile(old):
            os.remove(old)
    make_shortcut(DESKTOP_LINK, "Servidor e painel de administração ADM Kiosk")
    make_shortcut(os.path.join(START_MENU, "ADM Kiosk Servidor.lnk"), "Servidor e painel de administração ADM Kiosk")

    print("[7/7] A registar em Aplicações instaladas...")
    try:
        uninstall_key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0,
                                           winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY)
    except OSError:
        uninstall_key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0, winreg.KEY_WRITE)
    with uninstall_key as k:
        for name, value in (
            ("DisplayName", "ADM Kiosk - Servidor de administração"),
            ("DisplayVersion", srv.VERSION),
            ("Publisher", "Harmonico Lucas"),
            ("DisplayIcon", INSTALLED_EXE if os.path.isfile(INSTALLED_EXE) else pythonw_path()),
            ("InstallLocation", INSTALL_DIR),
            ("UninstallString", " ".join(f'"{part}"' for part in program_command(["--uninstall"]))),
        ):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        if os.path.isfile(INSTALLED_EXE):
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, os.path.getsize(INSTALLED_EXE) // 1024)

    print("A aguardar o arranque do servidor...")
    if not _wait(port, 20):
        print("ATENÇÃO: o servidor ainda não respondeu. Use \"Iniciar servidor\" ou reinicie o computador.")
        return False
    print("Instalação concluída. O servidor arranca sozinho sempre que o Windows inicia.")
    return True


def uninstall(delete_data):
    print("A parar o servidor...")
    stop_everything_installed()
    ps(f"Unregister-ScheduledTask -TaskName {q(TASK)} -Confirm:$false -ErrorAction SilentlyContinue")
    print("A remover as regras da firewall, os atalhos e o registo...")
    remove_fw_rules()
    for path in (DESKTOP_LINK,) + OLD_LINKS:
        if os.path.isfile(path):
            os.remove(path)
    shutil.rmtree(START_MENU, ignore_errors=True)
    for flags in (winreg.KEY_WOW64_64KEY, 0):
        try:
            winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, flags, 0)
        except OSError:
            pass
    if delete_data:
        shutil.rmtree(DATA_ROOT, ignore_errors=True)
        print("Dados apagados.")
    elif os.path.isdir(DATA_DIR):
        print("Os dados foram mantidos em", DATA_DIR)
    if running_installed():
        # O próprio executável está nesta pasta: é apagada depois de este programa fechar.
        subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 4 >nul & rmdir /s /q "{INSTALL_DIR}"',
                         creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS)
    else:
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    print("O servidor ADM Kiosk foi desinstalado.")
    return True


def _loopback(url):
    """O Internet Explorer resolve 'localhost' em IPv6 e, com proxy, mostra
    'This page can't be displayed' mesmo com o servidor a funcionar."""
    return re.sub(r"://localhost(?=[:/]|$)", "://127.0.0.1", str(url), count=1, flags=re.I)


def _proxy_bypass():
    """Garante que o Internet Explorer não manda o painel para o proxy."""
    if os.name != "nt":
        return
    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE)
    except OSError:
        return
    try:
        try:
            current, _ = winreg.QueryValueEx(key, "ProxyOverride")
        except OSError:
            current = ""
        items = [part.strip() for part in str(current).split(";") if part.strip()]
        have = {part.lower() for part in items}
        for extra in ("<local>", "localhost", "127.0.0.1"):
            if extra.lower() not in have:
                items.append(extra)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, ";".join(items))
    except OSError:
        return
    finally:
        key.Close()
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(None, 39, None, 0)  # definições alteradas
        wininet.InternetSetOptionW(None, 37, None, 0)  # reler
    except (AttributeError, OSError):
        pass


def _browser_exe():
    roots = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
             os.environ.get("LocalAppData", "")]
    names = (
        os.path.join("Google", "Chrome", "Application", "chrome.exe"),
        os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
    )
    for root in roots:
        if not root:
            continue
        for name in names:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                return path
    return ""


def open_in_browser(url):
    """Abre o painel em 127.0.0.1, sem proxy. No Windows antigo o Internet Explorer
    é o navegador predefinido e falha com 'This page can't be displayed'."""
    url = _loopback(url)
    _proxy_bypass()
    exe = _browser_exe()
    if exe:
        # --no-proxy-server: o Chrome/Edge não manda o painel para o proxy do Windows.
        subprocess.Popen([exe, "--no-proxy-server", url], creationflags=NO_WINDOW, close_fds=True)
        return True
    try:
        webbrowser.open(url)
        return True
    except OSError:
        return False


def open_panel(port=None):
    open_in_browser(f"http://127.0.0.1:{port or current_port()}/")


def serve(args):
    """Servidor sem janela: as mensagens vão para servidor.log na pasta dos dados."""
    if sys.stdout is None or sys.stderr is None:
        data = args[args.index("--data") + 1] if "--data" in args[:-1] else os.path.dirname(sys.executable)
        os.makedirs(data, exist_ok=True)
        log = os.path.join(data, "servidor.log")
        if os.path.isfile(log) and os.path.getsize(log) > 5 * 1024 * 1024:
            os.replace(log, log + ".1")
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
    srv.main(args)


def entry():
    args = sys.argv[1:]
    if args[:1] == ["--serve"]:
        serve(args[1:])
    elif args[:1] == ["--stop"]:
        stop_server()
    elif args and args[0].startswith("--port"):
        serve(args)
    else:
        import adm_kiosk_gui
        adm_kiosk_gui.main(args)


if __name__ == "__main__":
    entry()
