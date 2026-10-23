
# ───────── exe build: things that only make sense when running as a .py (added by build_exe.py) ─────────
__file__ = sys.executable  # so the "relaunch" / taskbar-pin code points at LEMON.exe
os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # lets the single-file exe start a fresh copy of itself (relaunch)
LIBS = os.path.join(lemon_home(), "pylibs")  # a newer yt-dlp (from "update helpers") lives here
if os.path.isdir(LIBS):
    sys.path.insert(0, LIBS)  # ponytail: only wins over the built-in copy if the frozen importer lets it (tested)


def sync_installed_copy():
    pass  # nothing to copy: the exe is the app


def ytdlp_version():
    try:
        import yt_dlp.version
        return yt_dlp.version.__version__  # whichever copy was loaded: the built-in one or the updated one
    except Exception:  # noqa: BLE001
        return "not installed"


def pip_install(packages, upgrade=False):
    """exe version of 'update helpers': yt-dlp and its YouTube solver are plain-Python wheels, so
    download them from PyPI (hash-checked) into LIBS; the next start loads them instead of the built-in
    copy. ffmpeg + deno are binaries inside the exe: those need a rebuild."""
    if not upgrade:
        return True  # everything is already built in
    try:
        import hashlib
        import io
        import urllib.request
        import zipfile
        new = LIBS + ".new"
        shutil.rmtree(new, ignore_errors=True)
        os.makedirs(new)
        for name in ("yt-dlp", "yt-dlp-ejs"):
            with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as r:
                info = json.load(r)
            whl = next(u for u in info["urls"] if u["filename"].endswith("-py3-none-any.whl"))
            with urllib.request.urlopen(whl["url"], timeout=120) as r:
                blob = r.read()
            if hashlib.sha256(blob).hexdigest() != whl["digests"]["sha256"]:
                return False
            zipfile.ZipFile(io.BytesIO(blob)).extractall(new)
        shutil.rmtree(LIBS, ignore_errors=True)
        os.rename(new, LIBS)
        return True
    except Exception:  # noqa: BLE001
        return False


_find_js_runtime_py = find_js_runtime


def find_js_runtime():
    deno = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "deno.exe")
    return ("deno", deno) if os.path.exists(deno) else _find_js_runtime_py()


def install_shortcuts():
    """Desktop + Start menu icons that launch LEMON.exe."""
    app_dir = lemon_home()
    os.makedirs(app_dir, exist_ok=True)
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
  $s.TargetPath = $env:LEMON_EXE
  $s.WorkingDirectory = Split-Path $env:LEMON_EXE
  $s.IconLocation = $env:LEMON_ICO
  $s.Description = 'LEMON video downloader'
  $s.Save()
}
'''
    env = dict(os.environ, LEMON_EXE=sys.executable, LEMON_ICO=ico)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "PowerShell failed").strip().splitlines()[-1])


if os.environ.get("LEMON_SMOKE"):  # "does this build start?": build_exe.py --smoke runs the new exe like this
    _res = "ok"
    try:
        _root = tk.Tk()
        _root.withdraw()  # (nothing flashes on screen)
        App(_root)
        _root.withdraw()
        _t0 = time.time()
        while time.time() - _t0 < 4:
            _root.update()
            time.sleep(0.03)
        _res = f"ok v{APP_VERSION} yt_dlp={ytdlp_version()} frozen={bool(getattr(sys, 'frozen', False))}"
    except BaseException:  # noqa: BLE001
        import traceback
        _res = "CRASH " + traceback.format_exc()
    with open(os.environ["LEMON_SMOKE"], "w", encoding="utf-8") as _f:
        _f.write(_res)
    os._exit(0)
