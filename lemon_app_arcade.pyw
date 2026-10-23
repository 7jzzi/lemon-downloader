#!/usr/bin/env python3
"""
LEMON - a desktop MP4/MP3 downloader with an arcade look and a lemon that fills up as it downloads.

Double-click this file to open the app (needs Python with tkinter, which the
normal python.org installer includes).

Inside the app:
    paste a video link  ->  Download      saves the video as an MP4
    click a quality card                  best / 1080p / 720p / 480p
    Save folder card                      choose where videos go
    Open folder card                      open that folder
    "add to desktop" (bottom right)       puts a LEMON icon on your Desktop and
                                          Start menu, so it opens like any app
    "update helpers" (bottom right)       updates yt-dlp (do this if downloads break)

First run installs the free helpers it uses (yt-dlp, imageio-ffmpeg, deno).
Only download videos you own, that are free to share, or that you otherwise
have the right to save, and respect each site's terms.

Settings are saved in  ~/.lemon_downloader.json

License: GNU GPL v3.0 (see the LICENSE file).
"""

import base64
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import logging.handlers
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import textwrap
import threading
import time
import types
import zlib

# pythonw (double-click) has no console: make sure nothing crashes on print/log
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w"))
if sys.stdin is None:
    sys.stdin = open(os.devnull, "r")

import tkinter as tk  # noqa: E402
from tkinter import filedialog  # noqa: E402
from tkinter import font as tkfont  # noqa: E402

# Bump this number in every new release. The lemon button uses it to know what is newer.
APP_VERSION = "1.0"  # dotted: 1.0 -> 1.1 -> 2.0

IS_WIN = sys.platform.startswith("win")
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW


# ───────────────────────── colours ─────────────────────────
def mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def hexc(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


YELLOW = (255, 214, 10)
WHITE = (255, 255, 255)
DEEP = (232, 160, 0)
LEAF = (88, 170, 52)
LEAF_DARK = (52, 120, 38)
DARK = (28, 22, 0)
BG = (18, 15, 0)
CARD_BG = (22, 20, 11)
HINT = (205, 195, 135)
RED = (255, 125, 115)
ACCENTS = [
    (255, 214, 10),   # lemon
    (170, 225, 60),   # lime
    (255, 165, 50),   # orange
    (255, 130, 140),  # pink grapefruit
    (255, 245, 170),  # cream
    (110, 215, 170),  # mint
]

TITLE_COLORS = [YELLOW, ACCENTS[1], ACCENTS[5], WHITE, ACCENTS[3], ACCENTS[2]]  # lemon lime mint white pink orange


def flow_color(x):
    """Smooth walk through TITLE_COLORS (x wraps around 1.0)."""
    x = (x % 1.0) * len(TITLE_COLORS)
    i = int(x)
    return mix(TITLE_COLORS[i], TITLE_COLORS[(i + 1) % len(TITLE_COLORS)], x - i)


# ───────────────────────── the lemon (drawn as pixels) ─────────────────────────
BASE_W, BASE_H = 36, 26


def lemon_pixels(W=BASE_W, H=BASE_H):
    """H x W grid of RGB tuples (None = transparent); the lemon is scaled to fit."""
    k = min(W / BASE_W, H / BASE_H)
    ox = (W / k - BASE_W) / 2
    oy = (H / k - BASE_H) / 2
    cx, cy = 16.0, 14.0
    a, b = 12.0, 8.0
    tilt = math.radians(-18)
    cos_t, sin_t = math.cos(tilt), math.sin(tilt)
    leaf_cx, leaf_cy, ang = 29.8, 6.0, math.radians(-45)
    lc, ls = math.cos(ang), math.sin(ang)

    grid = [[None] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            px = (x + 0.5) / k - ox
            py = (y + 0.5) / k - oy
            dx, dy = px - leaf_cx, py - leaf_cy
            p = dx * lc + dy * ls
            q = -dx * ls + dy * lc
            if p ** 2 / 5.0 ** 2 + q ** 2 / 2.1 ** 2 <= 1:
                grid[y][x] = LEAF_DARK if abs(q) < 0.5 else LEAF
                continue
            dx, dy = px - cx, py - cy
            u = dx * cos_t + dy * sin_t
            v = -dx * sin_t + dy * cos_t
            inside = False
            if abs(u) <= a:
                half = b * (1 - (abs(u) / a) ** 2.4) ** 0.5
                inside = abs(v) <= half
            for sign in (-1, 1):
                nx = sign * (a - 0.2)
                if (u - nx) ** 2 / 2.6 ** 2 + v ** 2 / 2.0 ** 2 <= 1:
                    inside = True
            if not inside:
                continue
            hx, hy = -3.5, -3.0
            d = math.hypot(u - hx, v - hy) / 17.0
            col = mix(WHITE, YELLOW, d * 1.7)
            if d > 0.55:
                col = mix(YELLOW, DEEP, (d - 0.55) * 1.3)
            if (u + 5.5) ** 2 / 3.0 ** 2 + (v + 4.0) ** 2 / 1.0 ** 2 <= 1:
                col = WHITE
            grid[y][x] = tuple(col)
    return grid


def grid_to_image(grid, colour_of):
    """Build a tk.PhotoImage from a pixel grid. colour_of(x, y, c) -> rgb."""
    h, w = len(grid), len(grid[0])
    img = tk.PhotoImage(width=w, height=h)
    rows = []
    for y in range(h):
        rows.append("{" + " ".join(
            hexc(colour_of(x, y, grid[y][x]) if grid[y][x] is not None else BG)
            for x in range(w)) + "}")
    img.put(" ".join(rows))
    return img


def png_bytes(grid):
    """Encode a pixel grid as an RGBA PNG (used for the app icon)."""
    h, w = len(grid), len(grid[0])
    raw = bytearray()
    for row in grid:
        raw.append(0)
        for c in row:
            raw += bytes(c) + b"\xff" if c else b"\x00\x00\x00\x00"

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def write_ico(path, sizes=(16, 32, 48, 64, 128, 256)):
    """A real multi-size .ico of the lemon (crisp in the title bar, taskbar and Desktop)."""
    images = [png_bytes(lemon_pixels(n, n)) for n in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for n, png in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def lemon_home():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "LEMON")


def ensure_icon():
    """Make sure the lemon .ico exists (written once) and return its path."""
    try:
        os.makedirs(lemon_home(), exist_ok=True)
        path = os.path.join(lemon_home(), "lemon.ico")
        if not os.path.exists(path):
            write_ico(path)
        return path
    except OSError:
        return None


FONT = {
    "L": ["X....", "X....", "X....", "X....", "XXXXX"],
    "E": ["XXXXX", "X....", "XXXX.", "X....", "XXXXX"],
    "M": ["X...X", "XX.XX", "X.X.X", "X...X", "X...X"],
    "O": [".XXX.", "X...X", "X...X", "X...X", ".XXX."],
    "N": ["X...X", "XX..X", "X.X.X", "X..XX", "X...X"],
}


# ───────────────────────── settings, helpers, downloader ─────────────────────────
CONFIG = os.path.join(os.path.expanduser("~"), ".lemon_downloader.json")
LOG = logging.getLogger("lemon")
LOG.addHandler(logging.NullHandler())  # (until setup_logging() runs, e.g. in tests, logging does nothing)


# ───────────────────────── the log file (lemon.log) and hiding secrets in it ─────────────────────────
def log_path():
    return os.path.join(lemon_home(), "lemon.log")


_URL_RE = re.compile(r"(https?://[^\s?#\"'<>]+)\?([^\s\"'<>]*)")
_COOKIE_RE = re.compile(r"(?i)\b(cookies?|set-cookie|authorization|token)(\s*[:=]\s*)[^\s,;\"']+")


def scrub_log(text):
    """Keep private data out of the log: a link keeps only its video/playlist id (v=, list=), the rest of
    its query (signed tokens, session ids) is hidden; cookie / token values are hidden."""
    def link(mo):
        keep = [p for p in mo.group(2).split("&") if p.split("=")[0] in ("v", "list")]
        return mo.group(1) + ("?" + "&".join(keep) + "&..." if keep else "?...")
    return _COOKIE_RE.sub(r"\1\2[hidden]", _URL_RE.sub(link, text))


class ScrubFormatter(logging.Formatter):
    def format(self, record):
        return scrub_log(super().format(record))  # also covers the traceback text


def setup_logging():
    """A small log file (%LOCALAPPDATA%\\LEMON\\lemon.log, 2 x 0.5 MB) so a problem on any PC can be found later.
    pythonw has no console, so before this every error just vanished."""
    try:
        os.makedirs(lemon_home(), exist_ok=True)
        h = logging.handlers.RotatingFileHandler(log_path(), maxBytes=500_000, backupCount=1, encoding="utf-8")
        h.setFormatter(ScrubFormatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        LOG.addHandler(h)
        LOG.setLevel(logging.INFO)
    except OSError:
        return
    sys.excepthook = lambda t, v, tb: LOG.error("unhandled error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: LOG.error("unhandled error in a thread", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    LOG.info("==== LEMON v%s start | python %s | frozen=%s | %s", APP_VERSION, sys.version.split()[0],
             bool(getattr(sys, "frozen", False)), sys.platform)

    def environment():  # (in a thread: finding ffmpeg / VLC can take a moment)
        LOG.info("yt-dlp %s | ffmpeg %s | js runtime %s | vlc %s", ytdlp_version(), find_ffmpeg(),
                 find_js_runtime(), bool(load_vlc()))
    threading.Thread(target=environment, daemon=True).start()

NCARDS = 10  # menu cards; then the Paste key, the Download key and the link box

QUALITIES = [
    ("Best quality", None, "up to 4K"),
    ("1080p", 1080, "Full HD"),
    ("720p", 720, "HD"),
    ("480p", 480, "SD"),
]
AUDIO_FORMATS = ("mp3", "m4a", "flac")  # the MP3 card cycles OFF -> MP3 -> M4A -> FLAC
EXTRAS = (("subs", "SUBTITLES", "ENGLISH + ARABIC, INSIDE THE VIDEO"), ("thumb", "COVER PICTURE", "THE THUMBNAIL, INSIDE THE FILE"),
          ("tags", "TITLE & INFO", "TITLE, ARTIST, CHAPTERS IN THE FILE"))  # (settings key, name, what it does)
COOKIE_CHOICES = ["", "chrome", "edge", "firefox"]  # "" = don't use browser cookies
BROWSER_EXE = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}
MAIN_ANIM = {"sparkles": True, "side": True, "pulse": True, "glint": True}  # the light animations on the main screen (False = off)
LOCKED_WHILE_OPEN = ("chrome", "edge")  # these keep their cookie file locked while open; Firefox can be read while open
DEP_PACKAGES = ["yt-dlp[default]", "imageio-ffmpeg", "deno", "python-vlc"]  # python-vlc: the preview player (needs VLC too)
DEP_HELP = 'pip install -U "yt-dlp[default]" imageio-ffmpeg deno python-vlc'


# ───────────────────────── small helpers, the recent list, the settings file ─────────────────────────
def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_time(ms):
    s = int(ms // 1000)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def suggested_folder():
    return os.path.join(os.path.expanduser("~"), "Downloads", "Lemon")


RECENT_MAX = 30


def add_recent(settings, path, title):
    """Put a finished download at the top of the recent list (a file that is there already moves up and starts at 0:00)."""
    rest = [e for e in settings["recent"] if e["path"] != path]
    settings["recent"] = ([{"path": path, "title": title or "", "ts": time.time(), "pos": 0}] + rest)[:RECENT_MAX]


def remember_pos(settings, path, t_ms, len_ms):
    """Remember where you stopped watching (nothing worth keeping in the first 5 s or the last 5%)."""
    for e in settings["recent"]:
        if e["path"] == path:
            e["pos"] = int(t_ms) if len_ms and 5000 < t_ms < 0.95 * len_ms else 0
            return


def resume_pos(settings, path):
    return next((e["pos"] for e in settings["recent"] if e["path"] == path), 0)


def ago(ts, now=None):
    d = int((now or time.time()) - ts)
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{d // 60} min ago"
    if d < 86400:
        return f"{d // 3600} h ago"
    if d < 2 * 86400:
        return "yesterday"
    return f"{d // 86400} days ago" if d < 60 * 86400 else time.strftime("%d %b %Y", time.localtime(ts))


def default_settings():
    return {"folder": "", "quality": 0, "confirmed": False, "audio": False, "cookies": "", "volume": 70, "recent": [],
            "subs": False, "thumb": False, "tags": False, "afmt": "mp3", "lang": "en", "autostart": False, "tray": False}


def load_settings():
    """Read the saved settings. 'confirmed' is only True once the user has chosen a
    folder and pressed Confirm on LEMON's settings screen."""
    s = default_settings()
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("folder"), str):
            s["folder"] = data["folder"]
        if isinstance(data.get("quality"), int) and 0 <= data["quality"] < len(QUALITIES):
            s["quality"] = data["quality"]
        s["audio"] = bool(data.get("audio"))
        s["subs"], s["thumb"], s["tags"] = bool(data.get("subs")), bool(data.get("thumb")), bool(data.get("tags"))
        s["autostart"], s["tray"] = bool(data.get("autostart")), bool(data.get("tray"))
        if data.get("lang") in ("en", "ar"):
            s["lang"] = data["lang"]
        if data.get("afmt") in AUDIO_FORMATS:
            s["afmt"] = data["afmt"]
        if data.get("cookies") in COOKIE_CHOICES:
            s["cookies"] = data["cookies"]
        if type(data.get("volume")) is int and 0 <= data["volume"] <= 100:
            s["volume"] = data["volume"]
        s["recent"] = [{"path": e["path"], "title": str(e.get("title") or "")[:200],
                        "ts": float(e["ts"]) if type(e.get("ts")) in (int, float) else 0.0,
                        "pos": e["pos"] if type(e.get("pos")) is int and e["pos"] >= 0 else 0}
                       for e in (data.get("recent") or [])[:RECENT_MAX]
                       if isinstance(e, dict) and isinstance(e.get("path"), str) and e["path"] and is_media(e["path"])]
        s["confirmed"] = bool(data.get("confirmed")) and bool(s["folder"])
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return s


def save_settings(s):
    """Save settings safely (write a temp file, then swap it in) and read them back to
    be sure they really are on disk. Returns None on success, or an error message."""
    data = {k: s.get(k, v) for k, v in default_settings().items()}
    data["confirmed"] = bool(data["confirmed"])
    tmp = CONFIG + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG)
        if load_settings() != data:
            return "the file was written but did not read back correctly"
        return None
    except OSError as e:
        return str(e)


# ───────────────────────── site folders (Youtube, Tiktok, Instagram, ...) ─────────────────────────
SITE_FOLDERS = ["Youtube", "Tiktok", "Instagram", "Snapchat", "X", "Others"]  # inside the save folder; each video goes to its site's folder
_SITE_HOSTS = [("Youtube", ("youtube.com", "youtu.be", "youtube-nocookie.com")), ("Tiktok", ("tiktok.com",)),
               ("Instagram", ("instagram.com", "instagr.am")), ("Snapchat", ("snapchat.com",)),
               ("X", ("twitter.com", "x.com", "t.co"))]


def site_folder_name(url):
    """Which of the SITE_FOLDERS a link belongs to ('Others' for any other site)."""
    from urllib.parse import urlparse
    try:
        host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        host = ""
    for name, domains in _SITE_HOSTS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return "Others"


def ensure_site_folders(path):
    """Make the Youtube / Tiktok / Instagram / Snapchat / X / Others folders inside the save folder (quietly)."""
    for name in SITE_FOLDERS:
        try:
            os.makedirs(os.path.join(path, name), exist_ok=True)
        except OSError:
            pass


def check_folder(path):
    """Can LEMON create this folder and write into it? Returns None, or an error message.
    (It also makes the per-site folders inside it.)"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".lemon_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        ensure_site_folders(path)
        return None
    except OSError as e:
        return str(e)


# ───────────────────────── Windows integration: taskbar identity, shortcuts ─────────────────────────
AUMID = "lemon.downloader.app"
_FMT = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"  # System.AppUserModel.* property set
_IID_PROPSTORE = "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"


def _com_helpers():
    """Tiny raw-COM toolkit (ctypes only): guid(), key(pid), pv(text), com(ptr, slot, *args)."""
    import ctypes
    import uuid

    class Key(ctypes.Structure):
        _fields_ = [("g", ctypes.c_ubyte * 16), ("pid", ctypes.c_ulong)]

    class PropVar(ctypes.Structure):  # VT_LPWSTR (31) holding a string pointer
        _fields_ = [("vt", ctypes.c_ushort), ("pad", ctypes.c_ushort * 3),
                    ("p", ctypes.c_void_p), ("pad2", ctypes.c_void_p)]

    def guid(text):
        return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)

    def com(ptr, slot, *args):
        vt = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *[ctypes.c_void_p] * len(args))(vt[slot])(ptr, *args)

    def put(store, pid, text, keep):
        buf = ctypes.create_unicode_buffer(text)
        pv = PropVar(31, (0, 0, 0), ctypes.cast(buf, ctypes.c_void_p), None)
        keep += [buf, pv]
        com(store, 6, ctypes.byref(Key(guid(_FMT), pid)), ctypes.byref(pv))  # IPropertyStore::SetValue

    return guid, com, put


def set_taskbar_identity(root):
    """Windows pins a running pythonw window as plain pythonw.exe (Python icon). Telling the window
    how to relaunch + which icon to use makes the pin a real LEMON shortcut with the lemon."""
    import ctypes
    ico = ensure_icon()
    if not ico:
        return
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)  # 2 = the real top-level window
    guid, com, put = _com_helpers()
    sh = ctypes.windll.shell32
    sh.SHGetPropertyStoreForWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    store, keep = ctypes.c_void_p(), []
    if sh.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(guid(_IID_PROPSTORE)), ctypes.byref(store)) != 0:
        return
    put(store, 2, f'"{sibling_exe("pythonw.exe")}" "{os.path.abspath(__file__)}"', keep)  # RelaunchCommand
    put(store, 3, ico + ",0", keep)                                                       # RelaunchIconResource
    put(store, 4, "LEMON", keep)                                                          # RelaunchDisplayNameResource
    com(store, 7)  # Commit


def sync_installed_copy():
    """The Desktop/Start shortcuts launch the installed copy; keep it equal to the file being run."""
    target, me = os.path.join(lemon_home(), "lemon_app.pyw"), os.path.abspath(__file__)
    if os.path.exists(target) and os.path.normcase(me) != os.path.normcase(target):
        with open(me, "rb") as a, open(target, "rb") as b:
            same = a.read() == b.read()
        if not same:  # ponytail: last-run file wins, even if older. Add a version check if that bites.
            shutil.copyfile(me, target)


def tag_shortcuts():
    """Stamp our AppUserModelID on the Desktop/Start-menu LEMON.lnk files. Windows then pins THAT
    shortcut (lemon icon) when the running LEMON window is pinned, instead of pythonw.exe."""
    import ctypes
    guid, com, put = _com_helpers()
    ole = ctypes.windll.ole32
    ole.CoInitialize(None)
    home = os.path.expanduser("~")
    folders = [os.path.join(os.environ.get("APPDATA") or home, "Microsoft", "Windows", "Start Menu", "Programs"),
               os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop")]
    for folder in folders:
        path = os.path.join(folder, "LEMON.lnk")
        if not os.path.exists(path):
            continue
        # ponytail: COM objects are never Release()d - runs once per start, harmless
        link, pf, store, keep = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p(), []
        if ole.CoCreateInstance(ctypes.byref(guid("00021401-0000-0000-C000-000000000046")), None, 1,
                                ctypes.byref(guid("000214F9-0000-0000-C000-000000000046")), ctypes.byref(link)):
            return
        com(link, 0, ctypes.byref(guid("0000010B-0000-0000-C000-000000000046")), ctypes.byref(pf))  # IPersistFile
        com(pf, 5, ctypes.c_wchar_p(path), 2)                                                      # Load, read+write
        com(link, 0, ctypes.byref(guid(_IID_PROPSTORE)), ctypes.byref(store))
        put(store, 5, AUMID, keep)                                                                 # System.AppUserModel.ID
        com(store, 7)                                                                              # Commit
        com(pf, 6, None, 1)                                                                        # Save


# ───────────────────────── finding / installing the helpers (pip, ffmpeg, deno) ─────────────────────────
def sibling_exe(name):
    """python.exe <-> pythonw.exe next to the running interpreter."""
    exe = sys.executable
    if IS_WIN:
        folder = os.path.dirname(exe)
        cand = os.path.join(folder, name)
        if os.path.exists(cand):
            return cand
    return exe


def pip_install(packages, upgrade=False):
    cmd = [sibling_exe("python.exe"), "-m", "pip", "install"] + (["-U"] if upgrade else []) + packages
    kw = dict(capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    r = subprocess.run(cmd, **kw)
    importlib.invalidate_caches()
    return r.returncode == 0


def find_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def find_js_runtime():
    """(name, path) of a JavaScript engine yt-dlp can use for YouTube, or None."""
    path = shutil.which("deno")
    if not path:
        try:
            import deno
            path = deno.find_deno_bin()
        except Exception:  # noqa: BLE001
            path = None
    if path and os.path.exists(path):
        return "deno", path
    node = shutil.which("node")
    if node:
        try:
            out = subprocess.run([node, "--version"], capture_output=True, text=True,
                                 timeout=5, creationflags=NO_WINDOW).stdout
            if int(out.strip().lstrip("v").split(".")[0]) >= 22:
                return "node", node
        except Exception:  # noqa: BLE001
            pass
    return None


def youtube_ready():
    return importlib.util.find_spec("yt_dlp_ejs") is not None and find_js_runtime() is not None


def helpers_ready():
    return importlib.util.find_spec("yt_dlp") is not None and youtube_ready()


def ytdlp_version():
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:  # noqa: BLE001
        return "not installed"


# ───────────────────────── download options, links and clip ranges ─────────────────────────
def format_for(height, have_ffmpeg):
    h = f"[height<=?{height}]" if height else ""
    if have_ffmpeg:  # best video + best audio, joined into an MP4
        return f"bv*{h}+ba/b{h}"
    return f"b{h}[ext=mp4]/b{h}/b"


def looks_like_url(text):
    t = text.lower()
    if "://" in t and not t.startswith(("http://", "https://")):
        return False  # file://, ftp://, javascript: ... only web links
    return " " not in t and (t.startswith(("http://", "https://", "www."))
                             or ("." in t and "/" in t))


MEDIA_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mp3", ".m4a", ".opus", ".aac", ".wav", ".flac", ".ogg")


def is_media(path):
    """Only audio / video files are ever opened or played (a hand-edited settings file can't make LEMON run a program)."""
    return str(path).lower().endswith(MEDIA_EXT)


def normalise_url(text):
    return text if text.lower().startswith(("http://", "https://")) else "https://" + text


_CLIP_T = r"\d+(?::\d{1,2}){0,2}(?:\.\d+)?"  # 90  1:30  1:02:03  1:30.5
CLIP_RE = re.compile(rf"^(?P<link>\S+)\s+(?P<a>{_CLIP_T})\s*(?:-|\u2013|to)\s*(?P<b>{_CLIP_T})?\s*$", re.I)


def clip_seconds(t):
    secs = 0.0
    for part in t.split(":"):
        secs = secs * 60 + float(part)
    return secs


def split_clip(text):
    """'link 1:20-2:05' -> ('link', (80.0, 125.0)); 'link 1:20-' -> ('link', (80.0, None)); plain link -> (link, None)."""
    m = CLIP_RE.match(text.strip())
    if not m:
        return text, None
    return m["link"], (clip_seconds(m["a"]), clip_seconds(m["b"]) if m["b"] else None)


def clip_tag(rng):
    """For file names: ' [clip 1m20s-2m05s]' (no colons, Windows doesn't allow them)."""
    def nice(x):
        x = int(x)
        return f"{x // 3600}h{x // 60 % 60:02d}m{x % 60:02d}s" if x >= 3600 else f"{x // 60}m{x % 60:02d}s"
    return f" [clip {nice(rng[0])}-{nice(rng[1])}]" if rng[1] is not None else f" [clip from {nice(rng[0])}]"


# ───────────────────────── error messages in plain words ─────────────────────────
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


ERROR_HINTS = [  # (what to look for in yt-dlp's message, what to tell the user); first match wins
    (r"unsupported url", "that link isn't supported"),
    (r"private video", "that video is private"),
    (r"age[- ]restricted|confirm your age", "age-restricted video: turn on the Cookies card (a browser you're logged in with)"),
    (r"members[- ]only|join this channel", "members-only video: turn on the Cookies card with a browser that has access"),
    (r"not a bot|sign in", "YouTube wants a sign-in check. Turn on the Cookies card (pick the browser you're logged in with)"),
    (r"cookie|dpapi", "couldn't read your browser's cookies. Close that browser, or pick another on the Cookies card"),
    (r"not available in your country|blocked it in your country|geo.?restrict", "this video isn't available in your country"),
    (r"copyright", "the owner blocked this video (copyright)"),
    (r"video unavailable|no longer available|has been removed|not available", "that video is unavailable or was removed"),
    (r"live event will begin|premieres in|is upcoming|this live event", "that video hasn't started yet (live stream or premiere)"),
    (r"requested format is not available", "no downloadable format found. Click 'update helpers', then try again"),
    (r"\b429\b|too many requests", "too many requests. Wait a few minutes, then try again"),
    (r"\b403\b|forbidden", "the site blocked the request (403). Try the Cookies card, or 'update helpers'"),
    (r"no space left|errno 28|not enough space", "your disk is full. Free some space or pick another folder"),
    (r"permission denied|errno 13|access is denied", "LEMON can't write there. Pick another folder in settings, or close the program using the file"),
    (r"getaddrinfo|name or service|temporary failure in name|timed out|connection (reset|aborted|refused)|"
     r"network is unreachable|urlopen error|remote end closed", "no internet, or the site didn't answer. Check your connection and try again"),
    (r"ffmpeg (is )?not (found|installed)|ffprobe and ffmpeg not found", "ffmpeg is missing. Press 'update helpers'"),
    (r"unable to extract|extractorerror", "couldn't read that page. The site may have changed: press 'update helpers' and try again"),
    (r"incomplete|unable to download video data|content too short", "the download was cut off. Try again"),
]
ERROR_HINTS = [(re.compile(pat, re.I), text) for pat, text in ERROR_HINTS]


def tidy_error(exc):
    msg = ANSI_RE.sub("", str(exc)).strip().splitlines()[0] if str(exc).strip() else "unknown error"
    msg = re.sub(r"\s*\(caused by .*\)\s*$", "", msg.replace("ERROR: ", "").strip())
    for pat, text in ERROR_HINTS:
        if pat.search(msg):
            msg = text
            break
    return clip(msg, 120)


# ───────────────────────── Arabic interface (settings -> language) ─────────────────────────
# Every text goes through tr() before it is drawn. English is the default; a text that has no Arabic here is just
# shown in English (so a missing line never breaks anything). Layout is NOT mirrored (right-to-left text, left-to-right screen).
LANG = "en"  # "en" or "ar" (App sets it from the settings)
ARABIC_RE = re.compile("[؀-ۿ]")

_AR = [  # (English text in CAPITALS, Arabic)
    # main screen
    ("SETTINGS", "الإعدادات"), ("RECENT", "الأخيرة"), ("VIDEO DOWNLOADER", "تحميل الفيديوهات"),
    ("▶ SELECT QUALITY ◀", "▶ اختر الجودة ◀"), ("LINK▸", "الرابط"), ("PASTE", "لصق"), ("START", "ابدأ"),
    ("UPDATE", "تحديث"), ("UPDATE HELPERS", "تحديث المساعدات"), ("LOG", "السجل"), ("NOT SET", "غير محدد"),
    ("BEST", "الأفضل"), ("BEST QUALITY", "أفضل جودة"), ("UP TO 4K", "حتى 4K"), ("FULL HD", "دقة كاملة"),
    ("AUDIO ONLY", "صوت فقط"), ("COOKIES", "الكوكيز"), ("FOLDER", "المجلد"), ("OPEN", "فتح"),
    ("OFF", "إيقاف"), ("VIEW FILES", "عرض الملفات"),
    # recent
    ("CLICK ONE (OR PRESS ITS NUMBER) TO WATCH IT AGAIN", "اضغط على أحدها (أو رقمه) لمشاهدته مرة أخرى"),
    ("[ESC] BACK", "[ESC] رجوع"), ("NOTHING HERE YET", "لا شيء هنا بعد"),
    ("DOWNLOAD A VIDEO AND IT SHOWS UP HERE", "حمّل فيديو وسيظهر هنا"), ("WATCH▸", "شاهد"),
    ("CLEAR LIST", "مسح القائمة"), ("JUST NOW", "الآن"), ("YESTERDAY", "أمس"), 
    ("FILE MOVED OR DELETED", "الملف نُقل أو حُذف"),
    # settings
    ("SET IT ONCE  ·  LEMON REMEMBERS IT EVERY TIME", "اضبطها مرة واحدة  ·  ليمون يتذكرها دائمًا"),
    ("[ESC] CLOSE", "[ESC] إغلاق"), ("1  WHERE DO VIDEOS GO?", "1  أين تُحفظ الفيديوهات؟"),
    ("NO FOLDER CHOSEN YET", "لم تختر مجلدًا بعد"), ("BROWSE", "تصفّح"), ("2  DEFAULT QUALITY", "2  الجودة الافتراضية"),
    ("3  EXTRAS  (OPTIONAL)", "3  إضافات  (اختياري)"), ("SUBTITLES", "الترجمة"),
    ("ENGLISH + ARABIC, INSIDE THE VIDEO", "إنجليزي + عربي، داخل الفيديو"), ("COVER PICTURE", "صورة الغلاف"),
    ("THE THUMBNAIL, INSIDE THE FILE", "الصورة المصغّرة داخل الملف"), ("TITLE & INFO", "العنوان والمعلومات"),
    ("TITLE, ARTIST, CHAPTERS IN THE FILE", "العنوان والفنان والفصول داخل الملف"),
    ("KEEP LEMON RUNNING IN THE TRAY WHEN I CLOSE THE WINDOW", "أبقِ ليمون يعمل في صينية النظام عند إغلاق النافذة"),
    ("START LEMON WHEN WINDOWS STARTS", "شغّل ليمون عند تشغيل ويندوز"),
    ("PUT A LEMON ICON ON MY DESKTOP AND START MENU", "ضع أيقونة ليمون على سطح المكتب وقائمة ابدأ"),
    ("ONLY DOWNLOAD VIDEOS YOU HAVE THE RIGHT TO SAVE.", "حمّل فقط الفيديوهات التي لديك الحق في حفظها."),
    ("CHOOSE A FOLDER TO CONTINUE.", "اختر مجلدًا للمتابعة."), ("CONFIRM & SAVE", "تأكيد وحفظ"),
    # boot
    ("YOUTUBE HELPERS", "مساعدات يوتيوب"), ("FIRST START CAN TAKE A MINUTE", "أول تشغيل قد يستغرق دقيقة"), ("SETTINGS LOADED", "تم تحميل الإعدادات"),
    ("FIRST RUN - NEW SETTINGS", "أول تشغيل - إعدادات جديدة"), ("YT-DLP NOT INSTALLED YET", "YT-DLP غير مثبّت بعد"),
    ("YT-DLP CHECK FAILED", "فشل فحص YT-DLP"), ("FFMPEG FOUND", "تم العثور على FFMPEG"),
    ("FFMPEG NOT FOUND YET", "FFMPEG غير موجود بعد"), ("FFMPEG CHECK FAILED", "فشل فحص FFMPEG"),
    ("YOUTUBE HELPERS READY", "مساعدات يوتيوب جاهزة"), ("YOUTUBE HELPERS NEED SETUP", "مساعدات يوتيوب تحتاج إعدادًا"),
    ("HELPER CHECK FAILED", "فشل فحص المساعدات"), ("SKIPPED", "تم التخطي"), ("TIMED OUT", "انتهت المهلة"),
    # busy screen
    ("DOWNLOADING", "جارٍ التنزيل"), ("CANCELLING", "جارٍ الإلغاء"), ("SAVED!", "تم الحفظ!"),
    ("SETTING UP LEMON", "جارٍ إعداد LEMON"), ("UPDATING HELPERS", "جارٍ تحديث المساعدات"), ("ALL SET!", "كل شيء جاهز!"),
    ("QUALITY", "الجودة"), ("FORMAT", "الصيغة"), ("SAVING TO", "الحفظ في"), ("[ESC] CANCEL", "[ESC] إلغاء"),
    ("SQUEEZING THE LINK", "نعصر الرابط"), ("FINISHING UP", "اللمسات الأخيرة"), ("CUTTING YOUR CLIP", "نقصّ المقطع"),
    
    
    ("FIRST TIME ONLY - INSTALLING HELPERS", "أول مرة فقط - تثبيت المساعدات"),
    ("GETTING THE NEWEST VERSIONS", "جلب أحدث الإصدارات"),
    # done + player
    ("ALL DONE!", "اكتمل!"), ("YOUR AUDIO IS SAVED", "تم حفظ الصوت"), ("YOUR VIDEO IS SAVED", "تم حفظ الفيديو"),
    ("OPEN FOLDER", "فتح المجلد"), ("SHOW FILE", "إظهار الملف"), ("NEW LINK", "رابط جديد"),
    ("PASTE ANOTHER LINK TO KEEP GOING", "ألصق رابطًا آخر للمتابعة"),
    ("WANT A PREVIEW PLAYER HERE? INSTALL VLC, THEN PRESS UPDATE HELPERS",
     "تريد مشغّل معاينة هنا؟ ثبّت VLC ثم اضغط تحديث المساعدات"),
    ("WATCHING AGAIN", "مشاهدة مرة أخرى"), ("NOW PLAYING", "يُشغَّل الآن"),
    # updating screen
    ("UPDATING LEMON", "جارٍ تحديث LEMON"), ("UPDATED!", "تم التحديث!"), ("NOW", "الآن"), ("NEW!", "جديد!"),
    ("KEEP LEMON OPEN. IT RESTARTS BY ITSELF WHEN DONE.", "اترك LEMON مفتوحًا. سيعيد تشغيل نفسه عند الانتهاء."),
    ("LOOKING FOR THE NEW VERSION", "نبحث عن الإصدار الجديد"),
    ("BUILDING THE NEW VERSION  ·  ABOUT A MINUTE", "نبني الإصدار الجديد  ·  حوالي دقيقة"),
    ("SWAPPING IN THE NEW FILES", "نستبدل الملفات الجديدة"), ("RESTARTING LEMON", "إعادة تشغيل LEMON"),
    ("DOWNLOAD", "تنزيل"), ("VERIFY", "تحقق"), ("DOWNLOADING THE NEW VERSION", "نُنزّل النسخة الجديدة"),
    ("CHECKING THAT IT IS SAFE AND STARTS", "نتأكد أنها سليمة وتعمل"),
    ("CHECK", "فحص"), ("BUILD", "بناء"), ("SWAP", "استبدال"), ("RESTART", "إعادة تشغيل"),
    ("DONE", "تم"), ("WORKING", "قيد العمل"), ("WAITING", "انتظار"),
    # info line
    ("LOOKING AT THE LINK...", "نفحص الرابط..."),
    # toasts
    ("FOUND A LINK IN YOUR CLIPBOARD. PRESS START!", "وجدنا رابطًا في الحافظة. اضغط ابدأ!"),
    ("WAIT FOR THE CURRENT JOB TO FINISH, THEN PRESS THE LEMON.", "انتظر حتى تنتهي المهمة الحالية ثم اضغط الليمونة."),
    ("MP3 AUDIO ONLY.", "صوت MP3 فقط."), ("M4A AUDIO ONLY (SMALL, GOOD QUALITY).", "صوت M4A فقط (صغير وجودة جيدة)."),
    ("FLAC AUDIO ONLY (BIG FILES, NO QUALITY LOST BEYOND THE SOURCE).", "صوت FLAC فقط (ملفات كبيرة، بدون فقد جودة)."),
    ("BACK TO MP4 VIDEO.", "رجعنا إلى فيديو MP4."), ("COOKIES OFF.", "الكوكيز متوقفة."),
    ("UNSAVED TABS IN IT WILL BE LOST.", "ستفقد التبويبات غير المحفوظة فيه."),
    
    
    
    ("OPENED YOUR SAVE FOLDER.", "تم فتح مجلد الحفظ."),
    ("NOTHING TO PASTE YET. COPY A VIDEO LINK FIRST.", "لا يوجد شيء للصق. انسخ رابط فيديو أولًا."),
    ("PASTE A VIDEO LINK FIRST.", "ألصق رابط فيديو أولًا."),
    ("THAT DOESN'T LOOK LIKE A LINK. COPY THE VIDEO'S ADDRESS AND PASTE IT.", "هذا لا يشبه رابطًا. انسخ عنوان الفيديو وألصقه."),
    ("THE CLIP'S END TIME MUST BE AFTER ITS START TIME (LIKE 1:20-2:05).", "وقت نهاية المقطع يجب أن يكون بعد البداية (مثل 1:20-2:05)."),
    ("SETTING UP FIRST. ONE MOMENT...", "نجهّز أولًا. لحظة..."),
    ("FREE SOME SPACE OR PICK ANOTHER FOLDER.", "حرّر بعض المساحة أو اختر مجلدًا آخر."),
    ("ADDED LEMON TO YOUR DESKTOP AND START MENU.", "أُضيف LEMON إلى سطح المكتب وقائمة ابدأ."),
    ("DOWNLOAD CANCELLED.", "أُلغي التنزيل."), ("ALL SET! PASTE A LINK TO BEGIN.", "كل شيء جاهز! ألصق رابطًا للبدء."),
    ("HELPERS UPDATED. RESTARTING LEMON...", "تم تحديث المساعدات. نعيد تشغيل LEMON..."),
    # warnings under the done screen
    
    ("COULDN'T ADD THE SUBTITLES / COVER PICTURE", "تعذّرت إضافة الترجمة / صورة الغلاف"),
    # plain-language errors (ERROR_HINTS)
    ("THAT LINK ISN'T SUPPORTED", "هذا الرابط غير مدعوم"), ("THAT VIDEO IS PRIVATE", "هذا الفيديو خاص"),
    ("AGE-RESTRICTED VIDEO: TURN ON THE COOKIES CARD (A BROWSER YOU'RE LOGGED IN WITH)",
     "فيديو مقيّد بالعمر: شغّل بطاقة الكوكيز (متصفح مسجّل دخولك فيه)"),
    ("MEMBERS-ONLY VIDEO: TURN ON THE COOKIES CARD WITH A BROWSER THAT HAS ACCESS",
     "فيديو للأعضاء فقط: شغّل بطاقة الكوكيز مع متصفح لديه صلاحية"),
    ("YOUTUBE WANTS A SIGN-IN CHECK. TURN ON THE COOKIES CARD (PICK THE BROWSER YOU'RE LOGGED IN WITH)",
     "يوتيوب يطلب التحقق بتسجيل الدخول. شغّل بطاقة الكوكيز (اختر المتصفح المسجّل دخولك فيه)"),
    ("COULDN'T READ YOUR BROWSER'S COOKIES. CLOSE THAT BROWSER, OR PICK ANOTHER ON THE COOKIES CARD",
     "تعذّرت قراءة كوكيز المتصفح. أغلق ذلك المتصفح أو اختر غيره من بطاقة الكوكيز"),
    ("THIS VIDEO ISN'T AVAILABLE IN YOUR COUNTRY", "هذا الفيديو غير متاح في بلدك"),
    ("THE OWNER BLOCKED THIS VIDEO (COPYRIGHT)", "حجب المالك هذا الفيديو (حقوق النشر)"),
    ("THAT VIDEO IS UNAVAILABLE OR WAS REMOVED", "الفيديو غير متاح أو تمت إزالته"),
    ("THAT VIDEO HASN'T STARTED YET (LIVE STREAM OR PREMIERE)", "لم يبدأ هذا الفيديو بعد (بث مباشر أو عرض أول)"),
    ("NO DOWNLOADABLE FORMAT FOUND. CLICK 'UPDATE HELPERS', THEN TRY AGAIN",
     "لم نجد صيغة قابلة للتنزيل. اضغط «تحديث المساعدات» ثم حاول مجددًا"),
    ("TOO MANY REQUESTS. WAIT A FEW MINUTES, THEN TRY AGAIN", "طلبات كثيرة جدًا. انتظر بضع دقائق ثم حاول مجددًا"),
    ("THE SITE BLOCKED THE REQUEST (403). TRY THE COOKIES CARD, OR 'UPDATE HELPERS'",
     "الموقع حجب الطلب (403). جرّب بطاقة الكوكيز أو «تحديث المساعدات»"),
    ("YOUR DISK IS FULL. FREE SOME SPACE OR PICK ANOTHER FOLDER", "القرص ممتلئ. حرّر مساحة أو اختر مجلدًا آخر"),
    ("LEMON CAN'T WRITE THERE. PICK ANOTHER FOLDER IN SETTINGS, OR CLOSE THE PROGRAM USING THE FILE",
     "LEMON لا يستطيع الكتابة هناك. اختر مجلدًا آخر في الإعدادات أو أغلق البرنامج الذي يستخدم الملف"),
    ("NO INTERNET, OR THE SITE DIDN'T ANSWER. CHECK YOUR CONNECTION AND TRY AGAIN",
     "لا يوجد إنترنت أو الموقع لم يستجب. تحقق من اتصالك وحاول مجددًا"),
    ("FFMPEG IS MISSING. PRESS 'UPDATE HELPERS'", "ffmpeg مفقود. اضغط «تحديث المساعدات»"),
    ("COULDN'T READ THAT PAGE. THE SITE MAY HAVE CHANGED: PRESS 'UPDATE HELPERS' AND TRY AGAIN",
     "تعذّرت قراءة الصفحة. ربما تغيّر الموقع: اضغط «تحديث المساعدات» وحاول مجددًا"),
    ("THE DOWNLOAD WAS CUT OFF. TRY AGAIN", "انقطع التنزيل. حاول مجددًا"),
]
AR = {k.upper(): v for k, v in _AR}

_AR_PAT = [  # (regex over the whole text, function(match) -> Arabic); for texts with names and numbers in them
    (r"INSERT LINK\. GET (\w+)\. SQUEEZE IT!", lambda m: f"ضع الرابط. احصل على {m[1]}. اعصرها!"),
    (r"NEW V([\d.]+)!", lambda m: f"جديد V{m[1]}!"),
    (r"FROM (\w+)", lambda m: f"من {m[1]}"),
    (r"ON · <(\d+) MIN", lambda m: f"تشغيل · أقل من {m[1]} د"),
    (r"(\d+) MIN AGO", lambda m: f"قبل {m[1]} د"), (r"(\d+) H AGO", lambda m: f"قبل {m[1]} ساعة"),
    (r"(\d+) DAYS AGO", lambda m: f"قبل {m[1]} يوم"),
    (r"RESUME AT ([\d:]+)", lambda m: f"أكمل من {m[1]}"),
    (r"LOADING\.\.\. ?(\d+)%", lambda m: f"جارٍ التحميل... {m[1]}%"),
    (r"CHECKING (.*?)([_ ]*)", lambda m: f"فحص {tr(m[1])}{m[2]}"),
    (r"YT-DLP ([\d.]+) READY", lambda m: f"{ltr('YT-DLP ' + m[1])} جاهز"),
    (r"OR USE SUGGESTED: (.*)", lambda m: f"أو استخدم المقترح: {ltr(m[1])}"),
    (r"LEMON WILL SAVE TO (.*?)  ·  (.*)", lambda m: f"سيحفظ LEMON في {ltr(m[1])}  ·  {tr(m[2])}"),
    (r"YOUR CHOICES ARE STORED IN (.*)", lambda m: f"خياراتك محفوظة في {ltr(m[1])}"),
    (r"(.*) ✓", lambda m: tr(m[1]) + " ✓"),
    (r"STEP (\d+)", lambda m: f"الخطوة {m[1]}"),
    (r"([\d:]+) SO FAR", lambda m: f"{m[1]} حتى الآن"),
    (r"(.*) YOUR LEMON WAS NOT CHANGED\.", lambda m: f"{tr(m[1])} لم يتغير LEMON لديك."),
    (r"NOTE: (.*)", lambda m: "ملاحظة: " + "؛ ".join(tr(x) for x in m[1].split("; "))),
    (r"CONTINUING FROM ([\d:]+)  ·  PRESS 0 TO START OVER", lambda m: f"نكمل من {m[1]}  ·  اضغط 0 للبدء من جديد"),
    (r"COULDN'T OPEN IT: (.*)", lambda m: f"تعذّر فتحه: {ltr(m[1])}"),
    (r"([\d.]+ (?:GB|MB)) FREE", lambda m: f"{ltr(m[1])} متاحة"),
    (r"CAN'T CHECK THIS LINK: (.*)", lambda m: f"تعذّر فحص الرابط: {tr(m[1])}"),
    (r"NOT ENOUGH DISK SPACE \(NEED ~([\d.]+ \w+), ([\d.]+ \w+) FREE\)", lambda m: f"مساحة القرص لا تكفي (يلزم {ltr('~' + m[1])}، المتاح {ltr(m[2])})"),
    (r"NOT ENOUGH DISK SPACE: NEEDS ABOUT ([\d.]+ \w+), ONLY ([\d.]+ \w+) FREE\.",
     lambda m: f"مساحة القرص لا تكفي: يلزم حوالي {ltr(m[1])}، المتاح {ltr(m[2])} فقط."),
    (r"LEMON V([\d.]+) IS THE NEWEST\. RELOADING THE APP\.\.\.", lambda m: f"LEMON v{m[1]} هو الأحدث. نعيد تحميل التطبيق..."),
    (r"SETTINGS SAVED ✓  VIDEOS GO TO (.*)\.(.*)", lambda m: f"تم حفظ الإعدادات ✓  الفيديوهات تذهب إلى {ltr(m[1])}.{m[2]}"),
    (r"COULDN'T SAVE YOUR SETTINGS: (.*)", lambda m: f"تعذّر حفظ إعداداتك: {ltr(m[1])}"),
    (r"(.*)  ✓ SAVED", lambda m: f"{tr(m[1])}  ✓ تم الحفظ"),
    (r"QUALITY SET TO (.*)\.", lambda m: f"الجودة: {tr(m[1])}."),
    (r"USING (\w+) LOGIN COOKIES \(CLOSE \w+ FIRST\)\.", lambda m: f"نستخدم كوكيز {m[1]} (أغلق {m[1]} أولًا)."),
    (r"USING (\w+) LOGIN COOKIES\.", lambda m: f"نستخدم كوكيز {m[1]}."),
    (r"(\w+) MUST BE CLOSED FOR COOKIES", lambda m: f"يجب إغلاق {m[1]} حتى تعمل الكوكيز"),
    (r"CLOSE (\w+)", lambda m: f"إغلاق {m[1]}"),
    (r"(\w+) CLOSED\. PRESS START WHEN YOU ARE READY\.", lambda m: f"تم إغلاق {m[1]}. اضغط ابدأ عندما تكون جاهزًا."),
    (r"COULDN'T CLOSE (\w+)\. CLOSE IT YOURSELF, THEN PRESS START\.", lambda m: f"تعذّر إغلاق {m[1]}. أغلقه بنفسك ثم اضغط ابدأ."),
    (r"SAVING TO (.*) FROM NOW ON\.", lambda m: f"الحفظ في {ltr(m[1])} من الآن."),
    (r"LEMON CAN'T WRITE TO THAT FOLDER: (.*)", lambda m: f"LEMON لا يستطيع الكتابة في ذلك المجلد: {ltr(m[1])}"),
    (r"COULDN'T OPEN THE FOLDER: (.*)", lambda m: f"تعذّر فتح المجلد: {ltr(m[1])}"),
    (r"COULDN'T OPEN THE LOG: (.*)", lambda m: f"تعذّر فتح السجل: {ltr(m[1])}"),
    (r"COULDN'T ADD THE ICON: (.*)", lambda m: f"تعذّرت إضافة الأيقونة: {ltr(m[1])}"),
    (r"COULDN'T DOWNLOAD: (.*)", lambda m: f"تعذّر التنزيل: {tr(m[1])}"),
    (r"COULDN'T UPDATE: (.*)", lambda m: f"تعذّر التحديث: {ltr(m[1])}"),
    (r"SETUP DIDN'T FINISH\. CHECK YOUR INTERNET, OR RUN:  (.*)", lambda m: f"لم يكتمل الإعداد. تحقق من الإنترنت أو شغّل:  {ltr(m[1])}"),
    (r"UPDATED, BUT COULDN'T RESTART ON ITS OWN - JUST OPEN LEMON AGAIN\. (.*)", lambda m: f"تم التحديث لكن لم يعد التشغيل تلقائيًا - افتح LEMON من جديد. {ltr(m[1])}"),
]
_AR_PAT = [(re.compile(p, re.I | re.S), fn) for p, fn in _AR_PAT]


def ltr(s):
    """Keep an English / number / path piece together as one left-to-right unit inside Arabic text (else Tk scrambles it)."""
    return "‪" + s + "‬" if LANG == "ar" and s else s


def tr(s):
    """The text in the chosen language. Unknown text comes back unchanged (English)."""
    if LANG != "ar" or not isinstance(s, str) or not s.strip():
        return s
    t = s.strip()
    hit = AR.get(t.upper())
    if hit:
        return hit
    for pat, fn in _AR_PAT:
        m = pat.fullmatch(t)
        if m:
            return fn(m)
    parts = re.split(r"(?<=[.!?])\s+", t)  # a toast of several sentences: translate what we can, sentence by sentence
    if len(parts) > 1:
        out = [tr(p) for p in parts]
        if out != parts:
            return " ".join(out)
    return s


# ───────────────────────── disk space and the link probe (info line) ─────────────────────────
def fmt_size(b):
    return f"{b / 1073741824:.1f} GB" if b >= 1073741824 * 0.95 else f"{max(1, round(b / 1048576))} MB"


def disk_free(folder):
    """Free bytes on the drive of `folder` (the folder may not exist yet), or None."""
    path = folder
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    try:
        return shutil.disk_usage(path or ".").free
    except OSError:
        return None


def probe_link(url, height, audio, cookies, rng):
    """Look at a link without downloading it: {'title', 'secs', 'size'} (size = bytes, None if the site won't say).
    Raises yt-dlp's error (private video, bad link...)."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": _Quiet(), "socket_timeout": 15,
            "format": "bestaudio/best" if audio else format_for(height, True), "format_sort": ["res", "ext:mp4:m4a"]}
    if cookies:
        opts["cookiesfrombrowser"] = (cookies,)
    runtime = find_js_runtime()
    if runtime:
        opts["js_runtimes"] = {runtime[0]: {"path": runtime[1]}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("entries"):
        info = next((e for e in info["entries"] if e), info)
    secs = info.get("duration") or 0
    sizes = [f.get("filesize") or f.get("filesize_approx") or (f.get("tbr") and f["tbr"] * 125 * secs)
             for f in (info.get("requested_formats") or [info])]
    size = sum(sizes) if sizes and all(sizes) else None
    if audio and secs:
        size = secs * 24000  # MP3 at 192 kbit/s
    if rng and secs:  # a clip: only that part
        part = max(0, min(rng[1] or secs, secs) - rng[0])
        size = size * part / secs if size else None
        secs = part
    height = max([f.get("height") or 0 for f in (info.get("requested_formats") or [info])] or [0])
    return {"title": info.get("title") or "", "secs": secs, "size": size, "height": height or 720}


# ───────────────────────── downloading: Download and Setup ─────────────────────────
class _Quiet:
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass


class Download:
    """Runs one yt-dlp download in a thread and exposes live progress."""

    def __init__(self, url, folder, height, audio=False, cookies="", clip=None, extras=None):
        self.url, self.folder, self.height = url, folder, height
        self.clip = clip  # None, or (start_seconds, end_seconds or None)
        self.extras = extras or {}  # subs / thumb / tags (bool) and afmt ('mp3', 'm4a', 'flac')
        self.clip_len, self.t_clip = 0, None
        self.audio, self.cookies = audio, cookies
        self.warn = ""
        self.frac, self.title, self.speed, self.eta = 0.0, "", "", ""
        self.phase = "Squeezing the link"
        self.done, self.error, self.path = False, None, None
        self.cancel = threading.Event()
        self.streams = {}
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def _check_cancel(self):
        if self.cancel.is_set():
            try:
                from yt_dlp.utils import DownloadCancelled
            except ImportError:
                DownloadCancelled = Exception  # noqa: N806
            raise DownloadCancelled()

    def hook(self, d):
        self._check_cancel()
        info = d.get("info_dict") or {}
        if info.get("title"):
            self.title = info["title"]
        key = d.get("filename") or d.get("tmpfilename") or "x"
        if d.get("status") == "downloading":
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            frac = done / total if total else 0.0
            fi, fc = d.get("fragment_index"), d.get("fragment_count")
            if not total and fi and fc:
                frac = fi / fc
            self.streams[key] = (done, total, frac)
            vals = list(self.streams.values())
            if all(v[1] for v in vals):
                overall = sum(v[0] for v in vals) / max(1, sum(v[1] for v in vals))
            else:
                overall = sum(v[2] for v in vals) / len(vals)
            self.frac = max(self.frac, min(0.97, overall))  # never goes backwards
            self.phase = "Downloading"
            sp, eta = d.get("speed"), d.get("eta")
            self.speed = f"{sp / 1048576:.1f} MB/s" if sp else ""
            self.eta = f"ETA {int(eta) // 60}:{int(eta) % 60:02d}" if eta is not None else ""
        elif d.get("status") == "finished" and key in self.streams:
            done, total, _ = self.streams[key]
            full = total or done
            self.streams[key] = (full, full, 1.0)

    def clip_progress(self):
        """ffmpeg cuts a clip without reporting progress, so creep toward 90% (never reaching it) instead of sitting at 0."""
        if self.t_clip is None:
            return 0.0
        return 0.9 * (1 - math.exp(-(time.time() - self.t_clip) / (4 + (self.clip_len or 20) * 0.35)))

    def pp_hook(self, d):
        if d.get("status") == "started":
            self.phase = "Finishing up"
            self.speed = self.eta = ""
            self.frac = max(self.frac, 0.97)

    def run(self):
        t0 = time.time()
        LOG.info("download start: %s | height=%s audio=%s cookies=%s clip=%s extras=%s", self.url,
                 self.height, self.audio, self.cookies or "off", self.clip, self.extras)
        try:
            try:
                self.fetch()
            except BaseException as e:  # noqa: BLE001
                low = str(e).lower()
                if self.cancel.is_set():
                    raise
                if "403" in low or "forbidden" in low:
                    self.streams.clear()  # blocked: try once more with other YouTube clients
                    self.fetch({"youtube": {"player_client": ["mweb", "android_vr", "tv_simply"]}})
                elif ("subtitle" in low or "thumbnail" in low or "postprocess" in low or "ffmpeg" in low) and any(
                        self.extras.get(k) for k in ("subs", "thumb")):
                    self.streams.clear()  # the extras broke it (an odd subtitle / picture): the video itself comes first
                    LOG.warning("extras failed, retrying without them: %s", e)
                    self.extras = dict(self.extras, subs=False, thumb=False)
                    self.fetch()
                    self.warn = "couldn't add the subtitles / cover picture"
                else:
                    raise
        except BaseException as e:  # noqa: BLE001 - report anything to the user
            self.error = tidy_error(e)
            if self.cancel.is_set():
                LOG.info("download cancelled by the user")
            else:
                LOG.error("download failed (%s): %s", self.error, e, exc_info=True)
        else:
            LOG.info("download done in %.0fs: %s | warn=%r", time.time() - t0, self.path, self.warn)
        finally:
            self.done = True

    def fetch(self, extractor_args=None):
        import yt_dlp
        ffmpeg = find_ffmpeg()
        opts = {
            "outtmpl": os.path.join(self.folder, "%(title).110B" + (clip_tag(self.clip) if self.clip else "") + ".%(ext)s"),
            "windows_filenames": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _Quiet(),
            "socket_timeout": 20,
            "retries": 3,
            "progress_hooks": [self.hook],
            "postprocessor_hooks": [self.pp_hook],
        }
        ex, pps = self.extras, []
        if self.audio:  # audio only, converted to MP3 / M4A / FLAC
            opts["format"] = "bestaudio/best"
            if ffmpeg:
                pps.append({"key": "FFmpegExtractAudio", "preferredcodec": ex.get("afmt", "mp3"), "preferredquality": "192"})
        else:
            opts["format"] = format_for(self.height, bool(ffmpeg))
            opts["format_sort"] = ["res", "ext:mp4:m4a"]
            opts["merge_output_format"] = "mp4"
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
            if ex.get("tags"):  # title / artist / date / chapters written into the file
                pps.append({"key": "FFmpegMetadata", "add_chapters": True, "add_metadata": True})
            if ex.get("subs") and not self.audio:  # (the order matters: yt-dlp runs them one after the other)
                opts.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=["en", "ar"])
                pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
            if ex.get("thumb"):
                opts["writethumbnail"] = True
                pps += [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                        {"key": "EmbedThumbnail", "already_have_thumbnail": False}]
            opts["postprocessors"] = pps
        if self.cookies:
            opts["cookiesfrombrowser"] = (self.cookies,)
        if extractor_args:
            opts["extractor_args"] = extractor_args
        runtime = find_js_runtime()
        if runtime:
            opts["js_runtimes"] = {runtime[0]: {"path": runtime[1]}}
        os.makedirs(self.folder, exist_ok=True)
        if self.clip:  # only this part of the video (ffmpeg cuts it; the cut points are re-encoded so they are exact)
            from yt_dlp.utils import download_range_func
            opts["download_ranges"] = download_range_func(None, [(self.clip[0], self.clip[1] or float("inf"))])
            opts["force_keyframes_at_cuts"] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            if self.clip:
                pre = ydl.extract_info(self.url, download=False)  # first look, so a bad start time gets a clear message
                dur = pre.get("duration") if pre else None
                if dur and self.clip[0] >= dur:
                    raise ValueError(f"the clip starts at {fmt_time(self.clip[0] * 1000)} but the video is only "
                                     f"{fmt_time(dur * 1000)} long")
                self.clip_len = (min(self.clip[1] or dur or 0, dur or 1e9) - self.clip[0]) if (dur or self.clip[1]) else 0
                self.phase, self.t_clip = "Cutting your clip", time.time()
                info = ydl.process_ie_result(pre, download=True)
            else:
                info = ydl.extract_info(self.url, download=True)
            if info and info.get("entries"):
                entries = [e for e in info["entries"] if e]
                info = entries[0] if entries else info
            self.title = info.get("title") or self.title
            rd = info.get("requested_downloads") or []
            self.path = (rd[0].get("filepath") if rd else None) or ydl.prepare_filename(info)

class Setup:
    """Installs / updates the helper packages in a thread."""

    def __init__(self, upgrade):
        self.upgrade = upgrade
        self.done, self.ok = False, False
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        try:
            self.ok = pip_install(DEP_PACKAGES, upgrade=self.upgrade) and helpers_ready()
            LOG.info("helpers setup (upgrade=%s): ok=%s", self.upgrade, self.ok)
        except Exception:  # noqa: BLE001
            self.ok = False
            LOG.error("helpers setup failed", exc_info=True)
        finally:
            self.done = True


# ───────────────────────── the preview player (VLC) ─────────────────────────
def load_vlc():
    """python-vlc (pip) plus the VLC program: the preview player. None if either is missing."""
    try:
        import vlc
        return vlc
    except Exception:  # noqa: BLE001 - package not installed, or VLC itself not found
        return None


class Preview:
    """The preview video player: VLC draws into a Tk window; LEMON draws the controls."""
    SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

    def __init__(self, vlc, hwnd):
        self.vlc = vlc
        self.inst = vlc.Instance("--no-video-title-show", "--quiet")
        self.mp = self.inst.media_player_new()
        self.mp.set_hwnd(hwnd)
        self.mp.video_set_mouse_input(False)
        self.mp.video_set_key_input(False)
        self.loop, self.muted, self.speed, self.pending = False, False, 1.0, None
        self.resume = None  # after a seek / "continue where you stopped": (milliseconds, was_paused, speed, tries)
        self.pause_next = False

    def play(self, path, volume):
        self.speed, self.pending = 1.0, None
        self.mp.set_media(self.inst.media_new(path))
        self.mp.audio_set_volume(volume)
        self.mp.audio_set_mute(self.muted)
        self.mp.play()

    def ended(self):
        return self.mp.get_state() in (self.vlc.State.Ended, self.vlc.State.Stopped)

    def finished(self):
        return self.mp.get_state() == self.vlc.State.Ended

    def playing(self):
        return bool(self.mp.is_playing())

    def toggle(self):
        if self.ended():
            self.mp.stop()
            self.mp.play()  # play again from the start
        else:
            self.mp.set_pause(1 if self.playing() else 0)

    def time(self):
        return max(0, self.mp.get_time())

    def length(self):
        return max(0, self.mp.get_length())

    def seek(self, frac):
        frac = min(max(frac, 0.0), 1.0)
        if self.ended():  # a finished video can't seek: restart it and jump once it is playing again
            self.pending = frac
            self.mp.stop()
            self.mp.play()
        else:
            self.mp.set_position(min(frac, 0.999))

    def jump(self, secs):
        n = self.length()
        if n:
            self.seek((self.time() + secs * 1000) / n)

    def volume(self, v):
        self.mp.audio_set_volume(int(v))

    def mute(self):
        self.muted = not self.muted
        self.mp.audio_set_mute(self.muted)

    def faster(self):
        self.speed = self.SPEEDS[(self.SPEEDS.index(self.speed) + 1) % len(self.SPEEDS)]
        self.mp.set_rate(self.speed)

    def step(self):  # one frame forward (pauses first)
        self.mp.set_pause(1)
        self.mp.next_frame()

    def tick(self):  # about 4 times a second
        if self.pause_next:  # (pausing in the same moment as the seek makes VLC forget the seek)
            self.pause_next = False
            self.mp.set_pause(1)
        elif self.resume is not None and self.playing() and self.length() > 0 and self.mp.get_time() > 0:
            ms, paused, rate, tries = self.resume
            if abs(self.mp.get_time() - ms) > 2500 and tries < 8:  # not there yet (VLC ignores a seek that comes too early)
                self.mp.set_time(ms)
                self.resume = (ms, paused, rate, tries + 1)
            else:
                self.resume = None
                self.mp.set_rate(rate)
                self.pause_next = paused
        elif self.pending is not None and self.playing():
            self.mp.set_position(self.pending)
            self.pending = None
        elif self.loop and self.mp.get_state() == self.vlc.State.Ended:
            self.mp.stop()
            self.mp.play()

    def stop(self):
        self.pending = None
        self.mp.stop()


# ───────────────────────── Windows toast, browsers, folders, shortcuts ─────────────────────────
TOAST_PS = r"""
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml('<toast><visual><binding template="ToastText02"><text id="1"></text><text id="2"></text></binding></visual></toast>')
$t = $x.GetElementsByTagName('text')
$t.Item(0).InnerText = $env:LEMON_T
$t.Item(1).InnerText = $env:LEMON_M
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:LEMON_ID).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def notify(root, title, text):
    """A Windows toast ('LEMON - Your video is ready') and the taskbar button flashes. Called when you are not looking at LEMON.
    Never raises: a missing notification must not break a download."""
    if not IS_WIN:
        return
    try:
        import ctypes
        import winreg

        class FLASHW(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("flags", ctypes.c_uint),
                        ("count", ctypes.c_uint), ("timeout", ctypes.c_uint)]
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(FLASHW(ctypes.sizeof(FLASHW), hwnd, 0xE, 0, 0)))  # until you click it
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Classes\\AppUserModelId\\" + AUMID)  # gives the toast LEMON's name + icon
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "LEMON")
        ico = ensure_icon()
        if ico:
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, ico)
        winreg.CloseKey(key)
        env = dict(os.environ, LEMON_T=title, LEMON_M=text, LEMON_ID=AUMID)  # (env vars: no quoting trouble with odd titles)
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", TOAST_PS],
                         env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    except Exception:  # noqa: BLE001
        LOG.warning("notification failed", exc_info=True)


class Tray:
    """A system-tray icon (Windows), drawn with the plain Windows API: no extra package. It lives in its own small thread
    with its own message loop; clicks are put in a queue (events()) that the app reads, so Tk is never touched from here.
    Left click = 'open', right click = a menu (Open LEMON / Quit LEMON)."""
    CB = 0x8001  # our own message for icon clicks (WM_APP + 1)

    def __init__(self, ico, tip="LEMON", cls="LemonTrayWnd"):
        import queue
        self.q, self.hwnd, self.ok, self._cls, self._tip, self._ico = queue.Queue(), None, False, cls, tip, ico
        self._ready = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        self._ready.wait(3)

    def events(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return out

    def stop(self):
        if self.hwnd:
            self.u.PostMessageW(self.hwnd, 0x10, 0, 0)  # WM_CLOSE -> the window goes, the icon goes, the thread ends
        self._t.join(2)
        self.hwnd = None

    def _run(self):
        try:
            import ctypes
            from ctypes import wintypes as wt
            u = self.u = ctypes.WinDLL("user32", use_last_error=True)
            sh = ctypes.WinDLL("shell32", use_last_error=True)
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

            class WNDCLASS(ctypes.Structure):
                _fields_ = [("style", wt.UINT), ("proc", WNDPROC), ("cbCls", ctypes.c_int), ("cbWnd", ctypes.c_int),
                            ("inst", wt.HINSTANCE), ("icon", wt.HANDLE), ("cursor", wt.HANDLE), ("bg", wt.HANDLE),
                            ("menu", wt.LPCWSTR), ("name", wt.LPCWSTR)]

            class NID(ctypes.Structure):
                _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                            ("uCallbackMessage", wt.UINT), ("hIcon", wt.HANDLE), ("szTip", wt.WCHAR * 128),
                            ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                            ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                            ("guid", ctypes.c_byte * 16), ("hBalloonIcon", wt.HANDLE)]
            u.DefWindowProcW.argtypes, u.DefWindowProcW.restype = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM], LRESULT
            u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
            u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
            u.CreateWindowExW.restype = wt.HWND
            u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
            u.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
            u.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
            u.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
            u.CreatePopupMenu.restype = wt.HMENU
            u.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
            u.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
            u.DestroyMenu.argtypes = [wt.HMENU]
            u.SetForegroundWindow.argtypes = [wt.HWND]
            u.DestroyWindow.argtypes = [wt.HWND]
            u.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
            u.LoadImageW.restype = wt.HANDLE
            k.GetModuleHandleW.restype = wt.HINSTANCE
            sh.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NID)]
            created = u.RegisterWindowMessageW("TaskbarCreated")  # explorer restarted: put the icon back
            icon = u.LoadImageW(None, self._ico, 1, 16, 16, 0x10) if self._ico else None  # IMAGE_ICON, LR_LOADFROMFILE

            nid = NID()
            nid.cbSize = ctypes.sizeof(NID)
            nid.uID, nid.uFlags, nid.uCallbackMessage, nid.hIcon, nid.szTip = 1, 0x7, self.CB, icon, self._tip

            def menu():
                m = u.CreatePopupMenu()
                u.AppendMenuW(m, 0, 1, "Open LEMON")
                u.AppendMenuW(m, 0, 2, "Quit LEMON")
                pt = wt.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                u.SetForegroundWindow(self.hwnd)  # (or the menu never closes when you click elsewhere)
                cmd = u.TrackPopupMenu(m, 0x100 | 0x2, pt.x, pt.y, 0, self.hwnd, None)  # RETURNCMD | RIGHTBUTTON
                u.PostMessageW(self.hwnd, 0, 0, 0)
                u.DestroyMenu(m)
                if cmd:
                    self.q.put("open" if cmd == 1 else "quit")

            def proc(hwnd, msg, wp, lp):
                try:
                    if msg == self.CB:
                        if lp in (0x202, 0x203):  # left button up / double click
                            self.q.put("open")
                        elif lp == 0x205:  # right button up
                            menu()
                        return 0
                    if msg == created:
                        sh.Shell_NotifyIconW(0, ctypes.byref(nid))
                        return 0
                    if msg == 0x2:  # WM_DESTROY
                        sh.Shell_NotifyIconW(2, ctypes.byref(nid))  # NIM_DELETE
                        u.PostQuitMessage(0)
                        return 0
                except Exception:  # noqa: BLE001
                    LOG.warning("tray message failed", exc_info=True)
                return u.DefWindowProcW(hwnd, msg, wp, lp)

            self._proc = WNDPROC(proc)  # keep it alive: Windows calls it
            wc = WNDCLASS()
            wc.proc, wc.inst, wc.name = self._proc, k.GetModuleHandleW(None), self._cls
            u.RegisterClassW(ctypes.byref(wc))
            self.hwnd = u.CreateWindowExW(0, self._cls, "LEMON tray", 0, 0, 0, 0, 0, None, None, wc.inst, None)  # never shown
            nid.hWnd = self.hwnd
            self.ok = bool(self.hwnd) and bool(sh.Shell_NotifyIconW(0, ctypes.byref(nid)))  # NIM_ADD
            self._ready.set()
            msg = wt.MSG()
            while self.ok and u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
            if not self.ok and self.hwnd:
                u.DestroyWindow(self.hwnd)
            u.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
            u.UnregisterClassW(self._cls, wc.inst)  # (or a second tray would call this freed callback)
        except Exception:  # noqa: BLE001
            LOG.warning("tray icon failed", exc_info=True)
        finally:
            self._ready.set()


SHOW_REQUEST = threading.Event()  # set when a second LEMON was started: the running one should come to the front
_SINGLE_KEEP = []  # the mutex / event handles live as long as the process


def claim_single_instance(suffix=""):
    """Only one LEMON at a time (Windows). Returns True if we are the first. Otherwise it asks the running LEMON to show
    its window (even from the tray) and returns False: the caller should just exit.
    Not used by the update smoke test (LEMON_SMOKE: the new build must start next to the old one) and, for a restart
    after an update (LEMON_RESTART), it waits up to 10 s for the old one to finish."""
    if not IS_WIN or os.environ.get("LEMON_SMOKE"):
        return True
    import ctypes
    from ctypes import wintypes as wt
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes, k.CreateMutexW.restype = [wt.LPVOID, wt.BOOL, wt.LPCWSTR], wt.HANDLE
    k.CreateEventW.argtypes, k.CreateEventW.restype = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR], wt.HANDLE
    k.OpenEventW.argtypes, k.OpenEventW.restype = [wt.DWORD, wt.BOOL, wt.LPCWSTR], wt.HANDLE
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k.SetEvent.argtypes = [wt.HANDLE]
    k.CloseHandle.argtypes = [wt.HANDLE]
    mname, ename = "Local\\LEMON_single_instance" + suffix, "Local\\LEMON_show" + suffix
    for _ in range(50 if os.environ.get("LEMON_RESTART") else 1):
        mutex = k.CreateMutexW(None, False, mname)
        if mutex and ctypes.get_last_error() != 183:  # 183 = ERROR_ALREADY_EXISTS: another LEMON owns it
            break
        if mutex:
            k.CloseHandle(mutex)
        mutex = None
        time.sleep(0.2)
    if mutex is None:
        ev = k.OpenEventW(0x2, False, ename)  # EVENT_MODIFY_STATE
        if ev:
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # let the running LEMON take the front
            except Exception:  # noqa: BLE001
                pass
            k.SetEvent(ev)
            k.CloseHandle(ev)
        return False
    ev = k.CreateEventW(None, False, False, ename)  # auto-reset
    _SINGLE_KEEP.extend((mutex, ev))

    def wait():
        while k.WaitForSingleObject(ev, 0xFFFFFFFF) == 0:
            SHOW_REQUEST.set()
    threading.Thread(target=wait, daemon=True).start()
    return True


def browser_running(name):
    """Is this browser open right now? (Windows only; anywhere else we just say no.)"""
    exe = BROWSER_EXE.get(name)
    if not exe or not IS_WIN:
        return False
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe, "/NH", "/FO", "CSV"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=6)
        return exe.lower() in (r.stdout or "").lower()
    except Exception:  # noqa: BLE001
        return False


def close_browser(name):
    """Close every window and background process of this browser. True if it is gone afterwards."""
    exe = BROWSER_EXE.get(name)
    if not exe or not IS_WIN:
        return False
    try:
        subprocess.run(["taskkill", "/F", "/T", "/IM", exe], capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW, timeout=8)
        for _ in range(8):
            time.sleep(0.35)
            if not browser_running(name):
                return True
    except Exception:  # noqa: BLE001
        LOG.debug("close_browser failed", exc_info=True)
    return not browser_running(name)


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    if IS_WIN:
        os.startfile(path)  # noqa: S606 - opens the folder in Explorer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_file(path):
    if IS_WIN and path and os.path.exists(path):
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        open_folder(os.path.dirname(path) if path else default_settings()["folder"])


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # "start with Windows" lives here, per user (no admin needed)


def autostart_command():
    """The command Windows runs at log-in: the exe (or pythonw + this file), started minimised to the taskbar."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")  # no console window
    return f'"{pyw if os.path.isfile(pyw) else py}" "{os.path.abspath(__file__)}" --minimized'


def set_autostart(on, key=RUN_KEY):
    """Add / remove LEMON from the Windows start-up list. Raises OSError if the registry refuses."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        if on:
            winreg.SetValueEx(k, "LEMON", 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, "LEMON")
            except FileNotFoundError:
                pass


def install_shortcuts():
    """Copy the app to a permanent folder and add Desktop + Start menu icons (Windows)."""
    if not IS_WIN:
        raise RuntimeError("Desktop icons are only set up on Windows")
    app_dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "LEMON")
    os.makedirs(app_dir, exist_ok=True)
    target = os.path.join(app_dir, "lemon_app.pyw")
    src = os.path.abspath(__file__)
    if os.path.normcase(src) != os.path.normcase(target):
        shutil.copyfile(src, target)
    ico = os.path.join(app_dir, "lemon.ico")
    write_ico(ico)
    script = r'''
$ws = New-Object -ComObject WScript.Shell
$paths = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'LEMON.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'LEMON.lnk')
)
foreach ($p in $paths) {
  $s = $ws.CreateShortcut($p)
  $s.TargetPath = $env:LEMON_PYW
  $s.Arguments = '"' + $env:LEMON_SCRIPT + '"'
  $s.WorkingDirectory = $env:LEMON_DIR
  $s.IconLocation = $env:LEMON_ICO
  $s.Description = 'LEMON video downloader'
  $s.Save()
}
'''
    env = dict(os.environ, LEMON_PYW=sibling_exe("pythonw.exe"), LEMON_SCRIPT=target,
               LEMON_DIR=app_dir, LEMON_ICO=ico)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "PowerShell failed").strip().splitlines()[-1])


# ───────────────────────── is there a newer version? ─────────────────────────
def _vkey(v):
    return tuple(int(x) for x in str(v).split("."))


RELEASES_REPO = "7jzzi/lemon-downloader"  # GitHub "owner/name" whose Releases LEMON checks (once at start-up, and when the lemon is pressed)


SELF_UPDATE_MAX_ZIP = 900 * 1048576        # the release zip may be at most this big
SELF_UPDATE_MAX_UNZIPPED = 2 * 1024 ** 3   # ... and at most this big once unzipped


def _release_json():
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest",
                                 headers={"User-Agent": "LEMON", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read(1 << 20))  # (at most 1 MB)


def _release_basics(data):
    ver, url = str(data.get("tag_name", "")).lstrip("vV"), str(data.get("html_url", ""))
    if not re.fullmatch(r"\d{1,4}(\.\d{1,4}){0,3}", ver) or not url.startswith(f"https://github.com/{RELEASES_REPO}/"):
        return None
    return ver, url


def latest_release():
    """(version, page_url) of the newest GitHub release, or None if there is none / it looks wrong.
    One plain HTTPS request (at start-up and when the lemon is pressed)."""
    return _release_basics(_release_json())


def release_package(data):
    """The app package of a release: {"url", "sha256", "size"} for the LEMON*.zip attached to OUR releases page, or None.
    It must come with a SHA-256 fingerprint (GitHub's own `digest`, or one written in the release text)."""
    base = f"https://github.com/{RELEASES_REPO}/releases/download/"
    body = str(data.get("body") or "")
    for a in data.get("assets") or []:
        name, url = str(a.get("name", "")), str(a.get("browser_download_url", ""))
        if not (re.fullmatch(r"LEMON[\w .-]*\.zip", name, re.I) and url.startswith(base)):
            continue
        digest = str(a.get("digest") or "")
        sha = digest[7:] if digest.lower().startswith("sha256:") else ""
        if not sha:
            m = re.search(r"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])", body)
            sha = m[1] if m else ""
        try:
            size = int(a.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if re.fullmatch(r"[0-9a-fA-F]{64}", sha) and 0 < size <= SELF_UPDATE_MAX_ZIP:
            return {"url": url, "sha256": sha.lower(), "size": size}
    return None


def release_info():
    """(version, page_url, package or None) of the newest release, or None. One request."""
    data = _release_json()
    basics = _release_basics(data)
    return (basics[0], basics[1], release_package(data)) if basics else None


def dev_project():
    """(project folder, python.exe) when BUILD_LEMON.bat built this LEMON.exe on a developer PC, else None.
    The bat writes %LOCALAPPDATA%\\LEMON\\dev_source.txt (project folder, then python.exe); a normal user never has that file."""
    if not (IS_WIN and getattr(sys, "frozen", False)):
        return None
    try:
        with open(os.path.join(lemon_home(), "dev_source.txt"), encoding="utf-8-sig") as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
        proj, py = lines[0].rstrip("\\/"), lines[1]
    except (OSError, IndexError):
        return None
    ok = (os.path.isfile(os.path.join(proj, "lemon_app_arcade.pyw")) and os.path.isfile(os.path.join(proj, "exe_build", "build_exe.py"))
          and os.path.isfile(py))
    return (proj, py) if ok else None


def can_self_update():
    """Only the folder-build LEMON.exe, in a folder we may write to, can replace itself."""
    if not (IS_WIN and getattr(sys, "frozen", False)):
        return False
    folder = os.path.dirname(sys.executable)
    return (os.path.basename(sys.executable).lower() == "lemon.exe" and os.path.isdir(os.path.join(folder, "_internal"))
            and os.access(folder, os.W_OK))


def download_package(pkg, dest, progress):
    """Download the release zip to dest (progress(done, total) is called now and then) and check its SHA-256."""
    import hashlib
    import urllib.request
    req = urllib.request.Request(pkg["url"], headers={"User-Agent": "LEMON"})
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        if not r.geturl().lower().startswith("https://"):
            raise RuntimeError("the download link isn't secure")
        total = int(r.headers.get("Content-Length") or pkg["size"] or 0)
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            done += len(chunk)
            if done > SELF_UPDATE_MAX_ZIP:
                raise RuntimeError("the download is bigger than expected")
            h.update(chunk)
            f.write(chunk)
            progress(done, total)
    if h.hexdigest().lower() != pkg["sha256"]:
        raise RuntimeError("the download doesn't match its fingerprint")


def unpack_package(zip_path, dest):
    """Unzip safely (no file may land outside dest) and return the folder that holds LEMON.exe."""
    import zipfile
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > SELF_UPDATE_MAX_UNZIPPED:
            raise RuntimeError("the package is bigger than expected")
        for i in infos:
            target = os.path.realpath(os.path.join(dest, i.filename))
            if target != root and not target.startswith(root + os.sep):
                raise RuntimeError("the package has a file in a bad place")
        z.extractall(dest)
    for base in [dest] + [os.path.join(dest, d) for d in sorted(os.listdir(dest))]:
        if os.path.isfile(os.path.join(base, "LEMON.exe")) and os.path.isdir(os.path.join(base, "_internal")):
            return base
    raise RuntimeError("the package doesn't look like LEMON")


def smoke_test(exe):
    """Start the NEW LEMON.exe once, hidden, to see that it runs. None = fine, else the reason it isn't."""
    out = os.path.join(lemon_home(), "smoke.txt")
    try:
        os.remove(out)
    except OSError:
        pass
    env = dict(os.environ, LEMON_SMOKE=out, PYINSTALLER_RESET_ENVIRONMENT="1")
    p = subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    try:
        p.wait(timeout=90)
    except subprocess.TimeoutExpired:
        p.kill()
        return "the new version didn't start in time"
    try:
        with open(out, encoding="utf-8") as f:
            res = f.read()
    except OSError:
        res = ""
    return None if res.startswith("ok") else "the new version didn't start (see the LOG)"


def start_swap(new_dir):
    """Write + start the little script that waits for LEMON to close, keeps a copy of the old version in
    %LOCALAPPDATA%\\LEMON\\exe_previous, copies the new files over the app folder (restoring the old ones if that
    fails) and starts LEMON again."""
    app = os.path.dirname(sys.executable)
    prev = os.path.join(lemon_home(), "exe_previous")
    path = os.path.join(lemon_home(), "swap_update.cmd")

    def q(p):
        return p.replace("%", "%%")
    opts = "/MIR /R:10 /W:1 /NFL /NDL /NJH /NJS /NP"
    lines = ["@echo off", "chcp 65001 >nul", f'set "APP={q(app)}"', f'set "NEW={q(new_dir)}"', f'set "PREV={q(prev)}"',
             "set /a n=0", ":wait", f'tasklist /FI "PID eq {os.getpid()}" /NH 2>nul | find /I "LEMON.exe" >nul',
             "if errorlevel 1 goto go", "set /a n+=1", "if %n% GEQ 90 goto fail", "ping -n 2 127.0.0.1 >nul", "goto wait",
             ":go", f'robocopy "%APP%" "%PREV%" {opts} >nul', f'robocopy "%NEW%" "%APP%" {opts} >nul',
             f'if errorlevel 8 robocopy "%PREV%" "%APP%" {opts} >nul',
             'start "" "%APP%\\LEMON.exe"', 'rd /s /q "%NEW%" >nul 2>nul', "exit /b 0",
             ":fail", 'start "" "%APP%\\LEMON.exe"', "exit /b 1"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    subprocess.Popen(["cmd", "/c", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000200 | NO_WINDOW, close_fds=True)


# ───────────────────────── the Arcade look: palette, pixel font, sprites ─────────────────────────
# Why this is smooth: Tk repaints ONE rectangle around everything that changed in a moment.
# So the whole UI is flat rectangles + tiny cached pixel images (no smooth polygons, no gradients,
# no full-window image), screens are built once and only recoloured / nudged, and every animation
# runs on its own beat so two far-apart animations never land in the same repaint.
PAL = {  # name: (face, hard shadow)
    "yel": ("#FFD60A", "#7A5C00"),
    "lim": ("#A8E040", "#3E5410"),
    "ora": ("#FFA52E", "#6B4308"),
    "pnk": ("#FF7B8A", "#6B2D35"),
    "crm": ("#FFF09A", "#6B6538"),
    "mnt": ("#5FD6A4", "#1F5A44"),
}
C_BG, C_CARD, C_INK, C_DARK, C_PANEL = "#120F00", "#1C1700", "#0A0800", "#1A1500", "#1A1500"
C_DIM, C_FAINT, C_LINK, C_HI, C_OK, C_WHITE = "#A89A50", "#7D7340", "#C8BD7E", "#FFF6B0", "#5ADB5A", "#FFFFFF"
C_RED = "#FF7B8A"
CARD_PAL = ["yel", "lim", "ora", "pnk", "crm", "mnt", "ora", "pnk", "yel", "lim"]
SHORT_Q = ["BEST", "1080P", "720P", "480P"]

_GLYPH_SRC = {
    "A": ".XXX./X...X/X...X/XXXXX/X...X/X...X/X...X",
    "B": "XXXX./X...X/X...X/XXXX./X...X/X...X/XXXX.",
    "C": ".XXX./X...X/X..../X..../X..../X...X/.XXX.",
    "D": "XXXX./X...X/X...X/X...X/X...X/X...X/XXXX.",
    "E": "XXXXX/X..../X..../XXXX./X..../X..../XXXXX",
    "F": "XXXXX/X..../X..../XXXX./X..../X..../X....",
    "G": ".XXX./X...X/X..../X.XXX/X...X/X...X/.XXXX",
    "H": "X...X/X...X/X...X/XXXXX/X...X/X...X/X...X",
    "I": ".XXX./..X../..X../..X../..X../..X../.XXX.",
    "J": "..XXX/...X./...X./...X./...X./X..X./.XX..",
    "K": "X...X/X..X./X.X../XX.../X.X../X..X./X...X",
    "L": "X..../X..../X..../X..../X..../X..../XXXXX",
    "M": "X...X/XX.XX/X.X.X/X.X.X/X...X/X...X/X...X",
    "N": "X...X/XX..X/XX..X/X.X.X/X..XX/X..XX/X...X",
    "O": ".XXX./X...X/X...X/X...X/X...X/X...X/.XXX.",
    "P": "XXXX./X...X/X...X/XXXX./X..../X..../X....",
    "Q": ".XXX./X...X/X...X/X...X/X.X.X/X..X./.XX.X",
    "R": "XXXX./X...X/X...X/XXXX./X.X../X..X./X...X",
    "S": ".XXXX/X..../X..../.XXX./....X/....X/XXXX.",
    "T": "XXXXX/..X../..X../..X../..X../..X../..X..",
    "U": "X...X/X...X/X...X/X...X/X...X/X...X/.XXX.",
    "V": "X...X/X...X/X...X/X...X/X...X/.X.X./..X..",
    "W": "X...X/X...X/X...X/X.X.X/X.X.X/XX.XX/X...X",
    "X": "X...X/X...X/.X.X./..X../.X.X./X...X/X...X",
    "Y": "X...X/X...X/.X.X./..X../..X../..X../..X..",
    "Z": "XXXXX/....X/...X./..X../.X.../X..../XXXXX",
    "0": ".XXX./X...X/X..XX/X.X.X/XX..X/X...X/.XXX.",
    "1": "..X../.XX../..X../..X../..X../..X../.XXX.",
    "2": ".XXX./X...X/....X/...X./..X../.X.../XXXXX",
    "3": "XXXXX/...X./..X../...X./....X/X...X/.XXX.",
    "4": "...X./..XX./.X.X./X..X./XXXXX/...X./...X.",
    "5": "XXXXX/X..../XXXX./....X/....X/X...X/.XXX.",
    "6": "..XX./.X.../X..../XXXX./X...X/X...X/.XXX.",
    "7": "XXXXX/....X/...X./..X../.X.../.X.../.X...",
    "8": ".XXX./X...X/X...X/.XXX./X...X/X...X/.XXX.",
    "9": ".XXX./X...X/X...X/.XXXX/....X/...X./.XX..",
    " ": "...../...../...../...../...../...../.....",
    ".": "...../...../...../...../...../.XX../.XX..",
    ",": "...../...../...../...../.XX../..X../.X...",
    ":": "...../.XX../.XX../...../.XX../.XX../.....",
    ";": "...../.XX../.XX../...../.XX../..X../.X...",
    "!": "..X../..X../..X../..X../..X../...../..X..",
    "?": ".XXX./X...X/....X/...X./..X../...../..X..",
    "-": "...../...../...../XXXXX/...../...../.....",
    "_": "...../...../...../...../...../...../XXXXX",
    "+": "...../..X../..X../XXXXX/..X../..X../.....",
    "/": "....X/....X/...X./..X../.X.../X..../X....",
    "\\": "X..../X..../.X.../..X../...X./....X/....X",
    "(": "...X./..X../.X.../.X.../.X.../..X../...X.",
    ")": ".X.../..X../...X./...X./...X./..X../.X...",
    "[": ".XXX./.X.../.X.../.X.../.X.../.X.../.XXX.",
    "]": ".XXX./...X./...X./...X./...X./...X./.XXX.",
    "<": "...X./..X../.X.../X..../.X.../..X../...X.",
    ">": ".X.../..X../...X./....X/...X./..X../.X...",
    "'": "..X../..X../...../...../...../...../.....",
    "\"": ".X.X./.X.X./...../...../...../...../.....",
    "&": ".XX../X..X./X.X../.X.../X.X.X/X..X./.XX.X",
    "%": "XX..X/XX..X/...X./..X../.X.../X..XX/X..XX",
    "#": ".X.X./XXXXX/.X.X./.X.X./.X.X./XXXXX/.X.X.",
    "=": "...../...../XXXXX/...../XXXXX/...../.....",
    "*": "...../X.X.X/.XXX./XXXXX/.XXX./X.X.X/.....",
    "@": ".XXX./X...X/X.XXX/X.XX./X..../X...X/.XXX.",
    "~": "...../...../.XX.X/X.XX./...../...../.....",
    "|": "..X../..X../..X../..X../..X../..X../..X..",
    "^": "..X../.X.X./X...X/...../...../...../.....",
    "$": "..X../.XXXX/X.X../.XXX./..X.X/XXXX./..X..",
    "▶": "X..../XX.../XXX../XXXX./XXX../XX.../X....",   # ▶
    "◀": "....X/...XX/..XXX/.XXXX/..XXX/...XX/....X",   # ◀
    "▼": "XXXXX/XXXXX/.XXX./.XXX./..X../..X../.....",   # ▼
    "▸": "...../X..../XX.../XXX../XX.../X..../.....",   # ▸
    "·": "...../...../...../..X../...../...../.....",   # ·
    "✓": "...../....X/...XX/X.XX./.XXX./..X../.....",   # ✓
    "●": "...../.XXX./XXXXX/XXXXX/XXXXX/.XXX./.....",   # ●
    "…": "...../...../...../...../...../...../X.X.X",   # …
}
GLYPHS = {k: v.split("/") for k, v in _GLYPH_SRC.items()}

LEMON16 = [
    "...........aa...",
    "....ccccccaaa...",
    "...cccccccccc...",
    "..ccddcccccccc..",
    ".ccdccccccccccc.",
    "cccccccccccccccc",
    ".cccccccccccccb.",
    "..ccccccccccbb..",
    "...ccccccccbb...",
    ".....ccccbbb....",
]
LEMON_COL = {"a": "#5CB338", "b": "#E0A800", "c": "#FFD60A", "d": "#FFF6B0"}
ICONS = {  # (still used by the player bar: the small folder)
    "folder": (["........", "XXX.....", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "........"], {}),
}
# ----- the new pixel icons (designed in Figma: "LEMON pixel icons"); '.' = see-through -----
ICON_COL = {"Y": "#FFD60A", "F": "#FFF6B0", "S": "#FFF6B0", "a": "#5CB338", "b": "#E0A800", "K": "#7A5C00", "L": "#A8E040",
            "c": "#FFD60A", "d": "#FFF6B0", "k": "#0A0800"}
ICON_DETAIL = set("FKb")  # on a lit (ON) card these parts show the card colour, everything else is dark
_SLICE = ["YYYYYYYYYYYYYYY", "YFFFFYFFFYFFFFY", ".YFFFYFFFYFFFY.", "..YYYYYYYYYYY.."]
_GAP = ["..............."]
SETTINGS_I = _SLICE + _GAP + _SLICE + _GAP + _SLICE                      # three lemon slices
SETTINGS_I_OPEN = _SLICE + _GAP * 2 + _SLICE + _GAP * 2 + _SLICE         # the same, spread apart (mouse over)
RECENT_I = ["......ccaaa....", "......cccaaa...", ".....ccccc.....", "....ccccccc....", "...cddckcccc...", "..cdccckccccc..",
            ".ccdccckcccccc.", ".cccccckcccccc.", ".cccccckkkkccb.", ".ccccccccccccb.", ".cccccccccccbb.", "..ccccccccccb..",
            "...ccccccccb...", "....cccccbb....", ".....cccbb....."]   # a round lemon with clock hands
CARD_ICONS = {  # the four small cards on the main page (13 x 13)
    "note": [".......SSSSS.", ".......SSSSSS", ".......SS..SS", ".......SS...S", ".......SS....", ".......SS....", ".......SS....",
             "..a.YYYYSS...", ".YYYYYYYYS...", "YYFFYYYYYY...", "YYFYYYYYYY...", "YYYYYYYYbb...", ".YYYYYYbb...."],
    "cookie": ["....YYYYY....", "..YYYYYYYYY..", ".YYYKYYYYYYY.", ".YYYYYYYYKYY.", "YYYYYYYYYYY..", "YYKYYYYYYY...", "YYYYYYKYYYY..",
               "YYYYYYYYYYYY.", ".YYYKYYYYKYY.", ".YYYYYYYYYYY.", "..YYYYKYYYY..", "...YYYYYYY...", ".....YYYYY..."],
    "folder": [".............", ".YYYYY.......", "YYYYYYYYYYYY.", "YYYYYYYYYYYY.", "YYYYYYYYYYYYY", "YYYFFFFFFFYYY", "YYYFFFYFFFYYY",
               "YYYYFFFFFYYYY", "YYYYYFFFYYYYY", "YYYYYYYYYYYYY", "YYYYYYYYYYYYY", "YYYYYYYYYYYYY", ".YYYYYYYYYYY."],
    "open": [".......LLLLLL", ".......LLLLLL", "..........LLL", ".........LLLL", "YYYYYY..LL.LL", "YYYYYY.LL..LL", "YY....LL...LL",
             "YY...LL......", "YY..LL...YY..", "YY.......YY..", "YY.......YY..", "YYYYYYYYYYY..", "YYYYYYYYYYY.."],
}
WARN_TRI = ["......X......", ".....XXX.....", ".....XXX.....", "....XX.XX....", "....XX.XX....", "...XXX.XXX...", "...XXX.XXX...",
            "..XXXXXXXXX..", "..XXXX.XXXX..", ".XXXXXXXXXXX.", "XXXXXXXXXXXXX"]  # the warning triangle
CHECK4 = ["...X", "...X", "X.X.", ".X.."]


def tail(s, n):
    return s if len(s) <= n else "..." + s[-(n - 3):]


class Pix:
    """Pixel-font text and sprites, rendered once into small PhotoImages and cached.
    (The cache keeps every image alive - canvas items only hold the image *name*.)"""

    def __init__(self):
        self.cache = {}

    @staticmethod
    def can(s):
        return all(c.upper() in GLYPHS for c in s)

    @staticmethod
    def width(s, z, gap=1):
        return (len(s) * 5 + max(0, len(s) - 1) * gap) * z

    def text(self, s, color, z, shadow=(), under=False, gap=1):
        key = ("t", s, color, z, shadow, under, gap)
        img = self.cache.get(key)
        if img is not None:
            return img
        s = s.upper()
        n = len(s)
        cols = max(1, n * 5 + (n - 1) * gap)
        rows = 7 + (2 if under else 0)
        bits = []
        for r in range(7):
            line = []
            for i, ch in enumerate(s):
                line.append(GLYPHS[ch][r])
                if i < n - 1:
                    line.append("." * gap)
            bits.append("".join(line))
        if under:
            bits += ["." * cols, "X" * cols]
        sx = max((d[0] for d in shadow), default=0)
        sy = max((d[1] for d in shadow), default=0)
        img = tk.PhotoImage(width=cols * z + sx, height=rows * z + sy)
        for dx, dy, col in list(reversed(shadow)) + [(0, 0, color)]:
            for r, line in enumerate(bits):
                for m in re.finditer(r"X+", line):
                    img.put(col, to=(m.start() * z + dx, r * z + dy, m.end() * z + dx, (r + 1) * z + dy))
        self.cache[key] = img
        return img

    def sprite(self, rows, colors, z, flip=False, holes=()):
        """rows: equal-length strings, '.' = transparent; colors: char -> '#rrggbb'.
        holes: {(x, y)} cells painted with colors['h'] instead."""
        key = ("s", tuple(rows), tuple(sorted(colors.items())), z, flip, tuple(sorted(holes)))
        img = self.cache.get(key)
        if img is not None:
            return img
        w, h = len(rows[0]), len(rows)
        img = tk.PhotoImage(width=w * z, height=h * z)
        for y, line in enumerate(rows):
            cells = [None if ch == "." else (colors["h"] if (x, y) in holes else colors[ch])
                     for x, ch in enumerate(line)]
            if flip:
                cells.reverse()
            x = 0
            while x < w:
                col = cells[x]
                x2 = x + 1
                while x2 < w and cells[x2] == col:
                    x2 += 1
                if col:
                    img.put(col, to=(x * z, y * z, x2 * z, (y + 1) * z))
                x = x2
        self.cache[key] = img
        return img


def hmix(a, b, t):
    """Mix two '#rrggbb' colours."""
    ca = tuple(int(a[i:i + 2], 16) for i in (1, 3, 5))
    cb = tuple(int(b[i:i + 2], 16) for i in (1, 3, 5))
    return hexc(mix(ca, cb, t))


# ───────────────────────── the app window ─────────────────────────
U = 1.0  # UI scale (set from the display DPI / window size)


def u(v):
    return int(round(v * U))


class App:
    W, H = 960, 720

    def __init__(self, root):
        global U
        self.root = root
        try:
            dpi_scale = root.winfo_fpixels("1i") / 96.0
        except Exception:  # noqa: BLE001
            dpi_scale = 1.0
        # never let the window be bigger than the screen (small laptops, big scaling); the 110 px
        # is the title bar + taskbar, so the bottom of the UI never hides behind the taskbar
        fit = min((root.winfo_screenheight() - 110) / self.H, root.winfo_screenwidth() * 0.96 / self.W)
        U = max(0.7, min(2.5, dpi_scale, fit))
        root.title("LEMON")
        root.configure(bg=C_BG)
        self.w, self.h = u(self.W), u(self.H)
        root.minsize(int(self.W * 0.7), int(self.H * 0.7))  # resizable: the UI rescales to fit
        x = max(0, (root.winfo_screenwidth() - self.w) // 2)
        y = max(0, min((root.winfo_screenheight() - self.h) // 3, root.winfo_screenheight() - self.h - 100))
        root.geometry(f"{self.w}x{self.h}+{x}+{y}")
        icon_set = False
        if IS_WIN:  # a real .ico gives the crispest title-bar, Alt-Tab and taskbar icon
            ico = ensure_icon()
            if ico:
                try:
                    root.iconbitmap(default=ico)
                    icon_set = True
                except tk.TclError:
                    pass
        if not icon_set:
            try:
                root.iconphoto(True, tk.PhotoImage(
                    data=base64.b64encode(png_bytes(lemon_pixels(64, 64)))))
            except Exception:  # noqa: BLE001
                pass

        self.dark_titlebar()
        if IS_WIN:
            try:
                set_taskbar_identity(root)
                sync_installed_copy()
                tag_shortcuts()
            except Exception:  # noqa: BLE001  ponytail: cosmetic only, never block startup
                pass

        self.cv = tk.Canvas(root, width=self.w, height=self.h, bg=C_BG, highlightthickness=0)
        self.cv.pack(expand=True)  # 4:3 stage centered in the window (side bars when it's wider)
        self.pix = Pix()
        self.fonts = {}  # tk fonts for the text the pixel font can't draw
        self.settings = load_settings()
        global LANG
        LANG = self.settings["lang"]
        if IS_WIN and self.settings["autostart"]:  # keep the start-up entry pointing at this exe (moved / updated folder)
            try:
                set_autostart(True)
            except Exception:  # noqa: BLE001  ponytail: never block startup
                LOG.warning("couldn't refresh the start-with-Windows entry")
        self.msg, self.msg_color, self.last_path = "", YELLOW, None
        self.busy = False
        self.in_settings = False
        self.update_info = None
        self.start_btn = None  # the START button (it pulses once a link is pasted)
        self._auto_checked, self._auto_res = False, None  # the quiet once-per-launch "is there a newer version?" check
        self.job = None
        self.placeholder = self.placeholder_text()
        self.screen, self.frame_pal = "boot", None
        self.hits, self.hot, self.hand, self.mouse = [], None, False, (-1, -1)
        self.cards, self.pressing = {}, False
        self.beat, self.gen, self._n, self._rs = 0, 0, 0, None
        self.toast_on, self.toast_until, self.toast_pending, self.toast_id = False, 0.0, False, 0
        self.warn_name, self.warn_hits = "", []  # the browser the orange cookies warning is about, and its button's click areas
        self.clip_seen, self.ytv, self.bob, self.flash = "", "...", False, False
        self.done_job = None
        self.vlc, self.vlc_tried, self.prev, self.prev_path, self.dragging = None, False, None, None, None

        self.entry = tk.Entry(root, font=("Consolas", -u(16), "bold"), bg=C_INK, fg=C_DIM,
                              insertbackground=PAL["yel"][0], insertwidth=max(2, u(3)), relief="flat",
                              highlightthickness=0, bd=0)
        self.entry.insert(0, self.placeholder)
        self.entry_active = False
        self.entry.bind("<FocusIn>", self._entry_focus_in)
        self.entry.bind("<FocusOut>", self._entry_focus_out)
        self.entry.bind("<Return>", lambda e: self.start_download())
        self.entry.bind("<KeyRelease>", lambda e: self.link_changed())
        self.entry_win = self.cv.create_window(0, 0, window=self.entry, anchor="w", state="hidden")
        self.pframe = tk.Frame(root, bg="black", bd=0, highlightthickness=0)  # VLC draws the preview video in here
        self.fsbtn = tk.Canvas(root, bg=C_INK, bd=0, highlightthickness=0, cursor="hand2")  # fullscreen button ON the video
        self.fsbar = tk.Canvas(root, bg=C_INK, bd=0, highlightthickness=0, cursor="hand2")  # the fullscreen control bar
        self.fpix = Pix()  # images for those two widgets: never cleared, so they can't vanish
        self.pn, self.pfs, self.fs_hits, self.fs_h, self.fs_scale = None, False, [], 0, 1.0
        self.fs_shown, self.fs_last = False, 0.0
        self.audio = False
        self.pc_hidden, self.pc_last = False, 0.0  # (kept: hit_at looks at pc_hidden; the boxed player's bar is its own widget)
        self.box_shown, self.box_last, self._box_ptr, self.box_rect, self.box_bar_h, self.box_place = \
            False, 0.0, None, (0, 0, 0, 0), 0, (0, 0, 0, 0)
        self.done_recent = False  # the done screen was opened from the Recent list (Esc goes back there)
        self._fs_ptr, self._fs_t0 = None, 0.0  # fullscreen safety net: last mouse position, and when fullscreen started
        self.plain_job = None  # the job whose video was closed with the fullscreen exit button: its done screen has no player
        self.resumed = 0
        self.upd = None  # state of the updating screen
        self.probes, self.probe_key, self.probe_after, self._probe_res = {}, None, None, None  # 'info before download'

        self.cv.bind("<Motion>", self.on_motion)
        self.cv.bind("<Leave>", self.on_leave)
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<B1-Motion>", lambda e: self.dragging and self.dragging(e.x))
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.pframe.bind("<Button-1>", lambda e: self.prev and self.prev.toggle())  # click the video = play/pause
        self.pframe.bind("<Double-Button-1>", lambda e: self.toggle_fs())
        self.pframe.bind("<Motion>", lambda e: (self.fs_wake(), self.pc_wake()))
        self.fsbtn.bind("<Button-1>", lambda e: self.enter_fs())
        self.fsbar.bind("<Button-1>", self.fs_click)
        self.fsbar.bind("<B1-Motion>", lambda e: self.dragging and self.dragging(e.x))
        self.fsbar.bind("<ButtonRelease-1>", self.on_release)
        self.fsbar.bind("<Motion>", lambda e: self.fs_wake())
        root.bind("<Configure>", self.on_resize)
        root.bind("<Key>", self.on_key)
        root.bind("<Return>", lambda e: self.on_return())
        root.bind("<F11>", lambda e: self.toggle_fs() if self.screen == "done" and self.prev else
                  root.attributes("-fullscreen", not root.attributes("-fullscreen")))
        root.bind("<Escape>", lambda e: self.on_escape())
        root.bind("<Control-l>", lambda e: self.entry.focus_set() if self.screen == "main" else None)
        root.protocol("WM_DELETE_WINDOW", self.on_x)
        self.tray = None

        self.draw_frame("yel")
        self.show_boot()
        root.update_idletasks()
        root.after(50, self.master_tick)
        root.after(2000, self.watch_clipboard)

    @staticmethod
    def placeholder_text():
        return "‫ألصق الرابط (Ctrl+V)   مقطع: الرابط 1:20-2:05‬" if LANG == "ar" else "paste a link (Ctrl+V)   clip: link 1:20-2:05"

    # ═════════════ small drawing toolkit (everything is flat rectangles + cached pixel images) ═════════════
    # ═════ DRAWING HELPERS (TEXT, BOXES, FONTS) ═════
    def zf(self, size):
        return max(1, int(size * U + 0.5))

    def draw_frame(self, pal):
        self.frame_pal = pal
        face = PAL[pal][0]
        self.cv.delete("frame")
        self.cv.create_rectangle(u(12), u(12), u(948), u(708), outline=face, width=max(1, u(4)), tags="frame")
        self.cv.create_rectangle(u(18), u(18), u(942), u(702), outline="#5A4700" if pal == "yel" else "#3E5410",
                                 width=max(1, u(2)), tags="frame")
        self.cv.tag_lower("frame")

    def begin_screen(self, name, pal="yel"):
        """Throw away the old screen's items; start a fresh one."""
        self.cv.delete("scr")
        if name != "done" and self.pfs:
            self.leave_fs()
        if not self.pfs:
            self.hide_video()
        if name != "done":
            self.stop_preview()
        self.dragging = None
        if name != "main":  # a rebuilt main screen keeps the link box (and its focus) untouched
            self.cv.itemconfigure(self.entry_win, state="hidden")
        self.screen = name
        self.gen += 1
        self.hits, self.hot, self.cards, self.pressing = [], None, {}, False
        if self.hand:
            self.cv.config(cursor="")
            self.hand = False
        if len(self.pix.cache) > 700:  # nothing from the old screen is on the canvas any more
            self.pix.cache.clear()
        if pal != self.frame_pal:
            self.draw_frame(pal)

    def R(self, x1, y1, x2, y2, fill, tags=()):
        return self.cv.create_rectangle(u(x1), u(y1), u(x2), u(y2), fill=fill, outline="",
                                        tags=("scr",) + tuple(tags))

    def box(self, x1, y1, x2, y2, edge, fill, bw=4, tags=()):
        """A pixel box: an edge-coloured rectangle with the face inset on top (exact on every PC)."""
        tg = ("scr",) + tuple(tags)
        o = self.cv.create_rectangle(u(x1), u(y1), u(x2), u(y2), fill=edge, outline="", tags=tg)
        b = max(1, u(bw))
        i = self.cv.create_rectangle(u(x1) + b, u(y1) + b, u(x2) - b, u(y2) - b, fill=fill, outline="", tags=tg)
        return o, i

    def T(self, x, y, s, color, size=2, anchor="nw", tags=(), shadow=(), under=False, max_w=None, gap=1):
        """Pixel-font text at design coords. size = cell size (1 small, 2 normal, 3+ big).
        shadow = ((dx, dy, colour), ...). Characters the font lacks fall back to a normal font."""
        s = tr(s)
        z = self.zf(size)
        if max_w is not None and self.pix.can(s):
            while z > 1 and self.pix.width(s, z, gap) > max_w * U:
                z -= 1
        tg = ("scr",) + tuple(tags)
        px, py = u(x), u(y)
        if self.pix.can(s):
            sh = tuple((max(1, u(dx)), max(1, u(dy)), c) for dx, dy, c in shadow)
            if sh and anchor in ("n", "center", "s"):
                px += max(d[0] for d in sh) // 2
            img = self.pix.text(s, color, z, sh, under, gap)
            return self.cv.create_image(px, py, image=img, anchor=anchor, tags=tg)
        fam = "Tahoma" if ARABIC_RE.search(s) else "Consolas"  # (Tk shapes Arabic and orders its words right-to-left by itself)
        if fam == "Tahoma":
            s = "‫" + s + "‬"  # RLE..PDF: without it Tk puts the Arabic and the English words of one line in the wrong order
        size_px = 8 * z + 4 if fam == "Tahoma" else 7 * z + 2
        while max_w is not None and size_px > 9 and self.font(fam, size_px, under).measure(s) > max_w * U:
            size_px -= 1
        font = self.font(fam, size_px, under)
        for dx, dy, c in reversed(shadow):
            self.cv.create_text(px + max(1, u(dx)), py + max(1, u(dy)), text=s, fill=c, anchor=anchor, tags=tg, font=font)
        return self.cv.create_text(px, py, text=s, fill=color, anchor=anchor, tags=tg, font=font)

    def font(self, fam, size_px, under=False):
        key = (fam, size_px, under)
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(family=fam, size=-size_px, weight="bold", underline=under)
        return self.fonts[key]

    def S(self, x, y, img, anchor="nw", tags=()):
        return self.cv.create_image(u(x), u(y), image=img, anchor=anchor, tags=("scr",) + tuple(tags))

    def lemon(self, z, flip=False):
        return self.pix.sprite(LEMON16, LEMON_COL, z, flip)

    def plus(self, cx, cy, color, tag):
        self.R(cx - 18, cy - 6, cx + 18, cy + 6, color, tags=(tag,))
        self.R(cx - 6, cy - 18, cx + 6, cy + 18, color, tags=(tag,))

    def width_of(self, item):
        b = self.cv.bbox(item)
        return (b[2] - b[0]) / U if b else 0

    # ----- hit boxes / hover / press -----
    def add_hit(self, x1, y1, x2, y2, act, over=None, down=None, hand=True, pad=0):
        h = {"b": (u(x1 - pad), u(y1 - pad), u(x2 + pad), u(y2 + pad)),
             "act": act, "over": over, "down": down, "hand": hand}
        self.hits.append(h)
        return h

    def hit_at(self, x, y):
        for h in self.hits:
            if h.get("pc") and self.pc_hidden:  # (player controls that are hidden can't be clicked)
                continue
            b = h["b"]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                return h
        return None

    def set_hot(self, h):
        old = self.hot
        if old is h:
            return
        self.hot = h
        if old and old["over"]:
            old["over"](False)
        if h and h["over"]:
            h["over"](True)
        hand = bool(h and h["hand"])
        if hand != self.hand:
            self.cv.config(cursor="hand2" if hand else "")
            self.hand = hand

    def refresh_hover(self):
        if self.mouse[0] >= 0:
            self.set_hot(self.hit_at(*self.mouse))

    def on_motion(self, e):
        self.mouse = (e.x, e.y)
        self.pc_wake()
        if self.screen != "boot":
            self.set_hot(self.hit_at(e.x, e.y))

    def on_leave(self, _e=None):
        self.mouse = (-1, -1)
        self.set_hot(None)

    def on_click(self, e):
        if self.screen == "boot":
            return
        h = self.hit_at(e.x, e.y)
        if h and h.get("drag"):  # the seek / volume bars: act now and keep following the mouse
            self.dragging = h["drag"]
            self.dragging(e.x)
        elif h:
            self.press(h)
        else:
            self.cv.focus_set()  # clicking the background leaves the link box (so keys 1-8 work again)

    def on_release(self, _e=None):
        if self.dragging:
            self.dragging = None
            if self.settings.get("confirmed"):
                save_settings(self.settings)  # remembers the volume

    def press(self, h):
        """A quick pixel 'push' (70 ms) and then the action, so every click feels like a real key."""
        if self.pressing:
            return
        self.pressing = True
        if h["down"]:
            h["down"](True)
        gen = self.gen

        def go():
            if gen != self.gen:
                return
            self.pressing = False
            if h["down"]:
                h["down"](False)
            h["act"]()
        self.root.after(70, go)

    def lift(self, g, target):
        d = target - g["lift"]
        if d:
            self.cv.move(g["tag"], d, d)
            g["lift"] = target

    def button(self, x1, y1, x2, y2, text, act, pal="yel", filled=True, size=2, sh=5, enabled=True, tags=()):
        face, shade = PAL[pal]
        self._n += 1
        tg = f"g{self._n}"
        g = {"tag": tg, "lift": 0}
        if enabled and sh:
            self.R(x1 + sh, y1 + sh, x2 + sh, y2 + sh, shade, tags=tags)
        edge = face if enabled else "#5A5232"
        fill = face if (filled and enabled) else C_INK
        _o, inner = self.box(x1, y1, x2, y2, edge, fill, 4, tags=(tg,) + tuple(tags))
        ink = C_DARK if (filled and enabled) else (face if enabled else "#6E6540")
        self.T((x1 + x2) / 2, (y1 + y2) / 2, text, ink, size, "center", tags=(tg,) + tuple(tags),
               max_w=x2 - x1 - 24)
        if not enabled:
            return g
        hot_fill = "#FFE866" if filled else hmix(C_INK, face, 0.22)
        hit = None

        def over(on):
            self.lift(g, -u(2) if on else 0)
            self.cv.itemconfigure(inner, fill=hot_fill if on else fill)

        def down(d):
            self.lift(g, u(2) if d else (-u(2) if self.hot is hit else 0))
        hit = self.add_hit(x1, y1, x2, y2, act, over, down)
        g["inner"], g["fill"], g["hit"] = inner, fill, hit
        return g

    def textlink(self, x, y, text, act, color=C_LINK, anchor="nw", size=1, tags=()):
        text = tr(text)
        item = self.T(x, y, text, color, size, anchor, tags=tags, under=True)
        b = self.cv.bbox(item)
        can = self.pix.can(text)
        hot = self.pix.text(text, "#FFFFFF", self.zf(size), (), True) if can else None
        norm = self.pix.text(text, color, self.zf(size), (), True) if can else None

        def over(on):
            if norm is not None:
                self.cv.itemconfigure(item, image=hot if on else norm)
            else:
                self.cv.itemconfigure(item, fill="#FFFFFF" if on else color)
        self.add_hit(b[0] / U, b[1] / U, b[2] / U, b[3] / U, act, over, None, True, pad=6)
        return item

    def icon_button(self, x, y, rows, pal, act, label, rows_hover=None, size=58, tags=("main",)):
        """A small square button with a pixel icon, in the same look as the menu cards (hard shadow, coloured border).
        On mouse-over it lifts, a tiny label shows under it, and (if given) the icon swaps to rows_hover
        (the settings slices spread apart). Returns the hit box."""
        face, shade = PAL[pal]
        self._n += 1
        tg = f"g{self._n}"
        g = {"tag": tg, "lift": 0}
        self.R(x + 6, y + 6, x + size + 6, y + size + 6, shade, tags=tags)
        _o, inner = self.box(x, y, x + size, y + size, face, C_CARD, 4, tags=(tg,) + tuple(tags))
        z = self.zf(3)
        norm = self.pix.sprite(rows, ICON_COL, z)
        hov = self.pix.sprite(rows_hover or rows, ICON_COL, z)
        icon = self.S(x + size / 2, y + size / 2, norm, "center", tags=(tg,) + tuple(tags))
        tip = self.T(x + size / 2, y + size + 12, label, C_HI, 1, "n", tags=tuple(tags))
        self.cv.itemconfigure(tip, state="hidden")
        hot_fill = hmix(C_CARD, face, 0.16)
        hit = None

        def over(on):
            self.lift(g, -u(2) if on else 0)
            self.cv.itemconfigure(inner, fill=hot_fill if on else C_CARD)
            self.cv.itemconfigure(icon, image=hov if on else norm)
            self.cv.itemconfigure(tip, state="normal" if on else "hidden")

        def down(d):
            self.lift(g, u(2) if d else (-u(2) if self.hot is hit else 0))
        hit = self.add_hit(x, y, x + size, y + size + 6, act, over, down)
        return hit

    # ----- pop-in animation (like the design's steps(4)) -----
    def pop_in(self, groups):
        gen, dy = self.gen, u(7)
        for tag, delay in groups:
            self.cv.itemconfigure(tag, state="hidden")
            self.cv.move(tag, 0, 4 * dy)
            for s in range(4):
                def step(tag=tag, s=s):
                    if gen != self.gen:
                        return
                    if s == 0:
                        self.cv.itemconfigure(tag, state="normal")
                    self.cv.move(tag, 0, -dy)
                self.root.after(delay + 45 * s, step)

    # ═════════════ one timer for all the little animations ═════════════
    # ═════ THE MASTER TIMER ═════
    def master_tick(self):
        if SHOW_REQUEST.is_set():  # the user started LEMON again: show this one instead of opening a second
            SHOW_REQUEST.clear()
            self.bring_to_front()
        iconic = self.root.state() in ("iconic", "withdrawn")  # (withdrawn = hidden in the tray)
        # schedule first: an error below must never stop the loop. Minimised = 2 wake-ups a second, not 20 (least CPU)
        self.root.after(500 if iconic else 50, self.master_tick)
        if iconic and self.screen not in ("update", "busy", "boot"):  # (a download, an update and start-up must go on)
            return
        self.beat += 1
        scr = self.screen
        if scr == "boot":
            self.boot_tick(self.beat)
        elif scr == "main":
            self.main_tick(self.beat)
        elif scr == "busy":
            self.busy_tick(self.beat)
        elif scr == "done":
            self.done_tick(self.beat)
        elif scr == "update":
            self.update_tick(self.beat)

    def blink_pair(self, b, off, a_tag, b_tag):
        """Every 0.6 s: one sparkle group on, the other off."""
        if b % 12 == off:
            self.flash = not self.flash
            self.cv.itemconfigure(a_tag, state="normal" if self.flash else "hidden")
            self.cv.itemconfigure(b_tag, state="hidden" if self.flash else "normal")

    # ═════════════ boot / loading screen ═════════════
    BOOT_LABELS = ["SETTINGS", "YT-DLP", "FFMPEG", "YOUTUBE HELPERS"]

    # ═════ BOOT SCREEN ═════
    def show_boot(self):
        self.begin_screen("boot")
        z = self.zf(20)
        self.cv.create_image((self.w - 16 * z) // 2, u(78), image=self.lemon(z), anchor="nw",
                             tags=("scr", "bootlem"))
        self.plus(232, 140, C_HI, "spkA")
        self.plus(700, 196, C_HI, "spkB")
        self.cv.itemconfigure("spkB", state="hidden")
        self.T(480, 312, "LEMON", PAL["yel"][0], 9, "n", shadow=((3, 3, C_HI), (7, 7, "#7A5C00")))
        self.T(480, 396, "VIDEO DOWNLOADER", PAL["crm"][0], 2, "n", gap=2)
        self.R(236, 454, 736, 494, "#7A5C00")
        self.box(230, 448, 730, 488, PAL["yel"][0], C_INK, 4)
        bw = (480 - 15 * 4) / 16
        self.boot_blocks = [self.R(240 + k * (bw + 4), 458, 240 + k * (bw + 4) + bw, 478, "#2A2300")
                            for k in range(16)]
        self.T(34, 672, f"LEMON V{APP_VERSION}", C_FAINT, 1)
        self.T(926, 672, "FIRST START CAN TAKE A MINUTE", C_FAINT, 1, "ne")
        now = time.perf_counter()
        bt = self.boot = {"rows": [None] * 4, "shown": 0, "t_rev": now, "t0": now, "p": 0.0, "lit": 0,
                          "pct": -1, "last": now, "fin": None, "drawn": [None] * 4, "cur": False,
                          "update": None, "helpers": False, "ytv": "not installed", "last_done": now}
        self.boot_pct(0)
        threading.Thread(target=self.boot_work, args=(bt,), daemon=True).start()

    def boot_work(self, bt):
        """The real start-up checks (off the UI thread, so the window never freezes)."""
        def put(i, state, text):
            bt["rows"][i] = (state, text)
        try:
            put(0, "ok", "SETTINGS LOADED" if self.settings["confirmed"] else "FIRST RUN - NEW SETTINGS")
            try:
                bt["ytv"] = ytdlp_version()
                if bt["ytv"] == "not installed":
                    put(1, "warn", "YT-DLP NOT INSTALLED YET")
                else:
                    put(1, "ok", f"YT-DLP {bt['ytv']} READY")
            except Exception:  # noqa: BLE001
                put(1, "warn", "YT-DLP CHECK FAILED")
            try:
                put(2, *(("ok", "FFMPEG FOUND") if find_ffmpeg() else ("warn", "FFMPEG NOT FOUND YET")))
            except Exception:  # noqa: BLE001
                put(2, "warn", "FFMPEG CHECK FAILED")
            try:
                yt_ok = youtube_ready()
                bt["helpers"] = importlib.util.find_spec("yt_dlp") is not None and yt_ok
                put(3, *(("ok", "YOUTUBE HELPERS READY") if yt_ok else ("warn", "YOUTUBE HELPERS NEED SETUP")))
            except Exception:  # noqa: BLE001
                put(3, "warn", "HELPER CHECK FAILED")
        finally:
            for i in range(4):
                if bt["rows"][i] is None:
                    bt["rows"][i] = ("warn", "SKIPPED")

    def boot_pct(self, pct):
        self.cv.delete("bpct")
        self.T(480, 508, f"LOADING... {pct}%", C_WHITE, 2, "n", tags=("bpct",))

    def boot_row(self, i, state, text):
        self.cv.delete(f"row{i}")
        col = {"ok": C_OK, "warn": PAL["ora"][0], "pend": PAL["yel"][0]}[state]
        mark = {"ok": "[OK] ", "warn": "[!!] ", "pend": "[..] "}[state]
        self.T(300, 556 + 24 * i, mark + tr(text), col, 1, "nw", tags=(f"row{i}",))

    def boot_tick(self, b):
        bt = self.boot
        now = time.perf_counter()
        if self.quick_start() and all(r is not None for r in bt["rows"]):  # tray mode: no show, straight to the main screen
            self.finish_boot()
            return
        dt, bt["last"] = min(0.2, now - bt["last"]), now
        if b % 12 == 0:
            self.bob = not self.bob
            self.cv.move("bootlem", 0, -u(5) if self.bob else u(5))
        self.blink_pair(b, 6, "spkA", "spkB")
        n = bt["shown"]
        if n < 4 and (bt["rows"][n] is not None and now - bt["t_rev"] >= 0.32 or now - bt["t0"] > 14):
            if bt["rows"][n] is None:
                bt["rows"][n] = ("warn", "TIMED OUT")
            bt["shown"] = n = n + 1
            bt["t_rev"] = bt["last_done"] = now
        if b % 4 == 1:  # rows + cursor
            cur = (b // 10) % 2 == 0
            for i in range(min(4, n + 1)):
                want = ("done", bt["rows"][i]) if i < n else ("pend", cur)
                if bt["drawn"][i] != want:
                    bt["drawn"][i] = want
                    if i < n:
                        self.boot_row(i, *bt["rows"][i])
                    else:
                        self.boot_row(i, "pend", "CHECKING " + self.BOOT_LABELS[i] + ("_" if cur else " "))
        if b % 4 == 3:  # bar
            tgt = 1.0 if n >= 4 else min(1.0, (n + min(0.85, (now - bt["last_done"]) / 2.0)) / 4)
            bt["p"] += max(0.0, min(tgt - bt["p"], 1.0 * dt * 4))
            lit = int(bt["p"] * 16 + 0.001)
            if lit != bt["lit"]:
                for k in range(min(lit, bt["lit"]), max(lit, bt["lit"])):
                    self.cv.itemconfigure(self.boot_blocks[k], fill=PAL["yel"][0] if k < lit else "#2A2300")
                bt["lit"] = lit
            pct = int(bt["p"] * 100)
            if pct != bt["pct"]:
                bt["pct"] = pct
                self.boot_pct(pct)
        if n >= 4 and bt["p"] >= 0.995 and bt["fin"] is None:
            bt["fin"] = now
        if bt["fin"] is not None and now - bt["fin"] > 0.4:
            self.finish_boot()

    def quick_start(self):
        """With 'keep LEMON in the tray' on, the loading show is skipped: the real checks still run, then the main screen."""
        return bool(self.settings.get("tray") and self.settings.get("confirmed"))

    def finish_boot(self):
        bt = self.boot
        self.ytv = bt["ytv"]
        if not self.settings["confirmed"]:
            self.show_settings(first_run=True)  # make the user choose + confirm first
        elif not bt["helpers"]:
            self.start_setup(upgrade=False, first_run=True)
        else:
            self.show_main(intro=not self.quick_start())
            if self.settings.get("folder"):
                ensure_site_folders(self.settings["folder"])  # (for folders chosen before the per-site folders existed)
        self.auto_check_update()

    def auto_check_update(self):
        """Once per launch, quietly ask GitHub for the newest release (one request, nothing is installed).
        If it is newer than this version, the lemon shows a green NEW label; pressing it opens the release page."""
        if self._auto_checked:
            return
        self._auto_checked = True

        def work():
            try:
                self._auto_res = ("ok", release_info())
            except Exception as e:  # noqa: BLE001  (no internet / no release yet: just stay quiet)
                LOG.info("quiet version check failed: %s", e)
                self._auto_res = ("err", None)
        threading.Thread(target=work, daemon=True).start()

    # ═════════════ the main screen ═════════════
    # ═════ MAIN SCREEN (CARDS) ═════
    def menu_items(self):
        s = self.settings
        items = []
        for i, (_name, _h, label) in enumerate(QUALITIES):
            items.append({"short": SHORT_Q[i], "label": label.upper(), "bars": 4 - i,
                          "active": s["quality"] == i and not s["audio"], "action": ("quality", i)})
        items.append({"short": s["afmt"].upper(), "label": "AUDIO ONLY", "icon": "note",
                      "active": s["audio"], "action": ("audio", None)})
        items.append({"short": "COOKIES", "label": ("FROM " + s["cookies"].upper()) if s["cookies"] else "OFF",
                      "icon": "cookie", "active": bool(s["cookies"]), "action": ("cookies", None)})
        folder = s["folder"]
        items.append({"short": "FOLDER", "icon": "folder", "active": False, "action": ("folder", None),
                      "label": tail((os.path.basename(folder.rstrip("/\\")) or folder).upper(), 15)
                      if folder else "NOT SET"})
        items.append({"short": "OPEN", "label": "VIEW FILES", "icon": "open", "active": False,
                      "action": ("open", None)})
        return items

    def show_main(self, intro=False):
        self.draw_main(intro)

    def draw_card(self, i, x, y, w, h, item, big):
        face = PAL[CARD_PAL[i]][0]
        shade = PAL[CARD_PAL[i]][1]
        active = item["active"]
        gtag, ftag = f"cg{i}", f"cf{i}"
        self.R(x + 6, y + 6, x + w + 6, y + h + 6, shade, tags=(gtag, "main"))
        fill = face if active else C_CARD
        _o, inner = self.box(x, y, x + w, y + h, face, fill, 4, tags=(gtag, ftag, "main"))
        tg = (gtag, ftag, "main")
        ink = C_DARK if active else face
        self.T(x + 14, y + 12, f"[{(i + 1) % 10}]", C_DARK if active else C_DIM, 1, tags=tg)
        if big:
            self.T(x + 14, y + 36, item["short"], C_DARK if active else C_WHITE, 3, tags=tg, max_w=w - 36)
            self.T(x + 14, y + 68, item["label"], ink, 2, tags=tg, max_w=w - 36)
            for k in range(4):
                bx = x + 14 + k * 18
                col = ink if k < item["bars"] else hmix(fill, "#FFFFFF", 0.14)
                self.R(bx, y + h - 28, bx + 14, y + h - 14, col, tags=tg)
        else:
            rows = CARD_ICONS[item["icon"]]
            if active:  # lit card: the icon is cut out in dark, the small details show the card colour
                cols = {ch: (face if ch in ICON_DETAIL else C_DARK) for ch in set("".join(rows)) - {"."}}
            else:
                cols = ICON_COL
            img = self.pix.sprite(rows, cols, self.zf(3))
            self.S(x + w - 12, y + 8, img, "ne", tags=tg)
            self.T(x + 14, y + 34, item["short"], C_DARK if active else C_WHITE, 2, tags=tg, max_w=w - 36)
            self.T(x + 14, y + 58, item["label"], ink, 1, tags=tg, max_w=w - 36)
        if active:
            self.T(x + w - 12, y + h - 14, "▼ ON", C_DARK, 1, "se", tags=tg + ("blk",))
        g = {"tag": ftag, "lift": 0}
        hot_fill = hmix(face, "#FFFFFF", 0.3) if active else hmix(C_CARD, face, 0.16)
        hit = None

        def over(on):
            self.lift(g, -u(3) if on else 0)
            self.cv.itemconfigure(inner, fill=hot_fill if on else fill)

        def down(d):
            self.lift(g, u(2) if d else (-u(3) if self.hot is hit else 0))
        hit = self.add_hit(x, y, x + w, y + h + 6, lambda a=item["action"]: self.card_click(a), over, down)
        self.cards[i] = {"g": g, "hit": hit, "inner": inner, "box": (x, y, w, h), "face": face, "on": active}

    def draw_main(self, intro=False):
        self.begin_screen("main")
        s, cv = self.settings, self.cv
        self.bob = False
        # two pixel icons instead of words (designed in Figma: "LEMON pixel icons"): lemon slices and a lemon clock
        self.icon_button(34, 14, SETTINGS_I, "yel", lambda: self.show_settings(False), "SETTINGS", SETTINGS_I_OPEN)
        self.icon_button(34 + 58 + 16, 14, RECENT_I, "lim", self.show_recent, "RECENT")
        self.T(480, 58, "LEMON", PAL["yel"][0], 9, "n", tags=("main",),
               shadow=((3, 3, C_HI), (7, 7, "#7A5C00")))
        self.T(630, 64, f"V{APP_VERSION}", C_DIM, 2, "nw", tags=("main",))  # top right of the logo, above the side lemon
        z4 = self.zf(4)
        self.S(218, 82, self.lemon(z4), tags=("main", "lemL"))
        self.cv.create_image(self.w - u(218), u(82), image=self.lemon(z4, True), anchor="ne", tags=("scr", "main", "lemR"))
        if MAIN_ANIM["sparkles"]:  # two small sparkle groups take turns (main_tick)
            self.plus(150, 96, C_HI, "spA")
            self.R(176, 150, 184, 158, PAL["yel"][0], tags=("spA",))
            self.plus(800, 150, PAL["lim"][0], "spB")
            self.R(770, 190, 778, 198, C_HI, tags=("spB",))
            self.cv.itemconfigure("spA", state="hidden")
        self.T(480, 146, "INSERT LINK. GET " + (s["afmt"].upper() + "." if s["audio"] else "MP4.") + " SQUEEZE IT!", PAL["crm"][0], 2, "n", tags=("main",))
        self.T(480, 208, "▶ SELECT QUALITY ◀", C_WHITE, 2, "n", tags=("main",))

        for i, item in enumerate(self.menu_items()):
            if i < 4:
                self.draw_card(i, 60 + i * 215, 240, 195, 150, item, True)
            else:
                self.draw_card(i, 60 + (i - 4) * 215, 424, 195, 88, item, False)

        # --- link bar: LINK> [entry] PASTE START ---
        L = ("main", "lbar")
        G = 18  # extra space between the cards and the link box
        self.R(66, 552 + G, 906, 624 + G, PAL["yel"][1], tags=L)
        self.box(60, 546 + G, 900, 618 + G, PAL["yel"][0], C_INK, 4, tags=L)
        self.T(82, 582 + G, "LINK▸", PAL["yel"][0], 2, "w", tags=L)
        self.button(640, 562 + G, 752, 602 + G, "PASTE", self.paste, "crm", False, 2, 0, tags=L)
        self.start_btn = self.button(768, 562 + G, 888, 602 + G, "START", self.start_download, "yel", True, 2, 4, tags=L)
        self.add_hit(60, 546 + G, 900, 618 + G, self.entry.focus_set, None, None, False)
        cv.coords(self.entry_win, u(158), u(582 + G))
        cv.itemconfigure(self.entry_win, width=u(470), height=u(34), state="hidden" if intro else "normal")
        cv.tag_raise(self.entry_win)

        # --- update lemon (top right) ---
        zu = self.zf(6)
        lw = 16 * zu / U
        ux = 960 - 30 - lw
        U_ = ("main", "upd")
        self.S(ux, 18, self.lemon(zu), tags=U_)
        if self.update_info:
            self.T(ux + lw / 2, 18 + 10 * zu / U + 8, f"NEW V{self.update_info[0]}!".upper(), PAL["lim"][0], 1, "n",
                   tags=U_ + ("updlbl",))
        else:
            self.T(ux + lw / 2, 18 + 10 * zu / U + 8, "UPDATE", C_DIM, 1, "n", tags=U_)
        ug = {"tag": "upd", "lift": 0}
        self.add_hit(ux, 18, ux + lw, 18 + 10 * zu / U + 22, self.press_lemon,
                     lambda on: self.lift(ug, -u(3) if on else 0),
                     lambda d: self.lift(ug, u(2) if d else 0), True, pad=4)

        # --- footer ---
        folder = s["folder"]
        name = tail((os.path.basename(folder.rstrip("/\\")) or folder), 40) if folder else "NOT SET"
        self.T(34, 687, name, C_DIM, 1, tags=("main",))
        uh = self.textlink(926, 687, "UPDATE HELPERS", self.update_helpers, anchor="ne", tags=("main",))
        self.textlink(926 - self.width_of(uh) - 22, 687, "LOG", self.open_log, anchor="ne", tags=("main",))

        self.draw_info()
        self.toast_on = False
        if self.toast_pending or time.perf_counter() < self.toast_until:
            self.build_toast(animate=self.toast_pending)
        if intro:
            self.pop_in([(f"cg{i}", 60 * i) for i in range(4)] + [(f"cg{i}", 300 + 60 * (i - 4)) for i in range(4, 8)])
            gen = self.gen

            def show_bar():
                if gen == self.gen:
                    cv.itemconfigure("lbar", state="normal")
                    cv.itemconfigure(self.entry_win, state="normal")
            cv.itemconfigure("lbar", state="hidden")
            self.root.after(620, show_bar)
        self.refresh_hover()

    # ----- 'info before download': title, length, size, time, free disk space (one line under the cards) -----
    def link_key(self):
        """What the link box + the cards ask for right now, or None when there is no usable link."""
        raw, rng = split_clip(self.current_link())
        if not looks_like_url(raw):
            return None
        s = self.settings
        return (normalise_url(raw), QUALITIES[s["quality"]][1], s["audio"], s["cookies"], rng)

    def link_changed(self):
        """The link or a card changed: look the link up again once typing has stopped."""
        if self.probe_after:
            self.root.after_cancel(self.probe_after)
        self.probe_after = self.root.after(800, self.probe_start)

    def probe_start(self):
        self.probe_after = None
        key = self.probe_key = self.link_key()
        self.draw_info()
        if key is None or key in self.probes:
            return

        def work():
            try:
                res = probe_link(*key)
            except Exception as e:  # noqa: BLE001 - shown as a hint, never fatal
                res = {"error": tidy_error(e)}
            self._probe_res = (key, res)
        threading.Thread(target=work, daemon=True).start()

    def info_need(self):
        """Bytes this job may need on the disk, or None if unknown."""
        res = self.probes.get(self.probe_key) if self.probe_key else None
        if not res or not res.get("size"):
            return None
        return res["size"] * 1.2

    def draw_info(self):
        if self.screen != "main":
            return
        self.cv.delete("info")
        key, free = self.probe_key, disk_free(self.settings["folder"])
        res = self.probes.get(key) if key else None
        left = tr(f"{fmt_size(free)} FREE") if free else ""
        if key is None:
            text, color = left, C_DIM
        elif res is None:
            text, color = tr("LOOKING AT THE LINK...") + "  " + left, C_DIM
        elif res.get("error"):
            text, color = tr("CAN'T CHECK THIS LINK: " + res["error"]), PAL["ora"][0]
        else:
            parts = []
            if res["title"]:
                parts.append(clip(res["title"], 40))
            if res["secs"]:
                parts.append(fmt_time(res["secs"] * 1000))
            if res["size"]:
                parts.append("~" + fmt_size(res["size"]))
            parts.append(left)
            text, color = "  \u00b7  ".join(p for p in parts if p), C_DIM
            need = self.info_need()
            if need and free and need > free:
                text, color = tr("NOT ENOUGH DISK SPACE (NEED ~%s, %s FREE)" % (fmt_size(need), fmt_size(free))), C_RED
        self.T(480, 532, text, color, 2, "n", tags=("main", "info"), max_w=860)

    # ═════ TOASTS AND THE COOKIES WARNING ═════
    def build_toast(self, animate):
        cv = self.cv
        self.drop_toast()
        self.toast_pending = False
        if self.warn_name and self.screen == "main":
            self.build_warn(animate)
            return
        if not self.msg:
            self.toast_on = False
            return
        err = self.msg_color == RED
        fill, edge, shade = ("#FF7B8A", "#FFD0D5", "#6B2D35") if err else ("#A8E040", "#E4FFB0", "#3E5410")
        msg = tr(self.msg)
        msg = msg.upper() if self.pix.can(msg) else msg
        lines = textwrap.wrap(msg, 50)
        if len(lines) <= 2:  # normal size, one or two lines
            size, h, gap_y = 2, (44 if len(lines) <= 1 else 54), 9
        else:  # a long error: small text, two balanced lines
            size, h, gap_y = 1, 52, 9
            lines = textwrap.wrap(msg, min(96, max(60, len(msg) // 2 + 10)))[:2]
        lines = lines or [""]
        top, tg = 646, ("main", "toast")
        self.R(136, top + 6, 836, top + 6 + h, shade, tags=tg)
        self.box(130, top, 830, top + h, edge, fill, 4, tags=tg)
        mark = self.pix.sprite(CHECK4, {"X": C_DARK}, self.zf(3)) if not err else None
        if mark:
            self.S(150, top + h / 2, mark, "w", tags=tg)
        else:
            self.T(150, top + h / 2, "!", C_DARK, 2, "w", tags=tg)
        for k, ln in enumerate(lines):
            ly = top + h / 2 + (0 if len(lines) == 1 else (-gap_y if k == 0 else gap_y))
            self.T(490, ly, ln, C_DARK, size, "center", tags=tg, max_w=620)
        self.toast_on = True
        self.toast_until = time.perf_counter() + (12 if err else 7)
        self.toast_id += 1
        if animate:
            tid, gen, dy = self.toast_id, self.gen, u(11)
            cv.move("toast", 0, 4 * dy)
            for s in range(4):
                def step():
                    if tid == self.toast_id and gen == self.gen:
                        cv.move("toast", 0, -dy)
                self.root.after(45 * (s + 1), step)

    def drop_toast(self):
        """Remove the message bar (and the click areas of its button, if it has one)."""
        self.cv.delete("toast")
        if self.warn_hits:
            self.hits = [h for h in self.hits if h not in self.warn_hits]
            if self.hot in self.warn_hits:
                self.hot = None
            self.warn_hits = []

    def build_warn(self, animate):
        """The orange bar: this browser has to be closed for its cookies to work, with a button that closes it."""
        cv, name = self.cv, self.warn_name
        wt, wh, tg = 646, 54, ("main", "toast")
        face, shade = PAL["ora"]
        self.R(136, wt + 6, 836, wt + 6 + wh, shade, tags=tg)
        self.box(130, wt, 830, wt + wh, "#FFD9A0", face, 4, tags=tg)
        self.S(146, wt + wh / 2, self.pix.sprite(WARN_TRI, {"X": C_DARK}, self.zf(4)), "w", tags=tg)
        self.T(214, wt + wh / 2 - 9, f"{name.upper()} MUST BE CLOSED FOR COOKIES", C_DARK, 2, "w", tags=tg, max_w=430)
        self.T(214, wt + wh / 2 + 10, "UNSAVED TABS IN IT WILL BE LOST.", C_DARK, 1, "w", tags=tg, max_w=430)
        n0 = len(self.hits)
        self.button(658, wt + 8, 814, wt + wh - 8, f"CLOSE {name.upper()}", self.close_warned_browser, "ora", False, 2, 0, tags=tg)
        self.warn_hits = self.hits[n0:]
        self.toast_on = True
        self.toast_until = time.perf_counter() + 20
        self.toast_id += 1
        if animate:
            tid, gen, dy = self.toast_id, self.gen, u(11)
            cv.move("toast", 0, 4 * dy)
            for st in range(4):
                def step():
                    if tid == self.toast_id and gen == self.gen:
                        cv.move("toast", 0, -dy)
                self.root.after(45 * (st + 1), step)
        self.refresh_hover()

    def show_warn(self, name):
        self.set_msg("")
        self.warn_name = name
        self.build_toast(animate=True)

    def close_warned_browser(self):
        name = self.warn_name
        if not name or self.busy:
            return
        self.warn_name = ""
        if close_browser(name):
            self.say(f"{name.title()} closed. Press START when you are ready.")
        else:
            self.say(f"Couldn't close {name.title()}. Close it yourself, then press START.", RED)

    def link_ready(self):
        """Is there a valid video link in the box? (START pulses then.)"""
        try:
            raw = self.current_link()
            return bool(raw) and looks_like_url(split_clip(raw)[0])
        except Exception:  # noqa: BLE001
            return False

    def main_tick(self, b):
        if self._probe_res is not None:
            key, res = self._probe_res
            self._probe_res = None
            self.probes[key] = res
            if key == self.probe_key:
                self.draw_info()
        if self._auto_res is not None:  # the quiet start-up version check came back
            kind, found = self._auto_res
            self._auto_res = None
            if kind == "ok" and found and _vkey(found[0]) > _vkey(APP_VERSION) and not self.update_info:
                self.update_info = found
                LOG.info("newer version available: v%s", found[0])
                self.draw_main()  # the lemon now has its green NEW label
        if b % 12 == 0:  # the update lemon bobs; a NEW label blinks with it
            self.bob = not self.bob
            self.cv.move("upd", 0, -u(5) if self.bob else u(5))
            if MAIN_ANIM["side"]:  # the two lemons beside the title bob the other way
                self.cv.move("lemL", 0, u(4) if self.bob else -u(4))
                self.cv.move("lemR", 0, -u(4) if self.bob else u(4))
            if MAIN_ANIM["sparkles"]:
                self.cv.itemconfigure("spA", state="normal" if self.bob else "hidden")
                self.cv.itemconfigure("spB", state="hidden" if self.bob else "normal")
            g = self.start_btn
            if MAIN_ANIM["pulse"] and g and self.hot is not g["hit"]:  # START glows softly once a link is pasted
                self.cv.itemconfigure(g["inner"], fill="#FFF09A" if (self.bob and self.link_ready()) else g["fill"])
            if self.update_info:
                self.cv.itemconfigure("updlbl", state="normal" if self.bob else "hidden")
        elif b % 10 == 5:  # the "ON" markers blink
            self.flash = not self.flash
            self.cv.itemconfigure("blk", state="normal" if self.flash else "hidden")
        if MAIN_ANIM["glint"]:  # a light stripe crosses the selected card (0.3 s every 3 s)
            ph = b % 60
            if ph == 2:
                for i, c in self.cards.items():
                    if c["on"]:
                        x, y, _w, h = c["box"]
                        r = self.R(x + 6, y + 4, x + 16, y + h - 4, hmix(c["face"], "#FFFFFF", 0.5), tags=(f"cf{i}", "glint"))
                        self.cv.tag_raise(r, c["inner"])  # (just above the card face, under its text)
            elif 3 <= ph <= 7:
                self.cv.move("glint", u(35), 0)
            elif ph == 8:
                self.cv.delete("glint")
        if self.toast_on and time.perf_counter() > self.toast_until:
            self.drop_toast()
            self.warn_name = ""
            self.toast_on = False

    # ----- entry placeholder -----
    def _entry_focus_in(self, _e=None):
        if not self.entry_active:
            self.entry.delete(0, "end")
            self.entry.config(fg="white")
            self.entry_active = True

    def _entry_focus_out(self, _e=None):
        if not self.entry.get().strip():
            self.entry.delete(0, "end")
            self.entry.insert(0, self.placeholder)
            self.entry.config(fg=C_DIM)
            self.entry_active = False

    # ----- window resize: rebuild once the window stops changing -----
    def on_resize(self, e):
        if e.widget is self.root:
            if self._rs:
                self.root.after_cancel(self._rs)
            self._rs = self.root.after(150, self.rescale)

    def rescale(self):
        global U
        self._rs = None
        if self.busy or self.screen == "boot":  # ponytail: never rebuild mid-download, retry until it's over
            self._rs = self.root.after(500, self.rescale)
            return
        new = max(0.7, min(4.0, self.root.winfo_width() / self.W, self.root.winfo_height() / self.H))
        if abs(new - U) < 0.03:
            return
        U = new
        self.w, self.h = u(self.W), u(self.H)
        self.cv.config(width=self.w, height=self.h)
        self.cv.delete("scr")
        self.pix.cache.clear()
        self.entry.config(font=("Consolas", -u(16), "bold"), insertwidth=max(2, u(3)))
        self.draw_frame(self.frame_pal)
        if self.screen == "settings":
            self.draw_settings()
        elif self.screen == "done" and self.done_job is not None:
            self.show_done(self.done_job)
        else:
            self.draw_main()

    # ----- keyboard / clipboard -----
    def on_key(self, e):
        if self.screen == "done" and self.prev:
            self.preview_key(e)
            return
        try:
            typing = self.root.focus_get() is self.entry
        except KeyError:
            typing = False
        if self.screen == "recent" and e.char and e.char in "12345678":
            if self.rows[int(e.char) - 1:int(e.char)]:
                self.play_recent(self.rows[int(e.char) - 1])
            return
        if self.screen != "main" or typing or not e.char or e.char not in "1234567890":
            return
        c = self.cards.get((int(e.char) - 1) % 10)  # 1-9, then 0 = the tenth card
        if c:
            self.press(c["hit"])

    def on_return(self):
        if self.screen == "settings":
            self.confirm_settings()
        elif self.screen == "done" and not self.pfs:
            self.new_link()

    def on_escape(self):
        if self.screen == "settings":
            if not self.settings_first:
                self.close_settings()
        elif self.screen == "busy":
            self.cancel()
        elif self.screen == "recent":
            self.show_main()
        elif self.screen == "done":
            if self.pfs:
                self.leave_fs()
            elif self.done_recent:
                self.show_recent()
            else:
                self.new_link()

    def watch_clipboard(self):
        """If you copy a video link, drop it into the link box for you (once per copied link)."""
        try:
            if self.screen == "main" and not self.entry_active and self.root.focus_displayof() is not None:
                text = self.root.clipboard_get().strip()
                if text != self.clip_seen and looks_like_url(text):
                    self.clip_seen = text
                    self._entry_focus_in()
                    self.entry.delete(0, "end")
                    self.entry.insert(0, text)
                    self.say("Found a link in your clipboard. Press Start!")
                    self.link_changed()
        except tk.TclError:  # clipboard empty / not text
            pass
        finally:
            self.root.after(6000 if self.root.state() in ("iconic", "withdrawn") else 2000, self.watch_clipboard)  # ponytail: simple polling

    # ----- the lemon button: is there a newer version? -----
    def press_lemon(self):
        if self.busy:
            self.say("Wait for the current job to finish, then press the lemon.", RED)
            return
        if getattr(self, "_checking", False):
            return
        dev = dev_project()
        if dev:  # your own PC: rebuild from your files (like the old days), no GitHub involved
            self.dev_update(*dev)
            return
        if self.update_info and _vkey(self.update_info[0]) > _vkey(APP_VERSION):  # the start-up check already found one
            self.begin_self_update(self.update_info)
            return
        self._checking, self._ver_res = True, None
        self.say("Checking for a new version...")

        def work():
            try:
                self._ver_res = ("ok", release_info())
            except Exception as e:  # noqa: BLE001
                LOG.info("version check failed: %s", e)
                self._ver_res = ("ok", None) if getattr(e, "code", None) == 404 else ("err", None)  # 404 = no release yet
        threading.Thread(target=work, daemon=True).start()
        self.root.after(300, self._version_result)

    def _version_result(self):
        if self._ver_res is None:
            self.root.after(300, self._version_result)
            return
        self._checking = False
        kind, found = self._ver_res
        if kind == "err":
            self.say("Couldn't check for a new version (no internet?).", RED)
        elif found and _vkey(found[0]) > _vkey(APP_VERSION):
            self.update_info = found
            if self.screen == "main":
                self.draw_main()
            self.begin_self_update(found)
        else:
            self.say(f"LEMON v{APP_VERSION} is the newest.")

    def begin_self_update(self, info):
        """Download the new version's zip from GitHub, check it, and swap it in. The old version is kept."""
        ver, url = info[0], info[1]
        pkg = info[2] if len(info) > 2 else None
        if not (pkg and can_self_update()):  # a .pyw, a one-file exe, a read-only folder, or a release without a zip
            self.say(f"New version v{ver} is out! Opening the download page...")
            import webbrowser
            webbrowser.open(url)
            return
        from tkinter import messagebox
        mb = pkg["size"] / 1048576
        if not messagebox.askyesno("LEMON", f"LEMON v{ver} is ready.\n\nUpdate now? It downloads about {mb:.0f} MB, "
                                   "swaps the new files in and restarts LEMON.\nYour old version is kept as a backup.",
                                   parent=self.root, default="yes"):
            return
        self.show_update(APP_VERSION, ver, ["DOWNLOAD", "VERIFY", "SWAP", "RESTART"], after=self.close)
        up = self.upd
        up["frac"], self._upd_res = 0.0, None
        LOG.info("self-update to v%s starts (%d bytes)", ver, pkg["size"])
        threading.Thread(target=self.self_update_work, args=(pkg,), daemon=True).start()
        self.root.after(500, lambda: self.poll_self_update(up))

    def dev_update(self, proj, py):
        """Developer PC: if lemon_app_arcade.pyw changed since this exe was built, rebuild the exe from it and swap it in."""
        import hashlib
        src = os.path.join(proj, "lemon_app_arcade.pyw")
        try:
            with open(src, "rb") as f:
                data = f.read()
        except OSError as e:
            self.say("Couldn't read your lemon_app_arcade.pyw: " + clip(str(e), 60), RED)
            return
        sha = hashlib.sha256(data).hexdigest()
        try:
            with open(os.path.join(os.path.dirname(sys.executable), "built_from.txt"), encoding="utf-8") as f:
                built = f.read().strip()
        except OSError:
            built = ""
        if sha == built:
            self.say(f"LEMON v{APP_VERSION} already has your newest files.")
            return
        m = re.search(rb'^APP_VERSION = "([\d.]+)"', data, re.M)
        ver = m[1].decode() if m else APP_VERSION
        self.show_update(APP_VERSION, ver, ["CHECK", "BUILD", "SWAP", "RESTART"], after=self.close)
        up = self.upd
        up["frac"], up["dev"], self._upd_res = 0.0, True, None
        LOG.info("dev update: rebuilding the exe from %s", src)
        threading.Thread(target=self.dev_update_work, args=(proj, py, src), daemon=True).start()
        self.root.after(500, lambda: self.poll_self_update(up))

    def dev_update_work(self, proj, py, src):
        """(worker thread) build the exe into a scratch folder, then test-start it."""
        out = os.path.join(lemon_home(), "newbuild")
        try:
            shutil.rmtree(out, ignore_errors=True)
            self.update_set_step(1)
            r = subprocess.run([py, os.path.join(proj, "exe_build", "build_exe.py"), "--src", src, "--out", out], cwd=proj,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=1800)
            if r.returncode != 0:
                lines = [ln for ln in (r.stderr or r.stdout or "").splitlines() if ln.strip()]
                raise RuntimeError("the build failed: " + (lines[-1] if lines else "no details"))
            new_dir = os.path.join(out, "LEMON")
            if not os.path.isfile(os.path.join(new_dir, "LEMON.exe")):
                raise RuntimeError("the build didn't make LEMON.exe")
            bad = smoke_test(os.path.join(new_dir, "LEMON.exe"))
            if bad:
                raise RuntimeError(bad)
            self._upd_res = ("ok", new_dir)
        except Exception as e:  # noqa: BLE001
            LOG.error("dev update failed", exc_info=True)
            shutil.rmtree(out, ignore_errors=True)
            self._upd_res = ("err", str(e) or e.__class__.__name__)

    def self_update_work(self, pkg):
        """(worker thread) download, check, unzip and test-start the new version."""
        tmp = os.path.join(lemon_home(), "update")
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            zp = os.path.join(tmp, "LEMON.zip")

            def prog(done, total):
                if self.upd:
                    self.upd["frac"] = min(1.0, done / total) if total else 0.0
            download_package(pkg, zp, prog)
            self.update_set_step(1)
            new_dir = unpack_package(zp, os.path.join(tmp, "new"))
            os.remove(zp)
            bad = smoke_test(os.path.join(new_dir, "LEMON.exe"))
            if bad:
                raise RuntimeError(bad)
            self._upd_res = ("ok", new_dir)
        except Exception as e:  # noqa: BLE001
            LOG.error("self-update failed", exc_info=True)
            shutil.rmtree(tmp, ignore_errors=True)
            self._upd_res = ("err", str(e) or e.__class__.__name__)

    def poll_self_update(self, up):
        if self.upd is not up:
            return
        res = self._upd_res
        if res is None:
            if up.get("dev"):  # a build has no real percentage: the bar creeps towards the end while it works
                up["frac"] += (0.97 - up["frac"]) * 0.015
            self.root.after(500, lambda: self.poll_self_update(up))
            return
        kind, val = res
        if kind == "err":
            self.update_finish(False, "Couldn't update: " + clip(val, 70) + " Your LEMON was not changed.")
            return
        try:
            self.update_set_step(2)
            start_swap(val)
        except Exception as e:  # noqa: BLE001
            LOG.error("couldn't start the swap", exc_info=True)
            self.update_finish(False, "Couldn't update: " + clip(str(e), 70))
            return
        self.update_set_step(3)
        self.update_finish(True)  # the finale, then self.close(): the swap script takes over

    # ═════════════ recent downloads ═════════════
    # ═════ RECENT SCREEN ═════
    def show_recent(self):
        if self.busy:
            return
        self.begin_screen("recent")
        Y, YS = PAL["yel"]
        self.T(60, 40, "RECENT", Y, 4, shadow=((3, 3, C_HI), (6, 6, "#7A5C00")))
        self.T(60, 92, "CLICK ONE (OR PRESS ITS NUMBER) TO WATCH IT AGAIN", C_DIM, 1)
        self.textlink(900, 50, "[ESC] BACK", self.show_main, C_DIM, "ne")
        self.rows = self.settings["recent"][:8]
        if not self.rows:
            self.T(480, 330, "NOTHING HERE YET", C_WHITE, 3, "n")
            self.T(480, 380, "DOWNLOAD A VIDEO AND IT SHOWS UP HERE", C_DIM, 1, "n")
        for i, e in enumerate(self.rows):
            y, there = 124 + i * 62, os.path.isfile(e["path"])
            face = PAL[CARD_PAL[i % 4]][0] if there else "#5A5232"
            g = {"tag": f"row{i}", "lift": 0}
            self.R(66, y + 6, 906, y + 56, hmix(C_INK, face, 0.35), tags=())
            _o, inner = self.box(60, y, 900, y + 50, face, C_CARD, 4, tags=(g["tag"],))
            self.T(80, y + 10, f"[{i + 1}]", C_DIM, 1, tags=(g["tag"],))
            name = e["title"] or os.path.splitext(os.path.basename(e["path"]))[0]
            self.T(118, y + 10, clip(name, 56), C_WHITE if there else C_DIM, 2, tags=(g["tag"],), max_w=640)
            bits = [tr(ago(e["ts"]).upper())] if e["ts"] else []
            bits.append(os.path.splitext(e["path"])[1][1:].upper())
            if e["pos"] and there:
                bits.append(tr("RESUME AT " + fmt_time(e["pos"])))
            if not there:
                bits.append(tr("FILE MOVED OR DELETED"))
            self.T(118, y + 32, "  \u00b7  ".join(b for b in bits if b), face if there else C_RED, 1, tags=(g["tag"],))
            if there:
                self.T(884, y + 25, "WATCH\u25b8", face, 2, "e", tags=(g["tag"],))

            def over(on, g=g, inner=inner, face=face, there=there):
                self.lift(g, -u(2) if on and there else 0)
                self.cv.itemconfigure(inner, fill=hmix(C_CARD, face, 0.2) if on and there else C_CARD)
            self.add_hit(60, y, 900, y + 56, (lambda e=e: self.play_recent(e)), over, None, there)
        if self.rows:
            self.textlink(900, 660, "CLEAR LIST", self.clear_recent, C_DIM, "ne")
        self.T(34, 687, f"LEMON V{APP_VERSION}", C_FAINT, 1)
        self.refresh_hover()

    def clear_recent(self):
        self.settings["recent"] = []
        save_settings(self.settings)
        self.show_recent()

    def play_recent(self, e):
        if not os.path.isfile(e["path"]) or not is_media(e["path"]):
            return
        if not self.vlc_tried:
            self.vlc_tried, self.vlc = True, load_vlc()
        if not self.vlc:  # no preview player: hand it to Windows
            try:
                os.startfile(e["path"])
            except OSError:
                pass
            return
        self.done_recent = True
        self.show_done(types.SimpleNamespace(path=e["path"], warn="", error=None,
                                             title=e["title"]))

    # ═════════════ settings screen ═════════════
    # ═════ SETTINGS SCREEN ═════
    def show_settings(self, first_run=False):
        if self.busy:
            return
        self.in_settings, self.settings_first = True, first_run
        self.draft = {"folder": self.settings["folder"], "quality": self.settings["quality"],
                      "shortcut": IS_WIN and first_run, "autostart": self.settings["autostart"], "tray": self.settings["tray"],
                      **{k: self.settings[k] for k, _n, _d in EXTRAS}}
        self.settings_error = ""
        self.draw_settings()

    def close_settings(self):
        self.in_settings = False
        self.show_main()

    def draw_settings(self):
        self.begin_screen("settings")
        d, first = self.draft, self.settings_first
        Y, YS = PAL["yel"]
        self.T(60, 40, "SETTINGS", Y, 4, shadow=((3, 3, C_HI), (6, 6, "#7A5C00")))
        self.T(60, 92, "SET IT ONCE  ·  LEMON REMEMBERS IT EVERY TIME", C_DIM, 1)
        if not first:
            self.textlink(900, 50, "[ESC] CLOSE", self.close_settings, C_DIM, "ne")
        self.textlink(900, 70, "ENGLISH" if LANG == "ar" else "العربية", self.toggle_lang, PAL["crm"][0], "ne", 2)
        self.R(68, 120, 908, 664, YS)
        self.box(60, 112, 900, 656, Y, C_PANEL, 4)

        # 1) where to save
        folder = d["folder"]
        self.T(92, 144, "1  WHERE DO VIDEOS GO?", Y, 2)
        self.box(92, 174, 632, 226, Y if folder else C_RED, C_INK, 4)
        self.T(108, 200, tail(folder, 40) if folder else "NO FOLDER CHOSEN YET", C_WHITE if folder else C_RED,
               2, "w", max_w=506)
        self.button(648, 174, 852, 226, "BROWSE", self.browse_folder, "yel", True, 2, 5)
        self.textlink(92, 242, "OR USE SUGGESTED: " + tail(suggested_folder(), 50), self.use_suggested, PAL["crm"][0])

        # 2) default quality
        self.T(92, 292, "2  DEFAULT QUALITY", Y, 2)
        for i, (_name, _h, label) in enumerate(QUALITIES):
            x1 = 92 + i * 198
            face, shade = PAL[CARD_PAL[i]]
            sel = d["quality"] == i
            self.R(x1 + 5, 327, x1 + 187, 395, shade)
            g = {"tag": f"chip{i}", "lift": 0}
            _o, inner = self.box(x1, 322, x1 + 182, 390, face, face if sel else C_INK, 4, tags=(g["tag"],))
            self.T(x1 + 14, 336, SHORT_Q[i], C_DARK if sel else C_WHITE, 2, tags=(g["tag"],))
            self.T(x1 + 14, 362, label.upper(), C_DARK if sel else face, 1, tags=(g["tag"],))

            def over(on, g=g, inner=inner, face=face, sel=sel):
                self.lift(g, -u(2) if on else 0)
                self.cv.itemconfigure(inner, fill=(hmix(face, "#FFFFFF", 0.3) if sel else hmix(C_INK, face, 0.2))
                                      if on else (face if sel else C_INK))
            self.add_hit(x1, 322, x1 + 182, 390, lambda i=i: self.pick_quality(i), over)

        # 3) extras: what else to put into the downloaded file
        self.T(92, 412, "3  EXTRAS  (OPTIONAL)", Y, 2)
        for k, (key, name, note) in enumerate(EXTRAS):
            x1, face, shade = 92 + k * 248, PAL[("lim", "ora", "pnk")[k]][0], PAL[("lim", "ora", "pnk")[k]][1]
            on, tg = d[key], f"ext{k}"
            self.R(x1 + 5, 446 + 5, x1 + 232 + 5, 446 + 60 + 5, shade)
            _o, inner = self.box(x1, 446, x1 + 232, 506, face, face if on else C_INK, 4, tags=(tg,))
            self.T(x1 + 14, 458, name + (" \u2713" if on else ""), C_DARK if on else C_WHITE, 2, tags=(tg,), max_w=206)
            self.T(x1 + 14, 484, note, C_DARK if on else face, 1, tags=(tg,), max_w=206)
            g = {"tag": tg, "lift": 0}

            def over(o, g=g, inner=inner, face=face, on=on):
                self.lift(g, -u(2) if o else 0)
                self.cv.itemconfigure(inner, fill=(hmix(face, "#FFFFFF", 0.3) if on else hmix(C_INK, face, 0.2)) if o
                                      else (face if on else C_INK))
            self.add_hit(x1, 446, x1 + 232, 506, lambda key=key: self.toggle_extra(key), over)

        # 4) Windows options: desktop icon, start with Windows
        if IS_WIN:
            for i, (key, label, act) in enumerate((
                    ("shortcut", "PUT A LEMON ICON ON MY DESKTOP AND START MENU", self.toggle_shortcut),
                    ("autostart", "START LEMON WHEN WINDOWS STARTS", self.toggle_autostart),
                    ("tray", "KEEP LEMON RUNNING IN THE TRAY WHEN I CLOSE THE WINDOW", self.toggle_tray))):
                y, tg = 516 + i * 28, f"chk{i}"
                _o, inner = self.box(92, y, 116, y + 24, Y, C_INK, 4, tags=(tg,))
                if d[key]:
                    self.S(96, y + 4, self.pix.sprite(CHECK4, {"X": Y}, self.zf(4)), tags=(tg,))
                self.T(130, y + 12, label, C_WHITE, 2, "w", max_w=770)
                self.add_hit(92, y - 2, 800, y + 26, act, lambda on, inner=inner: self.cv.itemconfigure(
                    inner, fill=hmix(C_INK, Y, 0.25) if on else C_INK))

        # summary + confirm
        qname = QUALITIES[d["quality"]][0]
        if self.settings_error:
            lines = textwrap.wrap(self.settings_error, 90)[:2]
            for k, ln in enumerate(lines):
                self.T(480, 600 + 9 * k, ln, C_RED, 1, "n")
        elif folder:
            self.T(480, 602, f"LEMON WILL SAVE TO {tail(folder, 46)}  ·  {qname}", C_DIM, 1, "n")
        else:
            self.T(480, 602, "CHOOSE A FOLDER TO CONTINUE.", C_RED, 1, "n")
        self.button(288, 616, 672, 650, "CONFIRM & SAVE", self.confirm_settings, "yel", True, 2, 4,
                    enabled=bool(folder))
        self.T(480, 678, "YOUR CHOICES ARE STORED IN " + tail(CONFIG, 56), C_FAINT, 1, "n")
        self.T(480, 700, "ONLY DOWNLOAD VIDEOS YOU HAVE THE RIGHT TO SAVE.", C_DIM, 1, "n")
        self.T(34, 687, f"LEMON V{APP_VERSION}", C_FAINT, 1)
        self.refresh_hover()

    def browse_folder(self):
        start = self.draft["folder"] or os.path.dirname(suggested_folder())
        chosen = filedialog.askdirectory(initialdir=start if os.path.isdir(start) else None,
                                         title="Where should LEMON save your videos?")
        if chosen:
            self.draft["folder"] = os.path.normpath(chosen)
            self.settings_error = ""
            self.draw_settings()

    def use_suggested(self):
        self.draft["folder"] = suggested_folder()
        self.settings_error = ""
        self.draw_settings()

    def pick_quality(self, i):
        self.draft["quality"] = i
        self.draw_settings()

    def toggle_lang(self):
        global LANG
        LANG = self.settings["lang"] = "en" if LANG == "ar" else "ar"
        if self.settings.get("confirmed"):
            save_settings(self.settings)
        self.placeholder = self.placeholder_text()
        if not self.entry_active:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.placeholder)
        self.pix.cache.clear()
        self.draw_settings()

    def toggle_extra(self, key):
        self.draft[key] = not self.draft[key]
        self.draw_settings()

    def toggle_tray(self):
        self.draft["tray"] = not self.draft["tray"]
        self.draw_settings()

    def toggle_autostart(self):
        self.draft["autostart"] = not self.draft["autostart"]
        self.draw_settings()

    def toggle_shortcut(self):
        self.draft["shortcut"] = not self.draft["shortcut"]
        self.draw_settings()

    def confirm_settings(self):
        folder = self.draft["folder"]
        if not folder:
            return
        err = check_folder(folder)
        if err:
            self.settings_error = "LEMON can't write to that folder: " + clip(err, 70)
            self.draw_settings()
            return
        new = dict(self.settings, folder=folder, quality=self.draft["quality"], confirmed=True,
                   autostart=bool(self.draft["autostart"]) and IS_WIN, tray=bool(self.draft["tray"]) and IS_WIN,  # (lang is saved by toggle_lang)
                   **{k: self.draft[k] for k, _n, _d in EXTRAS})
        err = save_settings(new)  # writes the file AND reads it back to check
        if err:
            self.settings_error = "Couldn't save your settings: " + clip(err, 70)
            self.draw_settings()
            return
        self.settings = new
        extra = ""
        if IS_WIN:
            try:
                set_autostart(new["autostart"])
            except Exception as e:  # noqa: BLE001
                extra = "  (Couldn't change start with Windows: " + clip(str(e), 50) + ")"
        if self.draft.get("shortcut"):
            try:
                install_shortcuts()
                extra += "  LEMON icon added to your Desktop."
            except Exception as e:  # noqa: BLE001
                extra += "  (Couldn't add the Desktop icon: " + clip(str(e), 50) + ")"
        self.in_settings = False
        self.set_msg("Settings saved ✓  Videos go to " + clip(folder, 44) + "." + extra)
        if not helpers_ready():
            self.start_setup(upgrade=False, first_run=True)
        else:
            self.show_main()

    def persist(self, ok_message, warn=""):
        err = save_settings(self.settings)
        if err:
            self.set_msg("Couldn't save your settings: " + clip(err, 80), RED)
        else:
            self.set_msg(ok_message + "  ✓ saved")
        self.warn_name = warn  # (set_msg clears it) the orange "close your browser" bar replaces the green message
        if self.screen == "main":
            self.draw_main()  # the cards show the new choice
            self.link_changed()  # (size / time depend on them)

    # ═════════════ actions ═════════════
    def set_msg(self, text, color=YELLOW, path=None):
        self.msg, self.msg_color, self.last_path = text, color, path
        self.warn_name = ""
        self.toast_pending = True

    def say(self, text, color=YELLOW, path=None):
        self.set_msg(text, color, path)
        if self.screen == "main":
            self.build_toast(animate=True)

    # ═════ ACTIONS: CARDS, PASTE, START A DOWNLOAD, HELPERS ═════
    def card_click(self, action):
        if self.busy or self.screen != "main":
            return
        kind, val = action
        if kind == "quality":
            self.settings["quality"], self.settings["audio"] = val, False
            self.persist(f"Quality set to {QUALITIES[val][0]}.")
        elif kind == "audio":  # off -> MP3 -> M4A -> FLAC -> off
            st = self.settings
            if not st["audio"]:
                st["audio"], st["afmt"] = True, AUDIO_FORMATS[0]
            elif st["afmt"] != AUDIO_FORMATS[-1]:
                st["afmt"] = AUDIO_FORMATS[AUDIO_FORMATS.index(st["afmt"]) + 1]
            else:
                st["audio"], st["afmt"] = False, AUDIO_FORMATS[0]
            self.persist(({"mp3": "MP3 audio only.", "m4a": "M4A audio only (small, good quality).",
                           "flac": "FLAC audio only (big files, no quality lost beyond the source)."}[st["afmt"]])
                         if st["audio"] else "Back to MP4 video.")
        elif kind == "cookies":
            nxt = COOKIE_CHOICES[(COOKIE_CHOICES.index(self.settings["cookies"]) + 1) % len(COOKIE_CHOICES)]
            self.settings["cookies"] = nxt
            warn = nxt if nxt in LOCKED_WHILE_OPEN and browser_running(nxt) else ""
            self.persist(f"Using {nxt} login cookies." if nxt else "Cookies off.", warn)
        elif kind == "folder":
            start = self.settings["folder"]
            chosen = filedialog.askdirectory(initialdir=start if os.path.isdir(start) else None,
                                             title="Where should LEMON save your videos?")
            if chosen:
                chosen = os.path.normpath(chosen)
                err = check_folder(chosen)
                if err:
                    self.say("LEMON can't write to that folder: " + clip(err, 70), RED)
                else:
                    self.settings["folder"] = chosen
                    self.persist("Saving to " + clip(chosen, 60) + " from now on.")
        elif kind == "open":
            try:
                open_folder(self.settings["folder"])
                self.say("Opened your save folder.")
            except Exception as e:  # noqa: BLE001
                self.say(f"Couldn't open the folder: {e}", RED)

    def paste(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            self.say("Nothing to paste yet. Copy a video link first.", RED)
            return
        self._entry_focus_in()
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.entry.focus_set()
        self.link_changed()

    def current_link(self):
        return self.entry.get().strip().strip("\"'") if self.entry_active else ""

    def start_download(self):
        if self.busy or self.screen != "main":
            return
        if not self.settings["confirmed"]:
            self.show_settings(first_run=True)
            return
        raw = self.current_link()
        if not raw:
            self.say("Paste a video link first.", RED)
            return
        raw, rng = split_clip(raw)  # the box may hold  "link 1:20-2:05"  (a clip)
        if not looks_like_url(raw):
            self.say("That doesn't look like a link. Copy the video's address and paste it.", RED)
            return
        if rng and rng[1] is not None and rng[1] <= rng[0]:
            self.say("The clip's end time must be after its start time (like 1:20-2:05).", RED)
            return
        ck = self.settings["cookies"]
        if ck in LOCKED_WHILE_OPEN and browser_running(ck):  # its cookie file is locked while it is open
            self.show_warn(ck)
            return
        if not helpers_ready():
            self.say("Setting up first. One moment...", YELLOW)
            self.start_setup(upgrade=False, first_run=True)
            return
        need, free = self.info_need(), disk_free(self.settings["folder"])
        if free is not None and (free < 300 * 1048576 or (need and need > free)):
            self.say("Not enough disk space: needs about %s, only %s free. Free some space or pick another folder."
                     % (fmt_size(need or 300 * 1048576), fmt_size(free)), RED)
            return
        height = QUALITIES[self.settings["quality"]][1]
        url = normalise_url(raw)
        self.job = Download(url, os.path.join(self.settings["folder"], site_folder_name(url)), height,
                            self.settings["audio"], self.settings["cookies"], rng, dict(
                                {k: self.settings[k] for k in ("subs", "thumb", "tags")}, afmt=self.settings["afmt"]))
        self.begin_busy("download")

    def open_log(self):
        """Open the log file (in Notepad) so a problem can be read or sent to whoever is helping."""
        try:
            if not os.path.exists(log_path()):
                open(log_path(), "a", encoding="utf-8").close()
            os.startfile(log_path())
        except Exception as e:  # noqa: BLE001
            self.say("Couldn't open the log: " + clip(str(e), 70), RED)

    def update_helpers(self):
        if not self.busy:
            self.start_setup(upgrade=True, first_run=False)

    def start_setup(self, upgrade, first_run):
        if self.busy:
            return
        self.job = Setup(upgrade)
        self.first_run = first_run
        self.begin_busy("setup")

    def add_to_desktop(self):
        try:
            install_shortcuts()
            self.say("Added LEMON to your Desktop and Start menu.")
        except Exception as e:  # noqa: BLE001
            self.say(f"Couldn't add the icon: {e}", RED)

    # ═════════════ busy screen: the juice-filling pixel lemon ═════════════
    # ═════ DOWNLOADING SCREEN (THE JUICE LEMON) ═════
    def begin_busy(self, kind):
        self.busy, self.kind = True, kind
        self.shown, self.last_t = 0.0, time.perf_counter()
        self.finale_until = None
        self.cancelling = False
        self.show_busy(kind)
        self.job.start()

    def show_busy(self, kind):
        self.begin_screen("busy")
        z = self.zf(22)
        self.juice_init(z, 0.16, (self.w - 16 * z) // 2, u(92))
        self.bubbles = []
        for k, (bx, by, bs) in enumerate(((420, 230, 12), (500, 260, 8), (570, 240, 12))):
            it = self.R(bx, by, bx + bs, by + bs, C_HI, tags=("bub",))
            self.bubbles.append({"it": it, "off": 2 * k, "step": -1, "bx": bx, "by": by, "bs": bs})
        self.blit, self.bl, self.pct_shown = 0, {}, -1
        self.set_head({"download": "DOWNLOADING", "setup": "SETTING UP LEMON"}[kind])
        self.R(136, 494, 836, 534, PAL["yel"][1])
        self.box(130, 488, 830, 528, PAL["yel"][0], C_INK, 4)
        bw = (680 - 27 * 4) / 28
        self.bblocks = [self.R(140 + k * (bw + 4), 498, 140 + k * (bw + 4) + bw, 518, "#2A2300") for k in range(28)]
        self.busy_pct(0)
        if kind == "download":
            s = self.settings
            vals = [("QUALITY", "MP3" if s["audio"] else SHORT_Q[s["quality"]], "lim"),
                    ("FORMAT", "MP3" if s["audio"] else "MP4" + (" +CLIP" if self.job.clip else ""),
                     "yel"),
                    ("SAVING TO", tail((os.path.basename(s["folder"].rstrip("/\\")) or s["folder"]).upper(), 14), "crm")]
            for k, (lab, val, pal) in enumerate(vals):
                x1 = 130 + k * 240
                face, shade = PAL[pal]
                self.R(x1 + 5, 565, x1 + 225, 637, shade)
                self.box(x1, 560, x1 + 220, 632, face, C_CARD, 4)
                self.T(x1 + 14, 574, lab, C_DIM, 1)
                self.T(x1 + 14, 598, val, face, 2, max_w=190)
            self.cancel_g = self.button(390, 648, 570, 692, "[ESC] CANCEL", self.cancel, "pnk", False, 2, 4)

    def juice_init(self, z, dim_mix, lx, ly):
        """The juice-filling lemon (shared by the downloading and the updating screens): zoom z, how bright the
        empty lemon is (dim_mix), and its top-left corner in pixels."""
        lw, lh = 16 * z, 10 * z
        dim = {k: hmix(C_BG, v, dim_mix) for k, v in LEMON_COL.items()}
        foam_c = {k: hmix(v, C_HI, 0.75) for k, v in LEMON_COL.items()}
        j = self.juice = {"unf": self.pix.sprite(LEMON16, dim, z), "fil": self.lemon(z),
                          "foam": self.pix.sprite(LEMON16, foam_c, z), "w": lw, "h": lh, "y": lh,
                          "ft": max(2, z // 4), "disp": tk.PhotoImage(width=lw, height=lh)}
        self._cp(j["unf"], 0, lh)
        self.cv.create_image(lx, ly, image=j["disp"], anchor="nw", tags=("scr", "juice"))

    def _cp(self, src, y0, y1):
        j = self.juice
        y0, y1 = max(0, y0), min(j["h"], y1)
        if y1 > y0:
            j["disp"].tk.call(j["disp"].name, "copy", src.name, "-from", 0, y0, j["w"], y1, "-to", 0, y0)

    def juice_set(self, p):
        j = self.juice
        y = -j["ft"] if p >= 0.999 else int(j["h"] * (1 - p) + 0.5)
        if y == j["y"]:
            return
        lo, hi = min(y, j["y"]), max(y, j["y"]) + j["ft"]
        j["y"] = y
        self._cp(j["unf"], lo, y)
        self._cp(j["foam"], max(lo, y), min(hi, y + j["ft"]))
        self._cp(j["fil"], max(lo, y + j["ft"]), hi)

    def busy_pct(self, pct):
        self.cv.delete("bpct")
        self.T(480, 340, f"{pct}%", PAL["yel"][0], 7, "n", tags=("bpct",),
               shadow=((3, 3, C_HI), (6, 6, "#7A5C00")))

    def busy_line(self, key, y, text, color, size):
        if self.bl.get(key) == text:
            return
        self.bl[key] = text
        self.cv.delete(key)
        if text:
            self.T(480, y, text, color, size, "n", tags=(key,), max_w=800)

    def set_head(self, text):
        if self.bl.get("head") != text:
            self.bl["head"] = text
            self.cv.delete("head", "dots")
            it = self.T(480, 44, text, C_WHITE, 2, "n", tags=("head",))
            if not text.endswith("!"):
                self.T(480 + self.width_of(it) / 2 + 6, 44, "...", C_WHITE, 2, "nw", tags=("dots",))

    def cancel(self):
        if self.busy and self.kind == "download" and isinstance(self.job, Download):
            self.job.cancel.set()
            self.cancelling = True

    def busy_tick(self, b):
        if not self.busy:
            return
        now = time.perf_counter()
        dt, self.last_t = min(0.2, now - self.last_t), now
        job = self.job
        head, l1, l2 = None, "", ""
        if self.kind == "download":
            ok_done = job.done and not job.error and not self.cancelling
            failed = job.done and (job.error or self.cancelling)
            target = 1.0 if ok_done else min(max(job.frac, job.clip_progress() if job.frac == 0 else 0), 0.97)
            self.shown += (target - self.shown) * min(1.0, dt * (9 if ok_done else 5))
            if ok_done and self.shown > 0.995:
                self.shown = 1.0
            if failed:
                self.end_download()
                return
            extra = "  ·  ".join(x for x in (job.speed, job.eta) if x and not ok_done)
            if self.cancelling:
                head = "CANCELLING"
            elif self.finale_until is not None:
                head, l1, l2 = "SAVED!", "", clip(os.path.basename(job.path or ""), 50)
            else:
                head = "DOWNLOADING"
                l1 = (tr(job.phase.upper()) + ("  ·  " + ltr(extra.upper()) if extra else ""))
                l2 = clip(job.title, 60) if job.title else ""
            if ok_done and self.shown >= 1.0:
                if self.finale_until is None:
                    self.finale_until = now + 0.8
                elif now >= self.finale_until:
                    self.end_download()
                    return
        else:  # setup: slow, never-quite-finishing fill until pip is done
            first = getattr(self, "first_run", False)
            target = 1.0 if job.done and job.ok else 0.93
            self.shown += (target - self.shown) * min(1.0, dt * (9 if job.done else 0.35))
            if job.done and job.ok and self.shown > 0.995:
                self.shown = 1.0
            if job.done and not job.ok:
                self.end_setup()
                return
            head = "SETTING UP LEMON" if first else "UPDATING HELPERS"
            l1 = "FIRST TIME ONLY - INSTALLING HELPERS" if first else "GETTING THE NEWEST VERSIONS"
            if job.done and job.ok and self.shown >= 1.0:
                if self.finale_until is None:
                    self.finale_until = now + 0.7
                elif now >= self.finale_until:
                    self.end_setup()
                    return
            if self.finale_until is not None:
                head, l1 = "ALL SET!", ""
        # one kind of change per beat, so every repaint stays small
        ph = b % 3
        if ph == 0:
            self.juice_set(self.shown)
        elif ph == 1:
            pct = int(self.shown * 100)
            if pct != self.pct_shown:
                self.pct_shown = pct
                self.busy_pct(pct)
            lit = int(self.shown * 28 + 0.001)
            if lit != self.blit:
                for k in range(min(lit, self.blit), max(lit, self.blit)):
                    self.cv.itemconfigure(self.bblocks[k], fill=PAL["yel"][0] if k < lit else "#2A2300")
                self.blit = lit
        else:
            self.set_head(head)
            self.busy_line("bl1", 424, l1, C_WHITE, 2)
            self.busy_line("bl2", 452, l2, C_DIM, 1)
        for bub in self.bubbles:  # three sparkle squares rising through the lemon
            step = ((b + bub["off"]) // 6) % 5
            if step != bub["step"]:
                bub["step"] = step
                if step == 4:
                    self.cv.itemconfigure(bub["it"], state="hidden")
                else:
                    y = bub["by"] - 9 * step
                    self.cv.coords(bub["it"], u(bub["bx"]), u(y), u(bub["bx"] + bub["bs"]), u(y + bub["bs"]))
                    self.cv.itemconfigure(bub["it"], state="normal")
        if b % 10 == 5 and self.cv.find_withtag("dots"):
            self.flash = not self.flash
            self.cv.itemconfigure("dots", state="hidden" if self.flash else "normal")

    def end_download(self):
        job = self.job
        self.busy = False
        if not self.cancelling and (self.root.state() == "iconic" or self.root.focus_displayof() is None):
            ok = not job.error  # (you are in another window: tell you it's over)
            notify(self.root, "LEMON: " + ("your download is ready" if ok else "download failed"),
                   clip(getattr(job, "title", "") or os.path.basename(job.path or "") or "", 80) if ok else job.error)
        if self.cancelling:
            self.set_msg("Download cancelled.")
        elif job.error:
            self.set_msg("Couldn't download: " + job.error, RED)
        else:
            self.entry.delete(0, "end")
            self.probe_key = None
            self.entry_active = True
            self._entry_focus_out()
            self.root.focus_set()  # else the entry keeps focus, and "New link" gets no FocusIn: typing lands in the placeholder
            if job.path:
                add_recent(self.settings, job.path, getattr(job, "title", ""))
                if self.settings.get("confirmed"):
                    save_settings(self.settings)
            self.done_recent = False
            self.show_done(job)
            return
        self.show_main()

    def end_setup(self):
        job = self.job
        self.busy = False
        if job.ok:
            self.ytv = ytdlp_version()
            if getattr(self, "first_run", False):
                self.set_msg("All set! Paste a link to begin.")
            else:
                self.set_msg("Helpers updated. Restarting LEMON...")
                self.root.after(900, self.relaunch)
        else:
            self.set_msg("Setup didn't finish. Check your internet, or run:  " + DEP_HELP, RED)
        self.show_main()

    # ═════════════ the updating screen: the old grey lemon -> the new juicy lemon ═════════════
    OLD_LEMON = {"a": "#4b4b4b", "b": "#5e5e5e", "c": "#7d7d7d", "d": "#a8a8a8"}
    UPD_LINES = {"CHECK": "LOOKING FOR THE NEW VERSION", "BUILD": "BUILDING THE NEW VERSION  ·  ABOUT A MINUTE",
                 "SWAP": "SWAPPING IN THE NEW FILES", "RESTART": "RESTARTING LEMON",
                 "DOWNLOAD": "DOWNLOADING THE NEW VERSION", "VERIFY": "CHECKING THAT IT IS SAFE AND STARTS"}
    UPD_GOAL = {"CHECK": (0.10, 6.0), "BUILD": (0.88, 0.05), "SWAP": (0.96, 6.0), "RESTART": (1.0, 9.0),
                "DOWNLOAD": (0.83, 6.0), "VERIFY": (0.92, 0.25)}  # (target, rate/s)

    # ═════ UPDATING SCREEN ═════
    def show_update(self, old_ver, new_ver, steps, after):
        """Full screen while LEMON updates itself. steps = the boxes shown, e.g. ["CHECK", "SWAP", "RESTART"];
        after() is called at the end (it closes or restarts the app). Nothing here can be cancelled."""
        self.busy, self.kind = True, "update"
        now = time.perf_counter()
        up = self.upd = {"steps": steps, "step": 0, "want": 0, "tstep": now, "shown": 0.0, "last": now, "fin": False,
                         "fin_t": None, "after": after, "bl": {}, "blit": 0, "hop": 0, "pct": -1, "sec": -1,
                         "title": "", "done": False}
        self.begin_screen("update", "yel")
        Y, YS = PAL["yel"]
        L = PAL["lim"][0]
        self.cv.create_image(u(112), u(139), image=self.pix.sprite(LEMON16, self.OLD_LEMON, self.zf(9)),
                             anchor="nw", tags=("scr",))
        self.T(184, 256, "V" + old_ver, "#8c8c8c", 3, "n")
        self.T(184, 290, "NOW", "#6a6a6a", 1, "n")
        self.R(654, 102, 910, 278, YS)
        self.box(648, 96, 904, 272, Y, "#1F1A00", 4)
        self.juice_init(self.zf(13), 0.35, u(672), u(119))
        self.R(774, 82, 886, 114, "#3E5410")
        self.box(770, 78, 882, 110, "#E4FFB0", L, 3)
        self.T(826, 94, "NEW!", C_DARK, 2, "center")
        self.T(776, 288, "V" + new_ver, C_HI, 4, "n", shadow=((3, 3, YS),))
        self.R(908, 244, 932, 252, C_HI, tags=("spkA",))   # sparkles, two groups that take turns
        self.R(916, 236, 924, 260, C_HI, tags=("spkA",))
        self.R(626, 262, 638, 274, Y, tags=("spkA",))
        self.R(618, 118, 638, 126, L, tags=("spkB",))
        self.R(624, 112, 632, 132, L, tags=("spkB",))
        self.R(916, 150, 928, 162, C_HI, tags=("spkB",))
        self.cv.itemconfigure("spkB", state="hidden")
        hw = (336 - 72) / 10
        up["hops"] = [self.R(284 + k * (hw + 8), 214, 284 + k * (hw + 8) + hw, 242, "#2A2300") for k in range(10)]
        self.T(480, 368, "KEEP LEMON OPEN. IT RESTARTS BY ITSELF WHEN DONE.", C_DIM, 1, "n")
        self.R(136, 414, 836, 454, YS)
        self.box(130, 408, 830, 448, Y, C_INK, 4)
        bw = (680 - 27 * 4) / 28
        up["blocks"] = [self.R(140 + k * (bw + 4), 418, 140 + k * (bw + 4) + bw, 438, "#2A2300") for k in range(28)]
        self.T(34, 672, f"LEMON V{APP_VERSION}", C_FAINT, 1)
        self.update_title("UPDATING LEMON")
        self.update_pct(0)
        self.update_boxes()

    def update_title(self, text):
        if self.upd["title"] != text:
            self.upd["title"] = text
            self.cv.delete("utitle")
            self.T(480, 40, text, PAL["yel"][0], 4, "n", tags=("utitle",), shadow=((3, 3, C_HI), (6, 6, "#7A5C00")))

    def update_pct(self, pct):
        self.cv.delete("upct")
        self.T(452, 130, f"{pct}%", PAL["yel"][0], 7, "n", tags=("upct",), shadow=((3, 3, C_HI), (6, 6, "#7A5C00")))

    def update_line(self, text):
        if self.upd["bl"].get("l1") != text:
            self.upd["bl"]["l1"] = text
            self.cv.delete("ul1")
            self.T(480, 340, text, C_WHITE, 2, "n", tags=("ul1",), max_w=800)

    def update_boxes(self):
        """One box per step: done (lime), working (solid yellow, lifted) or waiting (grey)."""
        up = self.upd
        self.cv.delete("ustep")
        n, gap = len(up["steps"]), 20
        w = (700 - gap * (n - 1)) / n
        Y, YS = PAL["yel"]
        L = PAL["lim"][0]
        up["sec"] = int(time.perf_counter() - up["tstep"])
        for i, name in enumerate(up["steps"]):
            x1 = 130 + i * (w + gap)
            x2, cx, tg = x1 + w, x1 + w / 2, ("ustep",)
            if i < up["step"]:
                edge, fill, ink, low = L, C_INK, L, "DONE"
            elif i == up["step"]:
                self.R(x1 + 5, 505, x2 + 5, 597, YS, tags=tg)
                edge, fill, ink = Y, Y, C_DARK
                low = ((fmt_time(up["sec"] * 1000) + " SO FAR") if name == "BUILD"
                       else f"{int(up.get('frac', 0) * 100)}%" if name == "DOWNLOAD" else "WORKING")
            else:
                edge, fill, ink, low = "#5A5232", C_INK, C_FAINT, "WAITING"
            self.box(x1, 500, x2, 592, edge, fill, 4, tags=tg)
            self.T(cx, 512, f"STEP {i + 1}", ink, 1, "n", tags=tg)
            self.T(cx, 536, name, ink, 2, "n", tags=tg)
            self.T(cx, 570, low, ink, 1, "n", tags=tg)

    def update_set_step(self, i):
        """The work reached step i. (The screen shows each step for at least half a second.)"""
        if self.upd:
            self.upd["want"] = max(self.upd["want"], i)

    def update_finish(self, ok, err=""):
        up = self.upd
        if up is None:
            return
        if ok:
            up["fin"] = True
            up["want"] = len(up["steps"]) - 1  # on to RESTART, then the finale, then after()
        else:
            self.busy, self.upd = False, None
            self.set_msg(err, RED)
            self.show_main()

    def update_recover(self, up):
        if self.screen == "update" and self.upd is up:  # after() didn't close the app (e.g. relaunch failed): back to normal
            self.busy, self.upd = False, None
            self.show_main()

    def update_tick(self, b):
        up = self.upd
        if up is None or not self.busy:
            return
        now = time.perf_counter()
        dt, up["last"] = min(0.2, now - up["last"]), now
        steps = up["steps"]
        if up["step"] < up["want"] and now - up["tstep"] >= 0.5:
            up["step"] += 1
            up["tstep"] = now
            self.update_boxes()
        name = steps[up["step"]]
        goal, rate = self.UPD_GOAL[name]
        if name == "DOWNLOAD":  # real progress: the bar follows the bytes
            goal = 0.03 + 0.80 * up.get("frac", 0.0)
        up["shown"] += (goal - up["shown"]) * min(1.0, dt * rate)
        at_end = up["step"] == len(steps) - 1 and up["fin"]
        if at_end and up["shown"] > 0.995:
            up["shown"] = 1.0
            if up["fin_t"] is None:
                up["fin_t"] = now + 0.8
            elif now >= up["fin_t"] and not up["done"]:
                up["done"] = True
                self.root.after(2500, lambda: self.update_recover(up))
                up["after"]()
                return
        ph = b % 3  # one kind of change per beat, so every repaint stays small
        if ph == 0:
            self.juice_set(up["shown"])
        elif ph == 1:
            pct = int(up["shown"] * 100)
            if pct != up["pct"]:
                up["pct"] = pct
                self.update_pct(pct)
            lit = int(up["shown"] * 28 + 0.001)
            if lit != up["blit"]:
                for k in range(min(lit, up["blit"]), max(lit, up["blit"])):
                    self.cv.itemconfigure(up["blocks"][k], fill=PAL["yel"][0] if k < lit else "#2A2300")
                up["blit"] = lit
            hop = int(up["shown"] * 10 + 0.001)
            if hop != up["hop"]:
                for k in range(min(hop, up["hop"]), max(hop, up["hop"])):
                    self.cv.itemconfigure(up["hops"][k], fill=PAL["yel"][0] if k < hop else "#2A2300")
                up["hop"] = hop
        else:
            self.update_title("UPDATED!" if up["fin_t"] is not None else "UPDATING LEMON")
            self.update_line(self.UPD_LINES[name])
            if name == "BUILD" and int(now - up["tstep"]) != up["sec"]:
                self.update_boxes()  # the "0:12 SO FAR" clock
            elif name == "DOWNLOAD" and int(up.get("frac", 0) * 100) != up.get("dlpct", -1):
                up["dlpct"] = int(up.get("frac", 0) * 100)
                self.update_boxes()  # the "37%" in the step box
        self.blink_pair(b, 6, "spkA", "spkB")

    # ═════════════ the "all done" screen ═════════════
    # ═════ DONE SCREEN AND THE BOXED PLAYER ═════
    def show_done(self, job):
        self.done_job = job
        self.begin_screen("done", "lim")
        if not self.vlc_tried:
            self.vlc_tried, self.vlc = True, load_vlc()
        if job.path and self.vlc and os.path.isfile(job.path) and job is not self.plain_job:
            try:
                self.show_player(job)
                return
            except Exception:  # noqa: BLE001 - e.g. VLC refuses to start: fall back to the plain screen
                self.vlc, self.prev = None, None
                self.cv.delete("scr")
        z = self.zf(22.5)
        self.cv.create_image((self.w - 16 * z) // 2, u(58), image=self.lemon(z), anchor="nw", tags=("scr", "dlem"))
        self.plus(204, 126, C_HI, "spkA")
        self.R(760, 60, 768, 68, C_HI, tags=("spkA",))
        self.plus(722, 156, PAL["lim"][0], "spkB")
        self.R(176, 236, 184, 244, PAL["lim"][0], tags=("spkB",))
        self.cv.itemconfigure("spkB", state="hidden")
        L, LS = PAL["lim"]
        self.T(480, 312, "ALL DONE!", L, 4, "n", shadow=((3, 3, "#E4FFB0"), (6, 6, LS)))
        self.T(480, 366, "YOUR " + ("AUDIO" if self.settings["audio"] else "VIDEO") + " IS SAVED", C_WHITE, 2, "n")
        name = os.path.basename(job.path or "") or "(saved)"
        self.R(166, 416, 806, 488, LS)
        self.box(160, 410, 800, 482, L, C_CARD, 4)
        self.T(180, 424, clip(name, 44), C_WHITE, 2, max_w=600)
        folder = os.path.dirname(job.path) if job.path else self.settings["folder"]
        self.T(180, 456, tail(folder or "", 70), L, 1, max_w=600)
        self.button(120, 514, 340, 578, "OPEN FOLDER", lambda: self.done_do("folder"), "lim", False, 2, 6)
        self.button(370, 514, 590, 578, "SHOW FILE", lambda: self.done_do("file"), "crm", False, 2, 6,
                    enabled=bool(job.path))
        self.button(620, 514, 840, 578, "NEW LINK", self.new_link, "yel", True, 2, 6)
        if job.warn:  # e.g. "couldn't add the subtitles / cover picture"
            self.T(480, 596, clip("NOTE: " + job.warn, 100), PAL["ora"][0], 1, "n", max_w=800)
        self.T(480, 630, "PASTE ANOTHER LINK TO KEEP GOING", C_DIM, 1, "n", tags=("dnote",))
        if job.path and not self.vlc:
            self.T(480, 650, "WANT A PREVIEW PLAYER HERE? INSTALL VLC, THEN PRESS UPDATE HELPERS", C_DIM, 1, "n")
        self.T(34, 672, f"LEMON V{APP_VERSION}", C_FAINT, 1)
        self.refresh_hover()

    # ═════════════ the preview player (done screen): VLC draws the video, we draw the controls ═════════════
    FS_IN = ["XXX....XXX", "X........X", "X........X", "..........", "..........",
             "..........", "..........", "X........X", "X........X", "XXX....XXX"]
    FS_OUT = ["..........", ".XX....XX.", ".X......X.", "..........", "..........",
              "..........", "..........", ".X......X.", ".XX....XX.", ".........."]

    def relabel(self, lab, text):
        item, ink, z, max_w, cv, pix = lab
        while z > 1 and pix.width(text, z) > max_w:
            z -= 1
        cv.itemconfigure(item, image=pix.text(text, ink, z))

    def ctl(self, x1, x2, label, act, pal="yel", filled=False, size=2):
        """One control-row button; returns what relabel() needs to change its text later."""
        g = self.button(x1, 516, x2, 568, label, act, pal, filled, size, 4, tags=("pc",))
        return (self.cv.find_withtag(g["tag"])[-1], (C_DARK if filled else PAL[pal][0]), self.zf(size),
                (x2 - x1 - 24) * U, self.cv, self.pix)

    def raise_widget(self, w):  # (a Canvas's own .lift() raises canvas items, not the widget)
        self.root.tk.call("raise", str(w))

    def hide_video(self):
        for w in (self.pframe, self.fsbtn, self.fsbar):
            w.place_forget()

    def show_player(self, job):
        L, LS = PAL["lim"]
        first = False
        if self.prev is None:
            self.prev = Preview(self.vlc, self.pframe.winfo_id())
        if self.prev_path != job.path:  # (a window resize rebuilds this screen: don't restart the video)
            first = True
            self.prev_path = job.path
            self.prev.play(job.path, self.settings["volume"])
            self.resumed = 0 if not self.done_recent else resume_pos(self.settings, job.path)
            if self.resumed:  # carry on where you stopped last time (Preview.tick keeps seeking until VLC accepts it)
                self.prev.resume = (self.resumed, False, 1.0, 0)
        self.audio = job.path.lower().endswith((".mp3", ".m4a", ".opus", ".aac", ".wav", ".flac", ".ogg"))
        if self.pfs:  # fullscreen: the video and its bar already cover the screen, nothing else to draw
            self.place_fs()
            return
        if first and not self.audio:  # a freshly opened video starts in fullscreen; Esc / the exit logo brings you back here
            self.enter_fs()
            if self.pfs:
                return
        self.T(60, 34, "WATCHING AGAIN" if self.done_recent else "ALL DONE!", L, 3, shadow=((2, 2, "#E4FFB0"), (4, 4, LS)))
        self.T(60, 66, clip(os.path.basename(job.path), 64), C_WHITE, 2, max_w=840)
        # the box the video plays in (outer 100..860 x 92..524, video 104..856 x 96..520)
        self.R(106, 98, 866, 530, LS)
        self.box(100, 92, 860, 524, L, C_INK, 4)
        vx, vy, vw, vh = u(104), u(96), u(752), u(424)
        if self.audio:
            self.cv.create_image(u(480), u(262), image=self.lemon(self.zf(12)), tags=("scr", "dlem"))
            self.T(480, 396, "NOW PLAYING", L, 2, "n")
        else:
            self.pframe.place(in_=self.cv, x=vx, y=vy, width=vw, height=vh,
                              relx=0, rely=0, relwidth=0, relheight=0, anchor="nw")  # (place remembers old options)
            self.raise_widget(self.pframe)
        self.fsbtn.place_forget()
        self.build_box_bar(vx, vy, vw, vh)
        # under the box: the three buttons
        self.button(120, 552, 340, 608, "OPEN FOLDER", lambda: self.done_do("folder"), "lim", False, 2, 4)
        self.button(370, 552, 590, 608, "SHOW FILE", lambda: self.done_do("file"), "crm", False, 2, 4)
        self.button(620, 552, 840, 608, "NEW LINK", self.new_link, "yel", True, 2, 4)
        if job.warn:
            self.T(480, 628, clip("NOTE: " + job.warn, 100), PAL["ora"][0], 1, "n", max_w=800)
        self.draw_volume()
        self.draw_progress()
        self.refresh_hover()

    def build_box_bar(self, vx, vy, vw, vh):
        """The YouTube-style control bar that floats over the bottom of the boxed video while the mouse is on it.
        Same pieces as the fullscreen bar, smaller: progress line with the lemon, play, speaker + volume, time,
        -10 / +10, speed, and the fullscreen logo."""
        cv, pix, p = self.fsbar, self.fpix, self.prev
        bh = u(76)
        cv.delete("all")
        cv.config(width=vw, height=bh)
        self.fs_hits = []
        Y, M, O, K, L = (PAL[k][0] for k in ("yel", "mnt", "ora", "pnk", "lim"))
        TRACK = "#3A3200"
        cv.create_rectangle(0, 0, vw, bh, fill=C_INK, outline="")
        m, y0, y1 = u(16), u(26), u(26) + max(4, u(6))
        cv.create_rectangle(m, y0, vw - m, y1, fill=TRACK, outline="")
        zl = 2 if U < 1.5 else 3
        lemon = pix.sprite(LEMON16, LEMON_COL, zl)
        pn = self.pn = {"cv": cv, "pix": pix, "tz": self.zf(2), "tz2": self.zf(2), "sx": m, "sw": vw - 2 * m, "y0": y0,
                        "y1": y1, "kw": u(4), "ky0": y0 - u(4), "ky1": y1 + u(4), "box": True,
                        "last": {"frac": -1.0, "sec": -1, "len": -1, "icon": "||"}}
        pn["fill"] = cv.create_rectangle(m, y0, m, y1, fill=Y, outline="")
        pn["lemon"] = cv.create_image(m, y0, image=lemon, anchor="s")
        mid, pad = u(54), u(8)
        hy0, hy1 = mid - u(18), mid + u(18)
        self.fs_hits.append({"b": (m - 8 * zl, 0, vw - m + 8 * zl, y1 + u(10)), "drag": self.seek_x})

        def hit(x1, x2, act):
            self.fs_hits.append({"b": (x1 - pad, hy0, x2 + pad, hy1), "act": act})
        z3, z2 = self.zf(3), self.zf(2)
        pause, play = pix.sprite(self.PAUSE_I, {"X": Y}, z3), pix.sprite(self.PLAY_I, {"X": Y}, z3)
        pn["play_imgs"] = (cv.create_image(m, mid, image=pause, anchor="w"), pause, play)
        hit(m, m + pause.width(), p.toggle)
        sx = u(64)
        spk, spk_x = pix.sprite(self.SPK_I, {"X": M}, z2), pix.sprite(self.SPK_MUTE_I, {"X": K}, z2)
        pn["vol_imgs"] = (cv.create_image(sx, mid, image=spk, anchor="w"), spk, spk_x)
        hit(sx, sx + spk.width(), lambda: (p.mute(), self.draw_volume()))
        pn["vx"], pn["vw"] = u(98), u(60)
        pn["vy0"], pn["vy1"], pn["vkw"] = mid - u(3), mid + u(3), u(3)
        pn["vky0"], pn["vky1"] = mid - u(8), mid + u(8)
        cv.create_rectangle(pn["vx"], pn["vy0"], pn["vx"] + pn["vw"], pn["vy1"], fill=TRACK, outline="")
        pn["vfill"] = cv.create_rectangle(pn["vx"], pn["vy0"], pn["vx"], pn["vy1"], fill=M, outline="")
        pn["vknob"] = cv.create_rectangle(pn["vx"], pn["vky0"], pn["vx"], pn["vky1"], fill=C_WHITE, outline="")
        self.fs_hits.append({"b": (pn["vx"] - u(6), hy0, pn["vx"] + pn["vw"] + u(6), hy1), "drag": self.vol_x})
        pn["tx"], pn["tg"], pn["tb"] = u(180), u(8), mid + u(7)
        pn["t1"] = cv.create_image(pn["tx"], pn["tb"], image=pix.text("0:00", C_HI, pn["tz"]), anchor="sw")
        slash = pix.text("/", C_DIM, pn["tz2"])
        pn["slash_w"] = slash.width()
        pn["slash"] = cv.create_image(pn["tx"], pn["tb"], image=slash, anchor="sw")
        pn["t2"] = cv.create_image(pn["tx"], pn["tb"], image=pix.text("--:--", C_DIM, pn["tz2"]), anchor="sw")
        xr, gap = vw - m, u(22)

        def right(img, act):
            nonlocal xr
            item = cv.create_image(xr, mid, image=img, anchor="e")
            hit(xr - img.width(), xr, act)
            xr -= img.width() + gap
            return item
        right(pix.sprite(self.FS_IN, {"X": Y}, z2), self.enter_fs)
        item = right(pix.text(f"{p.speed:g}X", O, z2), self.change_speed)
        pn["speed"] = (item, O, z2, u(70), cv, pix)
        right(pix.text("10 \u25b6", L, z2), lambda: p.jump(10))
        right(pix.text("\u25c0 10", L, z2), lambda: p.jump(-10))
        # where it sits on the canvas, and where the mouse counts as "on the video" (window coordinates)
        self.box_rect, self.box_bar_h = (vx, vy, vx + vw, vy + vh), bh
        self.box_place = (vx, vy + vh - bh, vw, bh)
        self.box_shown, self.box_last, self._box_ptr = False, time.perf_counter(), None
        self.fsbar.place_forget()
        if self.audio or not self.prev.playing():  # (a paused video / an audio file keeps its controls up)
            self.box_show(True)

    def box_show(self, show):
        if show == self.box_shown:
            return
        self.box_shown = show
        if show:
            x, y, w, h = self.box_place
            self.fsbar.place(in_=self.cv, x=x, y=y, width=w, height=h, relx=0, rely=0, relwidth=0, relheight=0, anchor="nw")
            self.raise_widget(self.fsbar)
        else:
            self.fsbar.place_forget()

    def box_poll(self):
        """Boxed player (10 times a second): the bar shows while the mouse is on the video (or the bar), hides a couple of
        seconds after it stops moving while the video plays, and always shows while paused (and for audio)."""
        if self.pfs or self.screen != "done" or not self.pn or not self.pn.get("box") or not self.prev:
            return
        try:
            px, py = self.root.winfo_pointerxy()
        except tk.TclError:
            return
        ox, oy = self.cv.winfo_rootx(), self.cv.winfo_rooty()
        x1, y1, x2, y2 = self.box_rect
        inside = ox + x1 <= px < ox + x2 and oy + y1 <= py < oy + y2
        now = time.perf_counter()
        if inside and self._box_ptr is not None and (px, py) != self._box_ptr:
            self.box_last = now
        self._box_ptr = (px, py)
        show = (self.audio or not self.prev.playing() or self.dragging
                or (inside and now - self.box_last < 3))  # 3 s after the mouse last moved on the video, even if it rests on the bar
        self.box_show(bool(show))

    # ----- the panel that is on screen (windowed controls or the fullscreen bar): bars, times, labels -----
    def draw_progress(self, frac=None):
        p, pn = self.prev, self.pn
        if pn is None:
            return
        cv, pix, last = pn["cv"], pn["pix"], pn["last"]
        n = p.length()
        if frac is not None:  # dragging: show where the mouse is, VLC catches up
            t = int(frac * n)
        elif p.finished() and n:
            frac, t = 1.0, n
        else:
            t = p.time()
            frac = min(1.0, t / n) if n else 0.0
        if abs(frac - last["frac"]) > 0.0004:
            last["frac"] = frac
            x = pn["sx"] + pn["sw"] * frac
            cv.coords(pn["fill"], pn["sx"], pn["y0"], x, pn["y1"])
            if "lemon" in pn:  # fullscreen: a lemon rides on the end of the yellow line
                cv.coords(pn["lemon"], x, pn["y0"])
            else:
                cv.coords(pn["knob"], x - pn["kw"], pn["ky0"], x + pn["kw"], pn["ky1"])
        if t // 1000 != last["sec"]:
            last["sec"] = t // 1000
            img = pix.text(fmt_time(t), C_HI, pn["tz"])
            cv.itemconfigure(pn["t1"], image=img)
            if "slash" in pn:  # fullscreen: "/ 1:02" moves with the width of the current time
                x = pn["tx"] + img.width() + pn["tg"]
                cv.coords(pn["slash"], x, pn["tb"])
                cv.coords(pn["t2"], x + pn["slash_w"] + pn["tg"], pn["tb"])
        if n != last["len"]:
            last["len"] = n
            cv.itemconfigure(pn["t2"], image=pix.text(fmt_time(n) if n else "--:--", C_DIM, pn.get("tz2", pn["tz"])))
        icon = "||" if p.playing() else "▶"
        if icon != last["icon"]:
            last["icon"] = icon
            if "play_imgs" in pn:  # fullscreen bar: a pause / play picture
                item, pause, play = pn["play_imgs"]
                cv.itemconfigure(item, image=pause if icon == "||" else play)
            else:
                self.relabel(pn["play"], icon)

    def draw_volume(self):
        p, pn = self.prev, self.pn
        if pn is None:
            return
        v = 0 if p.muted else self.settings["volume"]
        x = pn["vx"] + pn["vw"] * v / 100
        pn["cv"].coords(pn["vfill"], pn["vx"], pn["vy0"], x, pn["vy1"])
        pn["cv"].coords(pn["vknob"], x - pn["vkw"], pn["vky0"], x + pn["vkw"], pn["vky1"])
        if "vol_imgs" in pn:  # fullscreen bar: a speaker picture (crossed out when muted)
            item, on, off = pn["vol_imgs"]
            pn["cv"].itemconfigure(item, image=off if p.muted else on)
        else:
            self.relabel(pn["vol"], "MUTE" if p.muted else "VOL")

    def preview_tick(self, b):
        if self.prev is None or self.screen != "done" or b % 5 or self.plain_job is self.done_job:  # 4 times a second
            return
        self.prev.tick()
        if not self.dragging:
            self.draw_progress()
        if self.pfs and self.fs_shown and self.prev.playing() and not self.dragging \
                and time.perf_counter() - self.fs_last > 2.5:
            self.fs_hide()  # like YouTube: the bar and the mouse hide while the video plays

    def seek_x(self, x):
        if self.prev and self.pn:
            self.prev.seek(min(max((x - self.pn["sx"]) / self.pn["sw"], 0.0), 1.0))
            self.draw_progress(min(max((x - self.pn["sx"]) / self.pn["sw"], 0.0), 1.0))

    def vol_x(self, x):
        if self.pn:
            self.set_volume((x - self.pn["vx"]) / self.pn["vw"] * 100)

    def set_volume(self, v):
        v = min(max(int(v), 0), 100)
        self.settings["volume"] = v
        self.prev.volume(v)
        if self.prev.muted and v:
            self.prev.mute()
        self.draw_volume()

    def change_speed(self):
        self.prev.faster()
        self.relabel(self.pn["speed"], f"{self.prev.speed:g}X")

    def toggle_loop(self):
        self.prev.loop = not self.prev.loop
        if self.pn and "loop" in self.pn:
            self.relabel(self.pn["loop"], "LOOP ✓" if self.prev.loop else "LOOP")

    def pc_wake(self):
        self.box_last = time.perf_counter()

    def preview_key(self, e):
        k, p = e.keysym, self.prev
        self.pc_wake()
        if self.pfs:
            self.fs_wake()
        if k == "space":
            p.toggle()
        elif k in ("Left", "j", "J"):
            p.jump(-10)
        elif k in ("Right", "l", "L"):
            p.jump(10)
        elif k in ("Up", "Down"):
            self.set_volume(self.settings["volume"] + (5 if k == "Up" else -5))
        elif k in ("m", "M"):
            p.mute()
            self.draw_volume()
        elif k == "period":
            p.step()
        elif k in ("f", "F"):
            self.toggle_fs()
        elif k in ("s", "S"):
            self.change_speed()
        elif k in ("r", "R"):
            self.toggle_loop()
        elif e.char and e.char.isdigit():
            p.seek(int(e.char) / 10)
        else:
            return
        self.draw_progress()

    # ----- real fullscreen: the same VLC window grows to the whole screen, a control bar floats over it -----
    def toggle_fs(self):
        if self.pfs:
            self.leave_fs()
        else:
            self.enter_fs()

    def enter_fs(self):
        if self.pfs or not self.prev or self.audio or self.screen != "done":
            return
        self.pfs = True
        self.fs_scale = max(0.7, self.root.winfo_screenheight() / 1080)
        self.root.attributes("-fullscreen", True)
        self.build_fs()
        self.place_fs()
        self.fs_wake()
        self.root.focus_force()
        self._fs_ptr, self._fs_t0 = None, time.perf_counter()
        self.esc_pressed()  # (clears Windows' memory of an old Esc press)
        for ms in (600, 1500, 3000):  # VLC opens its video window a moment later and can take the keyboard: take it back
            self.root.after(ms, lambda: self.pfs and self.root.focus_force())

    def esc_pressed(self):
        """Was Esc pressed since the last call? Asked straight from Windows, so it works even when the video window
        has the keyboard focus and Tk never sees the key."""
        if not IS_WIN:
            return False
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8001)
        except Exception:  # noqa: BLE001
            return False

    def fs_poll(self):
        """Fullscreen safety net (10 times a second): Windows can hand keys and mouse moves to the video window instead of
        LEMON, so a moved mouse still shows the bar (with its exit button) and Esc still leaves."""
        if not self.pfs:
            return
        try:
            pos = self.root.winfo_pointerxy()
        except tk.TclError:
            return
        if self._fs_ptr is not None and pos != self._fs_ptr:
            self.fs_wake()
        self._fs_ptr = pos
        if self.esc_pressed() and time.perf_counter() - self._fs_t0 > 0.6:
            self.leave_fs()

    def leave_fs(self):
        """Leave the fullscreen player (Esc, or the exit logo in the bar): back to the boxed video page, the video keeps
        playing in its box with the three buttons under it."""
        if not self.pfs:
            return
        self.pfs = False
        self.pn = None
        self.fsbar.place_forget()
        self.pframe.place_forget()
        self.pframe.config(cursor="")
        self.root.attributes("-fullscreen", False)
        self.dark_titlebar()  # at once (no white flash), and again once Windows has rebuilt the frame
        self.root.after(30, self.dark_titlebar)
        self.root.after(400, self.after_fullscreen)  # the window changes size: draw the boxed page once it has settled

    def dark_titlebar(self):
        """Dark title bar to match the app (Windows 10 20H1+/11; older Windows ignores it). Windows drops it when the
        window frame is rebuilt (leaving fullscreen), so this runs again then."""
        if not IS_WIN:
            return
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
            dwm(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)  # DWMWA_USE_IMMERSIVE_DARK_MODE
            col = ctypes.c_int(BG[0] | BG[1] << 8 | BG[2] << 16)
            dwm(hwnd, 35, ctypes.byref(col), 4)  # DWMWA_CAPTION_COLOR (Windows 11)
        except Exception:  # noqa: BLE001  ponytail: cosmetic only
            pass

    def after_fullscreen(self):
        """Draw the boxed video page (a window resize may already have drawn it: drawing it twice is harmless)."""
        self.dark_titlebar()
        if self.screen != "done" or self.pfs:
            return
        if self.done_job is None:
            self.show_main()
            return
        self.show_done(self.done_job)

    def refresh_player(self):
        if self.screen == "done" and self.prev and not self.pfs and self.done_job is not None:
            self.show_done(self.done_job)

    def place_fs(self):
        self.pframe.place(in_=self.root, x=0, y=0, width=0, height=0, relx=0, rely=0, relwidth=1, relheight=1,
                          anchor="nw")
        self.raise_widget(self.pframe)
        self.fsbtn.place_forget()
        if self.fs_shown:
            self.fsbar.place(in_=self.root, x=0, y=0, relx=0, rely=1.0, anchor="sw", width=0, relwidth=1,
                             height=self.fs_h, relheight=0)
            self.raise_widget(self.fsbar)

    def fs_wake(self):
        if not self.pfs:
            return
        self.fs_last = time.perf_counter()
        if not self.fs_shown:
            self.fs_shown = True
            self.pframe.config(cursor="")
            self.place_fs()

    def fs_hide(self):
        self.fs_shown = False
        self.fsbar.place_forget()
        self.pframe.config(cursor="none")

    def fs_click(self, e):
        self.fs_wake()
        for h in self.fs_hits:
            x1, y1, x2, y2 = h["b"]
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                if h.get("drag"):
                    self.dragging = h["drag"]
                    self.dragging(e.x)
                else:
                    h["act"]()
                return

    PAUSE_I = ["XXX...XXX"] * 9
    PLAY_I = ["XX.......", "XXXX.....", "XXXXXX...", "XXXXXXXX.", "XXXXXXXXX", "XXXXXXXX.", "XXXXXX...", "XXXX.....", "XX......."]
    SPK_I = ["...X......", "..XX...X..", "XXXX....X.", "XXXX.X..X.", "XXXX.X..X.", "XXXX.X..X.", "XXXX....X.", "..XX...X..", "...X......"]
    SPK_MUTE_I = ["...X......", "..XX.X...X", "XXXX..X.X.", "XXXX...X..", "XXXX..X.X.", "XXXX.X...X", "XXXX......", "..XX......", "...X......"]

    def build_fs(self):
        """The fullscreen bar (YouTube style), drawn for a 1920x1080 screen and scaled to the real one (s = 1 on 1080p).
        Left: play/pause, speaker + volume, time.  Right: -10, +10, speed, loop, folder, exit fullscreen."""
        cv, s, pix, p = self.fsbar, self.fs_scale, self.fpix, self.prev

        def F(v):  # a 1080p number -> whole pixels
            return int(v * s + 0.5)

        def zoom(v):  # a pixel-font / sprite zoom -> an integer zoom >= 1
            return max(1, int(v * s + 0.5))
        W = self.root.winfo_screenwidth()
        H = self.fs_h = F(124)
        cv.delete("all")
        cv.config(width=W, height=H)
        self.fs_hits = []
        Y, M, O, K, CR, L = (PAL[k][0] for k in ("yel", "mnt", "ora", "pnk", "crm", "lim"))
        TRACK = "#3A3200"
        cv.create_rectangle(0, 0, W, H, fill=C_INK, outline="")
        # progress line + the lemon that rides on the end of what is played
        m, y0, y1 = F(42), F(34), max(F(42), F(34) + 2)
        cv.create_rectangle(m, y0, W - m, y1, fill=TRACK, outline="")
        zl = min(max(2, zoom(3)), max(2, y0 // 10))  # the lemon is 10 cells tall: never let it poke out of the top of the bar
        lemon = pix.sprite(LEMON16, LEMON_COL, zl)
        mid = F(84)
        pn = self.pn = {"cv": cv, "pix": pix, "tz": zoom(4), "tz2": zoom(3), "sx": m, "sw": W - 2 * m, "y0": y0, "y1": y1,
                        "kw": F(4), "ky0": y0 - F(4), "ky1": y1 + F(4),
                        "last": {"frac": -1.0, "sec": -1, "len": -1, "icon": "||"}}
        pn["fill"] = cv.create_rectangle(m, y0, m, y1, fill=Y, outline="")
        pn["lemon"] = cv.create_image(m, y0, image=lemon, anchor="s")
        half = 8 * zl
        self.fs_hits.append({"b": (m - half, 0, W - m + half, y1 + F(22)), "drag": self.seek_x})
        pad, hy0, hy1 = F(14), mid - F(34), mid + F(34)

        def hit(x1, x2, act):
            self.fs_hits.append({"b": (x1 - pad, hy0, x2 + pad, hy1), "act": act})

        # left: play / pause
        z4 = zoom(4)
        pause, play = pix.sprite(self.PAUSE_I, {"X": Y}, z4), pix.sprite(self.PLAY_I, {"X": Y}, z4)
        pn["play_imgs"] = (cv.create_image(m, mid, image=pause, anchor="w"), pause, play)
        hit(m, m + pause.width(), p.toggle)
        # speaker + volume slider
        sx = F(130)
        spk, spk_x = pix.sprite(self.SPK_I, {"X": M}, z4), pix.sprite(self.SPK_MUTE_I, {"X": K}, z4)
        pn["vol_imgs"] = (cv.create_image(sx, mid, image=spk, anchor="w"), spk, spk_x)
        hit(sx, sx + spk.width(), lambda: (p.mute(), self.draw_volume()))
        pn["vx"], pn["vw"] = F(190), F(100)
        pn["vy0"], pn["vy1"], pn["vkw"] = mid - F(5), mid + F(5), F(4)
        pn["vky0"], pn["vky1"] = mid - F(11), mid + F(11)
        cv.create_rectangle(pn["vx"], pn["vy0"], pn["vx"] + pn["vw"], pn["vy1"], fill=TRACK, outline="")
        pn["vfill"] = cv.create_rectangle(pn["vx"], pn["vy0"], pn["vx"], pn["vy1"], fill=M, outline="")
        pn["vknob"] = cv.create_rectangle(pn["vx"], pn["vky0"], pn["vx"], pn["vky1"], fill=C_WHITE, outline="")
        self.fs_hits.append({"b": (pn["vx"] - F(8), hy0, pn["vx"] + pn["vw"] + F(8), hy1), "drag": self.vol_x})
        # time: "11:27" big, "/ 23:42" smaller; all three sit on one baseline (draw_progress moves the "/" and the length)
        pn["tx"], pn["tg"], pn["tb"] = F(330), F(13), mid + F(14)
        pn["t1"] = cv.create_image(pn["tx"], pn["tb"], image=pix.text("0:00", C_HI, pn["tz"]), anchor="sw")
        slash = pix.text("/", C_DIM, pn["tz2"])
        pn["slash_w"] = slash.width()
        pn["slash"] = cv.create_image(pn["tx"], pn["tb"], image=slash, anchor="sw")
        pn["t2"] = cv.create_image(pn["tx"], pn["tb"], image=pix.text("--:--", C_DIM, pn["tz2"]), anchor="sw")
        # right side, from the right: exit fullscreen, folder, loop, speed, +10, -10
        xr, gap, z3 = W - m, F(46), zoom(3)

        def right(img, act):
            nonlocal xr
            item = cv.create_image(xr, mid, image=img, anchor="e")
            hit(xr - img.width(), xr, act)
            xr -= img.width() + gap
            return item

        def right_text(label, color, act):
            item = right(pix.text(label, color, z3), act)
            return (item, color, z3, F(150), cv, pix)  # (what relabel() needs to change the text later)
        right(pix.sprite(self.FS_OUT, {"X": Y}, z4), self.leave_fs)
        rows, holes = ICONS["folder"]
        right(pix.sprite(rows, {"X": CR, "h": C_INK}, z3, holes=holes), lambda: self.done_do("folder"))
        pn["loop"] = right_text("LOOP ✓" if p.loop else "LOOP", K, self.toggle_loop)
        pn["speed"] = right_text(f"{p.speed:g}X", O, self.change_speed)
        right_text("10 ▶", L, lambda: p.jump(10))
        right_text("◀ 10", L, lambda: p.jump(-10))
        self.draw_volume()
        self.draw_progress()

    def stop_preview(self):
        if self.prev and self.prev_path:  # remember where you stopped (for the Recent list)
            remember_pos(self.settings, self.prev_path, self.prev.time(), self.prev.length())
            if self.settings.get("confirmed"):
                save_settings(self.settings)
        self.prev_path = None
        if self.prev:
            self.prev.stop()

    def done_do(self, what):
        try:
            if what == "folder":
                open_folder(self.settings["folder"])
            else:
                show_file(self.done_job.path)
        except Exception as e:  # noqa: BLE001
            self.cv.delete("dnote")
            self.T(480, 630, clip("COULDN'T OPEN IT: " + str(e), 90), C_RED, 1, "n", tags=("dnote",))

    def new_link(self):
        self.show_main()
        self.entry.focus_set()

    def done_tick(self, b):
        if b % 12 == 0:
            self.bob = not self.bob
            self.cv.move("dlem", 0, -u(5) if self.bob else u(5))
        self.blink_pair(b, 6, "spkA", "spkB")
        if b % 2 == 0:
            self.fs_poll() if self.pfs else self.box_poll()
        self.preview_tick(b)

    def relaunch(self):
        try:
            subprocess.Popen([sibling_exe("pythonw.exe"), os.path.abspath(__file__)],
                             creationflags=NO_WINDOW, env=dict(os.environ, LEMON_RESTART="1"))
        except Exception as e:  # noqa: BLE001
            self.say("Updated, but couldn't restart on its own - just open LEMON again. " + clip(str(e), 40), RED)
            return
        self.root.destroy()

    def on_x(self):
        """The window's X: hide to the tray (downloads keep going) when the setting is on, else quit."""
        if IS_WIN and self.settings.get("tray") and self.settings.get("confirmed"):
            if self.hide_to_tray():
                return
        self.close()

    def hide_to_tray(self):
        if self.tray:
            return True
        tray = Tray(ensure_icon())
        if not tray.ok:
            return False  # no tray icon possible: the caller quits / minimises instead of losing the window
        self.stop_preview()  # (a playing video must not go on with no window)
        self.tray = tray
        self.root.withdraw()
        self.root.after(250, self.tray_poll)
        return True

    def tray_poll(self):
        if not self.tray:
            return
        for ev in self.tray.events():
            if ev == "quit":
                self.close()
                return
            if ev == "open":
                self.show_from_tray()
                return
        self.root.after(250, self.tray_poll)

    def bring_to_front(self):
        if self.tray:
            self.show_from_tray()
            return
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.attributes("-topmost", True)  # (a plain lift() may stay behind other windows)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def show_from_tray(self):
        if self.tray:
            self.tray.stop()
            self.tray = None
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()
        self.dark_titlebar()

    def close(self):
        if self.tray:
            self.tray.stop()
            self.tray = None
        self.stop_preview()
        if self.busy and isinstance(self.job, Download):
            self.job.cancel.set()
        if self.settings.get("confirmed"):
            save_settings(self.settings)  # one last save, just to be sure
        self.root.destroy()


def main():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:  # noqa: BLE001
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass
    setup_logging()
    if not claim_single_instance():
        LOG.info("LEMON is already running: asked it to show its window")
        return
    root = tk.Tk()
    if "--minimized" in sys.argv and load_settings().get("confirmed"):
        root.withdraw()  # started by Windows: never flash a window on screen
    root.report_callback_exception = lambda t, v, tb: LOG.error("error inside the app", exc_info=(t, v, tb))
    app = App(root)
    if "--minimized" in sys.argv and app.settings.get("confirmed"):  # started by Windows: wait quietly
        if not (app.settings.get("tray") and app.hide_to_tray()):
            root.iconify()
    root.mainloop()
    LOG.info("LEMON closed")


if __name__ == "__main__":
    main()
