"""Player tests (VLC inside the window): play, seek, speed, fullscreen.
Skipped by themselves when VLC or ffmpeg is missing.  Run:  python -m unittest discover -s tests -v"""
import os
import subprocess
import sys
import time
import types
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import TMP, lemon as m  # noqa: E402

root = app = None
CLIP = os.path.join(TMP, "clip.mp4")


def pump(sec):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.02)


def setUpModule():
    global root, app
    ff = m.find_ffmpeg()
    if not (m.load_vlc() and ff):
        raise unittest.SkipTest("needs VLC (+ python-vlc) and ffmpeg")
    for path, pattern, size in ((CLIP, "testsrc", "1280x720"),):
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{pattern}=duration=40:size={size}:rate=30",
                        "-f", "lavfi", "-i", "sine=duration=40", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                        "-c:a", "aac", "-shortest", path], check=True)
    root = m.tk.Tk()
    app = m.App(root)
    pump(6)
    app.settings.update(folder=TMP, confirmed=True)
    app.in_settings = False
    app.show_done(types.SimpleNamespace(path=CLIP, warn="", error=None))
    pump(4)


def tearDownModule():
    try:
        app.stop_preview()
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


class Player(unittest.TestCase):
    def test_01_a_video_opens_fullscreen_and_plays(self):
        self.assertTrue(app.pfs)  # v3.4: there is no windowed layout for video, it goes straight to fullscreen
        self.assertTrue(app.prev.playing() and app.pframe.winfo_ismapped())
        self.assertGreater(app.prev.length(), 38_000)

    def test_02_pause_seek_jump_speed(self):
        p = app.prev
        p.toggle(); pump(0.8)
        self.assertFalse(p.playing())
        p.toggle(); pump(0.8)
        p.seek(0.5); pump(1.0)
        self.assertAlmostEqual(p.time() / 1000, 20, delta=3)
        t = p.time(); p.jump(10); pump(1.0)
        self.assertGreater(p.time() - t, 8000)
        app.change_speed(); self.assertAlmostEqual(p.mp.get_rate(), 1.25, places=2)
        for _ in range(5):
            app.change_speed()
        self.assertAlmostEqual(p.mp.get_rate(), 1.0, places=2)

    def test_05_fullscreen_covers_the_screen_and_leaves_to_the_main_screen(self):
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        pump(1.0)
        self.assertTrue(app.pfs)
        self.assertLessEqual(abs(app.pframe.winfo_width() - sw), 2)  # v2.7 bug: place() added the old size to the new one
        self.assertLessEqual(abs(app.pframe.winfo_height() - sh), 2)
        self.assertIn("lemon", app.pn)  # the bar with the lemon playhead
        self.assertIn("play_imgs", app.pn)  # v3.4 YouTube-style bar
        app.leave_fs(); pump(2.0)
        self.assertFalse(app.pfs)
        self.assertEqual(app.screen, "done")  # Esc / exit logo: the boxed video page, video still playing in its box
        self.assertTrue(app.pframe.winfo_ismapped() and app.prev.playing())
        self.assertTrue(app.pn.get("box"))
        x1, y1, x2, y2 = app.box_rect
        self.assertLessEqual(y2, root.winfo_height())  # the box sits inside the window

    def test_06_leaving_the_screen_stops_the_video(self):
        app.new_link(); pump(1.0)
        self.assertFalse(app.prev.playing())
        self.assertFalse(app.pframe.winfo_ismapped())

    def test_07_recent_list_resumes_where_you_stopped(self):
        m.add_recent(app.settings, CLIP, "Test clip")
        app.done_recent = False
        app.show_done(types.SimpleNamespace(path=CLIP, warn="", error=None))
        pump(2.5)
        app.prev.seek(0.5); pump(1.5)
        app.leave_fs(); pump(1.0)  # a user presses Esc out of fullscreen first
        app.show_recent(); pump(0.5)  # leaving the player remembers the moment
        pos = m.resume_pos(app.settings, CLIP)
        self.assertAlmostEqual(pos / 1000, 20, delta=4)
        self.assertEqual(app.screen, "recent")
        self.assertTrue(app.rows and app.rows[0]["path"] == CLIP)
        app.play_recent(app.rows[0]); pump(4.0)
        self.assertEqual(app.screen, "done")
        self.assertAlmostEqual(app.prev.time() / 1000, pos / 1000, delta=4)
        app.on_escape(); pump(1.5)  # Esc leaves fullscreen: the boxed page
        self.assertEqual(app.screen, "done")
        self.assertFalse(app.pfs)
        app.on_escape(); pump(1.5)  # opened from Recent: the next Esc goes back there
        self.assertEqual(app.screen, "recent")
        app.show_main()

    def test_08_the_bar_hides_while_playing_and_wakes_on_a_key(self):
        app.done_recent = False
        app.show_done(types.SimpleNamespace(path=CLIP, warn="", error=None))
        pump(2.5)
        p = app.prev
        self.assertTrue(app.pfs and p.playing() and app.fs_shown)
        app.root.winfo_pointerxy = lambda: (0, 0); app._fs_ptr = (0, 0)  # a real mouse moving during the test would wake the bar
        app.fs_last -= 10; pump(0.6)                      # no mouse or key for a while: like YouTube, the bar hides
        self.assertFalse(app.fs_shown)
        app.preview_key(types.SimpleNamespace(keysym="Up", char=""))  # any key brings it back
        self.assertTrue(app.fs_shown)
        p.toggle(); app.fs_last -= 10; pump(0.6)           # paused: never hides
        self.assertTrue(app.fs_shown)
        app.leave_fs(); pump(1.5)  # (still paused)
        self.assertEqual(app.screen, "done")  # the boxed page: a paused video shows its controls
        self.assertTrue(app.box_shown)
        app.new_link(); pump(0.5)
        self.assertEqual(app.screen, "main")


if __name__ == "__main__":
    unittest.main()
