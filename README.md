<p align="center">
  <img src="assets/lemon.png" width="110" alt="LEMON">
</p>

<h1 align="center">LEMON 🍋</h1>

<p align="center">
  <b>Paste a link. Get a video. Squeeze it!</b><br>
  A tiny Windows app that saves videos and music for you. Watch the lemon fill up while it works.
</p>

<p align="center">
  <a href="https://github.com/7jzzi/lemon-downloader/releases/latest"><img src="https://img.shields.io/github/v/release/7jzzi/lemon-downloader?label=latest&color=FFD60A&style=for-the-badge" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <a href="LICENSE"><img src="https://img.shields.io/badge/free-GPL--3.0-A8E040?style=for-the-badge" alt="Free and open source"></a>
</p>

<p align="center">
  <a href="https://github.com/7jzzi/lemon-downloader/releases/latest"><b>⬇️ Download LEMON</b></a>
</p>

<p align="center">
  <img src="assets/main-screen.png" width="49%" alt="LEMON main screen">
  <img src="assets/downloading.png" width="49%" alt="LEMON downloading">
</p>

---

## ✨ Why you'll like it

- 🔗 **Super simple.** Paste a link, hit Start. That's it.
- 🎬 **Video or just the sound.** MP4 in the quality you want, or MP3 / M4A / FLAC.
- ✂️ **Only want a piece?** Type `link 1:20-2:05` and get just that part.
- 📁 **Stays tidy.** Everything goes into folders: YouTube, TikTok, Instagram and more.
- ▶️ **Has its own player** and remembers where you stopped.
- 🌍 **English + Arabic.**
- 🔒 **No account. No ads. No tracking.**

## 📥 Get it

1. Grab **`LEMON-1.0.zip`** from the [**Releases**](https://github.com/7jzzi/lemon-downloader/releases/latest) page.
2. Unzip it anywhere.
3. Open **`LEMON.exe`** and pick where your videos go. Done! 🎉

> [!NOTE]
> Windows might say **"Windows protected your PC"**. That's normal for new apps that aren't code-signed. Click **More info → Run anyway**.

Want the built-in player? Install [VLC](https://www.videolan.org/) (free). Everything else works without it.

## 🎮 Handy keys

| Key | Does |
|---|---|
| `1` `2` `3` `4` | Pick quality |
| `5` | Audio only |
| `Ctrl` + `L` | Jump to the link box |
| `Esc` | Cancel / go back |
| `Space` · `M` · `F` | In the player: pause · mute · fullscreen |

## 🔒 Your privacy

- LEMON **never uploads** your files or settings.
- It only talks to the site you paste a link from, plus GitHub when it checks for updates.
- Updates **always ask first**, and the download is checked before it's installed.
- Cookies (for age-restricted videos) are **off** unless you turn them on.
- Settings and a small log stay on **your** PC.

## ⚖️ Be cool

Only download stuff you own, that's free to share, or that you're allowed to save. LEMON isn't connected to YouTube or any other site.

## 🙏 Made with

[yt-dlp](https://github.com/yt-dlp/yt-dlp) · [ffmpeg](https://ffmpeg.org/) · [VLC](https://www.videolan.org/) · [deno](https://deno.com/) — thank you! More in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

<details>
<summary>🛠️ For developers</summary>

Needs Python 3.12+ with `yt-dlp[default] imageio-ffmpeg deno python-vlc pyinstaller`.

```
python exe_build\build_exe.py --out build
python -m unittest discover -s tests
```

</details>

---

<p align="center"><sub>Free software under the <a href="LICENSE">GPL-3.0</a> · Made with 🍋</sub></p>
