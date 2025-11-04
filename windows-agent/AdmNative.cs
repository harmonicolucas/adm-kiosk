using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

/// Captura de ecrã, rato/teclado e painel de identificação para o agente ADM Kiosk (Windows).
public static class AdmNative
{
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
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

    const uint KEYUP = 0x0002, EXTENDED = 0x0001, UNICODE = 0x0004;

    public static void Init()
    {
        try { SetProcessDPIAware(); } catch { }
    }

    public static string Resolution
    {
        get { Rectangle b = Screen.PrimaryScreen.Bounds; return b.Width + "x" + b.Height; }
    }

    // ------------------------------------------------------------------ captura

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
            if (maxWidth > 0 && bmp.Width > maxWidth)
            {
                int h = bmp.Height * maxWidth / bmp.Width;
                output = new Bitmap(maxWidth, h, PixelFormat.Format24bppRgb);
                using (Graphics g2 = Graphics.FromImage(output))
                {
                    g2.InterpolationMode = InterpolationMode.Bilinear;
                    g2.DrawImage(bmp, 0, 0, maxWidth, h);
                }
                scaled = true;
            }
            try
            {
                ImageCodecInfo codec = null;
                foreach (ImageCodecInfo c in ImageCodecInfo.GetImageEncoders())
                    if (c.MimeType == "image/jpeg") codec = c;
                EncoderParameters ep = new EncoderParameters(1);
                ep.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, quality);
                using (MemoryStream ms = new MemoryStream())
                {
                    output.Save(ms, codec, ep);
                    return ms.ToArray();
                }
            }
            finally
            {
                if (scaled) output.Dispose();
            }
        }
    }

    // ------------------------------------------------------------------ rato

    static void MoveTo(double x, double y)
    {
        Rectangle b = Screen.PrimaryScreen.Bounds;
        SetCursorPos(b.Left + (int)(x * (b.Width - 1)), b.Top + (int)(y * (b.Height - 1)));
    }

    public static void Move(double x, double y) { MoveTo(x, y); }

    public static void Click(double x, double y, bool right, int count)
    {
        MoveTo(x, y);
        uint down = right ? 0x0008u : 0x0002u;
        uint up = right ? 0x0010u : 0x0004u;
        for (int i = 0; i < count; i++)
        {
            mouse_event(down, 0, 0, 0, UIntPtr.Zero);
            mouse_event(up, 0, 0, 0, UIntPtr.Zero);
            Thread.Sleep(50);
        }
    }

    /// Premir ou largar um botão (permite arrastar: premir, mover, largar).
    public static void Button(double x, double y, bool right, bool down)
    {
        MoveTo(x, y);
        uint flag = right ? (down ? 0x0008u : 0x0010u) : (down ? 0x0002u : 0x0004u);
        mouse_event(flag, 0, 0, 0, UIntPtr.Zero);
    }

    /// notches > 0 desce a página.
    public static void Wheel(double x, double y, int notches)
    {
        MoveTo(x, y);
        mouse_event(0x0800, 0, 0, -notches * 120, UIntPtr.Zero);
    }

    // ------------------------------------------------------------------ teclado

    static readonly Dictionary<string, byte> Named = new Dictionary<string, byte>(StringComparer.OrdinalIgnoreCase)
    {
        {"Enter", 0x0D}, {"Escape", 0x1B}, {"Backspace", 0x08}, {"Tab", 0x09}, {"Space", 0x20}, {" ", 0x20},
        {"ArrowLeft", 0x25}, {"ArrowUp", 0x26}, {"ArrowRight", 0x27}, {"ArrowDown", 0x28},
        {"Delete", 0x2E}, {"Insert", 0x2D}, {"Home", 0x24}, {"End", 0x23}, {"PageUp", 0x21}, {"PageDown", 0x22},
        {"Meta", 0x5B}, {"Win", 0x5B}, {"ContextMenu", 0x5D}, {"PrintScreen", 0x2C}, {"CapsLock", 0x14},
        {"F1", 0x70}, {"F2", 0x71}, {"F3", 0x72}, {"F4", 0x73}, {"F5", 0x74}, {"F6", 0x75},
        {"F7", 0x76}, {"F8", 0x77}, {"F9", 0x78}, {"F10", 0x79}, {"F11", 0x7A}, {"F12", 0x7B},
    };

    static bool IsExtended(byte vk)
    {
        return (vk >= 0x21 && vk <= 0x28) || vk == 0x2D || vk == 0x2E || vk == 0x5B || vk == 0x5D;
    }

    public static bool Key(string name, bool ctrl, bool alt, bool shift)
    {
        if (string.IsNullOrEmpty(name)) return false;
        byte vk;
        if (!Named.TryGetValue(name, out vk))
        {
            if (name.Length != 1) return false;
            if (!ctrl && !alt)
            {
                Unicode(name[0]);
                return true;
            }
            short s = VkKeyScan(name[0]);
            if (s == -1) return false;
            vk = (byte)(s & 0xFF);
            if ((s & 0x100) != 0) shift = true;
        }
        if (ctrl) keybd_event(0x11, 0, 0, UIntPtr.Zero);
        if (alt) keybd_event(0x12, 0, 0, UIntPtr.Zero);
        if (shift) keybd_event(0x10, 0, 0, UIntPtr.Zero);
        uint ext = IsExtended(vk) ? EXTENDED : 0u;
        keybd_event(vk, 0, ext, UIntPtr.Zero);
        keybd_event(vk, 0, ext | KEYUP, UIntPtr.Zero);
        if (shift) keybd_event(0x10, 0, KEYUP, UIntPtr.Zero);
        if (alt) keybd_event(0x12, 0, KEYUP, UIntPtr.Zero);
        if (ctrl) keybd_event(0x11, 0, KEYUP, UIntPtr.Zero);
        return true;
    }

    static void Unicode(char c)
    {
        INPUT[] a = new INPUT[2];
        a[0].type = 1; a[0].U.ki.wScan = c; a[0].U.ki.dwFlags = UNICODE;
        a[1].type = 1; a[1].U.ki.wScan = c; a[1].U.ki.dwFlags = UNICODE | KEYUP;
        SendInput(2, a, Marshal.SizeOf(typeof(INPUT)));
    }

    public static void Text(string text)
    {
        if (text == null) return;
        foreach (char c in text)
        {
            if (c == '\n') Key("Enter", false, false, false);
            else if (c != '\r') Unicode(c);
            Thread.Sleep(5);
        }
    }

    /// Traz uma janela para a frente (necessário antes de enviar F5 ao navegador).
    public static void Focus(IntPtr hWnd)
    {
        if (hWnd == IntPtr.Zero) return;
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        keybd_event(0x12, 0, KEYUP, UIntPtr.Zero);
        ShowWindow(hWnd, 9);
        SetForegroundWindow(hWnd);
    }

    // ------------------------------------------------------------------ identificação

    public static void ShowBanner(string text, int seconds)
    {
        Thread t = new Thread(() =>
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
            l.Font = new Font("Segoe UI", 40, FontStyle.Bold);
            l.Text = text;
            f.Controls.Add(l);
            System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
            timer.Interval = Math.Max(3, seconds) * 1000;
            timer.Tick += (s, e) => { timer.Stop(); f.Close(); };
            timer.Start();
            Application.Run(f);
        });
        t.SetApartmentState(ApartmentState.STA);
        t.IsBackground = true;
        t.Start();
    }
}

/// Sessão ao vivo em segundo plano: mantém um pedido de espera aberto com o servidor (acordado de
/// imediato quando há sessão, comando ou configuração) e transmite o ecrã continuamente.
public static class AdmLive
{
    static volatile string server = "";
    static volatile string id = "";
    static volatile bool wakeFlag;
    static volatile bool streaming;
    static Thread thread;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    public static volatile string LastError = "";
    public static bool Streaming { get { return streaming; } }

    public static void Configure(string serverUrl, string deviceId)
    {
        server = (serverUrl ?? "").TrimEnd('/');
        id = deviceId ?? "";
    }

    /// Devolve true (uma vez) quando o servidor pediu contacto imediato.
    public static bool TakeWake()
    {
        if (!wakeFlag) return false;
        wakeFlag = false;
        return true;
    }

    public static void Start()
    {
        if (thread != null) return;
        ServicePointManager.Expect100Continue = false;
        ServicePointManager.DefaultConnectionLimit = 10;
        thread = new Thread(Run);
        thread.IsBackground = true;
        thread.Start();
    }

    static void Run()
    {
        long gen = -1;
        while (true)
        {
            string s = server, d = id;
            if (s.Length == 0 || d.Length == 0) { Thread.Sleep(2000); continue; }
            try
            {
                string text = Post(s + "/api/device/wait?id=" + d + "&gen=" + gen, new byte[0], "application/json", 35000);
                Dictionary<string, object> r = Json.DeserializeObject(text) as Dictionary<string, object>;
                if (r == null) { Thread.Sleep(2000); continue; }
                gen = Convert.ToInt64(r["gen"]);
                if (Flag(r, "wake")) wakeFlag = true;
                Dictionary<string, object> live = r.ContainsKey("live") ? r["live"] as Dictionary<string, object> : null;
                if (live != null && Flag(live, "active")) StreamScreen(s, d, live);
            }
            catch (Exception ex)
            {
                LastError = ex.Message;
                Thread.Sleep(3000);
            }
        }
    }

    static void StreamScreen(string s, string d, Dictionary<string, object> live)
    {
        streaming = true;
        byte[] last = null;
        int fails = 0;
        try
        {
            while (live != null && Flag(live, "active"))
            {
                int interval = Math.Max(50, Math.Min(5000, (int)Num(live, "intervalMs", 100)));
                string q = Str(live, "quality");
                int width = q == "high" ? 1920 : q == "low" ? 1024 : 1366;
                long quality = q == "high" ? 70 : q == "low" ? 40 : 55;
                Stopwatch sw = Stopwatch.StartNew();

                byte[] jpeg = AdmNative.Capture(width, quality);
                // Ecrã igual ao anterior: envia corpo vazio e apenas recolhe os eventos de controlo.
                bool same = last != null && SameBytes(jpeg, last);
                string text;
                try
                {
                    text = Post(s + "/api/device/frame?id=" + d, same ? new byte[0] : jpeg, "image/jpeg", 10000);
                    fails = 0;
                }
                catch (Exception ex)
                {
                    LastError = ex.Message;
                    if (++fails >= 3) return;
                    Thread.Sleep(500);
                    continue;
                }
                if (!same) last = jpeg;

                Dictionary<string, object> r = Json.DeserializeObject(text) as Dictionary<string, object>;
                if (r == null) return;
                live = r.ContainsKey("live") ? r["live"] as Dictionary<string, object> : null;
                if (r.ContainsKey("inputs")) RunInputs(r["inputs"]);

                int rest = interval - (int)sw.ElapsedMilliseconds;
                if (rest > 0) Thread.Sleep(rest);
            }
        }
        finally { streaming = false; }
    }

    static void RunInputs(object inputs)
    {
        IEnumerable list = inputs as IEnumerable;
        if (list == null || inputs is string) return;
        foreach (object o in list)
        {
            Dictionary<string, object> ev = o as Dictionary<string, object>;
            if (ev == null) continue;
            try { RunInput(ev); }
            catch (Exception ex) { LastError = ex.Message; }
        }
    }

    static void RunInput(Dictionary<string, object> ev)
    {
        double x = Num(ev, "x", 0.5), y = Num(ev, "y", 0.5);
        bool right = Str(ev, "button") == "right";
        switch (Str(ev, "type"))
        {
            case "click": AdmNative.Click(x, y, false, 1); break;
            case "dblclick": AdmNative.Click(x, y, false, 2); break;
            case "rightclick": AdmNative.Click(x, y, true, 1); break;
            case "move": AdmNative.Move(x, y); break;
            case "down": AdmNative.Button(x, y, right, true); break;
            case "up": AdmNative.Button(x, y, right, false); break;
            case "scroll": AdmNative.Wheel(x, y, (int)Num(ev, "dy", 1)); break;
            case "key": AdmNative.Key(Str(ev, "key"), Flag(ev, "ctrl"), Flag(ev, "alt"), Flag(ev, "shift")); break;
            case "text": AdmNative.Text(Str(ev, "text")); break;
        }
    }

    static string Post(string url, byte[] body, string ctype, int timeout)
    {
        HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
        req.Method = "POST";
        req.ContentType = ctype;
        req.Timeout = timeout;
        req.ReadWriteTimeout = timeout;
        req.Proxy = null;
        req.ContentLength = body.Length;
        using (Stream rs = req.GetRequestStream()) rs.Write(body, 0, body.Length);
        using (WebResponse res = req.GetResponse())
        using (StreamReader reader = new StreamReader(res.GetResponseStream(), Encoding.UTF8))
            return reader.ReadToEnd();
    }

    static bool SameBytes(byte[] a, byte[] b)
    {
        if (a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }

    static string Str(Dictionary<string, object> d, string k)
    {
        object v;
        return d.TryGetValue(k, out v) && v != null ? v.ToString() : "";
    }

    static double Num(Dictionary<string, object> d, string k, double def)
    {
        object v;
        if (!d.TryGetValue(k, out v) || v == null) return def;
        try { return Convert.ToDouble(v, System.Globalization.CultureInfo.InvariantCulture); } catch { return def; }
    }

    static bool Flag(Dictionary<string, object> d, string k)
    {
        object v;
        return d.TryGetValue(k, out v) && v is bool && (bool)v;
    }
}
