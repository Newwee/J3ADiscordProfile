"""
RPC Studio - Discord Rich Presence Controller
Dev Panel theme · Dark · Smooth transitions

ติดตั้ง:  pip install customtkinter pypresence pillow
รัน:      python main.py
"""

import asyncio
import datetime
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageChops, ImageDraw, ImageTk
from pypresence import Presence

try:
    from pypresence.exceptions import (
        DiscordNotFound,
        InvalidID,
        InvalidPipe,
        PipeClosed,
    )

    CONN_ERRORS = (
        PipeClosed,
        InvalidPipe,
        DiscordNotFound,
        BrokenPipeError,
        ConnectionError,
    )
except Exception:  # pypresence เวอร์ชันเก่า
    CONN_ERRORS = (BrokenPipeError, ConnectionError)

# ─────────────────────────────────────────────────────────────
#  PyInstaller & Windows Compatibility
# ─────────────────────────────────────────────────────────────
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w")
    except Exception:
        pass

if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("J3A.DiscordProfile.App.1.0")
    except Exception:
        pass


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller bundle"""
    if hasattr(sys, "_MEIPASS"):
        p = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(p):
            return p
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
        p = os.path.join(base_dir, relative_path)
        if os.path.exists(p):
            return p
    script_dir = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(script_dir, relative_path)
    if os.path.exists(p):
        return p
    return os.path.abspath(relative_path)


# ─────────────────────────────────────────────────────────────
#  Constants & Theme
# ─────────────────────────────────────────────────────────────
APP_NAME = "J3A Discord Profile"
APP_VERSION = "2.0"

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
FONT = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
MONO = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")

C = {
    "bg": "#0a0c10",
    "sidebar": "#0e1116",
    "card": "#12161d",
    "card2": "#171c26",
    "border": "#1f2632",
    "input": "#0c0f14",
    "input_border": "#242c3a",
    "text": "#e8ebf1",
    "muted": "#8a93a5",
    "faint": "#4d5565",
    "ok": "#22c55e",
    "err": "#ef4444",
    "warn": "#f59e0b",
    "discord": "#15181f",
}

ACCENTS = {
    "Violet": "#7c5cff",
    "Blue": "#3b82f6",
    "Cyan": "#06b6d4",
    "Green": "#10b981",
    "Pink": "#ec4899",
    "Orange": "#f97316",
}

DEFAULT_SETTINGS = {
    "accent": "Violet",
    "opacity": 1.0,
    "animations": True,
    "topmost": False,
    "remember_fields": True,
    "auto_connect": False,
    "live_update": True,
}

FORM_KEYS = [
    "client_id",
    "activity_type",
    "details",
    "state",
    "large_image",
    "large_text",
    "small_image",
    "small_text",
    "btn1_text",
    "btn1_url",
    "btn2_text",
    "btn2_url",
]

PAGE_META = {
    "presence": ("Presence", "ออกแบบและควบคุมสถานะ Rich Presence ของคุณ"),
    "console": ("Console", "บันทึกการทำงานแบบเรียลไทม์"),
    "settings": ("Settings", "ปรับแต่งธีม พฤติกรรม และโลโก้ของแอป"),
    "help": ("Guide", "เริ่มใช้งานได้ภายใน 1 นาที"),
}

URL_RE = re.compile(r"^https?://\S+$", re.I)
ANIM = {"on": True}  # เปิด/ปิดแอนิเมชันทั้งแอป
START_OVERRIDE = {"ts": None}  # unix seconds ที่เว็บกำหนด (None = ใช้เวลาปัจจุบัน)


# ─────────────────────────────────────────────────────────────
#  Color & animation helpers
# ─────────────────────────────────────────────────────────────
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def mix(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return _hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def lighten(c, t=0.12):
    return mix(c, "#ffffff", t)


def darken(c, t=0.2):
    return mix(c, "#000000", t)


def ease_out(p):
    return 1 - (1 - p) ** 3


def linear(p):
    return p


class Anim:
    """ตัวช่วยทำ tween แบบ non-blocking ด้วย widget.after"""

    def __init__(self, widget, duration, fn, on_done=None, ease=ease_out):
        self.w = widget
        self.d = max(1, duration if ANIM["on"] else 1)
        self.fn = fn
        self.done = on_done
        self.ease = ease
        self.job = None
        self.cancelled = False
        self.t0 = time.perf_counter()
        self._tick()

    def _tick(self):
        if self.cancelled:
            return
        p = min(1.0, (time.perf_counter() - self.t0) * 1000 / self.d)
        try:
            self.fn(self.ease(p))
        except tk.TclError:
            return
        if p < 1.0:
            try:
                self.job = self.w.after(16, self._tick)
            except tk.TclError:
                pass
        elif self.done:
            try:
                self.done()
            except tk.TclError:
                pass

    def cancel(self):
        self.cancelled = True
        if self.job:
            try:
                self.w.after_cancel(self.job)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
#  Logo (ใช้ไฟล์ J3ADiscordProfileLogo.png หรือวาดด้วยโค้ดสำรอง)
# ─────────────────────────────────────────────────────────────
def make_logo(size=256, accent="#7c5cff"):
    logo_path = get_resource_path("J3ADiscordProfileLogo.png")
    if os.path.exists(logo_path):
        try:
            im = Image.open(logo_path).convert("RGBA")
            w, h = im.size
            scale = 2
            mask = Image.new("L", (w * scale, h * scale), 0)
            draw = ImageDraw.Draw(mask)
            radius = int(min(w, h) * 0.16 * scale)
            draw.rounded_rectangle([0, 0, w * scale - 1, h * scale - 1], radius=radius, fill=255)
            mask = mask.resize((w, h), Image.Resampling.LANCZOS)
            im.putalpha(mask)
            return im.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass

    S = size * 4
    g1 = Image.linear_gradient("L").resize((S, S))
    g2 = g1.rotate(90)
    mask = ImageChops.add(g1, g2, scale=2)  # ไล่เฉดแนวทแยง
    top = Image.new("RGB", (S, S), lighten(accent, 0.22))
    bottom = Image.new("RGB", (S, S), darken(accent, 0.38))
    img = Image.composite(bottom, top, mask).convert("RGBA")

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = S * 0.30, S * 0.70
    w = int(S * 0.075)
    for r, a in ((0.20, 255), (0.34, 215), (0.48, 170)):
        R = S * r
        col = (255, 255, 255, a)
        d.arc([cx - R, cy - R, cx + R, cy + R], start=270, end=360, fill=col, width=w)
        for ex, ey in ((cx, cy - R + w / 2), (cx + R - w / 2, cy)):  # หัวท้ายมน
            d.ellipse([ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2], fill=col)
    dr = S * 0.07
    d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=(255, 255, 255, 255))
    img = Image.alpha_composite(img, layer)

    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.24), fill=255)
    img.putalpha(m)
    return img.resize((size, size), Image.LANCZOS)


# ─────────────────────────────────────────────────────────────
#  Config storage
# ─────────────────────────────────────────────────────────────
class Store:
    def __init__(self):
        base = os.environ.get("APPDATA") or str(Path.home() / ".config")
        j3a_dir = Path(base) / "J3ADiscordProfile"
        rpc_dir = Path(base) / "RPCStudio"
        if not j3a_dir.exists() and rpc_dir.exists():
            self.dir = rpc_dir
        else:
            self.dir = j3a_dir
        self.path = self.dir / "config.json"
        self.data = {"settings": dict(DEFAULT_SETTINGS), "form": {}}
        self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            for k, v in raw.get("settings", {}).items():
                if k in DEFAULT_SETTINGS:
                    self.data["settings"][k] = v
            if isinstance(raw.get("form"), dict):
                self.data["form"] = raw["form"]
        except Exception:
            pass

    def save(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  RPC worker (thread เดียว จัดการ Discord ทั้งหมด)
# ─────────────────────────────────────────────────────────────
class RPCWorker(threading.Thread):
    def __init__(self, client_id):
        super().__init__(daemon=True)
        self.client_id = client_id
        self.notify = lambda ev, data=None: None
        self.q = queue.Queue()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        rpc = None
        try:
            rpc = Presence(self.client_id, loop=loop)
            rpc.connect()
        except Exception as e:
            self.notify("failed", e)
            self._close(rpc, loop)
            return

        self.notify("connected")
        while True:
            cmd, payload = self.q.get()
            if cmd == "stop":
                break
            if cmd == "update":
                stop = False
                while True:  # รวมคำสั่งที่ค้างให้เหลืออันล่าสุด
                    try:
                        c2, p2 = self.q.get_nowait()
                    except queue.Empty:
                        break
                    if c2 == "stop":
                        stop = True
                        break
                    if c2 == "update":
                        payload = p2
                if stop:
                    break
                try:
                    rpc.update(**payload)
                    self.notify("updated", payload)
                except Exception as e:
                    lost = isinstance(e, CONN_ERRORS)
                    if not lost and ("small_image" in payload or "large_image" in payload):
                        # หากลิงก์รูปภาพภายนอกทำให้ Discord คืนค่า ServerError ให้ลองตัดพารามิเตอร์หรือข้ามรูปที่มีปัญหาเพื่อให้สถานะยังขึ้นปกติ
                        fallback = dict(payload)
                        recovered = False
                        if "small_image" in fallback:
                            fallback.pop("small_image", None)
                            fallback.pop("small_text", None)
                            try:
                                rpc.update(**fallback)
                                recovered = True
                            except Exception:
                                pass
                        if not recovered and "large_image" in fallback:
                            fallback.pop("large_image", None)
                            fallback.pop("large_text", None)
                            try:
                                rpc.update(**fallback)
                                recovered = True
                            except Exception:
                                pass
                        if recovered:
                            self.notify("updated", fallback)
                            continue
                    self.notify("error", (e, lost))
                    if lost:
                        break
        self._close(rpc, loop)

    @staticmethod
    def _close(rpc, loop):
        if rpc:
            for fn in (rpc.clear, rpc.close):
                try:
                    fn()
                except Exception:
                    pass
        try:
            loop.close()
        except Exception:
            pass


def friendly_error(e):
    name = type(e).__name__
    table = {
        "DiscordNotFound": "ไม่พบ Discord Desktop — เปิดแอป Discord ค้างไว้แล้วลองใหม่",
        "InvalidID": "Application ID ไม่ถูกต้อง — ตรวจสอบใน Developer Portal",
        "InvalidPipe": "เชื่อมต่อ Discord ไม่ได้ — ลองรีสตาร์ท Discord",
        "PipeClosed": "การเชื่อมต่อกับ Discord ถูกปิด",
        "ServerError": "ลิงก์รูปภาพไม่รองรับหรือยาวเกินกำหนด — แนะนำให้กดปุ่ม 📁 เลือกรูปจากเครื่อง หรือใช้ลิงก์รูปตรง",
    }
    return table.get(name, f"{name}: {e}")


# ─────────────────────────────────────────────────────────────
#  Custom widgets
# ─────────────────────────────────────────────────────────────
class FxButton(ctk.CTkButton):
    """ปุ่มที่เปลี่ยนสีแบบ smooth ตอน hover"""

    def __init__(self, master, base, hover_amt=0.10, **kw):
        super().__init__(master, fg_color=base, hover=False, **kw)
        self.base = base
        self.hover_amt = hover_amt
        self._cur = base
        self._anim = None
        self.bind("<Enter>", lambda e: self._go(lighten(self.base, self.hover_amt)), add="+")
        self.bind("<Leave>", lambda e: self._go(self.base), add="+")

    def _go(self, target, ms=150):
        try:
            if self.cget("state") == "disabled":
                target = self.base
        except Exception:
            pass
        if self._anim:
            self._anim.cancel()
        start = self._cur

        def step(p):
            self._cur = mix(start, target, p)
            self.configure(fg_color=self._cur)

        self._anim = Anim(self, ms, step)

    def set_base(self, base):
        self.base = base
        self._go(base, 200)

    def set_enabled(self, on):
        self.configure(state="normal" if on else "disabled")
        self._go(self.base, 1)


class NavItem(ctk.CTkFrame):
    def __init__(self, master, icon, text, command):
        super().__init__(master, fg_color="transparent", height=42)
        self.indicator = ctk.CTkFrame(self, width=3, corner_radius=2, fg_color=C["sidebar"])
        self.indicator.place(x=0, rely=0.18, relheight=0.64)
        self.btn = FxButton(
            self,
            C["sidebar"],
            hover_amt=0.05,
            text=f"  {icon}   {text}",
            anchor="w",
            height=40,
            corner_radius=10,
            text_color=C["muted"],
            font=(FONT, 13),
            command=command,
        )
        self.btn.pack(fill="x", padx=(10, 0))
        self.active = False
        self._ind_color = C["sidebar"]
        self._anim = None

    def set_active(self, on, accent):
        self.active = on
        self.btn.set_base(C["card2"] if on else C["sidebar"])
        self.btn.configure(text_color=C["text"] if on else C["muted"])
        target = accent if on else C["sidebar"]
        start = self._ind_color
        if self._anim:
            self._anim.cancel()

        def step(p):
            self._ind_color = mix(start, target, p)
            self.indicator.configure(fg_color=self._ind_color)

        self._anim = Anim(self, 220, step)

    def apply_accent(self, c):
        if self.active:
            self._ind_color = c
            self.indicator.configure(fg_color=c)


# ─────────────────────────────────────────────────────────────
#  Main app
# ─────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.store = Store()
        self.settings = self.store.data["settings"]
        ANIM["on"] = bool(self.settings["animations"])
        self.accent = ACCENTS.get(self.settings["accent"], ACCENTS["Violet"])
        self.accent_cbs = []

        self.entries = {}
        self.counters = {}
        self.pages = {}
        self.nav = {}
        self.current = None
        self.conn_state = "off"  # off | connecting | online
        self.worker = None
        self.start_ts = None
        self.log_lines = []
        self.ui_q = queue.Queue()
        self._jobs = {}
        self._page_anim = None
        self._pulse_anim = None
        self._toast = None
        self._toast_job = None
        self._toast_anim = None
        self._manual_push = False

        self.title(APP_NAME)
        if IS_WIN:
            ico = get_resource_path("app_icon.ico")
            if os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                except Exception:
                    pass
        w, h = 1100, 720
        x = (self.winfo_screenwidth() - w) // 2
        y = max(0, (self.winfo_screenheight() - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(980, 660)
        self.configure(fg_color=C["bg"])
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self._build_ui()
        self._load_form()
        self.apply_settings()

        self.bind("<Control-Return>", lambda e: self.primary_action())
        for i, name in enumerate(("presence", "console", "settings", "help"), 1):
            self.bind(f"<Control-Key-{i}>", lambda e, n=name: self.show_page(n))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.after(40, self._pump)
        self.after(300, self.refresh_logo)
        self.after(1000, self._tick_clock)
        self.after(60, self._fade_in)
        self.log("พร้อมใช้งาน — กรอก Application ID แล้วกดเริ่มใช้งาน", "info")

        if self.settings["auto_connect"] and self.val("client_id"):
            self.after(900, self.start_presence)

    # ── thread-safe UI queue ──────────────────────────────────
    def ui(self, fn, *args):
        self.ui_q.put((fn, args))

    def _pump(self):
        try:
            while True:
                fn, args = self.ui_q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(40, self._pump)

    def debounce(self, key, ms, fn):
        if key in self._jobs:
            try:
                self.after_cancel(self._jobs[key])
            except Exception:
                pass

        def run():
            self._jobs.pop(key, None)
            fn()

        self._jobs[key] = self.after(ms, run)

    def on_accent(self, fn):
        self.accent_cbs.append(fn)
        fn(self.accent)

    def _fade_in(self):
        target = float(self.settings["opacity"])
        Anim(self, 420, lambda p: self.attributes("-alpha", p * target))

    # ── UI construction ───────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")

        # header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(22, 14))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        self.title_lbl = ctk.CTkLabel(titles, text="", font=(FONT, 24, "bold"), text_color=C["text"], anchor="w")
        self.title_lbl.pack(anchor="w")
        self.sub_lbl = ctk.CTkLabel(titles, text="", font=(FONT, 12), text_color=C["muted"], anchor="w")
        self.sub_lbl.pack(anchor="w")

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(side="right")
        self.btn_toggle = FxButton(
            controls,
            self.accent,
            hover_amt=0.14,
            text="▶  เริ่มใช้งาน",
            width=150,
            height=40,
            corner_radius=10,
            font=(FONT, 13, "bold"),
            text_color="#ffffff",
            command=self.toggle_presence,
        )
        self.btn_toggle.pack(side="right")
        self.btn_update = FxButton(
            controls,
            C["card2"],
            hover_amt=0.06,
            text="↻  อัปเดต",
            width=110,
            height=40,
            corner_radius=10,
            border_width=1,
            border_color=C["border"],
            font=(FONT, 13),
            text_color=C["text"],
            text_color_disabled=C["faint"],
            state="disabled",
            command=self.manual_update,
        )
        self.btn_update.pack(side="right", padx=(0, 10))

        pill = ctk.CTkFrame(controls, fg_color=C["card"], corner_radius=20, border_width=1, border_color=C["border"], height=34)
        pill.pack(side="right", padx=(0, 16))
        self.dot = ctk.CTkLabel(pill, text="●", font=(FONT, 12), text_color=C["faint"], width=14)
        self.dot.pack(side="left", padx=(12, 4), pady=5)
        self.status_lbl = ctk.CTkLabel(pill, text="ออฟไลน์", font=(FONT, 12), text_color=C["muted"])
        self.status_lbl.pack(side="left", padx=(0, 14))

        # page host
        self.host = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
        self.host.pack(fill="both", expand=True, padx=28, pady=(0, 22))

        builders = {
            "presence": self._build_presence,
            "console": self._build_console,
            "settings": self._build_settings,
            "help": self._build_help,
        }
        for name, build in builders.items():
            page = ctk.CTkFrame(self.host, fg_color=C["bg"], corner_radius=0)
            self.pages[name] = page
            build(page)

        self.on_accent(lambda c: self._paint_toggle())
        self.show_page("presence", animate=False)
        self.set_state("off")

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, width=232)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.pack_propagate(False)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(24, 18))
        self.logo_small = ctk.CTkLabel(brand, text="", width=42, height=42)
        self.logo_small.pack(side="left")
        bt = ctk.CTkFrame(brand, fg_color="transparent")
        bt.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(bt, text=APP_NAME, font=(FONT, 16, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(bt, text="Rich Presence Panel", font=(FONT, 11), text_color=C["muted"], anchor="w").pack(anchor="w")

        ctk.CTkFrame(sb, height=1, fg_color=C["border"]).pack(fill="x", padx=18, pady=(0, 14))

        items = [
            ("presence", "◉", "Presence"),
            ("console", "▤", "Console"),
            ("settings", "⚙", "Settings"),
            ("help", "?", "Guide"),
        ]
        for key, icon, text in items:
            item = NavItem(sb, icon, text, lambda k=key: self.show_page(k))
            item.pack(fill="x", pady=2)
            self.nav[key] = item
            self.on_accent(item.apply_accent)

        foot = ctk.CTkFrame(sb, fg_color=C["card"], corner_radius=12, border_width=1, border_color=C["border"])
        foot.pack(side="bottom", fill="x", padx=14, pady=16)
        ctk.CTkLabel(foot, text=f"เวอร์ชัน {APP_VERSION}", font=(FONT, 11), text_color=C["muted"], anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(foot, text="Ctrl+Enter  เริ่ม / อัปเดต", font=(MONO, 10), text_color=C["faint"], anchor="w").pack(fill="x", padx=14, pady=(2, 10))

    # ── reusable builders ─────────────────────────────────────
    def make_card(self, parent, title, subtitle=None):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14, border_width=1, border_color=C["border"])
        card.pack(fill="x", pady=(0, 14))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(14, 0))
        bar = ctk.CTkFrame(head, width=3, height=16, corner_radius=2, fg_color=self.accent)
        bar.pack(side="left", padx=(0, 10))
        self.on_accent(lambda c, b=bar: b.configure(fg_color=c))
        ctk.CTkLabel(head, text=title, font=(FONT, 14, "bold"), text_color=C["text"]).pack(side="left")
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, font=(FONT, 11), text_color=C["muted"], anchor="w").pack(fill="x", padx=18, pady=(3, 0))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(12, 16))
        return card, body

    def make_field(self, parent, label, key, placeholder="", maxlen=None):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        top = ctk.CTkFrame(wrap, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=label, font=(FONT, 11), text_color=C["muted"]).pack(side="left")
        if maxlen:
            cnt = ctk.CTkLabel(top, text=f"0/{maxlen}", font=(MONO, 10), text_color=C["faint"])
            cnt.pack(side="right")
            self.counters[key] = (cnt, maxlen)
        entry = ctk.CTkEntry(
            wrap,
            placeholder_text=placeholder,
            height=36,
            corner_radius=8,
            fg_color=C["input"],
            border_color=C["input_border"],
            border_width=1,
            text_color=C["text"],
            placeholder_text_color=C["faint"],
            font=(FONT, 12),
        )
        entry.pack(fill="x", pady=(4, 0))
        entry._rpc_focus = False
        entry._rpc_invalid = False
        entry._rpc_cur = C["input_border"]
        entry._rpc_anim = None
        entry.bind("<FocusIn>", lambda e, en=entry: self._focus(en, True), add="+")
        entry.bind("<FocusOut>", lambda e, en=entry: self._focus(en, False), add="+")
        for seq in ("<KeyRelease>", "<<Paste>>", "<<Cut>>"):
            entry.bind(seq, lambda e: self.after(15, self.on_form_change), add="+")
        self.entries[key] = entry
        return wrap

    def _focus(self, entry, on):
        entry._rpc_focus = on
        self._border(entry)

    def _border(self, entry):
        if entry._rpc_invalid:
            target = C["err"]
        elif entry._rpc_focus:
            target = self.accent
        else:
            target = C["input_border"]
        if entry._rpc_anim:
            entry._rpc_anim.cancel()
        start = entry._rpc_cur

        def step(p):
            entry._rpc_cur = mix(start, target, p)
            entry.configure(border_color=entry._rpc_cur)

        entry._rpc_anim = Anim(entry, 160, step)

    def set_invalid(self, entry, bad):
        if entry._rpc_invalid != bad:
            entry._rpc_invalid = bad
            self._border(entry)

    def val(self, key):
        return self.entries[key].get().strip()

    def make_switch(self, parent, text, command=None):
        sw = ctk.CTkSwitch(
            parent,
            text=text,
            command=command,
            progress_color=self.accent,
            fg_color="#2a3140",
            button_color="#ffffff",
            button_hover_color="#e5e7eb",
            text_color=C["text"],
            font=(FONT, 12),
            switch_width=42,
            switch_height=22,
        )
        self.on_accent(lambda c, s=sw: s.configure(progress_color=c))
        return sw

    # ── Presence page ─────────────────────────────────────────
    def _build_presence(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=0, minsize=350)
        page.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(
            page,
            fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["faint"],
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right = ctk.CTkFrame(page, fg_color="transparent", width=340)
        right.grid(row=0, column=1, sticky="nsew")

        # Application
        _, body = self.make_card(left, "Application", "Application ID จาก Discord Developer Portal")
        body.grid_columnconfigure(0, weight=1)
        self.make_field(body, "Application ID", "client_id", "เช่น 123456789012345678", 20).grid(row=0, column=0, sticky="ew")
        FxButton(
            body,
            C["card2"],
            hover_amt=0.08,
            text="Dev Portal ↗",
            width=118,
            height=36,
            corner_radius=8,
            border_width=1,
            border_color=C["border"],
            font=(FONT, 12),
            text_color=C["text"],
            command=lambda: webbrowser.open("https://discord.com/developers/applications"),
        ).grid(row=0, column=1, sticky="s", padx=(10, 0))

        # Text
        _, body = self.make_card(left, "ข้อความสถานะ", "บรรทัดที่แสดงใต้ชื่อแอปบนโปรไฟล์")
        body.grid_columnconfigure(0, weight=1)
        self.make_field(body, "Details (บรรทัดบน)", "details", "เช่น กำลังเขียนโค้ด", 128).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.make_field(body, "State (บรรทัดล่าง)", "state", "เช่น ฟังเพลงชิลๆ", 128).grid(row=1, column=0, sticky="ew")

        # Images
        _, body = self.make_card(left, "รูปภาพ", "ใช้ชื่อ Asset ที่อัปโหลดไว้ใน Developer Portal › Rich Presence")
        body.grid_columnconfigure((0, 1), weight=1, uniform="img")
        self.make_field(body, "Large image key", "large_image", "เช่น cover").grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 10))
        self.make_field(body, "Small image key", "small_image", "ไม่บังคับ").grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 10))
        self.make_field(body, "Large image text", "large_text", "ข้อความตอนชี้รูปใหญ่").grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.make_field(body, "Small image text", "small_text", "ข้อความตอนชี้รูปเล็ก").grid(row=1, column=1, sticky="ew", padx=(8, 0))

        # Buttons
        _, body = self.make_card(left, "ปุ่มลิงก์", "สูงสุด 2 ปุ่ม · ต้องขึ้นต้นด้วย http:// หรือ https://")
        body.grid_columnconfigure(0, weight=2, uniform="btn")
        body.grid_columnconfigure(1, weight=3, uniform="btn")
        for i in (1, 2):
            self.make_field(body, f"ปุ่ม {i} · ชื่อ", f"btn{i}_text", "ชื่อปุ่ม", 32).grid(row=i - 1, column=0, sticky="ew", padx=(0, 8), pady=(0, 10 if i == 1 else 0))
            self.make_field(body, f"ปุ่ม {i} · URL", f"btn{i}_url", "https://...").grid(row=i - 1, column=1, sticky="ew", padx=(8, 0), pady=(0, 10 if i == 1 else 0))

        # Timer
        _, body = self.make_card(left, "ตัวจับเวลา")
        self.show_time = self.make_switch(body, "แสดงเวลานับเดินหน้า (Elapsed time)", self.on_form_change)
        self.show_time.select()
        self.show_time.pack(anchor="w")

        # right column
        self._build_preview(right)

    def _build_preview(self, parent):
        _, body = self.make_card(parent, "Live preview", "ดูตัวอย่างการ์ดแบบเรียลไทม์ขณะพิมพ์")
        box = ctk.CTkFrame(body, fg_color=C["discord"], corner_radius=12, border_width=1, border_color=C["border"])
        box.pack(fill="x")
        ctk.CTkLabel(box, text="กำลังเล่น", font=(FONT, 10), text_color=C["faint"], anchor="w").pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(box, text="Your Application", font=(FONT, 12, "bold"), text_color=C["text"], anchor="w").pack(fill="x", padx=14, pady=(0, 8))

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=14)
        img_wrap = ctk.CTkFrame(row, fg_color="transparent", width=90, height=88)
        img_wrap.pack(side="left")
        img_wrap.pack_propagate(False)
        self.pv_large = ctk.CTkFrame(img_wrap, width=80, height=80, corner_radius=12, fg_color=C["card2"])
        self.pv_large.place(x=0, y=0)
        self.pv_large_lbl = ctk.CTkLabel(self.pv_large, text="▣", font=(MONO, 11), text_color=C["muted"], wraplength=70)
        self.pv_large_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self.pv_small = ctk.CTkFrame(img_wrap, width=28, height=28, corner_radius=14, fg_color=C["faint"], border_width=3, border_color=C["discord"])
        self.on_accent(lambda c: self.pv_large.configure(fg_color=mix(c, C["discord"], 0.62)))

        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.pv_details = ctk.CTkLabel(txt, text="", font=(FONT, 12, "bold"), anchor="w", justify="left", wraplength=190)
        self.pv_details.pack(fill="x")
        self.pv_state = ctk.CTkLabel(txt, text="", font=(FONT, 11), anchor="w", justify="left", wraplength=190)
        self.pv_state.pack(fill="x")
        self.pv_time = ctk.CTkLabel(txt, text="", font=(FONT, 11), text_color=C["ok"], anchor="w")
        self.pv_time.pack(fill="x")

        self.pv_btn_area = ctk.CTkFrame(box, fg_color="transparent")
        self.pv_btn_area.pack(fill="x", padx=14, pady=(10, 14))
        self.pv_btns = []
        for _ in range(2):
            b = ctk.CTkLabel(self.pv_btn_area, text="", height=30, corner_radius=6, fg_color="#242933", font=(FONT, 11), text_color=C["text"])
            self.pv_btns.append(b)

        _, tips = self.make_card(parent, "เคล็ดลับ")
        for t in (
            "ปุ่มลิงก์จะไม่แสดงบนโปรไฟล์ของคุณเอง ให้เพื่อนเป็นคนดู",
            "รูปที่เพิ่งอัปโหลดอาจใช้เวลาสักครู่กว่าจะขึ้น",
            "เปิด Live update ใน Settings เพื่อส่งอัตโนมัติขณะพิมพ์",
        ):
            ctk.CTkLabel(tips, text="•  " + t, font=(FONT, 11), text_color=C["muted"], anchor="w", justify="left", wraplength=290).pack(fill="x", pady=2)

    def _refresh_preview(self):
        def fill(lbl, text, placeholder):
            lbl.configure(text=text or placeholder, text_color=C["text"] if text else C["faint"])

        fill(self.pv_details, self.val("details"), "Details จะแสดงที่นี่")
        self.pv_state.configure(text=self.val("state") or "State จะแสดงที่นี่", text_color=C["muted"] if self.val("state") else C["faint"])

        key = self.val("large_image")
        self.pv_large_lbl.configure(text=key if key else "▣")
        if self.val("small_image"):
            self.pv_small.place(x=56, y=56)
        else:
            self.pv_small.place_forget()

        for b in self.pv_btns:
            b.pack_forget()
        for i, b in enumerate(self.pv_btns, 1):
            t = self.val(f"btn{i}_text")
            if t:
                b.configure(text=t)
                b.pack(fill="x", pady=(0, 6))
        self._refresh_clock()

    def _refresh_clock(self):
        if not self.show_time.get():
            self.pv_time.configure(text="")
            return
        el = int(time.time() - self.start_ts) if (self.start_ts and self.conn_state == "online") else 0
        h, rem = divmod(el, 3600)
        m, s = divmod(rem, 60)
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.pv_time.configure(text=f"{stamp} elapsed")

    def _tick_clock(self):
        self._refresh_clock()
        self.after(1000, self._tick_clock)

    # ── Console page ──────────────────────────────────────────
    def _build_console(self, page):
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        for text, cmd in (("ล้าง", self.clear_log), ("คัดลอก", self.copy_log), ("บันทึกไฟล์", self.save_log)):
            FxButton(
                bar,
                C["card2"],
                hover_amt=0.08,
                text=text,
                width=96,
                height=34,
                corner_radius=8,
                border_width=1,
                border_color=C["border"],
                font=(FONT, 12),
                text_color=C["text"],
                command=cmd,
            ).pack(side="left", padx=(0, 8))

        self.log_box = ctk.CTkTextbox(
            page,
            font=(MONO, 12),
            fg_color=C["input"],
            text_color=C["text"],
            border_color=C["input_border"],
            border_width=1,
            corner_radius=12,
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["faint"],
        )
        self.log_box.pack(fill="both", expand=True)
        for tag, col in (("ts", C["faint"]), ("info", C["text"]), ("ok", C["ok"]), ("err", C["err"]), ("warn", C["warn"])):
            self.log_box.tag_config(tag, foreground=col)
        self.log_box.configure(state="disabled")

    def log(self, msg, level="info"):
        self.ui(self._append_log, msg, level)

    def _append_log(self, msg, level):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"[{ts}] {msg}")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{ts}  ", "ts")
        self.log_box.insert("end", msg + "\n", level)
        try:
            if int(self.log_box.index("end-1c").split(".")[0]) > 500:
                self.log_box.delete("1.0", "51.0")
        except Exception:
            pass
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_log(self):
        self.log_lines.clear()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.log_lines))
        self.toast("คัดลอก log แล้ว", "ok")

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="rpc_studio_log.txt", filetypes=[("Text", "*.txt")])
        if path:
            Path(path).write_text("\n".join(self.log_lines), "utf-8")
            self.toast("บันทึก log แล้ว", "ok")

    # ── Settings page ─────────────────────────────────────────
    def _setting_row(self, parent, title, desc):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=7)
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(txt, text=title, font=(FONT, 12, "bold"), text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(txt, text=desc, font=(FONT, 11), text_color=C["muted"], anchor="w", justify="left", wraplength=460).pack(fill="x")
        return row

    def _switch_row(self, parent, title, desc, key):
        row = self._setting_row(parent, title, desc)
        sw = self.make_switch(row, "", lambda: self.set_setting(key, bool(sw.get())))
        sw.configure(width=46)
        if self.settings[key]:
            sw.select()
        sw.pack(side="right")

    def _build_settings(self, page):
        sc = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["faint"])
        sc.pack(fill="both", expand=True)

        # Brand
        _, body = self.make_card(sc, "โลโก้แอป", "วาดด้วยโค้ดและเปลี่ยนสีตามธีมอัตโนมัติ")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        self.logo_big = ctk.CTkLabel(row, text="", width=96, height=96)
        self.logo_big.pack(side="left")
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", padx=18)
        ctk.CTkLabel(col, text=APP_NAME, font=(FONT, 18, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(col, text="ใช้เป็นไอคอนแอปบน Discord Developer Portal ได้ (ส่งออก 1024 px)", font=(FONT, 11), text_color=C["muted"], anchor="w").pack(anchor="w", pady=(2, 10))
        btn = FxButton(col, self.accent, hover_amt=0.14, text="ส่งออกโลโก้ (PNG / ICO)", height=34, corner_radius=8, font=(FONT, 12, "bold"), text_color="#ffffff", command=self.export_logo)
        btn.pack(anchor="w")
        self.on_accent(btn.set_base)

        # Appearance
        _, body = self.make_card(sc, "รูปลักษณ์")
        row = self._setting_row(body, "สีธีม", "สีหลักของปุ่ม ตัวบ่งชี้ และโลโก้")
        sw_frame = ctk.CTkFrame(row, fg_color="transparent")
        sw_frame.pack(side="right")
        self.swatches = {}
        for name, color in ACCENTS.items():
            b = ctk.CTkButton(
                sw_frame,
                text="",
                width=28,
                height=28,
                corner_radius=14,
                fg_color=color,
                hover_color=lighten(color, 0.2),
                border_width=0,
                border_color="#ffffff",
                command=lambda n=name: self.set_accent(n),
            )
            b.pack(side="left", padx=3)
            self.swatches[name] = b
        self._mark_swatch()

        row = self._setting_row(body, "ความโปร่งใสหน้าต่าง", "ลดค่าเพื่อให้หน้าต่างโปร่งขึ้น")
        self.opacity_lbl = ctk.CTkLabel(row, text=f"{int(self.settings['opacity'] * 100)}%", font=(MONO, 11), text_color=C["muted"], width=42)
        self.opacity_lbl.pack(side="right")
        sl = ctk.CTkSlider(
            row,
            from_=0.6,
            to=1.0,
            number_of_steps=40,
            width=170,
            fg_color="#2a3140",
            progress_color=self.accent,
            button_color="#ffffff",
            button_hover_color="#e5e7eb",
            command=self._on_opacity,
        )
        sl.set(float(self.settings["opacity"]))
        sl.pack(side="right", padx=(0, 8))
        self.on_accent(lambda c: sl.configure(progress_color=c))

        self._switch_row(body, "แอนิเมชัน", "เปิด/ปิดการเปลี่ยนสีและการสไลด์หน้า (ปิดถ้าเครื่องช้า)", "animations")

        # Behavior
        _, body = self.make_card(sc, "การทำงาน")
        self._switch_row(body, "อยู่หน้าสุดเสมอ", "ให้หน้าต่างลอยเหนือแอปอื่น", "topmost")
        self._switch_row(body, "จำค่าที่กรอกไว้", "บันทึก Application ID และข้อความทั้งหมด เปิดแอปครั้งต่อไปไม่ต้องกรอกใหม่", "remember_fields")
        self._switch_row(body, "เชื่อมต่ออัตโนมัติ", "เริ่ม Presence ทันทีเมื่อเปิดแอป (ต้องมี Application ID ที่บันทึกไว้)", "auto_connect")
        self._switch_row(body, "Live update", "ส่งสถานะใหม่อัตโนมัติ 1.5 วินาทีหลังหยุดพิมพ์", "live_update")

        # Data
        _, body = self.make_card(sc, "ข้อมูล")
        row = self._setting_row(body, "โฟลเดอร์ข้อมูล", str(self.store.dir))
        FxButton(row, C["card2"], hover_amt=0.08, text="เปิดโฟลเดอร์", width=110, height=34, corner_radius=8, border_width=1, border_color=C["border"], font=(FONT, 12), text_color=C["text"], command=self.open_config_dir).pack(side="right")

        row = self._setting_row(body, "ล้างค่าที่กรอกไว้", "ลบข้อมูลในฟอร์มทั้งหมด")
        b = FxButton(row, C["card2"], hover_amt=0.08, text="ล้างฟอร์ม", width=110, height=34, corner_radius=8, border_width=1, border_color=C["border"], font=(FONT, 12), text_color=C["text"])
        b.pack(side="right")
        self.confirm_action(b, "ล้างฟอร์ม", self.clear_form)

        row = self._setting_row(body, "รีเซ็ตการตั้งค่า", "คืนค่าธีมและพฤติกรรมเป็นค่าเริ่มต้น")
        b = FxButton(row, C["card2"], hover_amt=0.08, text="รีเซ็ต", width=110, height=34, corner_radius=8, border_width=1, border_color=C["border"], font=(FONT, 12), text_color=C["text"])
        b.pack(side="right")
        self.confirm_action(b, "รีเซ็ต", self.reset_settings)

    def confirm_action(self, btn, label, action):
        st = {"armed": False, "job": None}

        def disarm():
            st["armed"] = False
            btn.configure(text=label, text_color=C["text"])
            btn.set_base(C["card2"])

        def click():
            if st["armed"]:
                if st["job"]:
                    self.after_cancel(st["job"])
                disarm()
                action()
            else:
                st["armed"] = True
                btn.configure(text="กดอีกครั้ง", text_color="#ffffff")
                btn.set_base("#7f1d1d")
                st["job"] = self.after(3000, disarm)

        btn.configure(command=click)

    def _mark_swatch(self):
        for name, b in self.swatches.items():
            b.configure(border_width=2 if name == self.settings["accent"] else 0)

    def set_accent(self, name):
        if name == self.settings["accent"]:
            return
        self.settings["accent"] = name
        self._mark_swatch()
        old, new = self.accent, ACCENTS[name]

        def step(p):
            c = mix(old, new, p)
            self.accent = c
            for cb in self.accent_cbs:
                try:
                    cb(c)
                except tk.TclError:
                    pass

        def done():
            self.accent = new
            self.refresh_logo()

        Anim(self, 380, step, done)
        self.save_soon()

    def _on_opacity(self, v):
        self.settings["opacity"] = round(float(v), 2)
        self.opacity_lbl.configure(text=f"{int(float(v) * 100)}%")
        try:
            self.attributes("-alpha", float(v))
        except tk.TclError:
            pass
        self.save_soon()

    def set_setting(self, key, value):
        self.settings[key] = value
        self.apply_settings()
        if key == "remember_fields" and not value:
            self.store.data["form"] = {}
        self.save_soon()

    def apply_settings(self):
        ANIM["on"] = bool(self.settings["animations"])
        try:
            self.attributes("-topmost", bool(self.settings["topmost"]))
        except tk.TclError:
            pass

    def refresh_logo(self):
        try:
            small = make_logo(128, self.accent)
            big = make_logo(256, self.accent)
            self._img_small = ctk.CTkImage(light_image=small, dark_image=small, size=(42, 42))
            self._img_big = ctk.CTkImage(light_image=big, dark_image=big, size=(96, 96))
            self.logo_small.configure(image=self._img_small)
            self.logo_big.configure(image=self._img_big)
            if IS_WIN:
                ico = get_resource_path("app_icon.ico")
                if not os.path.exists(ico):
                    self.store.dir.mkdir(parents=True, exist_ok=True)
                    ico = str(self.store.dir / "icon.ico")
                    make_logo(256, self.accent).save(ico, sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
                self.iconbitmap(str(ico))
            else:
                icon = make_logo(64, self.accent)
                self._icon = ImageTk.PhotoImage(icon)
                self.iconphoto(True, self._icon)
        except Exception:
            pass

    def export_logo(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            initialfile="J3ADiscordProfileLogo.png",
            filetypes=[("PNG", "*.png"), ("ICO", "*.ico")],
        )
        if not path:
            return
        try:
            if path.lower().endswith(".ico"):
                make_logo(256, self.accent).save(path, sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
            else:
                make_logo(1024, self.accent).save(path)
            self.toast("ส่งออกโลโก้แล้ว", "ok")
            self.log(f"ส่งออกโลโก้: {path}", "ok")
        except Exception as e:
            self.toast(f"ส่งออกไม่สำเร็จ: {e}", "err")

    def open_config_dir(self):
        self.store.dir.mkdir(parents=True, exist_ok=True)
        try:
            if IS_WIN:
                os.startfile(self.store.dir)  # noqa
            elif IS_MAC:
                subprocess.Popen(["open", str(self.store.dir)])
            else:
                subprocess.Popen(["xdg-open", str(self.store.dir)])
        except Exception as e:
            self.toast(f"เปิดโฟลเดอร์ไม่ได้: {e}", "err")

    def clear_form(self):
        for e in self.entries.values():
            e.delete(0, "end")
        self.show_time.select()
        self.store.data["form"] = {}
        self.on_form_change()
        self.toast("ล้างฟอร์มแล้ว", "ok")

    def reset_settings(self):
        self.settings.update(DEFAULT_SETTINGS)
        self.apply_settings()
        self.set_accent_force("Violet")
        self.attributes("-alpha", 1.0)
        self.save_soon()
        self.toast("รีเซ็ตการตั้งค่าแล้ว — เปิดหน้า Settings ใหม่เพื่อดูค่าล่าสุด", "ok")

    def set_accent_force(self, name):
        self.settings["accent"] = ""
        self.set_accent(name)

    # ── Help page ─────────────────────────────────────────────
    def _build_help(self, page):
        sc = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["faint"])
        sc.pack(fill="both", expand=True)
        _, body = self.make_card(sc, "เริ่มต้นใช้งาน")
        steps = [
            ("สร้าง Application", "เข้า Discord Developer Portal กด New Application แล้วคัดลอก Application ID มาวางในหน้า Presence"),
            ("อัปโหลดรูป (ไม่บังคับ)", "ที่ Rich Presence › Art Assets อัปโหลดรูป แล้วใช้ชื่อไฟล์เป็น Image key"),
            ("เปิด Discord Desktop", "แอปต้องเปิดอยู่ในเครื่องเดียวกัน (เวอร์ชันเว็บใช้ไม่ได้)"),
            ("กดเริ่มใช้งาน", "แก้ข้อความแล้วกดอัปเดต หรือเปิด Live update ให้ส่งเองอัตโนมัติ"),
        ]
        for i, (t, d) in enumerate(steps, 1):
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=6)
            badge = ctk.CTkLabel(row, text=str(i), width=28, height=28, corner_radius=14, fg_color=self.accent, text_color="#ffffff", font=(FONT, 12, "bold"))
            badge.pack(side="left", anchor="n")
            self.on_accent(lambda c, b=badge: b.configure(fg_color=c))
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", fill="x", expand=True, padx=(12, 0))
            ctk.CTkLabel(col, text=t, font=(FONT, 12, "bold"), text_color=C["text"], anchor="w").pack(fill="x")
            ctk.CTkLabel(col, text=d, font=(FONT, 11), text_color=C["muted"], anchor="w", justify="left", wraplength=620).pack(fill="x")
        FxButton(body, self.accent, hover_amt=0.14, text="เปิด Developer Portal ↗", height=36, corner_radius=8, font=(FONT, 12, "bold"), text_color="#ffffff", command=lambda: webbrowser.open("https://discord.com/developers/applications")).pack(anchor="w", pady=(10, 0))

        _, body = self.make_card(sc, "ถ้าสถานะไม่ขึ้น")
        for t in (
            "ตรวจว่า Discord ไปที่ User Settings › Activity Privacy › เปิด “Share my activity”",
            "ปิด Discord แล้วเปิดใหม่ จากนั้นกดเริ่มใช้งานอีกครั้ง",
            "ถ้ารูปไม่ขึ้น ให้ตรวจชื่อ Image key ว่าตรงกับ Asset และรอสักครู่หลังอัปโหลด",
            "Discord จำกัดความถี่ในการอัปเดต อย่ากดอัปเดตถี่เกินไป",
        ):
            ctk.CTkLabel(body, text="•  " + t, font=(FONT, 11), text_color=C["muted"], anchor="w", justify="left", wraplength=680).pack(fill="x", pady=3)

        _, body = self.make_card(sc, "คีย์ลัด")
        for k, d in (("Ctrl + Enter", "เริ่มใช้งาน / อัปเดตสถานะ"), ("Ctrl + 1 – 4", "สลับหน้า Presence, Console, Settings, Guide")):
            r = ctk.CTkFrame(body, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=k, font=(MONO, 11), text_color=C["text"], fg_color=C["card2"], corner_radius=6, width=120, height=26).pack(side="left")
            ctk.CTkLabel(r, text=d, font=(FONT, 11), text_color=C["muted"]).pack(side="left", padx=12)

    # ── Page switching ────────────────────────────────────────
    def show_page(self, name, animate=True):
        if name == self.current:
            return
        old = self.pages.get(self.current)
        for k, item in self.nav.items():
            item.set_active(k == name, self.accent)
        title, sub = PAGE_META[name]
        self.title_lbl.configure(text=title)
        self.sub_lbl.configure(text=sub)
        if self._page_anim:
            self._page_anim.cancel()
        if old:
            old.place_forget()
        new = self.pages[name]
        self.current = name
        if not animate or not ANIM["on"]:
            new.place(relx=0, rely=0, relwidth=1, relheight=1)
            return
        off = 0.03

        def step(p):
            new.place(relx=off * (1 - p), rely=0, relwidth=1, relheight=1)

        step(0)
        self._page_anim = Anim(self, 260, step)

    # ── Toast ─────────────────────────────────────────────────
    def toast(self, text, kind="info"):
        col = {"ok": C["ok"], "err": C["err"], "warn": C["warn"], "info": self.accent}[kind]
        icon = {"ok": "✓", "err": "✕", "warn": "!", "info": "i"}[kind]
        if self._toast is None:
            self._toast = ctk.CTkFrame(self, fg_color=C["card2"], corner_radius=12, border_width=1)
            self._toast_icon = ctk.CTkLabel(self._toast, text="", width=20, font=(FONT, 13, "bold"))
            self._toast_icon.pack(side="left", padx=(14, 0), pady=11)
            self._toast_lbl = ctk.CTkLabel(self._toast, text="", font=(FONT, 12), text_color=C["text"], wraplength=360, justify="left")
            self._toast_lbl.pack(side="left", padx=(8, 16), pady=11)
        self._toast.configure(border_color=col)
        self._toast_icon.configure(text=icon, text_color=col)
        self._toast_lbl.configure(text=text)

        if self._toast_job:
            self.after_cancel(self._toast_job)
        if self._toast_anim:
            self._toast_anim.cancel()

        def put(off):
            self._toast.place(relx=1.0, rely=1.0, x=-24 + off, y=-24, anchor="se")

        put(80)
        self._toast_anim = Anim(self, 280, lambda p: put(80 * (1 - p)))
        self._toast_job = self.after(2800, self._hide_toast)

    def _hide_toast(self):
        def put(off):
            self._toast.place(relx=1.0, rely=1.0, x=-24 + off, y=-24, anchor="se")

        self._toast_anim = Anim(self, 240, lambda p: put(100 * p), on_done=self._toast.place_forget)

    # ── Form / validation ─────────────────────────────────────
    def _load_form(self):
        form = self.store.data.get("form", {})
        for k in FORM_KEYS:
            if form.get(k):
                self.entries[k].insert(0, str(form[k]))
        if form.get("show_time") is False:
            self.show_time.deselect()
        self.on_form_change(save=False)

    def save_soon(self):
        def do():
            if self.settings["remember_fields"]:
                form = {k: self.entries[k].get().strip() for k in FORM_KEYS}
                form["show_time"] = bool(self.show_time.get())
                self.store.data["form"] = form
            self.store.save()

        self.debounce("save", 600, do)

    def on_form_change(self, save=True):
        for key, (lbl, mx) in self.counters.items():
            n = len(self.val(key))
            lbl.configure(text=f"{n}/{mx}", text_color=C["err"] if n > mx else C["faint"])
        self.validate()
        self._refresh_preview()
        if save:
            self.save_soon()
        if self.conn_state == "online" and self.settings["live_update"]:
            self.debounce("live", 1500, lambda: self.push_update(silent=True))

    def validate(self):
        v = self.val
        errors, bad = [], set()

        def fail(key, msg):
            errors.append(msg)
            bad.add(key)

        cid = v("client_id")
        if cid and not (cid.isdigit() and 17 <= len(cid) <= 20):
            fail("client_id", "Application ID ต้องเป็นตัวเลข 17–20 หลัก")
        for key, name in (("details", "Details"), ("state", "State")):
            t = v(key)
            if t and len(t) < 2:
                fail(key, f"{name} ต้องมีอย่างน้อย 2 ตัวอักษร")
            elif len(t) > 128:
                fail(key, f"{name} ยาวเกิน 128 ตัวอักษร")
        if v("small_image") and not v("large_image"):
            fail("small_image", "Small image ต้องใช้คู่กับ Large image")

        buttons = []
        for i in (1, 2):
            lt, lu = v(f"btn{i}_text"), v(f"btn{i}_url")
            if not (lt or lu):
                continue
            ok = True
            if not lt:
                fail(f"btn{i}_text", f"ปุ่ม {i}: กรอกชื่อปุ่ม")
                ok = False
            elif len(lt) > 32:
                fail(f"btn{i}_text", f"ปุ่ม {i}: ชื่อยาวเกิน 32 ตัวอักษร")
                ok = False
            if not lu:
                fail(f"btn{i}_url", f"ปุ่ม {i}: กรอก URL")
                ok = False
            elif not URL_RE.match(lu) or len(lu) > 512:
                fail(f"btn{i}_url", f"ปุ่ม {i}: URL ต้องขึ้นต้นด้วย http:// หรือ https://")
                ok = False
            if ok:
                buttons.append({"label": lt, "url": lu})

        for key, e in self.entries.items():
            self.set_invalid(e, key in bad)

        payload = {k: v(k) for k in ("details", "state", "large_image", "large_text", "small_image", "small_text") if v(k)}
        if self.show_time.get() and self.start_ts:
            payload["start"] = self.start_ts
        if buttons:
            payload["buttons"] = buttons
        return payload, errors

    # ── Connection state ──────────────────────────────────────
    def set_state(self, state):
        self.conn_state = state
        text, color = {
            "off": ("ออฟไลน์", C["faint"]),
            "connecting": ("กำลังเชื่อมต่อ…", C["warn"]),
            "online": ("ออนไลน์", C["ok"]),
        }[state]
        self.status_lbl.configure(text=text, text_color=C["text"] if state != "off" else C["muted"])
        self.btn_toggle.configure(text={"off": "▶  เริ่มใช้งาน", "connecting": "✕  ยกเลิก", "online": "■  หยุด"}[state])
        self.btn_update.set_enabled(state == "online")
        self._paint_toggle()
        if self._pulse_anim:
            self._pulse_anim.cancel()
        if state == "off":
            self.dot.configure(text_color=color)
        else:
            self._pulse(color)
        self._refresh_clock()

    def _paint_toggle(self):
        if self.conn_state == "off":
            self.btn_toggle.set_base(self.accent)
        else:
            self.btn_toggle.set_base("#dc2626")

    def _pulse(self, col):
        dim = darken(col, 0.55)

        def step(p):
            self.dot.configure(text_color=mix(dim, col, 0.5 + 0.5 * math.sin(p * 2 * math.pi - math.pi / 2)))

        self._pulse_anim = Anim(self, 1400, step, on_done=lambda: self.conn_state != "off" and self._pulse(col), ease=linear)

    def primary_action(self):
        if self.conn_state == "online":
            self.manual_update()
        elif self.conn_state == "off":
            self.start_presence()

    def toggle_presence(self):
        if self.conn_state == "off":
            self.start_presence()
        else:
            self.stop_presence()

    def start_presence(self):
        cid = self.val("client_id")
        if not cid:
            self.set_invalid(self.entries["client_id"], True)
            self.show_page("presence")
            self.toast("กรุณากรอก Application ID", "warn")
            self.log("ข้อผิดพลาด: ยังไม่ได้กรอก Application ID", "warn")
            return
        _, errors = self.validate()
        if errors:
            self.show_page("presence")
            self.toast(errors[0], "warn")
            self.log(errors[0], "warn")
            return
        self.log("กำลังเชื่อมต่อไปยัง Discord Desktop…", "info")
        self.set_state("connecting")
        w = RPCWorker(cid)
        w.notify = lambda ev, data=None, w=w: self.ui(self._on_rpc, w, ev, data)
        self.worker = w
        w.start()

    def stop_presence(self):
        if self.worker:
            self.worker.q.put(("stop", None))
            self.worker = None
        self.start_ts = None
        self.set_state("off")
        self.log("ตัดการเชื่อมต่อและปิดสถานะแล้ว", "info")
        self.toast("หยุด Presence แล้ว", "info")

    def manual_update(self):
        self.push_update(silent=False)

    def push_update(self, silent=False):
        if self.conn_state != "online" or not self.worker:
            return
        payload, errors = self.validate()
        if errors:
            self.log(errors[0], "warn")
            if not silent:
                self.toast(errors[0], "warn")
            return
        self._manual_push = not silent
        self.worker.q.put(("update", payload))

    def _on_rpc(self, worker, ev, data):
        if worker is not self.worker:
            return
        if ev == "connected":
            self.start_ts = (START_OVERRIDE["ts"] or int(time.time())) if self.show_time.get() else None
            self.set_state("online")
            self.log("เชื่อมต่อ Discord สำเร็จ!", "ok")
            self.toast("เชื่อมต่อ Discord สำเร็จ", "ok")
            self.push_update(silent=True)
        elif ev == "updated":
            self.log("อัปเดตสถานะสำเร็จ", "ok")
            if self._manual_push:
                self._manual_push = False
                self.toast("อัปเดตสถานะแล้ว", "ok")
        elif ev == "failed":
            msg = friendly_error(data)
            self.worker = None
            self.set_state("off")
            self.log(f"เชื่อมต่อไม่สำเร็จ: {msg}", "err")
            self.toast(msg, "err")
        elif ev == "error":
            e, lost = data
            msg = friendly_error(e)
            self.log(f"เกิดข้อผิดพลาดในการอัปเดต: {msg}", "err")
            self.toast(msg, "err")
            if lost:
                self.worker = None
                self.start_ts = None
                self.set_state("off")

    def on_close(self):
        try:
            if self.settings["remember_fields"]:
                self.store.data["form"] = {k: self.entries[k].get().strip() for k in FORM_KEYS}
                self.store.data["form"]["show_time"] = bool(self.show_time.get())
            self.store.save()
            if self.worker:
                self.worker.q.put(("stop", None))
                time.sleep(0.25)  # ให้ worker เคลียร์สถานะก่อนปิด
        finally:
            self.destroy()


if __name__ == "__main__":
    App().mainloop()