"""Loads lemon_app_arcade.pyw for the tests, with HOME/LOCALAPPDATA pointed at a temp folder so the tests never touch
the real settings, shortcuts or log. (Same trick as in CLAUDE.md 'GUI testing on Windows'.)"""
import importlib.machinery
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="lemon_tests_")
os.environ["USERPROFILE"] = os.environ["HOME"] = TMP
os.environ["LOCALAPPDATA"] = os.path.join(TMP, "la")
os.makedirs(os.environ["LOCALAPPDATA"], exist_ok=True)

_loader = importlib.machinery.SourceFileLoader("lemon_app_under_test", os.path.join(ROOT, "lemon_app_arcade.pyw"))
lemon = importlib.util.module_from_spec(importlib.util.spec_from_loader("lemon_app_under_test", _loader))
_loader.exec_module(lemon)
lemon.sync_installed_copy = lambda: None  # (App() would copy itself over the installed app / re-stamp shortcuts)
lemon.tag_shortcuts = lambda: None
lemon.notify = lambda *a: None  # (no real toasts / registry writes while testing)
