"""Zip the built app for a GitHub release.   Run:  python make_release.py [folder]
Makes LEMON-<version>.zip (with a LEMON folder inside) next to the build folder and prints its SHA-256.
Attach the zip to a GitHub Release tagged v<version>; GitHub shows the fingerprint by itself. LEMON checks it before installing."""
import hashlib
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
build = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dist_new"))
src = open(os.path.join(HERE, "..", "lemon_app_arcade.pyw"), encoding="utf-8").read()
ver = re.search(r'^APP_VERSION = "([\d.]+)"', src, re.M)[1]
assert os.path.isfile(os.path.join(build, "LEMON", "LEMON.exe")), "no LEMON\\LEMON.exe in " + build
for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):  # the GPL wants the license to travel with the exe
    shutil.copy(os.path.join(HERE, "..", name), os.path.join(build, "LEMON", name))
out = os.path.join(HERE, f"LEMON-{ver}")
print("zipping (a minute)...")
zp = shutil.make_archive(out, "zip", root_dir=build, base_dir="LEMON")
h = hashlib.sha256()
with open(zp, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
open(os.path.join(HERE, "last_release.txt"), "w").write(ver)  # PUBLISH_LEMON.bat reads the version from here
print("ZIP :", zp, f"({os.path.getsize(zp) / 1048576:.0f} MB)")
print("SHA-256:", h.hexdigest())
print(f"Next: on GitHub make a Release tagged v{ver} and attach this zip.")
