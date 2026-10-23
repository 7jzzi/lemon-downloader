# LEMON

A small Windows app that downloads a video (MP4) or just its audio (MP3 / M4A / FLAC) from a link, with a pixel-art lemon that fills up while it works. It is a friendly window around [yt-dlp](https://github.com/yt-dlp/yt-dlp).

- Paste a link, press Start. Pick 1080p / 720p / 480p / best, or audio only.
- Cut a clip: type `link 1:20-2:05` in the link box.
- Optional: subtitles, cover picture and title/artist tags inside the file.
- Built-in player (needs [VLC](https://www.videolan.org/) installed) with a Recent list that remembers where you stopped.
- English and Arabic interface.

## Install

1. Download `LEMON-<version>.zip` (for example `LEMON-1.0.zip`) from the **Releases** page and unzip it anywhere.
2. Run `LEMON.exe`. On first start choose the folder where videos are saved.

Windows SmartScreen may warn about an unknown app because LEMON is not code-signed. Compare the SHA-256 of the zip with the one on the Release page before you run it.

## Privacy and safety

- No account, no ads, no telemetry. LEMON never uploads your files or settings.
- It only talks to: the site you paste a link from (also when you paste, to read the title and size), `pypi.org` when you press **UPDATE HELPERS**, and `github.com` / `api.github.com` to check for a new version (quietly at start-up, and when you press the lemon at the top right). These requests carry no data about you, but those servers see your IP address like any website does.
- LEMON never installs an update without asking. If a newer version exists, pressing the lemon asks Yes/No, then downloads it from this project's GitHub Releases, checks its SHA-256 and swaps it in.
- **Cookies** (off by default): the cookies card lets yt-dlp read your logged-in browser cookies for age-restricted or members-only videos. They stay on your PC and are used only for that download.
- Saved on your PC: settings and the Recent list in `~/.lemon_downloader.json`, and a small log in `%LOCALAPPDATA%\LEMON\lemon.log` (links keep only their video id; cookie and token values are hidden). Video titles and file paths still appear in the log and the Recent list. Delete them any time: clear the Recent list in the app and delete the two files above.
- LEMON only opens audio and video files, and only web (`http`/`https`) links.
- It watches the clipboard for video links while its window is in front, to fill the link box for you. Nothing is stored or sent.

## Use it responsibly

Only download videos you own, that are free to share, or that you otherwise have the right to save, and respect each site's terms of service. LEMON is not affiliated with YouTube or any other site.

## License

LEMON is free software under the [GNU General Public License v3.0](LICENSE): you may use, change and share it, as long as shared copies stay under the same license and come with their source code.

## Build it yourself

Needs Python 3.12+ with `yt-dlp[default] imageio-ffmpeg deno python-vlc pyinstaller`.

```
python exe_build\build_exe.py --out build
python -m unittest discover -s tests
```

See `THIRD_PARTY_NOTICES.md` for the licenses of what is bundled.
