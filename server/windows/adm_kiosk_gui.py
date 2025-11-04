"""
Janela do ADM Kiosk Servidor (Windows): instalar, iniciar/parar o servidor, abrir o painel de
administração pelos endereços do servidor e desinstalar.
"""

import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import adm_kiosk_server as srv
import adm_kiosk_servidor_win as win
from adm_kiosk_win_common import INSTALL_DIR, PORT, active_ports, current_port, free_ports, port_busy

YELLOW = "#efe21a"
YELLOW_DARK = "#d8cb0c"
BLACK = "#121417"
INK = "#1c1f24"
DIM = "#6b7079"
FAINT = "#9aa0a8"
BG = "#f4f5f7"
SURFACE = "#ffffff"
BORDER = "#e5e7eb"
GREEN = "#0a8a4f"
RED = "#d21034"
BLUE = "#1f5fa8"
FONT = "Segoe UI"


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(srv.__file__)))
    return os.path.join(base, *parts)


class LogWriter:
    """Recebe os print() (instalação, servidor local) e envia-os, linha a linha, para a janela."""

    def __init__(self, out):
        self.out = out
        self.buf = ""

    def write(self, text):
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip() and not ('"GET ' in line or '"POST ' in line or '"PUT ' in line or '"DELETE ' in line):
                self.out.put(("log", line.rstrip()))
        return len(text)

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self, action=None, delete_data=None, install_port=None):
        super().__init__()
        self.title("ADM Kiosk Servidor")
        self.configure(bg=BG)
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96)
        self.geometry(f"{int(780 * self.scale)}x{int(760 * self.scale)}")
        self.minsize(int(700 * self.scale), int(680 * self.scale))
        self.ui = queue.Queue()
        sys.stdout = sys.stderr = LogWriter(self.ui)
        self.busy = False
        self.local_server = False
        self.local_port = None
        self._free = []
        self._auto_install = action == "install"
        self.shown_links = None
        self.state_running = False
        try:
            self.logo = tk.PhotoImage(file=resource("static", "logo.png"))
            self.iconphoto(True, self.logo)
            self.logo_small = self.logo.subsample(3, 3)
        except tk.TclError:
            self.logo = self.logo_small = None
        self._styles()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if install_port:
            self.port_var.set(str(install_port))
        self.after(100, self._pump)
        self.refresh(first=True)
        self.after(200, self.load_port_suggestions)
        if action == "uninstall":
            self.after(400, lambda: self.do_uninstall(delete_data))

    # ------------------------------------------------------------------ aparência

    def _styles(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", font=(FONT, 10), background=BG, foreground=INK)
        st.configure("TButton", padding=(14, 8), background=SURFACE, foreground=INK, bordercolor=BORDER,
                     lightcolor=SURFACE, darkcolor=SURFACE, focuscolor=SURFACE, relief="flat")
        st.map("TButton", background=[("disabled", BG), ("active", "#eef0f2")],
               foreground=[("disabled", FAINT)])
        st.configure("Primary.TButton", background=YELLOW, foreground=BLACK, bordercolor=YELLOW_DARK,
                     lightcolor=YELLOW, darkcolor=YELLOW, font=(FONT, 10, "bold"))
        st.map("Primary.TButton", background=[("disabled", "#f3eea0"), ("active", YELLOW_DARK)])
        st.configure("Danger.TButton", foreground=RED)
        st.map("Danger.TButton", background=[("active", "#fde8ec")], foreground=[("disabled", FAINT)])
        st.configure("Horizontal.TProgressbar", troughcolor=BORDER, background=YELLOW, bordercolor=BORDER,
                     lightcolor=YELLOW, darkcolor=YELLOW)

    def card(self, parent, title=None, subtitle=None):
        outer = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(outer, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        if title:
            tk.Label(inner, text=title, bg=SURFACE, fg=INK, font=(FONT, 11, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(inner, text=subtitle, bg=SURFACE, fg=DIM, font=(FONT, 9), justify="left",
                     wraplength=int(680 * self.scale)).pack(anchor="w", pady=(2, 8))
        return outer, inner

    def _build(self):
        head = tk.Frame(self, bg=BLACK, height=int(86 * self.scale))
        head.pack(fill="x")
        head.pack_propagate(False)
        if self.logo_small:
            box = tk.Frame(head, bg="white", padx=4, pady=4)
            box.pack(side="left", padx=(22, 14), pady=14)
            tk.Label(box, image=self.logo_small, bg="white").pack()
        titles = tk.Frame(head, bg=BLACK)
        titles.pack(side="left", pady=16)
        tk.Label(titles, text="ADM Kiosk Servidor", bg=BLACK, fg="white", font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(titles, text="Servidor de administração de ecrãs · Aeroportos de Moçambique, E.P.",
                 bg=BLACK, fg=FAINT, font=(FONT, 9)).pack(anchor="w")
        tk.Frame(self, bg=YELLOW, height=3).pack(fill="x")

        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=22, pady=(0, 10))
        tk.Label(foot, text="Desenvolvido por Harmonico Lucas", bg=BG, fg=FAINT, font=(FONT, 9)).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=18)

        # Estado e ações
        _, st = self.card(body)
        row = tk.Frame(st, bg=SURFACE)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=14, height=14, bg=SURFACE, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 10))
        self.dot_id = self.dot.create_oval(2, 2, 13, 13, fill=FAINT, outline="")
        text = tk.Frame(row, bg=SURFACE)
        text.pack(side="left", fill="x", expand=True)
        self.status = tk.Label(text, text="A verificar…", bg=SURFACE, fg=INK, font=(FONT, 12, "bold"))
        self.status.pack(anchor="w")
        self.detail = tk.Label(text, text="", bg=SURFACE, fg=DIM, font=(FONT, 9))
        self.detail.pack(anchor="w")

        buttons = tk.Frame(st, bg=SURFACE)
        buttons.pack(fill="x", pady=(14, 0))
        self.btn_open = ttk.Button(buttons, text="Abrir painel de administração", style="Primary.TButton",
                                   command=lambda: self.open_url(f"http://127.0.0.1:{self.main_port()}/"))
        self.btn_open.pack(side="left")
        self.btn_server = ttk.Button(buttons, text="Iniciar servidor", command=self.toggle_server)
        self.btn_server.pack(side="left", padx=8)
        self.btn_install = ttk.Button(buttons, text="Instalar", command=self.do_install)
        self.btn_install.pack(side="left")
        self.btn_uninstall = ttk.Button(buttons, text="Desinstalar", style="Danger.TButton",
                                        command=lambda: self.do_uninstall(None))
        self.btn_uninstall.pack(side="right")
        self.progress = ttk.Progressbar(st, mode="indeterminate", style="Horizontal.TProgressbar")

        # Porta, escolhida antes de instalar
        _, porta = self.card(body, "Porta do painel",
                             "Escolha a porta antes de instalar. O programa deteta as que estão livres "
                             "e sugere a primeira.")
        prow = tk.Frame(porta, bg=SURFACE)
        prow.pack(fill="x")
        tk.Label(prow, text="Porta", bg=SURFACE, fg=INK, font=(FONT, 10, "bold")).pack(side="left")
        self.port_var = tk.StringVar()
        self.port_entry = ttk.Entry(prow, textvariable=self.port_var, width=8, font=(FONT, 12))
        self.port_entry.pack(side="left", padx=(10, 8))
        ttk.Button(prow, text="Detetar portas livres", command=self.load_port_suggestions).pack(side="left")
        self.port_hint = tk.Label(porta, text="A detetar portas livres…", bg=SURFACE, fg=DIM,
                                  font=(FONT, 9), justify="left", wraplength=int(680 * self.scale))
        self.port_hint.pack(anchor="w", pady=(8, 0))
        self.port_picks = tk.Frame(porta, bg=SURFACE)
        self.port_picks.pack(fill="x", pady=(8, 0))
        self.port_var.trace_add("write", lambda *_: self._hint())

        # Endereços
        _, links = self.card(body, "Endereços do painel",
                             "Clique num endereço para abrir o painel de administração no navegador. Use estes "
                             "endereços também para configurar os equipamentos (botão direito para copiar).")
        self.links = tk.Text(links, height=6, bg=SURFACE, fg=INK, relief="flat", font=("Consolas", 11),
                             cursor="arrow", wrap="none", highlightthickness=0, padx=2, pady=2)
        self.links.pack(fill="x")
        self.links.tag_configure("link", foreground=BLUE, underline=True)
        self.links.tag_configure("muted", foreground=FAINT, font=(FONT, 9))
        self.links.tag_bind("link", "<Enter>", lambda e: self.links.configure(cursor="hand2"))
        self.links.tag_bind("link", "<Leave>", lambda e: self.links.configure(cursor="arrow"))
        self.links.configure(state="disabled")

        # Atividade
        _, act = self.card(body, "Atividade")
        self.log = tk.Text(act, height=7, bg="#fafafa", fg=INK, relief="flat", font=("Consolas", 9),
                           wrap="word", highlightthickness=1, highlightbackground=BORDER, padx=8, pady=6)
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ estado

    def main_port(self):
        if self.local_server and self.local_port:
            return self.local_port
        return current_port()

    def panel_port(self):
        """Porta escrita na janela; antes de instalar é a que os endereços mostram."""
        if self.local_server and self.local_port:
            return self.local_port
        if win.is_installed():
            return current_port()
        text = self.port_var.get().strip()
        return int(text) if text.isdigit() and 1 <= int(text) <= 65535 else PORT

    def load_port_suggestions(self):
        """Deteta portas livres e preenche a sugestão, sem apagar uma porta já escrita."""
        self.port_hint.configure(text="A detetar portas livres…")

        def done(ports):
            self._free = list(ports or [])
            self._fill_picks()
            if not self.port_var.get().strip():
                if win.is_installed():
                    self.port_var.set(str(current_port()))
                elif self._free:
                    self.port_var.set(str(self._free[0]))
                else:
                    self.port_var.set(str(PORT))
            else:
                self._hint()
            if self._auto_install:
                self._auto_install = False
                self.do_install()

        self.background(free_ports, done, busy=False)

    def _fill_picks(self):
        for child in self.port_picks.winfo_children():
            child.destroy()
        if not self._free:
            tk.Label(self.port_picks, text="Nenhuma porta livre na lista habitual. Escreva outra porta.",
                     bg=SURFACE, fg=DIM, font=(FONT, 9)).pack(side="left")
            return
        tk.Label(self.port_picks, text="Livres:", bg=SURFACE, fg=DIM, font=(FONT, 9)).pack(side="left", padx=(0, 6))
        for number in self._free:
            ttk.Button(self.port_picks, text=str(number),
                       command=lambda n=number: self.port_var.set(str(n))).pack(side="left", padx=(0, 4))

    def _hint(self):
        if not hasattr(self, "port_hint"):
            return
        text = self.port_var.get().strip()
        best = self._free[0] if self._free else None
        if not text:
            msg = f"Sugestão: {best}." if best else "Escreva o número da porta."
        elif not text.isdigit() or not 1 <= int(text) <= 65535:
            msg = "A porta tem de ser um número entre 1 e 65535."
        else:
            number = int(text)
            if win.is_installed() and number == current_port():
                msg = f"Porta atual do servidor: {number}. Pode alterá-la antes de reinstalar."
            elif best == number:
                msg = f"Sugestão: a porta {number} está livre e será usada se não alterar."
            elif number in self._free:
                msg = f"A porta {number} está livre."
            elif best:
                msg = f"A porta {number} não está entre as livres. Sugestão: {best}."
            else:
                msg = f"A porta {number} será verificada ao instalar."
        self.port_hint.configure(text=msg)
        if hasattr(self, "links") and not self.busy:
            self.show_links(self.state_running)

    def chosen_port(self):
        """Porta que o utilizador confirmou. Se estiver ocupada, propõe uma livre."""
        text = self.port_var.get().strip()
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            messagebox.showwarning("ADM Kiosk Servidor", "Indique uma porta entre 1 e 65535.")
            return None
        number = int(text)
        if port_busy(number) and not win.page_ok(number):
            suggestion = next((item for item in self._free if item != number), None)
            if suggestion and messagebox.askyesno(
                    "ADM Kiosk Servidor",
                    f"A porta {number} já está a ser usada por outro programa.\n\n"
                    f"Usar a porta {suggestion}, que está livre?"):
                self.port_var.set(str(suggestion))
                return suggestion
            messagebox.showwarning(
                "ADM Kiosk Servidor",
                f"A porta {number} já está a ser usada.\n\n"
                "Carregue em \"Detetar portas livres\" e escolha uma das sugeridas.")
            return None
        return number

    def refresh(self, first=False):
        if not self.busy:
            installed = win.is_installed()
            port = self.main_port()
            running = port_busy(port)
            self.state_running = running
            if running:
                self.dot.itemconfigure(self.dot_id, fill=GREEN)
                self.status.configure(text=f"Servidor a funcionar (porta {port})")
            else:
                self.dot.itemconfigure(self.dot_id, fill=RED if installed else FAINT)
                self.status.configure(text="Servidor parado")
            if self.local_server:
                self.detail.configure(text="A correr nesta janela, sem instalação: fecha quando fechar a janela.")
            elif installed:
                self.detail.configure(text=f"Instalado em {INSTALL_DIR} · arranca sozinho com o Windows")
            else:
                self.detail.configure(text="Não instalado. Escolha a porta abaixo e clique em Instalar "
                                      "para o servidor arrancar sozinho com o Windows.")
            self.btn_install.configure(text="Reinstalar / atualizar" if installed else "Instalar",
                                       style="TButton" if installed else "Primary.TButton")
            self.btn_open.configure(style="Primary.TButton" if installed or running else "TButton")
            if running:
                self.btn_server.configure(text="Parar servidor", state="disabled" if self.local_server else "normal")
            else:
                self.btn_server.configure(text="Iniciar servidor" if installed else "Executar sem instalar",
                                          state="normal")
            self.btn_uninstall.configure(state="normal" if installed else "disabled")
            self.btn_open.configure(state="normal" if installed or running else "disabled")
            self.btn_install.configure(state="normal")
            self.show_links(running)
            if first and installed and not running:
                self.log_line("O servidor está parado: a iniciar…")
                self.start_server(open_after=False)
        self.after(2000, self.refresh)

    def show_links(self, running):
        if self.local_server and self.local_port:
            ports = [self.local_port]
        elif win.is_installed():
            ports = active_ports()
        else:
            ports = [self.panel_port()]
        ips = ["127.0.0.1"] + [ip for ip in srv.local_addresses() if not ip.startswith("169.254.") and ip != "127.0.0.1"]
        urls = [f"http://{ip}:{p}/" for p in ports for ip in ips]
        key = (tuple(urls), running)
        if key == self.shown_links:
            return
        self.shown_links = key
        t = self.links
        t.configure(state="normal")
        t.delete("1.0", "end")
        for i, url in enumerate(urls):
            tag = f"u{i}"
            t.insert("end", url, ("link", tag))
            if i == 0:
                t.insert("end", "   porta principal", "muted")
            t.insert("end", "\n")
            t.tag_bind(tag, "<Button-1>", lambda e, u=url: self.open_url(u))
            t.tag_bind(tag, "<Button-3>", lambda e, u=url: self.copy(u))
        if not running:
            t.insert("end", "O servidor está parado: ao clicar num endereço, é iniciado primeiro.", "muted")
        t.configure(height=min(max(len(urls) + (0 if running else 1), 3), 9), state="disabled")

    # ------------------------------------------------------------------ utilitários

    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def copy(self, url):
        self.clipboard_clear()
        self.clipboard_append(url)
        self.log_line(f"Copiado: {url}")

    def _pump(self):
        try:
            while True:
                kind, payload = self.ui.get_nowait()
                if kind == "log":
                    self.log_line(payload)
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def background(self, work, done=None, busy=True):
        """Executa work() fora da janela; done(resultado) volta a correr na janela."""
        if busy:
            self.set_busy(True)

        def runner():
            try:
                result = work()
            except Exception as exc:  # mostrar o erro em vez de fechar a janela
                print(f"ERRO: {exc}")
                result = None
            self.ui.put(("call", lambda: self._finish(done, result, busy)))
        threading.Thread(target=runner, daemon=True).start()

    def _finish(self, done, result, busy):
        if busy:
            self.set_busy(False)
        if done:
            done(result)
        self.shown_links = None

    def set_busy(self, busy):
        self.busy = busy
        for b in (self.btn_open, self.btn_server, self.btn_install, self.btn_uninstall):
            b.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.pack(fill="x", pady=(14, 0))
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    # ------------------------------------------------------------------ ações

    def open_url(self, url):
        url = win._loopback(url)
        found = re.search(r":(\d+)", url)
        port = int(found.group(1)) if found else self.panel_port()

        def work():
            if win.page_ok(port):
                return True
            if not win.is_installed() and not port_busy(port) and not self.local_server:
                return "ask"
            return win.ensure_page(port, lambda: self._start_local_thread(port))

        def done(result):
            if result == "ask":
                if messagebox.askyesno("ADM Kiosk Servidor", "O servidor não está a funcionar.\n\n"
                                       "Executar agora, sem instalar?"):
                    self.run_local(then_open=url)
                return
            if result:
                win.open_in_browser(url)
                return
            messagebox.showerror(
                "ADM Kiosk Servidor",
                "O painel não abriu: o servidor não enviou a página.\n\n"
                "Se ficou um servidor antigo a correr, feche-o e carregue outra vez "
                "em \"Abrir painel\". Os detalhes estão em Atividade.")

        self.background(work, done)

    def start_server(self, open_after=None):
        self.log_line("A iniciar o servidor…")

        def done(ok):
            if ok:
                self.log_line(f"Servidor a funcionar na porta {current_port()}.")
                if open_after:
                    win.open_in_browser(open_after if isinstance(open_after, str) else
                                        f"http://127.0.0.1:{current_port()}/")
            else:
                self.log_line("O servidor não respondeu. Reinstale ou reinicie o computador.")
                messagebox.showerror("ADM Kiosk Servidor", "O servidor não respondeu.\n\n"
                                     "Experimente \"Reinstalar / atualizar\" ou reiniciar o computador.")
        self.background(win.start_server, done)

    def toggle_server(self):
        if not win.is_installed() and not self.state_running:
            self.run_local()
        elif self.state_running:
            self.stop_server()
        else:
            self.start_server()

    def stop_server(self):
        if not messagebox.askyesno("ADM Kiosk Servidor", "Parar o servidor?\n\n"
                                   "Os ecrãs deixam de poder ser geridos até voltar a iniciá-lo."):
            return
        self.log_line("A parar o servidor…")

        def done(stopped):
            if stopped:
                self.log_line("Servidor parado.")
            elif win.relaunch_as_admin("--stop"):
                self.log_line("Foi pedido ao Windows para parar o servidor (privilégios de administrador).")
            else:
                self.log_line("Não foi possível parar o servidor.")
        self.background(win.stop_server, done)

    def _start_local_thread(self, port=None):
        if self.local_server:
            return
        if not port:
            port = self.panel_port()
        port = int(port)
        self.local_port = port
        self.local_server = True
        print(f"A executar o servidor sem instalar, na porta {port} "
              "(dados na pasta 'data' ao lado deste programa)…")
        threading.Thread(target=lambda: srv.main(["--port", str(port)]), daemon=True).start()

    def run_local(self, then_open=None):
        port = self.chosen_port()
        if not port:
            return
        if win.page_ok(port):
            if then_open:
                win.open_in_browser(win._loopback(then_open))
            return
        if port_busy(port) and not win.stop_broken_server(port):
            messagebox.showwarning("ADM Kiosk Servidor",
                                   f"A porta {port} está a ser usada por outro programa, que não envia o painel.")
            return
        self._start_local_thread(port)

        def done(ok):
            if not then_open:
                return
            if ok:
                win.open_in_browser(win._loopback(then_open))
            else:
                messagebox.showerror("ADM Kiosk Servidor",
                                     "O servidor não enviou a página. Veja os detalhes em Atividade.")
        self.background(lambda: win._wait(port, 20), done, busy=False)

    def do_install(self):
        port = self.chosen_port()
        if not port:
            return
        if not win.is_admin():
            if win.relaunch_as_admin(f"--install --port {port}"):
                self.destroy()
            else:
                messagebox.showwarning("ADM Kiosk Servidor",
                                       "É preciso aceitar o pedido de administrador do Windows para instalar.")
            return
        self.log_line(f"Instalação iniciada na porta {port}.")

        def done(ok):
            if ok:
                if messagebox.askyesno("ADM Kiosk Servidor",
                                       "Instalação concluída.\n\nFoi criado o atalho \"ADM Kiosk Servidor\" no "
                                       "ambiente de trabalho.\n\nAbrir agora o painel de administração?"):
                    win.open_panel(port)
            else:
                messagebox.showerror("ADM Kiosk Servidor", "A instalação não foi concluída. Veja os detalhes em "
                                     "\"Atividade\".")
        self.background(win.install, done)

    def do_uninstall(self, delete_data):
        if delete_data is None:
            if not messagebox.askyesno("ADM Kiosk Servidor", "Desinstalar o servidor ADM Kiosk?"):
                return
            answer = messagebox.askyesnocancel(
                "ADM Kiosk Servidor",
                "Apagar também os dados?\n\n(equipamentos registados, configurações e palavra-passe)\n\n"
                "Sim = apagar   ·   Não = manter para uma futura instalação")
            if answer is None:
                return
            delete_data = answer
        if not win.is_admin():
            if win.relaunch_as_admin("--uninstall --delete-data" if delete_data else "--uninstall --keep-data"):
                self.destroy()
            else:
                messagebox.showwarning("ADM Kiosk Servidor",
                                       "É preciso aceitar o pedido de administrador do Windows para desinstalar.")
            return

        def done(ok):
            messagebox.showinfo("ADM Kiosk Servidor", "O servidor ADM Kiosk foi desinstalado.")
            if win.running_installed():
                self.destroy()
        self.background(lambda: win.uninstall(delete_data), done)

    def on_close(self):
        if self.busy:
            messagebox.showinfo("ADM Kiosk Servidor", "Aguarde até a operação terminar.")
            return
        if self.local_server and not messagebox.askyesno(
                "ADM Kiosk Servidor", "O servidor está a correr nesta janela, sem instalação.\n\n"
                "Ao fechar, deixa de funcionar. Fechar mesmo assim?"):
            return
        self.destroy()


def main(args):
    action = delete_data = install_port = None
    if "--port" in args:
        index = args.index("--port")
        if index + 1 < len(args) and args[index + 1].isdigit():
            install_port = int(args[index + 1])
    if "--install" in args:
        action = "install"
    elif "--uninstall" in args:
        action = "uninstall"
        if "--delete-data" in args:
            delete_data = True
        elif "--keep-data" in args:
            delete_data = False
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App(action, delete_data, install_port).mainloop()
