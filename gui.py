"""
R1X Optimizer v3 - Desktop Command Center (paid-tier).
Native customtkinter dashboard. Every heavy operation runs on a worker
thread and reports through r1x_core's log callback, so the UI never
freezes and every button actually works.
"""
import os
import sys
import threading
import time
from collections import deque
import tkinter as tk
import customtkinter as ctk
import r1x_core as core

try:
    import winsound

    def _beep(freq=800, ms=120):
        try:
            winsound.Beep(freq, ms)
        except Exception:
            pass
except Exception:
    def _beep(freq=800, ms=120):
        pass

ctk.set_appearance_mode("dark")

BG      = "#05090f"
PANEL   = "#0a1220"
PANEL2  = "#0d1830"
SIDE    = "#070d18"
ACCENT  = "#00e5ff"
ACCENT2 = "#7c4dff"
PINK    = "#ff2d6f"
WHITE   = "#e8f3ff"
DIM     = "#7d94b8"
DARK    = "#0b1119"
GREEN   = "#00e676"
ORANGE  = "#ff9100"
RED     = "#ff1744"
FONT    = "Segoe UI"
FONTM   = "Consolas"
TICK    = 1000

THEMES = {
    "Neon Cyan": ("#00e5ff", "#7c4dff", "#ff2d6f"),
    "Sunset": ("#ff9100", "#ff2d6f", "#ffd600"),
    "Matrix": ("#00e676", "#00b0ff", "#76ff03"),
    "Royal": ("#7c4dff", "#00e5ff", "#ff2d6f"),
    "Crimson": ("#ff1744", "#ff9100", "#ff2d6f"),
}

LANG = "en"

TRANSLATIONS = {
    "  DASHBOARD": "  ড্যাশবোর্ড",
    "  OPTIMIZER": "  অপ্টিমাইজার",
    "  GAME BOOSTER": "  গেম বুস্টার",
    "  EMULATOR": "  এমুলেটর",
    "  SHIELD": "  শিল্ড",
    "  STARTUP": "  স্টার্টআপ",
    "  PROCESSES": "  প্রসেস",
    "  NETWORK": "  নেটওয়ার্ক",
    "  SETTINGS": "  সেটিংস",
    "DASHBOARD": "ড্যাশবোর্ড",
    "OPTIMIZER": "অপ্টিমাইজার",
    "GAME BOOSTER": "গেম বুস্টার",
    "EMULATOR OPS": "এমুলেটর অপস",
    "MALWARE SHIELD": "ম্যালওয়্যার শিল্ড",
    "STARTUP MANAGER": "স্টার্টআপ ম্যানেজার",
    "PROCESS KILLER": "প্রসেস কিলার",
    "NETWORK & PING": "নেটওয়ার্ক ও পিং",
    "SETTINGS": "সেটিংস",
    "Live system telemetry, FPS index and instant cleaners.":
        "লাইভ সিস্টেম টেলিমেট্রি, FPS ইনডেক্স ও ইনস্ট্যান্ট ক্লিনার।",
    "Every tweak is fully reversible. Apply what you want, restore anytime.":
        "প্রতিটি টিউইক সম্পূর্ণ রিভার্সিবল। যা চাও প্রয়োগ করো, যেকোনো সময় ফেরাও।",
    "ARM MAX FPS": "MAX FPS চালু",
    "RESTORE": "রিস্টোর",
    "APPLY": "প্রয়োগ",
    "APPLY ALL": "সব প্রয়োগ",
    "RESTORE ALL": "সব রিস্টোর",
    "RUN SCAN": "স্ক্যান চালাও",
    "CLEAN THREATS": "থ্রেট ক্লিন",
    "STATUS": "স্ট্যাটাস",
    "ENGAGE BOOSTER": "বুস্টার চালু",
    "STAND DOWN": "বন্ধ করো",
    "Deep Clean": "ডিপ ক্লিন",
    "Clean Temp": "টেম্প ক্লিন",
    "Flush DNS": "DNS ফ্লাশ",
    "Clean RAM": "RAM ক্লিন",
    "Restart Explorer": "এক্সপ্লোরার রিস্টার্ট",
    "ENABLE": "চালু",
    "DISABLE": "বন্ধ",
    "RESTART AS ADMIN": "অ্যাডমিন হিসেবে রিস্টার্ট",
    "CREATE RESTORE POINT": "রিস্টোর পয়েন্ট বানাও",
    "BENCHMARK": "বেঞ্চমার্ক",
    "FPS OVERLAY": "FPS ওভারলে",
    "AUTO-BOOST": "অটো-বুস্ট",
    "KILL": "কিল",
    "REFRESH": "রিফ্রেশ",
    "SET DNS": "DNS সেট",
    "RESTORE DHCP": "DHCP ফেরাও",
    "LANGUAGE": "ভাষা",
    "THEME": "থিম",
}


def tr(s):
    if LANG == "bn":
        return TRANSLATIONS.get(s, s)
    return s


def apply_theme(name):
    global ACCENT, ACCENT2, PINK
    a, b, c = THEMES.get(name, THEMES["Neon Cyan"])
    ACCENT, ACCENT2, PINK = a, b, c

HISTORY = {"cpu": deque(maxlen=64), "ram": deque(maxlen=64),
           "gpu": deque(maxlen=64)}


def _lerp(c1, c2, t):
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r1 + (r2 - r1) * t),
                              int(g1 + (g2 - g1) * t),
                              int(b1 + (b2 - b1) * t))


def _val_color(pct):
    if pct < 50:
        return _lerp(GREEN, ORANGE, pct / 50.0)
    return _lerp(ORANGE, RED, (pct - 50) / 50.0)


def _run_bg(fn, *a, **kw):
    def runner():
        try:
            fn(*a, **kw)
        except Exception as e:
            print("R1X worker error:", e)
    threading.Thread(target=runner, daemon=True).start()


class _GlowHeader(tk.Canvas):
    """Animated neon gradient sweep bar."""

    def __init__(self, master, colors, height=3):
        super().__init__(master, height=height, highlightthickness=0,
                         bd=0, bg=BG)
        self.colors = colors
        self.height = height
        self._phase = 0
        self._on = True
        self.bind("<Configure>", lambda e: self._redraw())
        self.after(45, self._animate)

    def destroy(self):
        self._on = False
        super().destroy()

    def _animate(self):
        if not self._on:
            return
        self._phase = (self._phase + 1) % 60
        self._redraw()
        self.after(45, self._animate)

    def _redraw(self):
        w = self.winfo_width()
        if w < 10:
            return
        self.delete("all")
        seg = 14
        n = len(self.colors)
        sw = w / (seg * n)
        for s in range(seg * n):
            pos = (s + self._phase) % (seg * n)
            base = int(pos * n / (seg * n)) % n
            t = (pos * n / (seg * n)) - base
            col = _lerp(self.colors[base], self.colors[(base + 1) % n], t)
            self.create_rectangle(s * sw, 0, (s + 1) * sw, self.height,
                                  fill=col, outline="")


class _Sparkline(tk.Canvas):
    """Scrolling mini line graph."""

    def __init__(self, master, color, width=200, height=44):
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, bg=PANEL)
        self.color = color
        self.w = width
        self.h = height
        self.data = deque(maxlen=64)

    def push(self, value):
        self.data.append(float(value))
        self._draw()

    def _draw(self):
        self.delete("all")
        n = len(self.data)
        if n < 2:
            return
        pad = 2
        lo = min(self.data) * 0.9
        hi = max(self.data) * 1.1 or 1.0
        span = max(hi - lo, 1e-6)
        pts = []
        for i, v in enumerate(self.data):
            x = pad + i * ((self.w - 2 * pad) / max(n - 1, 1))
            y = self.h - pad - ((v - lo) / span) * (self.h - 2 * pad)
            pts.append((x, y))
        for i in range(1, len(pts)):
            self.create_line(pts[i - 1][0], pts[i - 1][1],
                             pts[i][0], pts[i][1], fill=self.color, width=1.5)
        self.create_line(pts[-1][0], pts[-1][1], self.w - pad, pts[-1][1],
                         fill=self.color, width=2)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        global LANG
        pref = {}
        try:
            pref = core._load_state()
        except Exception:
            pass
        self.lang = pref.get("ui_lang", "en")
        self.theme = pref.get("ui_theme", "Neon Cyan")
        LANG = self.lang
        apply_theme(self.theme)

        self.title("R1X Optimizer v3 - Desktop Command Center")
        self.geometry("1180x780")
        self.minsize(980, 640)
        self.configure(fg_color=BG)
        self._load_icon()

        self._active = None
        self._pages = {}
        self._btns = {}
        self._admin = core.is_admin()

        self._build_nav()
        self._build_content()
        self._build_status()

        self._show("dashboard")
        self._tick_status()

    def _save_pref(self, key, value):
        try:
            st = core._load_state()
            st[key] = value
            core._save_state(st)
        except Exception:
            pass

    def _set_lang(self, value):
        global LANG
        self.lang = "bn" if value == "বাংলা" else "en"
        LANG = self.lang
        self._save_pref("ui_lang", self.lang)
        self._rebuild_shell()

    def _set_theme(self, value):
        self.theme = value
        apply_theme(value)
        self._save_pref("ui_theme", value)
        self._rebuild_shell()

    def _rebuild_shell(self):
        for w in self.winfo_children():
            w.destroy()
        self._btns = {}
        self._pages = {}
        self._build_nav()
        self._build_content()
        self._build_status()
        active = self._active or "dashboard"
        self._active = None
        self._show(active)

    def _load_icon(self):
        base = os.path.dirname(os.path.abspath(__file__))
        for ico in ("r1x_icon.ico", "r1x.ico"):
            p = os.path.join(base, ico)
            if os.path.exists(p):
                try:
                    self.iconbitmap(p)
                except Exception:
                    pass
                return

    # ---------------------------------------------------------- shell
    def _build_nav(self):
        nav = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=SIDE)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        ctk.CTkLabel(nav, text="R1X", font=(FONT, 36, "bold"),
                     text_color=ACCENT).pack(padx=22, pady=(26, 0), anchor="w")
        ctk.CTkLabel(nav, text="OPTIMIZER  v3", font=(FONTM, 9),
                     text_color=DIM).pack(padx=22, anchor="w")
        ctk.CTkFrame(nav, height=1, fg_color=DIM).pack(
            padx=18, pady=16, fill="x")

        page_defs = [
            ("dashboard", "  DASHBOARD", self._mk_dashboard),
            ("optimize", "  OPTIMIZER", self._mk_optimize),
            ("booster", "  GAME BOOSTER", self._mk_booster),
            ("emulator", "  EMULATOR", self._mk_emulator),
            ("shield", "  SHIELD", self._mk_shield),
            ("startup", "  STARTUP", self._mk_startup),
            ("processes", "  PROCESSES", self._mk_processes),
            ("network", "  NETWORK", self._mk_network),
            ("settings", "  SETTINGS", self._mk_settings),
        ]
        for key, label, builder in page_defs:
            btn = ctk.CTkButton(
                nav, text=tr(label), height=36, anchor="w",
                fg_color="transparent", hover_color="#12233f",
                font=(FONT, 12, "bold"), text_color=DIM,
                command=lambda k=key: self._show(k))
            btn.pack(padx=12, pady=1, fill="x")
            self._btns[key] = btn
            self._pages[key] = builder

        ctk.CTkFrame(nav, height=1, fg_color=DIM).pack(
            padx=18, pady=16, fill="x")
        self._admin_lbl = ctk.CTkLabel(
            nav, text="ADMIN" if self._admin else "NOT ADMIN",
            font=(FONTM, 9), text_color=GREEN if self._admin else RED)
        self._admin_lbl.pack(side="bottom", pady=(0, 4))
        ctk.CTkLabel(nav, text="Desktop Edition", font=(FONTM, 8),
                     text_color=DIM).pack(side="bottom", pady=(8, 0))

    def _build_content(self):
        wrap = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        wrap.pack(side="right", fill="both", expand=True)

        self.content = ctk.CTkFrame(wrap, corner_radius=0, fg_color=BG)
        self.content.pack(fill="both", expand=True)

        # shared log console
        self.log_wrap = ctk.CTkFrame(wrap, corner_radius=0, fg_color=DARK)
        self.log_wrap.pack(fill="x")
        head = ctk.CTkFrame(self.log_wrap, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(head, text="CONSOLE", font=(FONTM, 9, "bold"),
                     text_color=ACCENT).pack(side="left")
        ctk.CTkButton(head, text="clear", width=52, height=20,
                      fg_color="transparent", hover_color="#153050",
                      font=(FONTM, 9), text_color=DIM,
                      command=self._clear_log).pack(side="right")
        self.log_box = ctk.CTkTextbox(self.log_wrap, height=150,
                                      fg_color=DARK, text_color=GREEN,
                                      font=(FONTM, 10))
        self.log_box.pack(fill="x", padx=12, pady=(2, 10))
        self.log_box.configure(state="disabled")

    def _build_status(self):
        bar = ctk.CTkFrame(self, height=24, corner_radius=0, fg_color=DARK)
        bar.pack(side="bottom", fill="x")
        self.status_lbl = ctk.CTkLabel(bar, text="R1X READY",
                                       font=(FONTM, 9), text_color=DIM)
        self.status_lbl.pack(side="left", padx=14, pady=3)
        self.status_rt = ctk.CTkLabel(bar, text="", font=(FONTM, 9),
                                      text_color=DIM)
        self.status_rt.pack(side="right", padx=14, pady=3)

    # ---------------------------------------------------------- helpers
    def _show(self, key):
        if self._active == key:
            return
        for k, b in self._btns.items():
            b.configure(text_color=ACCENT if k == key else DIM,
                        fg_color="#0e1d33" if k == key else "transparent")
        for w in self.content.winfo_children():
            w.destroy()
        self._active = key
        self._pages[key]()

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def log(self, msg, tag="info"):
        """Thread-safe logger passed to every r1x_core call."""
        text = str(msg)
        def push():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        try:
            self.after(0, push)
        except Exception:
            pass

    def _section(self, title, sub=""):
        ctk.CTkLabel(self.content, text=tr(title), font=(FONT, 23, "bold"),
                     text_color=WHITE).pack(padx=26, pady=(22, 2), anchor="w")
        if sub:
            ctk.CTkLabel(self.content, text=tr(sub), font=(FONT, 11),
                         text_color=DIM, wraplength=760,
                         justify="left").pack(padx=26, anchor="w")
        _GlowHeader(self.content, [ACCENT, ACCENT2, PINK]).pack(
            fill="x", padx=26, pady=(12, 0))
        return ctk.CTkScrollableFrame(self.content, fg_color="transparent")

    def _panel(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10, **kw)

    @staticmethod
    def _alive(widget):
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _safe_ui(self, widget, fn):
        try:
            if not self._alive(widget):
                return
            fn()
        except Exception:
            pass

    # ============================================================ DASHBOARD
    def _mk_dashboard(self):
        body = self._section("DASHBOARD",
                             "Live system telemetry, FPS index and instant cleaners.")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        row = self._panel(body)
        row.pack(fill="x", pady=(4, 10))
        self._gauges = {}
        self._sparks = {}
        for key, label, color in [("cpu", "CPU", ACCENT),
                                  ("ram", "RAM", PINK),
                                  ("gpu", "GPU", ACCENT2)]:
            g = self._panel(row)
            g.pack(side="left", padx=10, pady=10, expand=True, fill="both")
            ctk.CTkLabel(g, text=label, font=(FONT, 13, "bold"),
                         text_color=color).pack(pady=(12, 0))
            bar = ctk.CTkProgressBar(g, width=170, height=13, corner_radius=7,
                                     progress_color=color)
            bar.pack(pady=6)
            bar.set(0)
            pct = ctk.CTkLabel(g, text="0%", font=(FONTM, 20, "bold"),
                               text_color=WHITE)
            pct.pack(pady=(0, 4))
            spark = _Sparkline(g, color)
            spark.pack(pady=(2, 12))
            self._gauges[key] = (bar, pct)
            self._sparks[key] = spark

        stats = self._panel(body)
        stats.pack(fill="x", pady=6)
        self._stat_lbl = ctk.CTkLabel(stats, text="Reading system...",
                                      font=(FONTM, 11), text_color=DIM,
                                      anchor="w", justify="left")
        self._stat_lbl.pack(padx=16, pady=10, anchor="w")
        self._fps_lbl = ctk.CTkLabel(stats, text="FPS INDEX  --",
                                     font=(FONT, 15, "bold"),
                                     text_color=ACCENT)
        self._fps_lbl.pack(padx=16, pady=(0, 12), anchor="w")

        qa = self._panel(body)
        qa.pack(fill="x", pady=6)
        ctk.CTkLabel(qa, text="INSTANT CLEANERS", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        bf = ctk.CTkFrame(qa, fg_color="transparent")
        bf.pack(padx=16, pady=(0, 12), fill="x")
        for label, fn in [("Clean Temp", core.clear_temp),
                          ("Deep Clean", core.deep_clean),
                          ("Flush DNS", core.flush_dns),
                          ("Clean RAM", core.clean_ram),
                          ("Restart Explorer", core.restart_explorer)]:
            ctk.CTkButton(bf, text=tr(label), width=132, height=34,
                          fg_color=DARK, hover_color="#1a2a3a",
                          font=(FONT, 11), text_color=WHITE,
                          command=lambda f=fn: self._quick(f)).pack(
                side="left", padx=4)

        self._tick_dash()

    def _quick(self, fn):
        def worker():
            fn(self.log)
            _beep(600, 60)
        _run_bg(worker)

    def _tick_dash(self):
        if self._active != "dashboard":
            return
        def poll():
            try:
                s = core.live_snapshot()
                cpu = int(s.get("cpu", 0))
                ram = int(s.get("ram", 0))
                gpu = int(s.get("gpu") or 0)
                HISTORY["cpu"].append(cpu)
                HISTORY["ram"].append(ram)
                HISTORY["gpu"].append(gpu)
                txt = ("Cores: %s     GPU: %s\n"
                       "RAM  %s / %s GB free"
                       % (s.get("cores", "?"), s.get("gpu") or "N/A",
                          s.get("memAvailGB", "?"), s.get("memTotalGB", "?")))
                fps = s.get("fpsIndex", 0)
                self.after(0, lambda: self._safe_ui(
                    self, lambda: self._paint(cpu, ram, gpu, txt, fps)))
            except Exception:
                pass
        _run_bg(poll)
        self.after(TICK, self._tick_dash)

    def _paint(self, cpu, ram, gpu, txt, fps):
        for key, val in [("cpu", cpu), ("ram", ram), ("gpu", gpu)]:
            try:
                bar, pct = self._gauges[key]
                bar.set(val / 100.0)
                bar.configure(progress_color=_val_color(val))
                pct.configure(text="%d%%" % val, text_color=_val_color(val))
                self._sparks[key].push(val)
            except Exception:
                pass
        self._stat_lbl.configure(text=txt)
        col = _val_color(100 - fps)
        self._fps_lbl.configure(text="FPS INDEX  %s" % fps, text_color=col)

    # ============================================================ OPTIMIZER
    def _mk_optimize(self):
        body = self._section(
            "OPTIMIZER",
            "Every tweak is fully reversible. Apply what you want, restore anytime.")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        top = self._panel(body)
        top.pack(fill="x", pady=(4, 10))
        bf = ctk.CTkFrame(top, fg_color="transparent")
        bf.pack(padx=16, pady=12, anchor="w")
        ctk.CTkButton(bf, text=tr("APPLY ALL"), width=140, height=42,
                      fg_color=ACCENT2, hover_color="#9c6dff",
                      font=(FONT, 13, "bold"), text_color=WHITE,
                      command=self._apply_all).pack(side="left", padx=(0, 10))
        ctk.CTkButton(bf, text=tr("RESTORE ALL"), width=140, height=42,
                      fg_color=DARK, hover_color="#1a2a3a",
                      font=(FONT, 13), text_color=WHITE,
                      command=self._restore_all).pack(side="left", padx=(0, 10))
        ctk.CTkButton(bf, text=tr("CREATE RESTORE POINT"), width=190, height=42,
                      fg_color=PINK, hover_color="#ff5090",
                      font=(FONT, 12, "bold"), text_color=WHITE,
                      command=lambda: self._quick(core.create_restore_point)).pack(
            side="left", padx=(0, 10))
        ctk.CTkButton(bf, text=tr("BENCHMARK"), width=140, height=42,
                      fg_color=DARK, hover_color="#1a2a3a",
                      font=(FONT, 13), text_color=WHITE,
                      command=self._bench).pack(side="left")

        self._bench_lbl = ctk.CTkLabel(top, text="Benchmark: not run yet",
                                       font=(FONTM, 11), text_color=DIM,
                                       anchor="w", justify="left")
        self._bench_lbl.pack(padx=16, pady=(0, 12), anchor="w")

        try:
            fixes = core.get_fixes()
            applied = set(core.BACKUP.applied_ids())
        except Exception:
            fixes, applied = [], set()

        self._applied = applied
        by_cat = {}
        for f in fixes:
            by_cat.setdefault(f.get("category", "Other"), []).append(f)

        for cat, items in by_cat.items():
            head = self._panel(body)
            head.pack(fill="x", pady=(8, 2))
            ctk.CTkLabel(head, text=cat.upper(), font=(FONT, 13, "bold"),
                         text_color=ACCENT).pack(padx=16, pady=8, anchor="w")
            for f in items:
                self._fix_row(body, f, f["id"] in applied)

    def _fix_row(self, parent, fix, active):
        row = self._panel(parent)
        row.pack(fill="x", pady=3)
        title = ctk.CTkFrame(row, fg_color="transparent")
        title.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(title, text=fix.get("name", "?"),
                     font=(FONT, 13, "bold"), text_color=WHITE,
                     anchor="w").pack(side="left")
        risk = fix.get("risk", "low")
        rcol = {"low": GREEN, "medium": ORANGE, "high": RED}.get(risk, GREEN)
        ctk.CTkLabel(title, text="  %s" % risk.upper(), font=(FONTM, 8),
                     text_color=rcol).pack(side="left")
        if fix.get("admin"):
            ctk.CTkLabel(title, text="  ADMIN", font=(FONTM, 8),
                         text_color=ACCENT).pack(side="left")
        if active:
            ctk.CTkLabel(title, text="  ACTIVE", font=(FONTM, 8),
                         text_color=GREEN).pack(side="right")
        ctk.CTkLabel(row, text=fix.get("desc", ""), font=(FONT, 10),
                     text_color=DIM, anchor="w", wraplength=620,
                     justify="left").pack(padx=16, pady=(0, 8), anchor="w")
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(padx=16, pady=(0, 12), anchor="e")
        ctk.CTkButton(btns, text=tr("APPLY"), width=110, height=32,
                      fg_color=ACCENT2, hover_color="#9c6dff",
                      font=(FONT, 11, "bold"),
                      command=lambda i=fix["id"]: self._do_fix(i, True)).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text=tr("RESTORE"), width=110, height=32,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 11),
                      command=lambda i=fix["id"]: self._do_fix(i, False)).pack(
            side="left")

    def _bench(self):
        self._bench_lbl.configure(text="Benchmark: sampling %s..." % (
            time.strftime("%H:%M:%S")), text_color=ORANGE)
        def worker():
            b = core.benchmark(4)
            txt = ("FPS INDEX %s   CPU %s%%   RAM %s%%   GPU %s%%"
                   % (b["fps"], b["cpu"], b["ram"], b["gpu"]))
            self.after(0, lambda: self._safe_ui(
                    self._bench_lbl,
                    lambda: self._bench_lbl.configure(
                        text=txt, text_color=ACCENT)))
            self.log("BENCHMARK   | %s" % txt, "win")
            _beep(880, 100)
        _run_bg(worker)

    def _do_fix(self, fid, apply_):
        def worker():
            if apply_:
                core.apply_fix(fid, self.log)
                _beep(880, 90)
            else:
                core.restore_fix(fid, self.log)
                _beep(500, 90)
        _run_bg(worker)

    def _apply_all(self):
        def worker():
            for f in core.get_fixes():
                core.apply_fix(f["id"], self.log)
            _beep(1000, 160)
        _run_bg(worker)

    def _restore_all(self):
        def worker():
            for f in core.get_fixes():
                core.restore_fix(f["id"], self.log)
            _beep(420, 160)
        _run_bg(worker)

    # ============================================================ BOOSTER
    def _mk_booster(self):
        body = self._section(
            "GAME BOOSTER",
            "Live foreground-priority booster: the game in focus always gets "
            "CPU attention. Toggle it, forget it.")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        card = self._panel(body)
        card.pack(fill="x", pady=6)
        self._boost_lbl = ctk.CTkLabel(card, text="Booster: checking...",
                                       font=(FONTM, 11), text_color=DIM)
        self._boost_lbl.pack(padx=16, pady=14, anchor="w")
        bf = ctk.CTkFrame(card, fg_color="transparent")
        bf.pack(padx=16, pady=(0, 14), anchor="w")
        ctk.CTkButton(bf, text="ENGAGE BOOSTER", width=180, height=44,
                      fg_color=ACCENT2, hover_color="#9c6dff",
                      font=(FONT, 13, "bold"), text_color=WHITE,
                      command=lambda: self._boost(True)).pack(
            side="left", padx=(0, 10))
        ctk.CTkButton(bf, text="STAND DOWN", width=160, height=44,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 13),
                      text_color=WHITE,
                      command=lambda: self._boost(False)).pack(side="left")

        extra = self._panel(body)
        extra.pack(fill="x", pady=6)
        ctk.CTkLabel(extra, text="AUTO & OVERLAY", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        self._overlay_sw = ctk.CTkSwitch(
            extra, text=tr("FPS OVERLAY"), font=(FONT, 12),
            progress_color=ACCENT2, command=self._toggle_overlay)
        self._overlay_sw.pack(padx=16, pady=6, anchor="w")
        self._auto_sw = ctk.CTkSwitch(
            extra, text=tr("AUTO-BOOST"), font=(FONT, 12),
            progress_color=ACCENT2, command=self._toggle_auto)
        self._auto_sw.pack(padx=16, pady=6, anchor="w")
        ctk.CTkLabel(
            extra,
            text=("FPS OVERLAY: floating live monitor, right-click to close.\n"
                  "AUTO-BOOST: watches for BlueStacks/MSI and arms MAX FPS "
                  "automatically."),
            font=(FONTM, 9), text_color=DIM, justify="left").pack(
            padx=16, pady=(0, 12), anchor="w")
        self._sync_boost_switches()

        info = self._panel(body)
        info.pack(fill="x", pady=6)
        ctk.CTkLabel(info, text="How it works", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        ctk.CTkLabel(
            info,
            text=("1.  Runs quietly in the background.\n"
                  "2.  Detects whichever window is in focus.\n"
                  "3.  Raises that process to High CPU priority.\n"
                  "4.  Re-checks every 1.5 s - switch games freely.\n\n"
                  "No file changes. Stand down anytime."),
            font=(FONTM, 10), text_color=DIM, justify="left").pack(
            padx=16, pady=(0, 12), anchor="w")
        self._refresh_boost()

    def _boost(self, on):
        try:
            core.BOOSTER.start_boost() if on else core.BOOSTER.stop_boost()
        except Exception as e:
            self.log("BOOSTER | error: %s" % e, "error")
        _beep(900 if on else 500, 110)
        self.after(400, self._refresh_boost)

    def _refresh_boost(self):
        def poll():
            try:
                st = core.booster_status()
                on = st.get("running")
                txt = "Booster: %s   last boosted PID: %s" % (
                    "ACTIVE" if on else "STANDBY", st.get("pid") or "-")
                self.after(0, lambda: self._safe_ui(
                    self._boost_lbl,
                    lambda: self._boost_lbl.configure(
                        text=txt, text_color=GREEN if on else DIM)))
            except Exception:
                pass
        _run_bg(poll)

    def _sync_boost_switches(self):
        try:
            if core.WATCHER.running:
                self._auto_sw.select()
            if getattr(self, "_overlay_on", False):
                self._overlay_sw.select()
        except Exception:
            pass

    def _toggle_overlay(self):
        if not self._overlay_sw.get():
            self._overlay_on = False
            self.log("OVERLAY     | close an open overlay with right-click",
                     "info")
            return
        self._overlay_on = True
        self.log("OVERLAY     | floating FPS monitor launched", "win")
        _beep(900, 90)
        try:
            import subprocess
            if getattr(sys, "frozen", False):
                args = [sys.executable, "--overlay"]
            else:
                args = [sys.executable, os.path.abspath(__file__), "--overlay"]
            subprocess.Popen(args, creationflags=getattr(
                subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            self.log("OVERLAY     | error: %s" % e, "error")

    def _overlay_closed(self):
        self._overlay_on = False
        try:
            self.after(0, lambda: self._overlay_sw.deselect())
        except Exception:
            pass

    def _toggle_auto(self):
        on = bool(self._auto_sw.get())
        _run_bg(core.game_watch, on, self.log)
        _beep(880 if on else 500, 90)

    # ============================================================ EMULATOR
    def _mk_emulator(self):
        body = self._section(
            "EMULATOR OPS",
            "Game-safe MAX FPS pipeline for BlueStacks / MSI App Player - "
            "no cache-purging, no throttle.")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        try:
            emus = core.emulator_status()
        except Exception:
            emus = []
        if isinstance(emus, dict):
            emus = emus.get("emulators", [])

        for emu in emus or []:
            if not isinstance(emu, dict):
                continue
            key = emu.get("key", "?")
            name = emu.get("name", key)
            installed = bool(emu.get("installed"))
            running = bool(emu.get("running"))
            row = self._panel(body)
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=name, font=(FONT, 15, "bold"),
                         text_color=WHITE).pack(padx=16, pady=(12, 2),
                                                anchor="w")
            status = ("RUNNING" if running else
                      "Installed" if installed else "Not detected")
            ctk.CTkLabel(row, text=status, font=(FONTM, 10),
                         text_color=GREEN if installed else DIM).pack(
                padx=16, anchor="w")
            ctk.CTkLabel(row, text=emu.get("exe") or "", font=(FONTM, 9),
                         text_color=DIM).pack(padx=16, anchor="w")
            bf = ctk.CTkFrame(row, fg_color="transparent")
            bf.pack(padx=16, pady=(8, 14), anchor="w")
            if installed:
                ctk.CTkButton(bf, text="ARM MAX FPS", width=160, height=40,
                              fg_color=ACCENT2, hover_color="#9c6dff",
                              font=(FONT, 12, "bold"),
                              command=lambda k=key: self._emu_arm(k)).pack(
                    side="left", padx=(0, 8))
                ctk.CTkButton(bf, text="RESTORE", width=130, height=40,
                              fg_color=DARK, hover_color="#1a2a3a",
                              font=(FONT, 12),
                              command=self._emu_restore).pack(side="left")
            else:
                ctk.CTkButton(bf, text="NOT INSTALLED", width=160, height=40,
                              fg_color=DARK, font=(FONT, 12),
                              state="disabled").pack(side="left")

        card = self._panel(body)
        card.pack(fill="x", pady=6)
        ctk.CTkLabel(card, text="What MAX FPS does", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        ctk.CTkLabel(
            card,
            text=("+  High-Performance power plan with turbo boost\n"
                  "+  GPU scheduler priority for games (GPU Priority 8)\n"
                  "+  Game Mode on, GameDVR capture off\n"
                  "+  1 ms timer resolution (reduced CPU wake)\n"
                  "+  Windows Defender realtime AV muted for the session\n"
                  "+  Emulator process raised to High priority\n"
                  "+  Game cache preserved - hot assets stay in RAM\n\n"
                  "RESTORE reverts every change including Defender."),
            font=(FONTM, 10), text_color=DIM, justify="left").pack(
            padx=16, pady=(0, 14), anchor="w")

    def _emu_arm(self, key):
        def worker():
            core.emulator_run(key, self.log)
            _beep(1000, 150)
        _run_bg(worker)

    def _emu_restore(self):
        def worker():
            core.restore_emulator_optimize(self.log)
            _beep(460, 150)
        _run_bg(worker)

    # ============================================================ SHIELD
    def _mk_shield(self):
        body = self._section(
            "MALWARE SHIELD",
            "Scans running processes, autoruns, temp droppers and hosts file.")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        bf = self._panel(body)
        bf.pack(fill="x", pady=6)
        inner = ctk.CTkFrame(bf, fg_color="transparent")
        inner.pack(padx=16, pady=12, anchor="w")
        ctk.CTkButton(inner, text="RUN SCAN", width=150, height=42,
                      fg_color=ACCENT2, hover_color="#9c6dff",
                      font=(FONT, 13, "bold"), text_color=WHITE,
                      command=self._scan).pack(side="left", padx=(0, 10))
        ctk.CTkButton(inner, text="CLEAN THREATS", width=160, height=42,
                      fg_color=PINK, hover_color="#ff5090",
                      font=(FONT, 13, "bold"), text_color=WHITE,
                      command=self._clean).pack(side="left", padx=(0, 10))
        ctk.CTkButton(inner, text="STATUS", width=120, height=42,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 13),
                      text_color=WHITE, command=self._shield_status).pack(
            side="left")

        self._findings = []
        self._result_box = ctk.CTkTextbox(body, height=260, fg_color=PANEL,
                                          text_color=WHITE,
                                          font=(FONTM, 10))
        self._result_box.pack(fill="both", expand=True, pady=6)
        self._result_box.configure(state="disabled")

    def _rbox(self, text):
        if not self._alive(self._result_box):
            return

        def push():
            if not self._alive(self._result_box):
                return
            self._result_box.configure(state="normal")
            self._result_box.insert("end", text + "\n")
            self._result_box.see("end")
            self._result_box.configure(state="disabled")
        self.after(0, push)

    def _scan(self):
        self._rbox("--- SCAN STARTED ---")
        def worker():
            try:
                self._findings = core.malware_scan(self.log) or []
                if self._findings:
                    for f in self._findings:
                        self._rbox("  [sev %s] %s  ->  %s"
                                   % (f.get("severity", "?"),
                                      f.get("name", "?"), f.get("path", "")))
                else:
                    self._rbox("  No threats found. System clean.")
                self._rbox("--- SCAN COMPLETE: %d finding(s) ---"
                           % len(self._findings))
                _beep(900, 100)
            except Exception as e:
                self._rbox("ERROR: %s" % e)
        _run_bg(worker)

    def _clean(self):
        if not self._findings:
            self._rbox("Nothing to clean - run a scan first.")
            return
        def worker():
            core.malware_clean(self._findings, self.log)
            self._rbox("--- CLEAN COMPLETE ---")
            _beep(1100, 160)
            self._findings = []
        _run_bg(worker)

    def _shield_status(self):
        def worker():
            try:
                st = core.malware_status()
                for k, v in st.items():
                    self._rbox("  %-14s %s" % (k, v))
            except Exception as e:
                self._rbox("ERROR: %s" % e)
        _run_bg(worker)

    # ============================================================ STARTUP
    def _mk_startup(self):
        body = self._section(
            "STARTUP MANAGER",
            "Control which programs launch with Windows. Disabled registry "
            "items are saved and fully restorable.")
        body.pack(fill="both", expand=True, padx=16, pady=10)
        bar = self._panel(body)
        bar.pack(fill="x", pady=6)
        ctk.CTkButton(bar, text=tr("REFRESH"), width=130, height=36,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 12),
                      command=self._fill_startup).pack(padx=16, pady=10,
                                                      anchor="w")
        self._startup_box = ctk.CTkFrame(body, fg_color="transparent")
        self._startup_box.pack(fill="both", expand=True)
        self._fill_startup()

    def _fill_startup(self):
        for w in self._startup_box.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._startup_box, text="reading startup entries...",
                     font=(FONTM, 10), text_color=DIM).pack(padx=16, anchor="w")

        def worker():
            items = core.list_startup()
            self.after(0, lambda: self._render_startup(items))
        _run_bg(worker)

    def _render_startup(self, items):
        if not self._alive(self._startup_box):
            return
        for w in self._startup_box.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(self._startup_box, text="No startup entries found.",
                         font=(FONTM, 10), text_color=DIM).pack(padx=16,
                                                                anchor="w")
            return
        for it in items:
            row = self._panel(self._startup_box)
            row.pack(fill="x", pady=3)
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=16, pady=10)
            ctk.CTkLabel(left, text=it.get("name", "?"),
                         font=(FONT, 12, "bold"),
                         text_color=WHITE if it.get("enabled") else DIM,
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(left, text="%s   %s" % (it.get("location", ""),
                                                 (it.get("cmd", "") or "")[:78]),
                         font=(FONTM, 9), text_color=DIM,
                         anchor="w").pack(anchor="w")
            en = bool(it.get("enabled"))
            ctk.CTkButton(row, text=tr("DISABLE") if en else tr("ENABLE"),
                          width=100, height=32,
                          fg_color=DARK if en else ACCENT2,
                          hover_color="#1a2a3a" if en else "#9c6dff",
                          font=(FONT, 11),
                          command=lambda i=it: self._toggle_startup(i)).pack(
                side="right", padx=16)

    def _toggle_startup(self, item):
        def worker():
            core.toggle_startup(item, self.log)
            self._fill_startup()
            _beep(700, 80)
        _run_bg(worker)

    # ============================================================ PROCESSES
    def _mk_processes(self):
        body = self._section(
            "PROCESS KILLER",
            "Top CPU / RAM consumers right now. Kill any runaway task "
            "instantly.")
        body.pack(fill="both", expand=True, padx=16, pady=10)
        bar = self._panel(body)
        bar.pack(fill="x", pady=6)
        ctk.CTkButton(bar, text=tr("REFRESH"), width=130, height=36,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 12),
                      command=self._fill_procs).pack(padx=16, pady=10,
                                                     anchor="w")
        self._proc_box = ctk.CTkFrame(body, fg_color="transparent")
        self._proc_box.pack(fill="both", expand=True)
        self._fill_procs()

    def _fill_procs(self):
        for w in self._proc_box.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._proc_box, text="sampling processes...",
                     font=(FONTM, 10), text_color=DIM).pack(padx=16, anchor="w")

        def worker():
            procs = core.top_processes(15)
            self.after(0, lambda: self._render_procs(procs))
        _run_bg(worker)

    def _render_procs(self, procs):
        if not self._alive(self._proc_box):
            return
        for w in self._proc_box.winfo_children():
            w.destroy()
        head = self._panel(self._proc_box)
        head.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(head, text="%-24s %9s %11s" % ("PROCESS", "CPU%", "RAM MB"),
                     font=(FONTM, 9, "bold"), text_color=ACCENT,
                     anchor="w").pack(side="left", padx=16, pady=6)
        for p in procs:
            row = self._panel(self._proc_box)
            row.pack(fill="x", pady=2)
            col = ORANGE if p["cpu"] >= 25 else WHITE
            ctk.CTkLabel(row, text="%-24s %8.1f%% %10.1f"
                         % (p["name"][:24], p["cpu"], p["ram"]),
                         font=(FONTM, 10), text_color=col,
                         anchor="w").pack(side="left", padx=16, pady=8)
            ctk.CTkButton(row, text=tr("KILL"), width=70, height=28,
                          fg_color=PINK, hover_color="#ff5090",
                          font=(FONT, 10, "bold"),
                          command=lambda pid=p["pid"]: self._kill(pid)).pack(
                side="right", padx=16, pady=6)

    def _kill(self, pid):
        def worker():
            core.kill_process(pid, self.log)
            self._fill_procs()
            _beep(500, 90)
        _run_bg(worker)

    # ============================================================ NETWORK
    def _mk_network(self):
        body = self._section(
            "NETWORK & PING",
            "Find the fastest DNS resolver and measure game-server latency.")
        body.pack(fill="both", expand=True, padx=16, pady=10)
        bar = self._panel(body)
        bar.pack(fill="x", pady=6)
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(padx=16, pady=12, anchor="w")
        ctk.CTkButton(inner, text="Benchmark DNS", width=150, height=40,
                      fg_color=ACCENT2, hover_color="#9c6dff",
                      font=(FONT, 12, "bold"),
                      command=self._dns_bench).pack(side="left", padx=(0, 8))
        ctk.CTkButton(inner, text="Ping Games", width=140, height=40,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 12),
                      command=self._ping_games).pack(side="left", padx=(0, 8))
        ctk.CTkButton(inner, text=tr("RESTORE DHCP"), width=150, height=40,
                      fg_color=DARK, hover_color="#1a2a3a", font=(FONT, 12),
                      command=lambda: self._quick(core.restore_dns)).pack(
            side="left")
        self._dns_box = ctk.CTkFrame(body, fg_color="transparent")
        self._dns_box.pack(fill="x", pady=6)
        self._net_log = ctk.CTkTextbox(body, height=190, fg_color=PANEL,
                                       text_color=WHITE, font=(FONTM, 10))
        self._net_log.pack(fill="both", expand=True, pady=6)
        self._net_log.configure(state="disabled")

    def _nlog(self, text):
        if not self._alive(self._net_log):
            return

        def push():
            if not self._alive(self._net_log):
                return
            self._net_log.configure(state="normal")
            self._net_log.insert("end", str(text) + "\n")
            self._net_log.see("end")
            self._net_log.configure(state="disabled")
        self.after(0, push)

    def _dns_bench(self):
        for w in self._dns_box.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._dns_box, text="probing resolvers...",
                     font=(FONTM, 10), text_color=DIM).pack(padx=16, anchor="w")

        def worker():
            res = core.benchmark_dns(self.log, 3)
            self.after(0, lambda: self._render_dns(res))
        _run_bg(worker)

    def _render_dns(self, res):
        if not self._alive(self._dns_box):
            return
        for w in self._dns_box.winfo_children():
            w.destroy()
        for i, r in enumerate(res):
            row = self._panel(self._dns_box)
            row.pack(fill="x", pady=2)
            best = i == 0 and r.get("latency") is not None
            col = GREEN if best else WHITE
            lat = ("%d ms" % r["latency"]) if r.get("latency") is not None else "--"
            ctk.CTkLabel(row, text="%-11s  %-15s  %s"
                         % (r["name"], r["primary"], lat),
                         font=(FONTM, 11), text_color=col,
                         anchor="w").pack(side="left", padx=16, pady=8)
            ctk.CTkButton(row, text=tr("SET DNS"), width=100, height=28,
                          fg_color=ACCENT2 if best else DARK,
                          hover_color="#9c6dff", font=(FONT, 10, "bold"),
                          command=lambda n=r["name"]: self._set_dns(n)).pack(
                side="right", padx=16)

    def _set_dns(self, name):
        def worker():
            core.set_dns(name, self.log)
            _beep(900, 90)
        _run_bg(worker)

    def _ping_games(self):
        def worker():
            res = core.ping_games(self.log, 3)
            for r in res:
                lat = ("%d ms" % r["latency"]) if r.get("latency") is not None \
                    else "no reply"
                self._nlog("%-20s %s" % (r["name"], lat))
        _run_bg(worker)

    # ============================================================ SETTINGS
    def _mk_settings(self):
        body = self._section("SETTINGS",
                             "System overview, startup behaviour and maintenance.")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        info = self._panel(body)
        info.pack(fill="x", pady=6)
        ctk.CTkLabel(info, text="SYSTEM", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        self._sys_lbl = ctk.CTkLabel(info, text="Reading...", font=(FONTM, 10),
                                     text_color=DIM, justify="left",
                                     anchor="w")
        self._sys_lbl.pack(padx=16, pady=(0, 12), anchor="w")
        self._refresh_sys()

        auto = self._panel(body)
        auto.pack(fill="x", pady=6)
        ctk.CTkLabel(auto, text="START WITH WINDOWS", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        af = ctk.CTkFrame(auto, fg_color="transparent")
        af.pack(padx=16, pady=(0, 12), anchor="w")
        self._auto_lbl = ctk.CTkLabel(af, text="Checking...",
                                      font=(FONTM, 10), text_color=DIM)
        self._auto_lbl.pack(side="left", padx=(0, 12))
        ctk.CTkButton(af, text="ENABLE", width=110, height=32,
                      fg_color=ACCENT2, font=(FONT, 11),
                      command=lambda: self._autostart(True)).pack(
            side="left", padx=4)
        ctk.CTkButton(af, text="DISABLE", width=110, height=32,
                      fg_color=DARK, font=(FONT, 11),
                      command=lambda: self._autostart(False)).pack(
            side="left", padx=4)
        self._refresh_auto()

        maint = self._panel(body)
        maint.pack(fill="x", pady=6)
        ctk.CTkLabel(maint, text="MAINTENANCE", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        mf = ctk.CTkFrame(maint, fg_color="transparent")
        mf.pack(padx=16, pady=(0, 12), anchor="w")
        for label, fn in [("Clear Temp", core.clear_temp),
                          ("Deep Clean", core.deep_clean),
                          ("Clean RAM", core.clean_ram),
                          ("Flush DNS", core.flush_dns),
                          ("Restart Explorer", core.restart_explorer)]:
            ctk.CTkButton(mf, text=tr(label), width=140, height=34,
                          fg_color=DARK, hover_color="#1a2a3a",
                          font=(FONT, 11), text_color=WHITE,
                          command=lambda f=fn: self._quick(f)).pack(
                side="left", padx=4)

        appear = self._panel(body)
        appear.pack(fill="x", pady=6)
        ctk.CTkLabel(appear, text="APPEARANCE", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        af2 = ctk.CTkFrame(appear, fg_color="transparent")
        af2.pack(padx=16, pady=(0, 12), anchor="w")
        ctk.CTkLabel(af2, text=tr("LANGUAGE"), font=(FONT, 11),
                     text_color=DIM).pack(side="left", padx=(0, 8))
        lang_menu = ctk.CTkOptionMenu(
            af2, values=["English", "বাংলা"], width=130,
            fg_color=DARK, button_color=ACCENT2,
            command=self._set_lang)
        lang_menu.set("বাংলা" if self.lang == "bn" else "English")
        lang_menu.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(af2, text=tr("THEME"), font=(FONT, 11),
                     text_color=DIM).pack(side="left", padx=(0, 8))
        theme_menu = ctk.CTkOptionMenu(
            af2, values=list(THEMES.keys()), width=150,
            fg_color=DARK, button_color=ACCENT2,
            command=self._set_theme)
        theme_menu.set(self.theme)
        theme_menu.pack(side="left")

        admin = self._panel(body)
        admin.pack(fill="x", pady=6)
        ctk.CTkLabel(admin, text="ADMINISTRATOR", font=(FONT, 13, "bold"),
                     text_color=WHITE).pack(padx=16, pady=(10, 4), anchor="w")
        self._admin_lbl2 = ctk.CTkLabel(
            admin, text=("Running elevated - full arsenal unlocked"
                         if self._admin else
                         "Not elevated - power/registry tweaks need admin"),
            font=(FONTM, 10), text_color=GREEN if self._admin else ORANGE,
            justify="left")
        self._admin_lbl2.pack(padx=16, pady=(0, 8), anchor="w")
        if not self._admin:
            ctk.CTkButton(admin, text="RESTART AS ADMIN", width=180, height=38,
                          fg_color=PINK, hover_color="#ff5090",
                          font=(FONT, 12, "bold"), text_color=WHITE,
                          command=self._elevate).pack(padx=16, pady=(0, 14),
                                                      anchor="w")

    def _elevate(self):
        if core.elevate():
            self.destroy()

    def _autostart(self, on):
        def worker():
            core.set_autostart(on, self.log)
            self.after(400, self._refresh_auto)
        _run_bg(worker)

    def _refresh_sys(self):
        def poll():
            try:
                si = core.system_info()
                ram_gb = round(si.get("ram", 0) / 1024 ** 3, 1) if si.get("ram") else "?"
                txt = ("OS     : %s\nCPU    : %s\nCores  : %s    GPU: %s\nRAM    : %s GB"
                       % (si.get("os", "?"), si.get("cpu", "?"),
                          si.get("cores", "?"), si.get("gpu", "?"), ram_gb))
                self.after(0, lambda: self._safe_ui(
                    self._sys_lbl,
                    lambda: self._sys_lbl.configure(text=txt)))
            except Exception:
                pass
        _run_bg(poll)

    def _refresh_auto(self):
        def poll():
            try:
                on = core.autostart_status()
                self.after(0, lambda: self._safe_ui(
                    self._auto_lbl,
                    lambda: self._auto_lbl.configure(
                        text="Enabled" if on else "Disabled",
                        text_color=GREEN if on else DIM)))
            except Exception:
                pass
        _run_bg(poll)

    # ============================================================ STATUS
    def _tick_status(self):
        def poll():
            try:
                s = core.live_snapshot()
                txt = "CPU %s%%   RAM %s%%   GPU %s%%   |   %s" % (
                    int(s.get("cpu", 0)), int(s.get("ram", 0)),
                    int(s.get("gpu") or 0), time.strftime("%H:%M:%S"))
                self.after(0, lambda: self._safe_ui(
                    self.status_rt,
                    lambda: self.status_rt.configure(text=txt)))
            except Exception:
                pass
        _run_bg(poll)
        self.after(TICK, self._tick_status)


def main():
    if "--overlay" in sys.argv:
        core.spawn_overlay(core.live_snapshot)
        return
    if not core.is_admin():
        if core.elevate():
            return
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()




