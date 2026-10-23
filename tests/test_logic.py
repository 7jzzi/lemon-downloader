"""Fast tests of the plain logic (no window, no network, no VLC).   Run:  python -m unittest discover -s tests -v"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import TMP, lemon as m  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "Windows start-up list")
class Autostart(unittest.TestCase):
    KEY = r"Software\LEMON_TEST_RUN"  # a throwaway key: the real start-up list is never touched

    def tearDown(self):
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.KEY)
        except FileNotFoundError:
            pass

    def value(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as k:
                return winreg.QueryValueEx(k, "LEMON")[0]
        except FileNotFoundError:
            return None

    def test_add_and_remove(self):
        m.set_autostart(True, self.KEY)
        self.assertEqual(self.value(), m.autostart_command())
        self.assertIn("--minimized", self.value())  # started by Windows = waits in the taskbar
        m.set_autostart(False, self.KEY)
        self.assertIsNone(self.value())
        m.set_autostart(False, self.KEY)  # removing twice is fine

    def test_setting_is_saved(self):
        self.assertFalse(m.default_settings()["autostart"])
        self.assertTrue(m.load_settings().get("autostart") in (True, False))


@unittest.skipUnless(sys.platform == "win32", "Windows tray")
class TrayIcon(unittest.TestCase):
    def test_click_becomes_an_event_and_stop_removes_it(self):
        for _ in range(2):  # twice: the window class must be gone after stop()
            tray = m.Tray(m.ensure_icon())
            self.assertTrue(tray.ok)
            tray.u.PostMessageW(tray.hwnd, tray.CB, 0, 0x202)  # a left click on the icon
            import time
            for _i in range(50):
                ev = tray.events()
                if ev:
                    break
                time.sleep(0.05)
            self.assertEqual(ev, ["open"])
            tray.stop()
            self.assertFalse(tray._t.is_alive())


@unittest.skipUnless(sys.platform == "win32", "Windows single instance")
class OneLemon(unittest.TestCase):
    def test_second_start_asks_the_first_to_show_itself(self):
        import time
        suffix = "_test_%d" % os.getpid()  # its own names: a real running LEMON is never involved
        m.SHOW_REQUEST.clear()
        self.assertTrue(m.claim_single_instance(suffix))   # the first one starts
        self.assertFalse(m.claim_single_instance(suffix))  # a second one is refused...
        for _ in range(40):
            if m.SHOW_REQUEST.is_set():
                break
            time.sleep(0.05)
        self.assertTrue(m.SHOW_REQUEST.is_set())            # ...and the first is told to come to the front
        m.SHOW_REQUEST.clear()

    def test_update_smoke_test_may_run_next_to_the_old_one(self):
        os.environ["LEMON_SMOKE"] = "x"
        try:
            self.assertTrue(m.claim_single_instance("_smoke"))
            self.assertTrue(m.claim_single_instance("_smoke"))
        finally:
            del os.environ["LEMON_SMOKE"]


class Clips(unittest.TestCase):
    def test_parse(self):
        L = "https://x.com/v"
        for text, want in {f"{L} 1:20-2:05": (L, (80, 125)), f"{L} 80-125": (L, (80, 125)), f"{L} 1:20-": (L, (80, None)),
                           f"{L} 0:05 to 0:12": (L, (5, 12)), f"{L} 1:02:03-1:05:00": (L, (3723, 3900)),
                           f"{L} 0:30.5-0:40": (L, (30.5, 40)), L: (L, None),
                           "https://x.com/watch?v=a-b 5": ("https://x.com/watch?v=a-b 5", None)}.items():
            self.assertEqual(m.split_clip(text), want, text)

    def test_file_tag(self):
        self.assertEqual(m.clip_tag((80, 125)), " [clip 1m20s-2m05s]")
        self.assertEqual(m.clip_tag((80, None)), " [clip from 1m20s]")
        self.assertEqual(m.clip_tag((3723, 3900)), " [clip 1h02m03s-1h05m00s]")
        self.assertNotIn(":", m.clip_tag((3723, 3900)))  # Windows file names can't hold a colon


class Text(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(m.fmt_time(0), "0:00")
        self.assertEqual(m.fmt_time(83_000), "1:23")
        self.assertEqual(m.fmt_time(3_723_000), "1:02:03")

    def test_errors(self):
        for msg, word in {"HTTP Error 429: Too Many Requests": "too many", "HTTP Error 403: Forbidden": "403",
                          "[Errno 28] No space left on device": "disk is full", "<urlopen error getaddrinfo failed>": "no internet",
                          "Sign in to confirm you're not a bot": "sign-in", "This video is age-restricted": "age-restricted",
                          "Private video. Sign in if you've been granted access": "private",
                          "ERROR: [youtube] abc429xyz: Video unavailable": "unavailable",   # '429' inside an id is NOT rate limiting
                          "Permission denied: 'x.mp4'": "can't write", "Unable to extract uploader id": "update helpers"}.items():
            self.assertIn(word, m.tidy_error(Exception(msg)).lower(), msg)
        self.assertEqual(m.tidy_error(Exception("Something brand new")), "Something brand new")  # unknown: shown as it is
        self.assertLessEqual(len(m.tidy_error(Exception("x" * 500))), 120)

    def test_links(self):
        self.assertTrue(m.looks_like_url("https://youtu.be/abc"))
        self.assertFalse(m.looks_like_url("hello world"))
        self.assertEqual(m.normalise_url("www.x.com/a"), "https://www.x.com/a")

    def test_versions(self):
        self.assertGreater(m._vkey("2.10"), m._vkey("2.9"))
        self.assertGreater(m._vkey("3.0"), m._vkey("2.9"))


class Settings(unittest.TestCase):
    def test_roundtrip_and_validation(self):
        s = m.default_settings()
        s.update(folder=TMP, confirmed=True, quality=2, volume=33)
        self.assertIsNone(m.save_settings(s))
        back = m.load_settings()
        self.assertEqual((back["quality"], back["volume"]), (2, 33))
        with open(m.CONFIG, "w", encoding="utf-8") as f:  # garbage values must fall back to the defaults, not crash
            json.dump({"folder": TMP, "confirmed": True, "volume": 250, "quality": 99, "cookies": "opera", "up2x": True}, f)
        bad = m.load_settings()
        self.assertEqual((bad["volume"], bad["quality"], bad["cookies"]), (70, 0, ""))
        self.assertNotIn("up2x", bad)  # settings saved before the Video2X features were removed are ignored
        with open(m.CONFIG, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertFalse(m.load_settings()["confirmed"])


class Logging(unittest.TestCase):
    def test_log_file(self):
        m.setup_logging()
        m.LOG.info("hello from the test")
        for h in m.LOG.handlers:
            h.flush()
        with open(m.log_path(), encoding="utf-8") as f:
            self.assertIn("hello from the test", f.read())


class Info(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(m.fmt_size(5 * 1048576), "5 MB")
        self.assertEqual(m.fmt_size(3 * 1073741824), "3.0 GB")
        self.assertEqual(m.fmt_size(10), "1 MB")

    def test_disk_free_of_a_folder_that_does_not_exist_yet(self):
        self.assertGreater(m.disk_free(os.path.join(TMP, "no", "such", "dir")), 0)


class Recent(unittest.TestCase):
    def test_list_resume_and_ago(self):
        st = {"recent": []}
        m.add_recent(st, "a.mp4", "A")
        m.add_recent(st, "b.mp4", "B")
        m.add_recent(st, "a.mp4", "A again")  # moves to the top, no duplicate
        self.assertEqual([e["path"] for e in st["recent"]], ["a.mp4", "b.mp4"])
        for _ in range(40):
            m.add_recent(st, "x%d.mp4" % _, "")
        self.assertEqual(len(st["recent"]), m.RECENT_MAX)
        m.add_recent(st, "c.mp4", "C")
        m.remember_pos(st, "c.mp4", 3000, 100000)    # first 5 s: not worth keeping
        self.assertEqual(m.resume_pos(st, "c.mp4"), 0)
        m.remember_pos(st, "c.mp4", 40000, 100000)
        self.assertEqual(m.resume_pos(st, "c.mp4"), 40000)
        m.remember_pos(st, "c.mp4", 97000, 100000)   # nearly the end: start over next time
        self.assertEqual(m.resume_pos(st, "c.mp4"), 0)
        self.assertEqual(m.resume_pos(st, "nope.mp4"), 0)
        self.assertEqual([m.ago(1000 - d, 1000) for d in (10, 300, 7200, 100000, 5 * 86400)],
                         ["just now", "5 min ago", "2 h ago", "yesterday", "5 days ago"])

    def test_saved_and_read_back_even_with_garbage(self):
        m.CONFIG, old = os.path.join(TMP, "recent_cfg.json"), m.CONFIG
        try:
            st = m.default_settings()
            st.update(folder=TMP, confirmed=True)
            m.add_recent(st, os.path.join(TMP, "v.mp4"), "T")
            self.assertIsNone(m.save_settings(st))
            self.assertEqual(m.load_settings()["recent"][0]["title"], "T")
            with open(m.CONFIG, "w", encoding="utf-8") as f:
                json.dump({"folder": TMP, "recent": [5, {"path": 3}, {"path": "ok.mp4", "pos": -4, "ts": "x"}, None]}, f)
            self.assertEqual(m.load_settings()["recent"], [{"path": "ok.mp4", "title": "", "ts": 0.0, "pos": 0}])
            with open(m.CONFIG, "w", encoding="utf-8") as f:
                json.dump({"recent": 7}, f)
            self.assertEqual(m.load_settings()["recent"], [])
        finally:
            m.CONFIG = old


class Extras(unittest.TestCase):
    """subtitles / cover picture / tags / audio format -> the options handed to yt-dlp (a fake YoutubeDL records them)."""

    def fetch(self, audio=False, extras=None, fail_first=False):
        import yt_dlp
        made, real = [], yt_dlp.YoutubeDL

        class Fake:
            def __init__(s, opts):
                s.opts = opts
                made.append(opts)

            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def extract_info(s, url, download=True):
                if fail_first and len(made) == 1:
                    raise RuntimeError("ffmpeg exited with code 1")
                return {"title": "T", "requested_downloads": [{"filepath": "x"}]}
        yt_dlp.YoutubeDL = Fake
        try:
            job = m.Download("https://x.com/v", TMP, 720, audio=audio, extras=extras)
            job.run()
        finally:
            yt_dlp.YoutubeDL = real
        return made, job

    def keys(self, opts):
        return [p["key"] for p in opts.get("postprocessors", [])]

    def test_nothing_extra_by_default(self):
        made, job = self.fetch()
        self.assertIsNone(job.error)
        self.assertNotIn("writesubtitles", made[0])
        self.assertNotIn("writethumbnail", made[0])
        self.assertNotIn("FFmpegMetadata", self.keys(made[0]))

    def test_video_with_everything(self):
        made, job = self.fetch(extras={"subs": True, "thumb": True, "tags": True, "afmt": "flac"})
        o = made[0]
        self.assertTrue(o["writesubtitles"] and o["writethumbnail"])
        self.assertEqual(o["subtitleslangs"], ["en", "ar"])
        self.assertEqual(self.keys(o), ["FFmpegMetadata", "FFmpegEmbedSubtitle", "FFmpegThumbnailsConvertor", "EmbedThumbnail"])

    def test_audio_formats_and_no_subtitles_for_audio(self):
        for fmt in m.AUDIO_FORMATS:
            made, _ = self.fetch(audio=True, extras={"subs": True, "thumb": True, "tags": True, "afmt": fmt})
            pps = made[0]["postprocessors"]
            self.assertEqual(pps[0]["key"], "FFmpegExtractAudio")
            self.assertEqual(pps[0]["preferredcodec"], fmt)
            self.assertNotIn("FFmpegEmbedSubtitle", self.keys(made[0]))
            self.assertIn("EmbedThumbnail", self.keys(made[0]))

    def test_broken_extras_fall_back_to_a_plain_download(self):
        made, job = self.fetch(extras={"subs": True, "thumb": True}, fail_first=True)
        self.assertIsNone(job.error)
        self.assertEqual(len(made), 2)
        self.assertNotIn("writesubtitles", made[1])
        self.assertIn("couldn't add", job.warn)
        made, job = self.fetch(fail_first=True)  # no extras asked: a real ffmpeg error is still an error
        self.assertIsNotNone(job.error)

    def test_settings_round_trip(self):
        m.CONFIG, old = os.path.join(TMP, "extras_cfg.json"), m.CONFIG
        try:
            st = m.default_settings()
            st.update(folder=TMP, confirmed=True, subs=True, tags=True, afmt="m4a")
            self.assertIsNone(m.save_settings(st))
            got = m.load_settings()
            self.assertEqual((got["subs"], got["thumb"], got["tags"], got["afmt"]), (True, False, True, "m4a"))
            with open(m.CONFIG, "w", encoding="utf-8") as f:
                json.dump({"afmt": "wav", "subs": "yes"}, f)
            got = m.load_settings()
            self.assertEqual((got["afmt"], got["subs"]), ("mp3", True))
        finally:
            m.CONFIG = old


class Arabic(unittest.TestCase):
    def tearDown(self):
        m.LANG = "en"

    def test_english_is_untouched(self):
        m.LANG = "en"
        self.assertEqual(m.tr("SETTINGS"), "SETTINGS")
        self.assertEqual(m.tr("Quality set to 720p."), "Quality set to 720p.")

    def test_arabic_texts_patterns_and_unknowns(self):
        m.LANG = "ar"
        self.assertEqual(m.tr("SETTINGS"), "الإعدادات")
        self.assertEqual(m.tr("Settings"), "الإعدادات")                       # (not case sensitive)
        self.assertEqual(m.tr("INSERT LINK. GET MP3. SQUEEZE IT!"), "ضع الرابط. احصل على MP3. اعصرها!")
        self.assertIn("15", m.tr("15 MIN AGO"))
        self.assertIn("1080p", m.tr("Quality set to 1080p.  ✓ saved"))
        self.assertTrue(m.ARABIC_RE.search(m.tr("Quality set to Best quality.  ✓ saved")))
        both = m.tr("Back to MP4 video. Cookies off.")  # 2 sentences
        self.assertEqual(len(m.ARABIC_RE.findall(both)) > 20, True)
        self.assertEqual(m.tr("some text nobody translated"), "some text nobody translated")
        self.assertEqual(m.tr(m.tr("SETTINGS")), m.tr("SETTINGS"))             # translating twice changes nothing
        self.assertEqual(m.tr(""), "")

    def test_every_plain_language_error_has_an_arabic_text(self):
        for _pat, text in m.ERROR_HINTS:
            self.assertIn(text.upper(), m.AR, text)
        m.LANG = "ar"
        self.assertTrue(m.ARABIC_RE.search(m.tr("Couldn't download: " + m.tidy_error(Exception("ERROR: Private video")))))

    def test_the_fixed_texts_of_the_screens_are_translated(self):
        for word in ("SETTINGS", "RECENT", "PASTE", "START", "UPDATE HELPERS", "ALL DONE!", "NEW LINK", "OPEN FOLDER", "SHOW FILE",
                     "CONFIRM & SAVE", "BROWSE", "[ESC] CANCEL", "DOWNLOADING", "SQUEEZING THE LINK", "FINISHING UP",
                     "UPDATING LEMON", "UPDATED!"):
            self.assertIn(word, m.AR, word)
        for _k, name, note in m.EXTRAS:
            self.assertIn(name, m.AR)
            self.assertIn(note, m.AR)
        for _n, _h, label in m.QUALITIES:
            self.assertIn(label.upper(), m.AR) if label.upper() not in ("HD", "SD") else None

    def test_language_setting_round_trip(self):
        m.CONFIG, old = os.path.join(TMP, "lang_cfg.json"), m.CONFIG
        try:
            st = m.default_settings()
            st.update(folder=TMP, confirmed=True, lang="ar")
            self.assertIsNone(m.save_settings(st))
            self.assertEqual(m.load_settings()["lang"], "ar")
            with open(m.CONFIG, "w", encoding="utf-8") as f:
                json.dump({"lang": "fr"}, f)
            self.assertEqual(m.load_settings()["lang"], "en")
        finally:
            m.CONFIG = old


if __name__ == "__main__":
    unittest.main()


class Privacy(unittest.TestCase):
    def test_log_hides_link_secrets(self):
        out = m.scrub_log("start: https://x.com/watch?v=abc&sig=SECRET&list=PL1&t=9 and https://y.com/f?token=ZZZ done")
        self.assertIn("v=abc", out)
        self.assertIn("list=PL1", out)
        self.assertNotIn("SECRET", out)
        self.assertNotIn("ZZZ", out)
        self.assertIn("https://x.com/watch", out)
        self.assertEqual(m.scrub_log("https://x.com/plain"), "https://x.com/plain")

    def test_log_hides_cookies(self):
        self.assertNotIn("abc123", m.scrub_log("Cookie: abc123; other"))
        self.assertNotIn("abc123", m.scrub_log("authorization=abc123"))

    def test_log_file_is_scrubbed(self):
        import logging
        m.setup_logging()
        m.LOG.info("go https://x.com/a?sig=SECRET")
        for h in m.LOG.handlers:
            h.flush()
        with open(m.log_path(), encoding="utf-8") as f:
            self.assertNotIn("SECRET", f.read())

    def test_release_check_accepts_only_a_sane_release_of_our_repo(self):
        import io
        from unittest import mock
        repo = m.RELEASES_REPO

        def check(payload):
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
                return m.latest_release()
        ok = f"https://github.com/{repo}/releases/tag/v3.9"
        self.assertEqual(check({"tag_name": "v3.9", "html_url": ok}), ("3.9", ok))
        self.assertIsNone(check({"tag_name": "v3.9; rm -rf", "html_url": ok}))                 # odd version text
        self.assertIsNone(check({"tag_name": "v3.9", "html_url": "https://evil.example/x"}))   # not our releases page
        self.assertIsNone(check({"tag_name": "v3.9", "html_url": f"https://github.com/{repo}-evil/x"}))
        self.assertIsNone(check({}))

    def test_only_web_links_and_media_files(self):
        for bad in ("file:///C:/Windows/x.mp4", "ftp://x.com/a.mp4", "javascript://x.com/a"):
            self.assertFalse(m.looks_like_url(bad), bad)
        self.assertTrue(m.looks_like_url("https://youtu.be/abc"))
        self.assertTrue(m.is_media("C:/v/a.MP4") and m.is_media("a.flac"))
        self.assertFalse(m.is_media("C:/v/evil.exe") or m.is_media("a.lnk") or m.is_media("a.mp4.bat"))
        with open(m.CONFIG, "w", encoding="utf-8") as f:  # a hand-edited settings file
            json.dump({"folder": TMP, "confirmed": True, "recent": [{"path": "C:/v/a.mp4", "title": "ok"},
                                                                     {"path": "C:/v/evil.exe", "title": "no"}]}, f)
        self.assertEqual([e["path"] for e in m.load_settings()["recent"]], ["C:/v/a.mp4"])

    def test_no_code_can_be_installed_by_the_app(self):
        for gone in ("find_update", "apply_update", "install_v2x", "enhance_seconds"):
            self.assertFalse(hasattr(m, gone), gone)
