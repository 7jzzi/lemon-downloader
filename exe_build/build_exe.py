"""Build LEMON.exe from ../lemon_app_arcade.pyw.   Run:  python build_exe.py

Options:  --src FILE     build from this file instead of ../lemon_app_arcade.pyw
          --out DIR      where the build goes (default: dist; result is DIR\\LEMON\\LEMON.exe)
          --onefile      one single LEMON.exe (slow start: unpacks ~250 MB each launch)
          --selftest     throwaway test build (see exe_selftest.py)

It never edits lemon_app.pyw: it makes a patched COPY (work\\) and runs PyInstaller on it.
Re-run it whenever the app changes, or to get newer ffmpeg/deno inside the exe.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


SRC = os.path.abspath(opt("--src", os.path.join(HERE, "..", "lemon_app_arcade.pyw")))
OUT = os.path.abspath(opt("--out", os.path.join(HERE, "dist")))
selftest, onefile = "--selftest" in sys.argv, "--onefile" in sys.argv
WORK = os.path.join(HERE, "work_test" if selftest else "work")
os.makedirs(WORK, exist_ok=True)

raw = open(SRC, "rb").read()
src = raw.decode("utf-8")
marker = "\ndef main():"
assert src.count(marker) == 1, "the app file changed shape: expected exactly one 'def main():'"
extra = open(os.path.join(HERE, "exe_overrides.py"), encoding="utf-8-sig").read()
if selftest:
    extra += open(os.path.join(HERE, "exe_selftest.py"), encoding="utf-8-sig").read()
patched = os.path.join(WORK, "lemon_app_exe.py")
with open(patched, "w", encoding="utf-8", newline="\n") as f:
    f.write(src.replace(marker, "\n" + extra + marker))

# icon for the exe file itself (the app's own generated lemon)
spec = importlib.machinery.SourceFileLoader("lemon_src", SRC)
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("lemon_src", spec))
spec.exec_module(mod)
ico = os.path.join(WORK, "lemon.ico")
mod.write_ico(ico)

deno = shutil.which("deno") or os.path.join(os.path.dirname(sys.executable), "Scripts", "deno.exe")
assert os.path.exists(deno), "deno.exe not found (pip install deno)"
hidden = [m for m in ("brotli", "mutagen", "Cryptodome", "websockets", "certifi", "requests", "urllib3", "curl_cffi", "vlc")
          if importlib.util.find_spec(m)]

cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile" if onefile else "--onedir",
       "--windowed", "--name", "LEMON", "--icon", ico,
       "--distpath", OUT, "--workpath", os.path.join(WORK, "pyi"), "--specpath", WORK,
       "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs", "--collect-all", "imageio_ffmpeg",
       "--copy-metadata", "yt-dlp", "--copy-metadata", "imageio-ffmpeg",
       "--add-binary", f"{deno};."]
for m in hidden:
    cmd += ["--hidden-import", m]
cmd.append(patched)
rc = subprocess.call(cmd)
if rc == 0:  # remember which source file this build came from (the update lemon on a dev PC compares it)
    import hashlib
    with open(os.path.join(OUT, "LEMON", "built_from.txt"), "w", encoding="utf-8") as f:
        f.write(hashlib.sha256(raw).hexdigest())
sys.exit(rc)
