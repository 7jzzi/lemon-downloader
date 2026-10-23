"""Window tests: opens the real app window for a few seconds (needs a Windows desktop session, no VLC needed).
Run:  python -m unittest discover -s tests -v"""
import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import TMP, lemon as m  # noqa: E402

root = app = None


def pump(sec):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.02)


def setUpModule():
    global root, app
    root = m.tk.Tk()
    app = m.App(root)
    pump(6)  # boot screen -> first-run settings (the temp profile has no settings yet)
    app.settings.update(folder=TMP, confirmed=True)
    app.in_settings = False
    app.show_main()
    pump(0.5)


def tearDownModule():
    try:
        root.destroy()
    except m.tk.TclError:
        pass


def card(short):
    return [x for x in app.menu_items() if x["short"] == short][0]


class Notify(unittest.TestCase):
    def test_notified_only_when_you_are_in_another_window(self):
        calls, real = [], m.notify
        m.notify = lambda *a: calls.append(a[1:])
        try:
            for away, expect in ((True, 1), (False, 0)):
                del calls[:]
                app.busy, app.cancelling = True, False
                app.job = types.SimpleNamespace(error=None, path=None, warn="", orig=None, title="Cat video")
                root.focus_displayof = (lambda: None) if away else (lambda: root)
                app.end_download()
                self.assertEqual(len(calls), expect, away)
            self.assertEqual(calls, [])
            root.focus_displayof = lambda: None
            app.busy, app.job = True, types.SimpleNamespace(error="no internet", path=None, warn="", orig=None, title="")
            app.end_download()
            self.assertIn("failed", calls[0][0])
        finally:
            m.notify = real
            del root.focus_displayof
            app.show_main()


class Info(unittest.TestCase):
    def test_info_line_and_the_disk_space_block(self):
        app.settings.update(folder=TMP, audio=False)
        app.show_main()
        key = ("https://x.com/v", None, False, "", None)
        app.probe_key = key
        app.probes[key] = {"title": "Cat video", "secs": 125, "size": 50 * 1048576}
        app.draw_info()
        self.assertTrue(app.cv.find_withtag("info"))
        free, real = m.disk_free(TMP), m.disk_free
        self.assertEqual(round(app.info_need() / 1048576), 60)  # 50 MB x1.2
        m.disk_free = lambda f: 10 * 1048576  # a nearly full disk
        try:
            app._entry_focus_in()
            app.entry.delete(0, "end")
            app.entry.insert(0, "https://x.com/v")
            app.start_download()
            self.assertEqual(app.screen, "main")  # blocked: no download started
            self.assertEqual(app.msg_color, m.RED)
            self.assertIn("disk space", app.msg)
        finally:
            m.disk_free = real
            app.entry.delete(0, "end")
            app.probe_key = None
            app._entry_focus_out()
            self.assertGreater(free, 0)


class Recent(unittest.TestCase):
    def test_recent_screen(self):
        gone = os.path.join(TMP, "gone.mp4")
        app.settings["recent"] = []
        app.show_recent()
        self.assertEqual(app.screen, "recent")
        m.add_recent(app.settings, gone, "Deleted video")
        app.show_recent()
        pump(0.3)
        self.assertEqual(len(app.rows), 1)
        app.play_recent(app.rows[0])  # the file isn't there: nothing happens, no crash
        self.assertEqual(app.screen, "recent")
        app.on_key(types.SimpleNamespace(char="1"))
        app.on_escape()
        self.assertEqual(app.screen, "main")
        app.settings["recent"] = []


class Extras(unittest.TestCase):
    def test_audio_card_cycles_mp3_m4a_flac_off(self):
        app.settings.update(audio=False, afmt="mp3")
        seen = []
        for _ in range(5):
            seen.append((app.menu_items()[4]["short"], app.settings["audio"]))  # the 5th card
            app.card_click(("audio", None))
        self.assertEqual(seen, [("MP3", False), ("MP3", True), ("M4A", True), ("FLAC", True), ("MP3", False)])

    def test_settings_screen_has_extras_and_saves_them(self):
        app.settings.update(subs=False, thumb=False, tags=False)
        app.show_settings(False)
        pump(0.3)
        app.toggle_extra("thumb")
        self.assertTrue(app.draft["thumb"])
        err, real = None, m.save_settings
        m.save_settings = lambda s: None
        try:
            app.confirm_settings()
        finally:
            m.save_settings = real
        self.assertTrue(app.settings["thumb"] and not app.settings["subs"])
        app.settings["thumb"] = False
        app.show_main()


class Arabic(unittest.TestCase):
    def test_every_screen_draws_in_arabic_and_the_switch_works(self):
        try:
            app.settings.update(lang="en", folder=TMP, confirmed=True)
            app.show_settings(False)
            app.toggle_lang()
            self.assertEqual((m.LANG, app.settings["lang"], app.screen), ("ar", "ar", "settings"))
            self.assertTrue(any(app.cv.itemcget(i, "text") and m.ARABIC_RE.search(app.cv.itemcget(i, "text"))
                                for i in app.cv.find_withtag("scr") if app.cv.type(i) == "text"))
            app.show_main(); pump(0.3)
            app.say("Quality set to 1080p.  ✓ saved"); app.say("Couldn't download: that video is private", m.RED)
            app.show_recent(); pump(0.2)
            app.show_done(types.SimpleNamespace(path=None, warn="couldn't add the subtitles / cover picture", error=None, title=""))
            pump(0.2)
            app.show_update("3.0", "3.1", ["CHECK", "SWAP", "RESTART"], after=lambda: None); pump(0.3)
            app.busy, app.upd = False, None
            app.show_settings(False)
            app.toggle_lang()  # back to English: the same screens still draw
            self.assertEqual(m.LANG, "en")
            app.show_main(); pump(0.2)
        finally:
            m.LANG = app.settings["lang"] = "en"
            app.placeholder = app.placeholder_text()
            app.busy, app.upd = False, None
            app.show_main()


class QuickStart(unittest.TestCase):
    def tearDown(self):
        app.settings["tray"] = False
        app.show_main()
        pump(0.3)

    def test_tray_mode_skips_the_loading_show(self):
        app.settings.update(tray=True, confirmed=True)
        app.show_boot()
        pump(2.0)  # the real checks take a moment, but the 5 s animated show must not play
        self.assertEqual(app.screen, "main")

    def test_normal_mode_still_shows_it(self):
        app.settings.update(tray=False, confirmed=True)
        app.show_boot()
        pump(1.5)
        self.assertEqual(app.screen, "boot")


class Main(unittest.TestCase):
    def test_boot_reaches_main_and_window_fits_the_screen(self):
        self.assertEqual(app.screen, "main")
        self.assertLessEqual(root.winfo_rooty() + root.winfo_height(), root.winfo_screenheight())  # v2.3 taskbar bug

    def test_no_upscale_or_60fps_cards(self):
        """LEMON no longer has the Video2X features: only 4 qualities + audio, cookies, folder, open."""
        app.show_main()
        shorts = [it["short"] for it in app.menu_items()]
        self.assertEqual(len(shorts), 8)
        for gone in ("UPSCALE", "60 FPS"):
            self.assertNotIn(gone, shorts)
        for key in ("up2x", "upbest", "fps60", "fps_max"):
            self.assertNotIn(key, app.settings)

    def test_the_link_box_keeps_working_after_a_download(self):
        """v2.3 bug: after a download, 'New link' + typing landed INSIDE the placeholder."""
        app.entry.delete(0, "end")
        app.entry_active = True
        app.entry.focus_force()
        pump(0.3)
        app.job = types.SimpleNamespace(error=None, path=None, warn="")
        app.cancelling = False
        app.end_download()
        pump(0.3)
        self.assertIsNot(root.focus_get(), app.entry)  # focus moved away, so New link's focus_set fires a real FocusIn
        app.new_link()
        pump(0.3)
        self.assertTrue(app.entry_active)
        self.assertEqual(app.screen, "main")


class UpdateScreen(unittest.TestCase):
    def setUp(self):
        app.busy = False
        app.show_main()

    def test_success_runs_every_step_then_calls_after(self):
        done = []
        app.show_update("2.9", "9.9", ["CHECK", "SWAP", "RESTART"], after=lambda: done.append(1))
        self.assertTrue(app.busy and app.screen == "update")
        app.update_set_step(1)
        app.update_finish(True)
        t = time.time()
        while not done and time.time() - t < 8:
            pump(0.2)
        self.assertEqual(done, [1])
        self.assertEqual(app.upd["title"], "UPDATED!")
        self.assertEqual(app.upd["steps"][app.upd["step"]], "RESTART")
        app.busy, app.upd = False, None
        app.show_main()

    def test_failure_returns_to_main_with_the_message(self):
        app.show_update("2.9", "9.9", ["CHECK", "BUILD", "SWAP", "RESTART"], after=lambda: None)
        pump(0.3)
        app.update_finish(False, "Couldn't rebuild: pretend")
        self.assertEqual((app.screen, app.busy, app.upd), ("main", False, None))
        self.assertIn("pretend", app.msg)

    def test_the_bar_never_finishes_on_its_own_while_building(self):
        app.show_update("2.9", "9.9", ["CHECK", "BUILD", "SWAP", "RESTART"], after=lambda: None)
        app.update_set_step(1)
        pump(2.5)
        self.assertLess(app.upd["shown"], 0.9)
        app.update_finish(False, "stop")


class DoneScreenWithoutVlc(unittest.TestCase):
    def test_plain_done_screen_and_hint(self):
        app.vlc, app.vlc_tried = None, True
        path = os.path.join(TMP, "v.mp4")
        open(path, "w").close()
        app.show_done(types.SimpleNamespace(path=path, orig=None, warn="", error=None))
        pump(0.5)
        self.assertEqual(app.screen, "done")
        self.assertFalse(app.pframe.winfo_ismapped())
        app.vlc_tried = False  # let the other tests find VLC again
        app.show_main()


if __name__ == "__main__":
    unittest.main()
