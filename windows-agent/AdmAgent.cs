// ADM Kiosk - Agente para computadores / netboxes Windows
// Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas
//
// Executável autónomo (WinForms, .NET Framework 4). O cabeçalho do programa pede
// o subsistema do Windows XP, por isso corre do XP SP3 (com .NET 4) ao Windows 11.
// Toda a comunicação é HTTP/UDP na rede local: não precisa de Internet.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Management;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("ADM Kiosk Agente")]
[assembly: System.Reflection.AssemblyProduct("ADM Kiosk")]
[assembly: System.Reflection.AssemblyCompany("Harmonico Lucas")]
[assembly: System.Reflection.AssemblyCopyright("Aeroportos de Moçambique, E.P. - Desenvolvido por Harmonico Lucas")]
[assembly: System.Reflection.AssemblyVersion("2.6.1.0")]

static class Agent
{
    public const string Version = "2.6.1";
    public static string Dir;
    public static string ServerUrl = "";
    public static volatile bool Paused;
    public static volatile string StatusLine = "A iniciar…";
    public static volatile string DetailLine = "";
    public static MainForm Ui;

    static readonly object StateLock = new object();
    static readonly object LogLock = new object();
    static readonly List<string> LogLines = new List<string>();
    static Settings st = new Settings();
    static string discovered = "";
    static volatile int failures;
    static bool skipConfigured;
    static bool hostOk;
    static DateTime lastReload = DateTime.MinValue;
    static DateTime boot = DateTime.Now;
    static string manufacturer = "", model = "", osName = "";
    static bool infoReady;
    static int liveRunning;

    public static Settings State { get { lock (StateLock) return st.Copy(); } }

    [STAThread]
    static void Main(string[] args)
    {
        Dir = AppDomain.CurrentDomain.BaseDirectory;
        if (args != null && args.Length > 0 && args[0] == "--selftest")
        {
            File.WriteAllText(Path.Combine(Dir, "selftest-result.txt"), Js.SelfTest() ? "OK" : "FAIL");
            return;
        }
        bool created;
        Mutex mutex = new Mutex(true, "Local\\ADMKioskAgent", out created);
        if (!created) return;
        GC.KeepAlive(mutex);
        try { SetProcessDPIAware(); } catch { }
        try { SetThreadExecutionState(0x80000003); } catch { }
        try { SystemParametersInfo(0x0011, 0, IntPtr.Zero, 0); } catch { }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.ThreadException += delegate(object s, ThreadExceptionEventArgs e) { Log("Erro: " + e.Exception.Message); };
        LoadConfig();
        Log("Agente " + Version + " iniciado (ID " + DeviceId() + ")");
        Ui = new MainForm();
        Thread worker = new Thread(Loop);
        worker.IsBackground = true;
        worker.Start();
        Thread waiter = new Thread(WaitLoop);
        waiter.IsBackground = true;
        waiter.Start();
        Application.Run(Ui);
    }

    public static void Log(string msg)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + msg;
        try
        {
            string path = Path.Combine(Dir, "agent.log");
            if (File.Exists(path) && new FileInfo(path).Length > 1000000)
            {
                File.Copy(path, path + ".old", true);
                File.Delete(path);
            }
            File.AppendAllText(path, line + Environment.NewLine, Encoding.UTF8);
        }
        catch { }
        lock (LogLock)
        {
            LogLines.Add(line);
            if (LogLines.Count > 200) LogLines.RemoveAt(0);
        }
    }

    public static string LogText()
    {
        lock (LogLock) return string.Join(Environment.NewLine, LogLines.ToArray());
    }

    public static void Async(ThreadStart work)
    {
        Thread t = new Thread(work);
        t.IsBackground = true;
        t.Start();
    }

    // ---------------------------------------------------------------- configuração

    static void LoadConfig()
    {
        JVal cfg = Js.ReadFile(Path.Combine(Dir, "agent.json"));
        JVal saved = Js.ReadFile(Path.Combine(Dir, "state.json"));
        lock (StateLock)
        {
            st.Id = saved.Str("id", "");
            st.ConfigVersion = saved.Int("configVersion", 0);
            st.Name = saved.Str("name", "");
            st.Terminal = saved.Str("terminal", "");
            st.ScreenType = saved.Str("screenType", "");
            st.Gate = saved.Str("gate", "");
            st.Url = saved.Str("url", cfg.Str("url", ""));
            st.Browser = saved.Str("browser", cfg.Str("browser", ""));
            st.Zoom = saved.Int("zoom", cfg.Int("zoom", 100));
            st.RefreshSeconds = saved.Int("refreshSeconds", 0);
            st.KioskEnabled = saved.Bool("kioskEnabled", true);
            st.ReloadOnError = saved.Bool("reloadOnError", true);
            st.RetryDelaySeconds = saved.Int("retryDelaySeconds", 10);
            if (st.Zoom < 50 || st.Zoom > 300) st.Zoom = 100;
        }
        ServerUrl = NormalizeServer(cfg.Str("serverUrl", ""));
    }

    public static void ApplyLocal(string server, string url, string browser, int zoom)
    {
        ServerUrl = NormalizeServer(server);
        JVal cfg = Js.ReadFile(Path.Combine(Dir, "agent.json"));
        Dictionary<string, JVal> o = cfg.O ?? new Dictionary<string, JVal>();
        o["serverUrl"] = JVal.String(ServerUrl);
        o["url"] = JVal.String(url ?? "");
        o["browser"] = JVal.String(browser ?? "");
        o["zoom"] = JVal.Number(zoom.ToString(CultureInfo.InvariantCulture));
        cfg.K = JKind.Obj;
        cfg.O = o;
        Js.WriteFile(Path.Combine(Dir, "agent.json"), cfg);
        lock (StateLock)
        {
            st.Url = (url ?? "").Trim();
            st.Browser = browser ?? "";
            st.Zoom = zoom;
        }
        SaveState();
        failures = 0;
        discovered = "";
        Log("Configuração local guardada.");
    }

    public static void SaveState()
    {
        Settings s = State;
        Js.WriteFile(Path.Combine(Dir, "state.json"), s.ToJson());
    }

    static string NormalizeServer(string url)
    {
        url = (url ?? "").Trim().TrimEnd('/');
        if (url.Length == 0) return "";
        if (!url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
            !url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            url = "http://" + url;
        try
        {
            Uri u = new Uri(url);
            if (u.IsDefaultPort && u.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase))
                return "http://" + u.Host + ":8080";
            return u.Scheme + "://" + u.Authority;
        }
        catch { return url; }
    }

    static string DeviceId()
    {
        lock (StateLock) { if (st.Id.Length > 0) return st.Id; }
        string guid = Reg(@"SOFTWARE\Microsoft\Cryptography", "MachineGuid");
        if (guid.Length == 0) guid = Guid.NewGuid().ToString("D");
        NetInfo net = GetNet();
        byte[] hash = SHA1.Create().ComputeHash(Encoding.UTF8.GetBytes(guid + "|" + net.Mac));
        StringBuilder sb = new StringBuilder("w");
        for (int i = 0; i < hash.Length && sb.Length < 24; i++) sb.Append(hash[i].ToString("x2"));
        string id = sb.ToString().Substring(0, 24);
        lock (StateLock) st.Id = id;
        SaveState();
        return id;
    }

    static string Reg(string path, string name)
    {
        try
        {
            object v = RegistryLocal(path, name);
            return v == null ? "" : v.ToString();
        }
        catch { return ""; }
    }

    static object RegistryLocal(string path, string name)
    {
        object native = RegNative(path, name);
        if (native != null) return native;
        using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(path))
            return k == null ? null : k.GetValue(name);
    }

    /* KEY_WOW64_64KEY existe a partir do XP e, num processo de 32 bits, lê a vista
       de 64 bits quando o Windows a tem. No XP de 32 bits é a única vista. */
    static object RegNative(string path, string name)
    {
        IntPtr key;
        int type;
        int size = 0;
        if (RegOpenKeyEx(new IntPtr(unchecked((int)0x80000002)), path, 0, 0x20019 | 0x0100, out key) != 0)
            return null;
        try
        {
            if (RegQueryValueEx(key, name, 0, out type, null, ref size) != 0 || size <= 0 || size > 8192)
                return null;
            byte[] buf = new byte[size];
            if (RegQueryValueEx(key, name, 0, out type, buf, ref size) != 0) return null;
            if (type == 1 || type == 2)
            {
                string text = Encoding.Unicode.GetString(buf);
                int zero = text.IndexOf('\0');
                return zero >= 0 ? text.Substring(0, zero) : text;
            }
            if (type == 4 && buf.Length >= 4) return BitConverter.ToInt32(buf, 0);
            return null;
        }
        finally { RegCloseKey(key); }
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Auto)]
    static extern int RegOpenKeyEx(IntPtr key, string sub, int options, int sam, out IntPtr result);
    [DllImport("advapi32.dll", CharSet = CharSet.Auto)]
    static extern int RegQueryValueEx(IntPtr key, string name, int reserved, out int type, byte[] data, ref int size);
    [DllImport("advapi32.dll")]
    static extern int RegCloseKey(IntPtr key);

    // ---------------------------------------------------------------- equipamento / rede (só LAN)

    public static NetInfo GetNet()
    {
        NetInfo info = new NetInfo();
        NetInfo withGw = null;
        try
        {
            using (ManagementObjectSearcher s = new ManagementObjectSearcher(
                "SELECT IPAddress, IPSubnet, DefaultIPGateway, DNSServerSearchOrder, MACAddress, Description, Index FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True"))
            {
                foreach (ManagementObject mo in s.Get())
                {
                    using (mo)
                    {
                        NetInfo n = ReadNic(mo);
                        if (n.Ip.Length == 0) continue;
                        if (withGw == null && n.Gateway.Length > 0) withGw = n;
                        if (info.Ip.Length == 0) info = n;
                    }
                }
            }
        }
        catch (Exception ex) { Log("rede: " + ex.Message); }
        if (withGw != null) info = withGw;
        if (info.Ip.Length == 0)
        {
            try
            {
                foreach (IPAddress a in Dns.GetHostAddresses(Dns.GetHostName()))
                {
                    if (a.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(a))
                    {
                        info.Ip = a.ToString();
                        break;
                    }
                }
            }
            catch { }
        }
        return info;
    }

    static NetInfo ReadNic(ManagementObject mo)
    {
        NetInfo n = new NetInfo();
        string[] ips = mo["IPAddress"] as string[];
        string[] masks = mo["IPSubnet"] as string[];
        if (ips != null)
        {
            for (int i = 0; i < ips.Length; i++)
            {
                IPAddress parsed;
                if (IPAddress.TryParse(ips[i], out parsed) && parsed.AddressFamily == AddressFamily.InterNetwork)
                {
                    n.Ip = ips[i];
                    if (masks != null && i < masks.Length) n.Mask = masks[i];
                    break;
                }
            }
        }
        if (n.Mask.Length > 0)
        {
            int bits = 0;
            foreach (string p in n.Mask.Split('.'))
            {
                int b;
                if (int.TryParse(p, out b)) { while (b != 0) { bits += b & 1; b >>= 1; } }
            }
            n.Prefix = bits;
        }
        string[] gw = mo["DefaultIPGateway"] as string[];
        if (gw != null)
        {
            foreach (string g in gw)
            {
                IPAddress parsed;
                if (IPAddress.TryParse(g, out parsed) && parsed.AddressFamily == AddressFamily.InterNetwork)
                { n.Gateway = g; break; }
            }
        }
        string[] dns = mo["DNSServerSearchOrder"] as string[];
        if (dns != null) n.Dns.AddRange(dns);
        n.Mac = ((mo["MACAddress"] as string) ?? "").Replace('-', ':').ToUpperInvariant();
        n.Iface = (mo["Description"] as string) ?? "";
        n.Transport = "Ethernet";
        try
        {
            int index = Convert.ToInt32(mo["Index"]);
            using (ManagementObjectSearcher s = new ManagementObjectSearcher(
                "SELECT Name, NetConnectionID FROM Win32_NetworkAdapter WHERE Index = " + index))
            {
                foreach (ManagementObject a in s.Get())
                {
                    using (a)
                    {
                        string blob = ((a["Name"] as string) ?? "") + " " + ((a["NetConnectionID"] as string) ?? "");
                        if (blob.IndexOf("Wi-Fi", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            blob.IndexOf("Wireless", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            blob.IndexOf("WLAN", StringComparison.OrdinalIgnoreCase) >= 0)
                            n.Transport = "Wi-Fi";
                    }
                }
            }
        }
        catch { }
        return n;
    }

    static void EnsureInfo()
    {
        if (infoReady) return;
        try
        {
            using (ManagementObjectSearcher s = new ManagementObjectSearcher(
                "SELECT Manufacturer, Model FROM Win32_ComputerSystem"))
            {
                foreach (ManagementObject mo in s.Get())
                {
                    using (mo)
                    {
                        manufacturer = (mo["Manufacturer"] as string) ?? "";
                        model = (mo["Model"] as string) ?? "";
                    }
                }
            }
            using (ManagementObjectSearcher s = new ManagementObjectSearcher(
                "SELECT Caption, Version, LastBootUpTime FROM Win32_OperatingSystem"))
            {
                foreach (ManagementObject mo in s.Get())
                {
                    using (mo)
                    {
                        osName = (((mo["Caption"] as string) ?? "") + " (" + ((mo["Version"] as string) ?? "") + ")").Trim();
                        string raw = mo["LastBootUpTime"] as string;
                        if (raw != null) boot = ManagementDateTimeConverter.ToDateTime(raw);
                    }
                }
            }
        }
        catch { }
        if (osName.Length == 0)
        {
            string product = Reg(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName");
            osName = product.Length > 0 ? product : Environment.OSVersion.VersionString;
        }
        infoReady = true;
    }

    static string Resolution()
    {
        try
        {
            Rectangle b = Screen.PrimaryScreen.Bounds;
            return b.Width + "x" + b.Height;
        }
        catch { return ""; }
    }

    // ---------------------------------------------------------------- navegador

    static string ProfileDir { get { return Path.Combine(Dir, "browser-profile"); } }

    static Browser FindBrowser()
    {
        string want;
        lock (StateLock) want = st.Browser ?? "";
        Browser[] all = Browsers();
        foreach (Browser b in all) if (b.Kind == want && File.Exists(b.Path)) return b;
        foreach (Browser b in all) if (File.Exists(b.Path)) return b;
        return null;
    }

    static Browser[] Browsers()
    {
        List<string> roots = new List<string>();
        AddRoot(roots, Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles));
        AddRoot(roots, Environment.GetEnvironmentVariable("ProgramFiles(x86)"));
        AddRoot(roots, Environment.GetEnvironmentVariable("ProgramW6432"));
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        List<Browser> list = new List<Browser>();
        foreach (string r in roots)
        {
            list.Add(new Browser("edge", "Microsoft Edge", Path.Combine(r, @"Microsoft\Edge\Application\msedge.exe")));
            list.Add(new Browser("chrome", "Google Chrome", Path.Combine(r, @"Google\Chrome\Application\chrome.exe")));
            list.Add(new Browser("firefox", "Mozilla Firefox", Path.Combine(r, @"Mozilla Firefox\firefox.exe")));
            list.Add(new Browser("ie", "Internet Explorer", Path.Combine(r, @"Internet Explorer\iexplore.exe")));
        }
        list.Add(new Browser("chrome", "Google Chrome", Path.Combine(local, @"Google\Chrome\Application\chrome.exe")));
        return list.ToArray();
    }

    static void AddRoot(List<string> roots, string path)
    {
        if (string.IsNullOrEmpty(path)) return;
        foreach (string r in roots) if (string.Equals(r, path, StringComparison.OrdinalIgnoreCase)) return;
        roots.Add(path);
    }

    static int[] BrowserPids()
    {
        string needle = ProfileDir.ToLowerInvariant();
        string url;
        lock (StateLock) url = (st.Url ?? "").ToLowerInvariant();
        List<int> ids = new List<int>();
        try
        {
            using (ManagementObjectSearcher s = new ManagementObjectSearcher(
                "SELECT ProcessId, Name, CommandLine FROM Win32_Process WHERE Name = 'msedge.exe' OR Name = 'chrome.exe' OR Name = 'firefox.exe' OR Name = 'iexplore.exe'"))
            {
                foreach (ManagementObject mo in s.Get())
                {
                    using (mo)
                    {
                        string cmd = ((mo["CommandLine"] as string) ?? "").ToLowerInvariant();
                        string name = ((mo["Name"] as string) ?? "").ToLowerInvariant();
                        bool mine = cmd.Contains(needle) || (name == "iexplore.exe" && url.Length > 0 && cmd.Contains(url));
                        if (mine) ids.Add(Convert.ToInt32(mo["ProcessId"]));
                    }
                }
            }
        }
        catch (Exception ex) { Log("processos: " + ex.Message); }
        return ids.ToArray();
    }

    public static void StopKiosk()
    {
        foreach (int pid in BrowserPids())
        {
            try { Process.GetProcessById(pid).Kill(); } catch { }
        }
        Thread.Sleep(800);
    }

    public static void StartKiosk()
    {
        if (Paused) return;
        Settings s = State;
        if (s.Url.Length == 0) return;
        Browser b = FindBrowser();
        if (b == null) { Log("Nenhum navegador encontrado (Edge, Chrome, Firefox ou Internet Explorer)."); return; }
        try { Directory.CreateDirectory(ProfileDir); } catch { }
        string scale = (s.Zoom / 100.0).ToString("0.##", CultureInfo.InvariantCulture);
        string args;
        if (b.Kind == "ie")
        {
            args = (s.KioskEnabled ? "-k " : "") + Quote(s.Url);
        }
        else if (b.Kind == "firefox")
        {
            int major = 0;
            try { major = FileVersionInfo.GetVersionInfo(b.Path).FileMajorPart; } catch { }
            string mode = s.KioskEnabled ? (major >= 71 || major == 0 ? "-kiosk " : "-fullscreen ") : "";
            try
            {
                File.WriteAllText(Path.Combine(ProfileDir, "user.js"),
                    "user_pref(\"layout.css.devPixelsPerPx\", \"" + scale + "\");\r\n" +
                    "user_pref(\"browser.sessionstore.resume_from_crash\", false);\r\n" +
                    "user_pref(\"browser.shell.checkDefaultBrowser\", false);\r\n" +
                    "user_pref(\"network.captive-portal-service.enabled\", false);\r\n" +
                    "user_pref(\"network.connectivity-service.enabled\", false);\r\n" +
                    "user_pref(\"network.proxy.type\", 0);\r\n", Encoding.UTF8);
            }
            catch { }
            args = mode + "-no-remote -profile " + Quote(ProfileDir) + " " + Quote(s.Url);
        }
        else
        {
            // direct:// evita um proxy de sistema que, sem Internet, impediria a página da LAN.
            string mode = s.KioskEnabled ? "--kiosk " + Quote(s.Url) : "--start-fullscreen --app=" + Quote(s.Url);
            args = mode + " --user-data-dir=" + Quote(ProfileDir) +
                " --no-first-run --no-default-browser-check --disable-session-crashed-bubble" +
                " --noerrdialogs --disable-infobars --disable-sync --disable-background-networking" +
                " --disable-component-update --disable-domain-reliability --no-pings" +
                " --proxy-server=direct:// --proxy-bypass-list=* " +
                "--disable-features=Translate,DnsOverHttps,MediaRouter,OptimizationHints,DialMediaRouteProvider" +
                " --autoplay-policy=no-user-gesture-required --force-device-scale-factor=" + scale;
            if (b.Kind == "edge" && s.KioskEnabled) args += " --edge-kiosk-type=fullscreen";
        }
        Log("A abrir " + b.Label + ": " + s.Url);
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = b.Path;
            psi.Arguments = args;
            psi.UseShellExecute = false;
            Process.Start(psi);
        }
        catch (Exception ex) { Log("Falha ao abrir o navegador: " + ex.Message); }
        lastReload = DateTime.Now;
    }

    public static void RestartKiosk() { StopKiosk(); StartKiosk(); }

    public static void ReloadPage()
    {
        if (Paused) return;
        int[] pids = BrowserPids();
        if (pids.Length == 0) { StartKiosk(); return; }
        foreach (int pid in pids)
        {
            try
            {
                Process p = Process.GetProcessById(pid);
                if (p.MainWindowHandle != IntPtr.Zero)
                {
                    Focus(p.MainWindowHandle);
                    Thread.Sleep(200);
                    Key("F5", false, false, false);
                    lastReload = DateTime.Now;
                    return;
                }
            }
            catch { }
        }
        RestartKiosk();
    }

    static string Quote(string s) { return "\"" + (s ?? "").Replace("\"", "") + "\""; }

    static bool PageHostOk()
    {
        Settings s = State;
        if (s.Url.Length == 0) return false;
        try
        {
            Uri u = new Uri(s.Url);
            if (u.Host.Length == 0) return false;
            int port = u.Port;
            using (TcpClient client = new TcpClient())
            {
                IAsyncResult ar = client.BeginConnect(u.Host, port, null, null);
                bool ok = ar.AsyncWaitHandle.WaitOne(2500) && client.Connected;
                try { client.Close(); } catch { }
                return ok;
            }
        }
        catch { return false; }
    }

    static void UpdatePageState(out string page, out string error)
    {
        if (Paused) { page = "paused"; error = "Modo kiosk em pausa — ambiente de trabalho"; return; }
        Settings s = State;
        if (s.Url.Length == 0) { page = "nolinks"; error = ""; return; }
        if (FindBrowser() == null) { page = "error"; error = "Navegador não encontrado"; return; }
        if (!hostOk) { page = "offline"; error = "Página inacessível na rede"; return; }
        if (BrowserPids().Length == 0) { page = "loading"; error = ""; return; }
        page = "ok";
        error = "";
    }

    // ---------------------------------------------------------------- servidor na rede local

    static List<string> BroadcastTargets()
    {
        List<string> list = new List<string>();
        try
        {
            foreach (NetworkInterface ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.OperationalStatus != OperationalStatus.Up) continue;
                if (ni.NetworkInterfaceType == NetworkInterfaceType.Loopback) continue;
                foreach (UnicastIPAddressInformation ua in ni.GetIPProperties().UnicastAddresses)
                {
                    try
                    {
                        if (ua.Address.AddressFamily != AddressFamily.InterNetwork) continue;
                        if (IPAddress.IsLoopback(ua.Address) || ua.IPv4Mask == null) continue;
                        if (ua.Address.ToString().StartsWith("169.254.")) continue;
                        byte[] ip = ua.Address.GetAddressBytes();
                        byte[] mk = ua.IPv4Mask.GetAddressBytes();
                        if (ip.Length != 4 || mk.Length != 4) continue;
                        byte[] bc = new byte[4];
                        for (int i = 0; i < 4; i++) bc[i] = (byte)(ip[i] | (mk[i] ^ 255));
                        string text = new IPAddress(bc).ToString();
                        if (!list.Contains(text)) list.Add(text);
                    }
                    catch { }
                }
            }
        }
        catch { }
        if (!list.Contains("255.255.255.255")) list.Add("255.255.255.255");
        return list;
    }

    static string ServerFromPacket(byte[] data, int length)
    {
        string text = Encoding.UTF8.GetString(data, 0, length).Trim();
        const string prefix = "ADM-KIOSK-ANNOUNCE ";
        if (text.StartsWith(prefix, StringComparison.Ordinal)) text = text.Substring(prefix.Length);
        try
        {
            string url = Js.Parse(text).Str("server", "").TrimEnd('/');
            if (url.StartsWith("http", StringComparison.OrdinalIgnoreCase)) return url;
        }
        catch { }
        return "";
    }

    static string FindServer()
    {
        using (UdpClient udp = new UdpClient())
        {
            udp.EnableBroadcast = true;
            try { udp.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true); } catch { }
            try { udp.Client.Bind(new IPEndPoint(IPAddress.Any, 47801)); }
            catch
            {
                try { udp.Client.Bind(new IPEndPoint(IPAddress.Any, 0)); } catch { }
            }
            udp.Client.ReceiveTimeout = 600;
            byte[] msg = Encoding.ASCII.GetBytes("ADM-KIOSK-DISCOVER");
            for (int attempt = 0; attempt < 3; attempt++)
            {
                foreach (string target in BroadcastTargets())
                {
                    try { udp.Send(msg, msg.Length, target, 47800); } catch { }
                }
                DateTime deadline = DateTime.UtcNow.AddMilliseconds(1200);
                while (DateTime.UtcNow < deadline)
                {
                    try
                    {
                        IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
                        byte[] data = udp.Receive(ref remote);
                        string url = ServerFromPacket(data, data.Length);
                        if (url.Length > 0) { discovered = url; return url; }
                    }
                    catch { break; }
                }
            }
        }
        return "";
    }

    static string GetServer()
    {
        if (ServerUrl.Length > 0 && !skipConfigured && failures < 2) return ServerUrl;
        if (discovered.Length > 0) return discovered;
        string found = "";
        try { found = FindServer(); } catch (Exception ex) { Log("descoberta: " + ex.Message); }
        if (found.Length > 0) return found;
        return ServerUrl;
    }

    static string Post(string url, byte[] body, string ctype, int timeout)
    {
        HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
        req.Method = "POST";
        req.ContentType = ctype;
        req.Timeout = timeout;
        req.ReadWriteTimeout = timeout;
        req.Proxy = new WebProxy();
        req.KeepAlive = true;
        req.UserAgent = "ADM-Kiosk-Agent/" + Version;
        req.ContentLength = body.Length;
        using (Stream rs = req.GetRequestStream()) rs.Write(body, 0, body.Length);
        using (HttpWebResponse res = (HttpWebResponse)req.GetResponse())
        using (StreamReader reader = new StreamReader(res.GetResponseStream(), Encoding.UTF8))
            return reader.ReadToEnd();
    }

    static JVal PostJson(string url, string json, int timeout)
    {
        string text = Post(url, Encoding.UTF8.GetBytes(json), "application/json; charset=utf-8", timeout);
        return text == null || text.Trim().Length == 0 ? new JVal() : Js.Parse(text);
    }

    static readonly object HbLock = new object();

    static void Heartbeat()
    {
        lock (HbLock) HeartbeatCore();
    }

    static void HeartbeatCore()
    {
        string server = GetServer();
        if (server.Length == 0)
        {
            StatusLine = "Servidor não encontrado na rede";
            DetailLine = "Indique o endereço (ex.: 192.168.1.10:8080) ou ligue o servidor na mesma rede.";
            if (failures % 6 == 0) Log(StatusLine);
            failures++;
            return;
        }
        EnsureInfo();
        NetInfo net = GetNet();
        Settings s = State;
        string page, error;
        UpdatePageState(out page, out error);
        Browser b = FindBrowser();
        string json = "{\"id\":" + Js.Esc(DeviceId()) +
            ",\"platform\":\"windows\",\"configVersion\":" + s.ConfigVersion +
            ",\"device\":{" +
            "\"manufacturer\":" + Js.Esc(manufacturer) + ",\"model\":" + Js.Esc(model) +
            ",\"os\":" + Js.Esc(osName) + ",\"hostname\":" + Js.Esc(Environment.MachineName) +
            ",\"user\":" + Js.Esc(Environment.UserDomainName + "\\" + Environment.UserName) +
            ",\"resolution\":" + Js.Esc(Resolution()) +
            ",\"uptimeSec\":" + (int)(DateTime.Now - boot).TotalSeconds +
            ",\"appVersion\":" + Js.Esc("Agente " + Version) +
            ",\"isLauncher\":true,\"browserName\":" + Js.Esc(b == null ? "não encontrado" : b.Label) +
            "},\"network\":{" +
            "\"ip\":" + Js.Esc(net.Ip) + ",\"prefix\":" + net.Prefix + ",\"mask\":" + Js.Esc(net.Mask) +
            ",\"gateway\":" + Js.Esc(net.Gateway) + ",\"dns\":" + Js.StringArray(net.Dns) +
            ",\"mac\":" + Js.Esc(net.Mac) + ",\"iface\":" + Js.Esc(net.Iface) +
            ",\"transport\":" + Js.Esc(net.Transport) +
            "},\"state\":{\"url\":" + Js.Esc(s.Url) + ",\"page\":" + Js.Esc(page) + ",\"error\":" + Js.Esc(error) +
            "},\"settings\":{" +
            "\"name\":" + Js.Esc(s.Name) + ",\"terminal\":" + Js.Esc(s.Terminal) +
            ",\"screenType\":" + Js.Esc(s.ScreenType) + ",\"gate\":" + Js.Esc(s.Gate) +
            ",\"url\":" + Js.Esc(s.Url) + ",\"zoom\":" + s.Zoom +
            ",\"refreshSeconds\":" + s.RefreshSeconds + ",\"autoScroll\":false,\"autoScrollSeconds\":10" +
            ",\"kioskEnabled\":" + (s.KioskEnabled ? "true" : "false") +
            ",\"reloadOnError\":" + (s.ReloadOnError ? "true" : "false") +
            ",\"retryDelaySeconds\":" + s.RetryDelaySeconds + ",\"browser\":" + Js.Esc(s.Browser) + "}}";
        JVal r;
        try
        {
            r = PostJson(server + "/api/device/heartbeat", json, 8000);
            failures = 0;
            if (ServerUrl.Length > 0 && server == ServerUrl) skipConfigured = false;
            StatusLine = "Ligado a " + server;
            DetailLine = "IP " + (net.Ip.Length == 0 ? "—" : net.Ip);
        }
        catch (Exception ex)
        {
            failures++;
            StatusLine = "Sem contacto com " + server;
            DetailLine = ex.Message;
            Log(StatusLine + ": " + ex.Message);
            if (failures >= 2)
            {
                skipConfigured = true;
                discovered = "";
            }
            return;
        }
        JVal cfg = r["config"];
        if (cfg != null && cfg.K == JKind.Obj) ApplyRemote(cfg);
        JVal cmds = r["commands"];
        if (cmds != null && cmds.A != null)
        {
            foreach (JVal c in cmds.A) RunCommand(server, c);
        }
        JVal live = r["live"];
        if (live != null && live.Bool("active", false)) StartLive(server, live);
    }

    static void ApplyRemote(JVal c)
    {
        int version = c.Int("version", 0);
        Settings s = State;
        if (version <= 0 || version == s.ConfigVersion) return;
        JVal file = Js.ReadFile(Path.Combine(Dir, "agent.json"));
        string newUrl = c.Str("url", "");
        if (newUrl.Length == 0) newUrl = file.Str("url", s.Url);
        bool restart = s.Url != newUrl || s.Browser != c.Str("browser", "") || s.Zoom != c.Int("zoom", 100) ||
                       s.KioskEnabled != c.Bool("kioskEnabled", true);
        lock (StateLock)
        {
            st.ConfigVersion = version;
            st.Name = c.Str("name", "");
            st.Terminal = c.Str("terminal", "");
            st.ScreenType = c.Str("screenType", "");
            st.Gate = c.Str("gate", "");
            st.Url = newUrl;
            st.Browser = c.Str("browser", "");
            st.Zoom = c.Int("zoom", 100);
            st.RefreshSeconds = c.Int("refreshSeconds", 0);
            st.KioskEnabled = c.Bool("kioskEnabled", true);
            st.ReloadOnError = c.Bool("reloadOnError", true);
            st.RetryDelaySeconds = c.Int("retryDelaySeconds", 10);
        }
        SaveState();
        Log("Configuração remota v" + version + " aplicada");
        if (Ui != null && Ui.IsHandleCreated)
            Ui.BeginInvoke((MethodInvoker)delegate { Ui.LoadFields(); });
        if (restart && !Paused) RestartKiosk();
    }

    static void SendResult(string server, long id, bool ok, string message)
    {
        try
        {
            PostJson(server + "/api/device/command-result",
                "{\"id\":" + Js.Esc(DeviceId()) + ",\"commandId\":" + id +
                ",\"ok\":" + (ok ? "true" : "false") + ",\"message\":" + Js.Esc(message) + "}", 8000);
        }
        catch { }
    }

    static void RunCommand(string server, JVal c)
    {
        string type = c.Str("type", "");
        long id = c.Long("id", 0);
        Log("Comando remoto: " + type);
        JVal payload = c["payload"] ?? new JVal();
        if (type == "reload" || type == "restart_app" || type == "clear_cache")
        {
            Paused = false;
            if (Ui != null && Ui.IsHandleCreated) Ui.BeginInvoke((MethodInvoker)delegate { Ui.SendBack(); });
        }
        if (type == "reload")
        {
            if (BrowserPids().Length == 0) StartKiosk(); else ReloadPage();
            SendResult(server, id, true, "Página recarregada");
        }
        else if (type == "clear_cache")
        {
            StopKiosk();
            try { Directory.Delete(ProfileDir, true); } catch { }
            StartKiosk();
            SendResult(server, id, true, "Cache limpa e navegador reaberto");
        }
        else if (type == "restart_app")
        {
            RestartKiosk();
            SendResult(server, id, true, "Navegador reiniciado");
        }
        else if (type == "identify")
        {
            int seconds = payload.Int("seconds", 20);
            NetInfo net = GetNet();
            Settings s = State;
            string title = s.Name.Length > 0 ? s.Name : Environment.MachineName;
            string text = title + "\r\nIP " + net.Ip + "   Gateway " + net.Gateway +
                "\r\nID " + DeviceId().Substring(16).ToUpperInvariant();
            ShowBanner(text, seconds);
            SendResult(server, id, true, "Identificação mostrada " + seconds + "s");
        }
        else if (type == "screenshot")
        {
            try
            {
                byte[] jpeg = Capture(1280, 70L);
                Post(server + "/api/device/screenshot?id=" + DeviceId() + "&cmd=" + id, jpeg, "image/jpeg", 15000);
            }
            catch (Exception ex) { SendResult(server, id, false, "Falha na captura: " + ex.Message); }
        }
        else if (type == "reboot")
        {
            SendResult(server, id, true, "A forçar o reinício do computador");
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "shutdown.exe";
                psi.Arguments = "/r /f /t 0";
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                Process.Start(psi);
            }
            catch (Exception ex) { Log("reinício: " + ex.Message); }
        }
        else SendResult(server, id, false, "Comando não suportado: " + type);
    }

    static void ShowBanner(string text, int seconds)
    {
        Thread t = new Thread(delegate()
        {
            Form f = new Form();
            f.FormBorderStyle = FormBorderStyle.None;
            f.WindowState = FormWindowState.Maximized;
            f.TopMost = true;
            f.ShowInTaskbar = false;
            f.BackColor = Color.FromArgb(17, 17, 17);
            f.Opacity = 0.92;
            Label l = new Label();
            l.Dock = DockStyle.Fill;
            l.TextAlign = ContentAlignment.MiddleCenter;
            l.ForeColor = Color.FromArgb(239, 226, 26);
            l.Font = new Font("Tahoma", 36, FontStyle.Bold);
            l.Text = text;
            f.Controls.Add(l);
            System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
            timer.Interval = Math.Max(3, seconds) * 1000;
            timer.Tick += delegate { timer.Stop(); f.Close(); };
            f.Shown += delegate { timer.Start(); };
            Application.Run(f);
        });
        t.SetApartmentState(ApartmentState.STA);
        t.IsBackground = true;
        t.Start();
    }

    static void Loop()
    {
        Thread.Sleep(4000);
        hostOk = PageHostOk();
        if (!Paused) StartKiosk();
        DateTime nextCheck = DateTime.Now;
        DateTime nextHb = DateTime.Now;
        while (true)
        {
            try
            {
                DateTime now = DateTime.Now;
                if (now >= nextCheck)
                {
                    nextCheck = now.AddSeconds(5);
                    bool was = hostOk;
                    hostOk = PageHostOk();
                    bool running = BrowserPids().Length > 0;
                    Settings s = State;
                    if (!Paused && s.Url.Length > 0 && !running) StartKiosk();
                    else if (!Paused && hostOk && !was && s.ReloadOnError)
                    {
                        Log("Ligação à página restabelecida: a recarregar.");
                        ReloadPage();
                    }
                    else if (!Paused && s.RefreshSeconds > 0 && hostOk &&
                             (now - lastReload).TotalSeconds >= s.RefreshSeconds)
                        ReloadPage();
                }
                if (now >= nextHb)
                {
                    nextHb = now.AddSeconds(10);
                    Heartbeat();
                }
                Thread.Sleep(250);
            }
            catch (Exception ex)
            {
                Log("Erro: " + ex.Message);
                Thread.Sleep(2000);
            }
        }
    }

    static void WaitLoop()
    {
        long gen = -1;
        while (true)
        {
            string server = "";
            try { server = GetServer(); } catch { }
            if (server.Length == 0 || failures > 0) { Thread.Sleep(2000); continue; }
            try
            {
                JVal r = PostJson(server + "/api/device/wait?id=" + DeviceId() + "&gen=" + gen, "{}", 35000);
                gen = r.Long("gen", gen);
                if (r.Bool("wake", false)) Heartbeat();
                JVal live = r["live"];
                if (live != null && live.Bool("active", false)) StartLive(server, live);
            }
            catch { Thread.Sleep(3000); }
        }
    }

    static void StartLive(string server, JVal live)
    {
        if (Interlocked.CompareExchange(ref liveRunning, 1, 0) != 0) return;
        Thread t = new Thread(delegate() { Stream(server, live); });
        t.IsBackground = true;
        t.Start();
    }

    static void Stream(string server, JVal live)
    {
        byte[] last = null;
        int fails = 0;
        try
        {
            while (live != null && live.Bool("active", false))
            {
                int interval = Math.Max(50, Math.Min(5000, live.Int("intervalMs", 100)));
                string q = live.Str("quality", "normal");
                int width = q == "high" ? 1920 : q == "low" ? 1024 : 1366;
                long quality = q == "high" ? 70L : q == "low" ? 40L : 55L;
                DateTime started = DateTime.UtcNow;
                byte[] jpeg = null;
                try { jpeg = Capture(width, quality); } catch { }
                bool same = jpeg == null || (last != null && Same(jpeg, last));
                JVal r;
                try
                {
                    string text = Post(server + "/api/device/frame?id=" + DeviceId(),
                        same ? new byte[0] : jpeg, "image/jpeg", 10000);
                    r = text == null || text.Trim().Length == 0 ? new JVal() : Js.Parse(text);
                    fails = 0;
                }
                catch (Exception ex)
                {
                    if (++fails >= 3) { Log("Sessão ao vivo interrompida: " + ex.Message); return; }
                    Thread.Sleep(500);
                    continue;
                }
                if (!same) last = jpeg;
                live = r["live"];
                JVal inputs = r["inputs"];
                if (inputs != null && inputs.A != null)
                {
                    foreach (JVal ev in inputs.A)
                    {
                        try { RunInput(ev); } catch (Exception ex) { Log("Controlo remoto: " + ex.Message); }
                    }
                }
                int rest = interval - (int)(DateTime.UtcNow - started).TotalMilliseconds;
                if (rest > 0) Thread.Sleep(rest);
            }
        }
        finally { Interlocked.Exchange(ref liveRunning, 0); }
    }

    static bool Same(byte[] a, byte[] b)
    {
        if (a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }

    // ---------------------------------------------------------------- ecrã, rato e teclado

    public static byte[] Capture(int maxWidth, long quality)
    {
        Rectangle b = Screen.PrimaryScreen.Bounds;
        using (Bitmap bmp = new Bitmap(b.Width, b.Height, PixelFormat.Format24bppRgb))
        {
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.CopyFromScreen(b.Left, b.Top, 0, 0, b.Size, CopyPixelOperation.SourceCopy);
                CURSORINFO ci = new CURSORINFO();
                ci.cbSize = Marshal.SizeOf(typeof(CURSORINFO));
                if (GetCursorInfo(ref ci) && ci.flags == 1)
                {
                    IntPtr hdc = g.GetHdc();
                    DrawIcon(hdc, ci.pt.X - b.Left, ci.pt.Y - b.Top, ci.hCursor);
                    g.ReleaseHdc(hdc);
                }
            }
            Bitmap output = bmp;
            bool scaled = false;
            int w = bmp.Width, h = bmp.Height;
            if (maxWidth > 0 && w > maxWidth)
            {
                h = bmp.Height * maxWidth / bmp.Width;
                w = maxWidth;
            }
            if ((w & 1) == 1) w--;
            if ((h & 1) == 1) h--;
            if (w != bmp.Width || h != bmp.Height)
            {
                output = new Bitmap(w, h, PixelFormat.Format24bppRgb);
                using (Graphics g2 = Graphics.FromImage(output))
                {
                    g2.InterpolationMode = InterpolationMode.Bilinear;
                    g2.DrawImage(bmp, 0, 0, w, h);
                }
                scaled = true;
            }
            try
            {
                ImageCodecInfo codec = null;
                foreach (ImageCodecInfo c in ImageCodecInfo.GetImageEncoders())
                    if (c.MimeType == "image/jpeg") codec = c;
                if (codec == null) return null;
                EncoderParameters ep = new EncoderParameters(1);
                ep.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, quality);
                using (MemoryStream ms = new MemoryStream())
                {
                    output.Save(ms, codec, ep);
                    return ms.ToArray();
                }
            }
            finally { if (scaled) output.Dispose(); }
        }
    }

    static void MoveTo(double x, double y)
    {
        Rectangle b = Screen.PrimaryScreen.Bounds;
        SetCursorPos(b.Left + (int)(Clamp(x) * (b.Width - 1)), b.Top + (int)(Clamp(y) * (b.Height - 1)));
    }

    static double Clamp(double v) { if (v < 0) return 0; if (v > 1) return 1; return v; }

    static void RunInput(JVal ev)
    {
        double x = ev.Num("x", 0.5), y = ev.Num("y", 0.5);
        bool right = ev.Str("button", "") == "right";
        string t = ev.Str("type", "");
        if (t == "click") Click(x, y, false, 1);
        else if (t == "dblclick") Click(x, y, false, 2);
        else if (t == "rightclick") Click(x, y, true, 1);
        else if (t == "move") MoveTo(x, y);
        else if (t == "down") Button(x, y, right, true);
        else if (t == "up") Button(x, y, right, false);
        else if (t == "scroll") Wheel(x, y, (int)ev.Num("dy", 1));
        else if (t == "key") Key(ev.Str("key", ""), ev.Bool("ctrl", false), ev.Bool("alt", false), ev.Bool("shift", false));
        else if (t == "text") Text(ev.Str("text", ""));
    }

    static void Click(double x, double y, bool right, int count)
    {
        MoveTo(x, y);
        uint down = right ? 0x0008u : 0x0002u;
        uint up = right ? 0x0010u : 0x0004u;
        for (int i = 0; i < count; i++)
        {
            mouse_event(down, 0, 0, 0, UIntPtr.Zero);
            mouse_event(up, 0, 0, 0, UIntPtr.Zero);
            Thread.Sleep(40);
        }
    }

    static void Button(double x, double y, bool right, bool down)
    {
        MoveTo(x, y);
        uint flag = right ? (down ? 0x0008u : 0x0010u) : (down ? 0x0002u : 0x0004u);
        mouse_event(flag, 0, 0, 0, UIntPtr.Zero);
    }

    static void Wheel(double x, double y, int notches)
    {
        MoveTo(x, y);
        mouse_event(0x0800, 0, 0, -notches * 120, UIntPtr.Zero);
    }

    public static bool Key(string name, bool ctrl, bool alt, bool shift)
    {
        if (string.IsNullOrEmpty(name)) return false;
        byte vk;
        if (!VkOf(name, out vk))
        {
            if (name.Length != 1) return false;
            if (!ctrl && !alt) { Unicode(name[0]); return true; }
            short s = VkKeyScan(name[0]);
            if (s == -1) return false;
            vk = (byte)(s & 0xFF);
            if ((s & 0x100) != 0) shift = true;
        }
        if (ctrl) keybd_event(0x11, 0, 0, UIntPtr.Zero);
        if (alt) keybd_event(0x12, 0, 0, UIntPtr.Zero);
        if (shift) keybd_event(0x10, 0, 0, UIntPtr.Zero);
        uint ext = IsExtended(vk) ? 1u : 0u;
        keybd_event(vk, 0, ext, UIntPtr.Zero);
        keybd_event(vk, 0, ext | 2u, UIntPtr.Zero);
        if (shift) keybd_event(0x10, 0, 2, UIntPtr.Zero);
        if (alt) keybd_event(0x12, 0, 2, UIntPtr.Zero);
        if (ctrl) keybd_event(0x11, 0, 2, UIntPtr.Zero);
        return true;
    }

    static bool VkOf(string name, out byte vk)
    {
        switch (name)
        {
            case "Enter": vk = 0x0D; return true;
            case "Escape": vk = 0x1B; return true;
            case "Backspace": vk = 0x08; return true;
            case "Tab": vk = 0x09; return true;
            case "Space": case " ": vk = 0x20; return true;
            case "ArrowLeft": vk = 0x25; return true;
            case "ArrowUp": vk = 0x26; return true;
            case "ArrowRight": vk = 0x27; return true;
            case "ArrowDown": vk = 0x28; return true;
            case "Delete": vk = 0x2E; return true;
            case "Insert": vk = 0x2D; return true;
            case "Home": vk = 0x24; return true;
            case "End": vk = 0x23; return true;
            case "PageUp": vk = 0x21; return true;
            case "PageDown": vk = 0x22; return true;
            case "Meta": case "Win": vk = 0x5B; return true;
            case "ContextMenu": vk = 0x5D; return true;
            case "PrintScreen": vk = 0x2C; return true;
            case "CapsLock": vk = 0x14; return true;
            case "F1": vk = 0x70; return true;
            case "F2": vk = 0x71; return true;
            case "F3": vk = 0x72; return true;
            case "F4": vk = 0x73; return true;
            case "F5": vk = 0x74; return true;
            case "F6": vk = 0x75; return true;
            case "F7": vk = 0x76; return true;
            case "F8": vk = 0x77; return true;
            case "F9": vk = 0x78; return true;
            case "F10": vk = 0x79; return true;
            case "F11": vk = 0x7A; return true;
            case "F12": vk = 0x7B; return true;
            default: vk = 0; return false;
        }
    }

    static bool IsExtended(byte vk)
    {
        return (vk >= 0x21 && vk <= 0x28) || vk == 0x2D || vk == 0x2E || vk == 0x5B || vk == 0x5D;
    }

    static void Unicode(char c)
    {
        INPUT[] a = new INPUT[2];
        a[0].type = 1; a[0].U.ki.wScan = c; a[0].U.ki.dwFlags = 4;
        a[1].type = 1; a[1].U.ki.wScan = c; a[1].U.ki.dwFlags = 4 | 2;
        SendInput(2, a, Marshal.SizeOf(typeof(INPUT)));
    }

    static void Text(string text)
    {
        if (text == null) return;
        foreach (char c in text)
        {
            if (c == '\n') Key("Enter", false, false, false);
            else if (c != '\r') Unicode(c);
            Thread.Sleep(5);
        }
    }

    static void Focus(IntPtr hWnd)
    {
        if (hWnd == IntPtr.Zero) return;
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        keybd_event(0x12, 0, 2, UIntPtr.Zero);
        ShowWindow(hWnd, 9);
        SetForegroundWindow(hWnd);
    }

    public static void InstallStartup()
    {
        string destDir = @"C:\ADM-Kiosk-Agent";
        Directory.CreateDirectory(destDir);
        string dest = Path.Combine(destDir, "ADM-Kiosk-Agente.exe");
        string src = Application.ExecutablePath;
        if (!string.Equals(Path.GetFullPath(src), Path.GetFullPath(dest), StringComparison.OrdinalIgnoreCase))
            File.Copy(src, dest, true);
        string cfgSrc = src + ".config";
        if (File.Exists(cfgSrc)) File.Copy(cfgSrc, dest + ".config", true);
        string agentJson = Path.Combine(Dir, "agent.json");
        if (File.Exists(agentJson) && !File.Exists(Path.Combine(destDir, "agent.json")))
            File.Copy(agentJson, Path.Combine(destDir, "agent.json"), false);
        using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
            @"Software\Microsoft\Windows\CurrentVersion\Run", true))
        {
            if (k != null) k.SetValue("ADM Kiosk Agente", "\"" + dest + "\"");
        }
        try
        {
            foreach (string a in new string[] { "-monitor-timeout-ac 0", "-standby-timeout-ac 0", "-hibernate-timeout-ac 0" })
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "powercfg.exe";
                psi.Arguments = "-change " + a;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                Process.Start(psi);
            }
        }
        catch { }
        Log("Arranque automático instalado para este utilizador.");
    }

    public static void RemoveStartup()
    {
        using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
            @"Software\Microsoft\Windows\CurrentVersion\Run", true))
        {
            if (k != null) k.DeleteValue("ADM Kiosk Agente", false);
        }
        Log("Arranque automático removido.");
    }

    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("kernel32.dll")] static extern uint SetThreadExecutionState(uint flags);
    [DllImport("user32.dll", SetLastError = true)] static extern bool SystemParametersInfo(int action, int param, IntPtr pv, int winini);
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, int dx, int dy, int data, UIntPtr extra);
    [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] static extern short VkKeyScan(char ch);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] static extern bool GetCursorInfo(ref CURSORINFO ci);
    [DllImport("user32.dll")] static extern bool DrawIcon(IntPtr hdc, int x, int y, IntPtr icon);
    [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);

    [StructLayout(LayoutKind.Sequential)] struct POINT { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential)]
    struct CURSORINFO { public int cbSize; public int flags; public IntPtr hCursor; public POINT pt; }
    [StructLayout(LayoutKind.Sequential)]
    struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)]
    struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Explicit)]
    struct InputUnion { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
    [StructLayout(LayoutKind.Sequential)]
    struct INPUT { public uint type; public InputUnion U; }
}

class Settings
{
    public string Id = "", Name = "", Terminal = "", ScreenType = "", Gate = "", Url = "", Browser = "";
    public int ConfigVersion, Zoom = 100, RefreshSeconds, RetryDelaySeconds = 10;
    public bool KioskEnabled = true, ReloadOnError = true;

    public Settings Copy()
    {
        Settings c = (Settings)MemberwiseClone();
        return c;
    }

    public JVal ToJson()
    {
        JVal o = new JVal();
        o.K = JKind.Obj;
        o.O = new Dictionary<string, JVal>();
        o.O["id"] = JVal.String(Id);
        o.O["configVersion"] = JVal.Number(ConfigVersion.ToString(CultureInfo.InvariantCulture));
        o.O["name"] = JVal.String(Name);
        o.O["terminal"] = JVal.String(Terminal);
        o.O["screenType"] = JVal.String(ScreenType);
        o.O["gate"] = JVal.String(Gate);
        o.O["url"] = JVal.String(Url);
        o.O["browser"] = JVal.String(Browser);
        o.O["zoom"] = JVal.Number(Zoom.ToString(CultureInfo.InvariantCulture));
        o.O["refreshSeconds"] = JVal.Number(RefreshSeconds.ToString(CultureInfo.InvariantCulture));
        o.O["kioskEnabled"] = JVal.Bool(KioskEnabled);
        o.O["reloadOnError"] = JVal.Bool(ReloadOnError);
        o.O["retryDelaySeconds"] = JVal.Number(RetryDelaySeconds.ToString(CultureInfo.InvariantCulture));
        return o;
    }
}

class NetInfo
{
    public string Ip = "", Mask = "", Gateway = "", Mac = "", Iface = "", Transport = "";
    public int Prefix;
    public List<string> Dns = new List<string>();
}

class Browser
{
    public string Kind, Label, Path;
    public Browser(string kind, string label, string path) { Kind = kind; Label = label; Path = path; }
}

class Choice
{
    public string Kind, Label;
    public Choice(string kind, string label) { Kind = kind; Label = label; }
    public override string ToString() { return Label; }
}

// ---------------------------------------------------------------- janela

class MainForm : Form
{
    readonly TextBox serverBox = new TextBox();
    readonly TextBox urlBox = new TextBox();
    readonly ComboBox browserBox = new ComboBox();
    readonly NumericUpDown zoomBox = new NumericUpDown();
    readonly Label status = new Label();
    readonly Label detail = new Label();
    readonly Label hint = new Label();
    readonly TextBox log = new TextBox();
    readonly Panel dot = new Panel();
    IntPtr hook;
    HookProc hookProc;
    DateTime armedUntil = DateTime.MinValue;
    bool allowExit;
    string shownLog = "";

    delegate IntPtr HookProc(int nCode, IntPtr wParam, IntPtr lParam);

    static readonly Color Yellow = Color.FromArgb(239, 226, 26);
    static readonly Color Black = Color.FromArgb(18, 20, 23);
    static readonly Color Ink = Color.FromArgb(28, 31, 36);
    static readonly Color Dim = Color.FromArgb(90, 96, 104);
    static readonly Color Faint = Color.FromArgb(154, 160, 168);
    static readonly Color Bg = Color.FromArgb(244, 245, 247);
    static readonly Color Surface = Color.White;
    static readonly Color Border = Color.FromArgb(229, 231, 235);
    static readonly Color Green = Color.FromArgb(10, 138, 79);
    static readonly Color Red = Color.FromArgb(210, 16, 52);

    public MainForm()
    {
        Text = "ADM Kiosk Agente";
        Font = new Font("Tahoma", 9F);
        BackColor = Bg;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(820, 700);
        MinimumSize = new Size(720, 620);
        Build();
        LoadFields();
        System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        timer.Interval = 1000;
        timer.Tick += delegate { RefreshStatus(); };
        timer.Start();
        Shown += delegate { InstallHook(); RefreshStatus(); };
        FormClosing += OnClosing;
    }

    void Build()
    {
        TableLayoutPanel root = new TableLayoutPanel();
        root.Dock = DockStyle.Fill;
        root.ColumnCount = 1;
        root.RowCount = 4;
        root.Margin = new Padding(0);
        root.Padding = new Padding(0);
        root.BackColor = Bg;
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 74));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 4));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 52));
        root.Parent = this;

        Panel head = new Panel();
        head.Dock = DockStyle.Fill;
        head.BackColor = Black;
        head.Margin = new Padding(0);
        Label title = new Label();
        title.Text = "ADM Kiosk Agente";
        title.ForeColor = Color.White;
        title.Font = new Font("Tahoma", 16F, FontStyle.Bold);
        title.AutoSize = true;
        title.Location = new Point(22, 12);
        title.BackColor = Black;
        title.Parent = head;
        Label sub = new Label();
        sub.Text = "Computador / netbox  ·  Aeroportos de Moçambique, E.P.";
        sub.ForeColor = Faint;
        sub.AutoSize = true;
        sub.Location = new Point(24, 42);
        sub.BackColor = Black;
        sub.Parent = head;
        root.Controls.Add(head, 0, 0);

        Panel stripe = new Panel();
        stripe.Dock = DockStyle.Fill;
        stripe.BackColor = Yellow;
        stripe.Margin = new Padding(0);
        root.Controls.Add(stripe, 0, 1);

        Panel foot = new Panel();
        foot.Dock = DockStyle.Fill;
        foot.BackColor = Bg;
        foot.Margin = new Padding(0);
        root.Controls.Add(foot, 0, 3);
        Label credit = new Label();
        credit.Text = "Desenvolvido por Harmonico Lucas";
        credit.ForeColor = Faint;
        credit.AutoSize = true;
        credit.Location = new Point(22, 8);
        credit.Parent = foot;
        hint.Text = "Para sair do modo kiosk: Ctrl+X e, em seguida, S. A janela do agente volta ao ambiente de trabalho.";
        hint.ForeColor = Dim;
        hint.AutoSize = false;
        hint.Bounds = new Rectangle(22, 28, 760, 22);
        hint.Parent = foot;

        TableLayoutPanel body = new TableLayoutPanel();
        body.Dock = DockStyle.Fill;
        body.ColumnCount = 1;
        body.RowCount = 4;
        body.BackColor = Bg;
        body.Padding = new Padding(16, 12, 16, 8);
        body.Margin = new Padding(0);
        body.RowStyles.Add(new RowStyle(SizeType.Absolute, 86));
        body.RowStyles.Add(new RowStyle(SizeType.Absolute, 200));
        body.RowStyles.Add(new RowStyle(SizeType.Absolute, 78));
        body.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.Controls.Add(body, 0, 2);

        Panel statusCard = Card(body, 0);
        statusCard.Dock = DockStyle.Fill;
        statusCard.Margin = new Padding(0, 0, 0, 8);
        body.Controls.Add(statusCard, 0, 0);
        dot.Size = new Size(14, 14);
        dot.Location = new Point(16, 22);
        dot.BackColor = Faint;
        dot.Parent = statusCard;
        status.Font = new Font("Tahoma", 11F, FontStyle.Bold);
        status.ForeColor = Ink;
        status.AutoSize = false;
        status.Bounds = new Rectangle(40, 14, 700, 24);
        status.Parent = statusCard;
        detail.ForeColor = Dim;
        detail.AutoSize = false;
        detail.Bounds = new Rectangle(40, 40, 700, 36);
        detail.Parent = statusCard;

        Panel cfg = Card(body, 0);
        cfg.Dock = DockStyle.Fill;
        cfg.Margin = new Padding(0, 0, 0, 8);
        body.Controls.Add(cfg, 0, 1);
        Label cfgTitle = new Label();
        cfgTitle.Text = "Este ecrã";
        cfgTitle.Font = new Font("Tahoma", 10F, FontStyle.Bold);
        cfgTitle.AutoSize = true;
        cfgTitle.Location = new Point(14, 10);
        cfgTitle.Parent = cfg;
        AddField(cfg, "Servidor de administração", serverBox, 32);
        serverBox.Width = 520;
        AddField(cfg, "Página a apresentar", urlBox, 78);
        urlBox.Width = 520;
        Label bl = new Label();
        bl.Text = "Navegador";
        bl.AutoSize = true;
        bl.ForeColor = Dim;
        bl.Location = new Point(14, 128);
        bl.Parent = cfg;
        browserBox.DropDownStyle = ComboBoxStyle.DropDownList;
        browserBox.Items.Add(new Choice("", "Automático"));
        browserBox.Items.Add(new Choice("edge", "Microsoft Edge"));
        browserBox.Items.Add(new Choice("chrome", "Google Chrome"));
        browserBox.Items.Add(new Choice("firefox", "Mozilla Firefox"));
        browserBox.Items.Add(new Choice("ie", "Internet Explorer"));
        browserBox.Location = new Point(14, 146);
        browserBox.Width = 220;
        browserBox.Parent = cfg;
        Label zl = new Label();
        zl.Text = "Zoom %";
        zl.AutoSize = true;
        zl.ForeColor = Dim;
        zl.Location = new Point(260, 128);
        zl.Parent = cfg;
        zoomBox.Minimum = 50;
        zoomBox.Maximum = 300;
        zoomBox.Value = 100;
        zoomBox.Location = new Point(260, 146);
        zoomBox.Width = 80;
        zoomBox.Parent = cfg;

        FlowLayoutPanel buttons = new FlowLayoutPanel();
        buttons.Dock = DockStyle.Fill;
        buttons.Margin = new Padding(0);
        buttons.Padding = new Padding(0, 4, 0, 0);
        buttons.BackColor = Bg;
        buttons.WrapContents = true;
        buttons.AutoScroll = true;
        body.Controls.Add(buttons, 0, 2);
        buttons.Controls.Add(MakeButton("Guardar", false, delegate { SaveFields(false); }));
        buttons.Controls.Add(MakeButton("Entrar no modo kiosk", true, delegate { EnterKiosk(); }));
        buttons.Controls.Add(MakeButton("Sair do modo kiosk", false, delegate { LeaveKiosk(); }));
        buttons.Controls.Add(MakeButton("Recarregar página", false, delegate { Agent.Async(delegate { Agent.ReloadPage(); }); }));
        buttons.Controls.Add(MakeButton("Instalar arranque", false, delegate { Install(); }));
        buttons.Controls.Add(MakeButton("Terminar agente", false, delegate { Quit(); }));

        Panel logCard = Card(body, 0);
        logCard.Dock = DockStyle.Fill;
        logCard.Margin = new Padding(0);
        body.Controls.Add(logCard, 0, 3);
        Label logTitle = new Label();
        logTitle.Text = "Atividade";
        logTitle.Font = new Font("Tahoma", 10F, FontStyle.Bold);
        logTitle.Dock = DockStyle.Top;
        logTitle.Height = 24;
        logTitle.Parent = logCard;
        log.Multiline = true;
        log.ReadOnly = true;
        log.ScrollBars = ScrollBars.Vertical;
        log.BorderStyle = BorderStyle.None;
        log.BackColor = Surface;
        log.Font = new Font("Courier New", 8.5F);
        log.Dock = DockStyle.Fill;
        log.Parent = logCard;
    }

    static Panel Card(Control parent, int height)
    {
        Panel p = new Panel();
        p.BackColor = Surface;
        p.Padding = new Padding(8);
        p.Margin = new Padding(0, 0, 0, 10);
        if (height > 0) p.Height = height;
        p.Paint += delegate(object s, PaintEventArgs e)
        {
            Control c = (Control)s;
            using (Pen pen = new Pen(Border))
                e.Graphics.DrawRectangle(pen, 0, 0, c.Width - 1, c.Height - 1);
        };
        p.Parent = parent;
        return p;
    }

    static void AddField(Control parent, string caption, TextBox box, int top)
    {
        Label l = new Label();
        l.Text = caption;
        l.ForeColor = Dim;
        l.AutoSize = true;
        l.Location = new Point(14, top);
        l.Parent = parent;
        box.Location = new Point(14, top + 18);
        box.Parent = parent;
    }

    static Button MakeButton(string text, bool primary, EventHandler click)
    {
        Button b = new Button();
        b.Text = text;
        b.AutoSize = true;
        b.Height = 32;
        b.Padding = new Padding(10, 2, 10, 2);
        b.FlatStyle = FlatStyle.Flat;
        b.FlatAppearance.BorderColor = primary ? Color.FromArgb(216, 203, 12) : Border;
        b.BackColor = primary ? Yellow : Surface;
        b.ForeColor = primary ? Black : Ink;
        b.Font = new Font("Tahoma", 9F, primary ? FontStyle.Bold : FontStyle.Regular);
        b.Margin = new Padding(0, 0, 8, 0);
        b.Click += click;
        return b;
    }

    public void LoadFields()
    {
        Settings s = Agent.State;
        if (!serverBox.Focused) serverBox.Text = Agent.ServerUrl;
        if (!urlBox.Focused) urlBox.Text = s.Url;
        if (!browserBox.Focused)
        {
            browserBox.SelectedIndex = 0;
            for (int i = 0; i < browserBox.Items.Count; i++)
            {
                Choice c = (Choice)browserBox.Items[i];
                if (c.Kind == (s.Browser ?? "")) { browserBox.SelectedIndex = i; break; }
            }
        }
        if (!zoomBox.Focused)
        {
            int z = s.Zoom;
            if (z < 50) z = 50;
            if (z > 300) z = 300;
            zoomBox.Value = z;
        }
    }

    void SaveFields(bool silent)
    {
        Choice c = browserBox.SelectedItem as Choice;
        Agent.ApplyLocal(serverBox.Text.Trim(), urlBox.Text.Trim(), c == null ? "" : c.Kind, (int)zoomBox.Value);
        if (!silent) RefreshStatus();
    }

    void EnterKiosk()
    {
        SaveFields(true);
        if (urlBox.Text.Trim().Length == 0)
        {
            MessageBox.Show(this, "Indique a página a apresentar neste ecrã.", "ADM Kiosk Agente",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        Agent.Paused = false;
        Agent.Async(delegate { Agent.RestartKiosk(); });
        SendBack();
        RefreshStatus();
    }

    public void LeaveKiosk()
    {
        if (Agent.Paused)
        {
            ShowFront();
            return;
        }
        Agent.Paused = true;
        Agent.Log("Ctrl+X, S — a voltar ao ambiente de trabalho.");
        ShowFront();
        Agent.Async(delegate { Agent.StopKiosk(); });
        RefreshStatus();
    }

    public void ShowFront()
    {
        if (!Visible) Show();
        WindowState = FormWindowState.Normal;
        ShowInTaskbar = true;
        TopMost = true;
        Activate();
        BringToFront();
        System.Windows.Forms.Timer t = new System.Windows.Forms.Timer();
        t.Interval = 700;
        t.Tick += delegate { t.Stop(); t.Dispose(); TopMost = false; };
        t.Start();
    }

    public void SendBack()
    {
        TopMost = false;
        SendToBack();
    }

    public void Hint(string text)
    {
        hint.Text = text;
        hint.ForeColor = Ink;
    }

    void RefreshStatus()
    {
        status.Text = Agent.StatusLine;
        string mode = Agent.Paused ? "No ambiente de trabalho."
            : (Agent.State.Url.Length == 0 ? "Sem página configurada." : "Modo kiosk activo.");
        detail.Text = mode + "   " + Agent.DetailLine;
        bool connected = Agent.StatusLine.StartsWith("Ligado");
        dot.BackColor = connected ? Green : (Agent.StatusLine.StartsWith("Sem") || Agent.StatusLine.StartsWith("Servidor não") ? Red : Faint);
        string text = Agent.LogText();
        if (text != shownLog)
        {
            shownLog = text;
            log.Text = text;
            log.SelectionStart = log.Text.Length;
            log.ScrollToCaret();
        }
        if (DateTime.UtcNow > armedUntil && hint.ForeColor == Ink)
        {
            hint.ForeColor = Dim;
            hint.Text = "Para sair do modo kiosk: Ctrl+X e, em seguida, S. A janela do agente volta ao ambiente de trabalho.";
        }
    }

    void Install()
    {
        SaveFields(true);
        try
        {
            Agent.InstallStartup();
            MessageBox.Show(this,
                "O agente arranca com o Windows neste utilizador.\r\nPasta: C:\\ADM-Kiosk-Agent",
                "ADM Kiosk Agente", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "ADM Kiosk Agente", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    void Quit()
    {
        if (MessageBox.Show(this, "O agente deixa de controlar este ecrã. Terminar?",
            "ADM Kiosk Agente", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
        allowExit = true;
        Close();
    }

    void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (allowExit)
        {
            if (hook != IntPtr.Zero) UnhookWindowsHookEx(hook);
            return;
        }
        e.Cancel = true;
        WindowState = FormWindowState.Minimized;
    }

    void InstallHook()
    {
        hookProc = new HookProc(OnKey);
        hook = SetWindowsHookEx(13, hookProc, GetModuleHandle(null), 0);
        if (hook == IntPtr.Zero) Agent.Log("Não foi possível instalar o atalho Ctrl+X, S.");
        else Agent.Log("Atalho ativo: Ctrl+X, depois S, sai do modo kiosk.");
    }

    IntPtr OnKey(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode >= 0 && (wParam == (IntPtr)0x100 || wParam == (IntPtr)0x104))
        {
            KBDLL kb = (KBDLL)Marshal.PtrToStructure(lParam, typeof(KBDLL));
            bool down = (kb.flags & 0x80) == 0;
            bool injected = (kb.flags & 0x10) != 0;
            if (down && !injected)
            {
                bool ctrl = (GetAsyncKeyState(0x11) & 0x8000) != 0;
                if (kb.vkCode == 0x58 && ctrl)
                {
                    armedUntil = DateTime.UtcNow.AddMilliseconds(2500);
                    BeginInvoke((MethodInvoker)delegate { Hint("Prima S para voltar ao ambiente de trabalho"); });
                    return (IntPtr)1;
                }
                if (kb.vkCode == 0x53 && DateTime.UtcNow <= armedUntil)
                {
                    armedUntil = DateTime.MinValue;
                    BeginInvoke((MethodInvoker)delegate { LeaveKiosk(); });
                    return (IntPtr)1;
                }
            }
        }
        return CallNextHookEx(hook, nCode, wParam, lParam);
    }

    [DllImport("user32.dll")] static extern IntPtr SetWindowsHookEx(int id, HookProc proc, IntPtr mod, uint thread);
    [DllImport("user32.dll")] static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32.dll")] static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int vk);
    [DllImport("kernel32.dll", CharSet = CharSet.Auto)] static extern IntPtr GetModuleHandle(string name);

    [StructLayout(LayoutKind.Sequential)]
    struct KBDLL
    {
        public uint vkCode, scanCode, flags, time;
        public IntPtr extra;
    }
}

// ---------------------------------------------------------------- JSON mínimo (sem depender de System.Web)

enum JKind { Null, Bool, Num, Str, Arr, Obj }

class JVal
{
    public JKind K;
    public bool B;
    public string S = "";
    public List<JVal> A;
    public Dictionary<string, JVal> O;

    public JVal this[string key]
    {
        get
        {
            JVal v;
            if (O != null && O.TryGetValue(key, out v)) return v;
            return null;
        }
    }

    public string Str(string key, string def)
    {
        JVal v = this[key];
        if (v == null || (v.K != JKind.Str && v.K != JKind.Num)) return def;
        return v.S ?? def;
    }

    public int Int(string key, int def)
    {
        JVal v = this[key];
        if (v == null) return def;
        int n;
        if (v.K == JKind.Num || v.K == JKind.Str)
            return int.TryParse(v.S, NumberStyles.Any, CultureInfo.InvariantCulture, out n) ? n : def;
        if (v.K == JKind.Bool) return v.B ? 1 : 0;
        return def;
    }

    public long Long(string key, long def)
    {
        JVal v = this[key];
        if (v == null || (v.K != JKind.Num && v.K != JKind.Str)) return def;
        long n;
        return long.TryParse(v.S, NumberStyles.Any, CultureInfo.InvariantCulture, out n) ? n : def;
    }

    public double Num(string key, double def)
    {
        JVal v = this[key];
        if (v == null || (v.K != JKind.Num && v.K != JKind.Str)) return def;
        double n;
        return double.TryParse(v.S, NumberStyles.Any, CultureInfo.InvariantCulture, out n) ? n : def;
    }

    public bool Bool(string key, bool def)
    {
        JVal v = this[key];
        if (v == null) return def;
        if (v.K == JKind.Bool) return v.B;
        if (v.K == JKind.Num) return v.S != "0";
        return def;
    }

    public static JVal String(string s) { JVal v = new JVal(); v.K = JKind.Str; v.S = s ?? ""; return v; }
    public static JVal Number(string s) { JVal v = new JVal(); v.K = JKind.Num; v.S = s; return v; }
    public static JVal Bool(bool b) { JVal v = new JVal(); v.K = JKind.Bool; v.B = b; return v; }
}

static class Js
{
    public static string Esc(string s)
    {
        if (s == null) s = "";
        StringBuilder sb = new StringBuilder(s.Length + 2);
        sb.Append('"');
        foreach (char c in s)
        {
            switch (c)
            {
                case '\\': sb.Append("\\\\"); break;
                case '"': sb.Append("\\\""); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 32) sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
        return sb.ToString();
    }

    public static string StringArray(List<string> items)
    {
        StringBuilder sb = new StringBuilder("[");
        if (items != null)
        {
            for (int i = 0; i < items.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(Esc(items[i]));
            }
        }
        sb.Append(']');
        return sb.ToString();
    }

    public static JVal Parse(string text)
    {
        Parser p = new Parser(text ?? "");
        return p.Parse();
    }

    public static JVal ReadFile(string path)
    {
        try { return Parse(File.ReadAllText(path, Encoding.UTF8)); }
        catch { return new JVal(); }
    }

    public static void WriteFile(string path, JVal value)
    {
        string tmp = path + ".tmp";
        File.WriteAllText(tmp, Write(value), new UTF8Encoding(false));
        if (File.Exists(path)) File.Delete(path);
        File.Move(tmp, path);
    }

    public static string Write(JVal v)
    {
        if (v == null || v.K == JKind.Null) return "null";
        if (v.K == JKind.Bool) return v.B ? "true" : "false";
        if (v.K == JKind.Num) return string.IsNullOrEmpty(v.S) ? "0" : v.S;
        if (v.K == JKind.Str) return Esc(v.S);
        if (v.K == JKind.Arr)
        {
            StringBuilder sb = new StringBuilder("[");
            if (v.A != null)
            {
                for (int i = 0; i < v.A.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(Write(v.A[i]));
                }
            }
            sb.Append(']');
            return sb.ToString();
        }
        StringBuilder o = new StringBuilder("{");
        if (v.O != null)
        {
            bool first = true;
            foreach (KeyValuePair<string, JVal> kv in v.O)
            {
                if (!first) o.Append(',');
                first = false;
                o.Append(Esc(kv.Key)).Append(':').Append(Write(kv.Value));
            }
        }
        o.Append('}');
        return o.ToString();
    }

    public static bool SelfTest()
    {
        JVal v = Parse("{\"config\":{\"version\":3,\"name\":\"Sala \\u00e7\",\"kioskEnabled\":true,\"url\":\"http://10.0.0.5/fids\",\"zoom\":100},\"commands\":[{\"id\":12,\"type\":\"reload\",\"payload\":{}}],\"live\":{\"active\":false,\"intervalMs\":100}}");
        if (v["config"].Int("version", 0) != 3) return false;
        if (v["config"].Str("name", "") != "Sala ç") return false;
        if (!v["config"].Bool("kioskEnabled", false)) return false;
        if (v["commands"].A == null || v["commands"].A.Count != 1) return false;
        if (v["commands"].A[0].Long("id", 0) != 12) return false;
        if (v["live"].Bool("active", true)) return false;
        if (v["live"].Int("intervalMs", 0) != 100) return false;
        return true;
    }

    class Parser
    {
        readonly string t;
        int i;
        public Parser(string text) { t = text; }
        public JVal Parse() { Skip(); return Val(); }
        void Skip() { while (i < t.Length && char.IsWhiteSpace(t[i])) i++; }
        JVal Val()
        {
            Skip();
            if (i >= t.Length) return new JVal();
            char c = t[i];
            if (c == '{') return Obj();
            if (c == '[') return Arr();
            if (c == '"') { JVal v = new JVal(); v.K = JKind.Str; v.S = Str(); return v; }
            if (c == 't' || c == 'f') return Bool();
            if (c == 'n') { i += 4; return new JVal(); }
            return Num();
        }
        JVal Obj()
        {
            JVal v = new JVal();
            v.K = JKind.Obj;
            v.O = new Dictionary<string, JVal>();
            i++;
            Skip();
            if (i < t.Length && t[i] == '}') { i++; return v; }
            while (i < t.Length)
            {
                Skip();
                string key = Str();
                Skip();
                if (i < t.Length && t[i] == ':') i++;
                v.O[key] = Val();
                Skip();
                if (i < t.Length && t[i] == ',') { i++; continue; }
                if (i < t.Length && t[i] == '}') i++;
                break;
            }
            return v;
        }
        JVal Arr()
        {
            JVal v = new JVal();
            v.K = JKind.Arr;
            v.A = new List<JVal>();
            i++;
            Skip();
            if (i < t.Length && t[i] == ']') { i++; return v; }
            while (i < t.Length)
            {
                v.A.Add(Val());
                Skip();
                if (i < t.Length && t[i] == ',') { i++; continue; }
                if (i < t.Length && t[i] == ']') i++;
                break;
            }
            return v;
        }
        string Str()
        {
            if (i >= t.Length || t[i] != '"') return "";
            i++;
            StringBuilder sb = new StringBuilder();
            while (i < t.Length)
            {
                char c = t[i++];
                if (c == '"') break;
                if (c == '\\' && i < t.Length)
                {
                    char e = t[i++];
                    if (e == 'n') sb.Append('\n');
                    else if (e == 'r') sb.Append('\r');
                    else if (e == 't') sb.Append('\t');
                    else if (e == 'u' && i + 4 <= t.Length)
                    {
                        int code;
                        if (int.TryParse(t.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out code))
                            sb.Append((char)code);
                        i += 4;
                    }
                    else sb.Append(e);
                }
                else sb.Append(c);
            }
            return sb.ToString();
        }
        JVal Bool()
        {
            JVal v = new JVal();
            v.K = JKind.Bool;
            if (t.Substring(i).StartsWith("true")) { v.B = true; i += 4; }
            else { v.B = false; i += 5; }
            return v;
        }
        JVal Num()
        {
            int start = i;
            while (i < t.Length && ("-0123456789.eE+".IndexOf(t[i]) >= 0)) i++;
            JVal v = new JVal();
            v.K = JKind.Num;
            v.S = t.Substring(start, i - start);
            return v;
        }
    }
}
