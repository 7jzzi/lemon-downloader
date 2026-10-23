# Third-party software

LEMON.exe bundles these programs and libraries. Each keeps its own license; see the linked projects for the full text. LEMON itself is under the GPL-3.0 (see `LICENSE`), which is compatible with the GPL parts above.

| Component | What for | License |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) and yt-dlp-ejs | finds and downloads the videos | Unlicense (public domain) |
| [FFmpeg](https://ffmpeg.org/) (via [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)) | joins video and audio, cuts clips, converts audio | LGPL / GPL, depending on the build |
| [Deno](https://deno.land/) | runs the JavaScript YouTube needs | MIT |
| [mutagen](https://github.com/quodlibet/mutagen) | writes tags and cover pictures | GPL-2.0-or-later |
| python-vlc | controls VLC for the preview player | LGPL-2.1-or-later |
| requests, urllib3, certifi, websockets, brotli, pycryptodomex, curl_cffi | networking and crypto used by yt-dlp | Apache-2.0 / MIT / MPL-2.0 / BSD |
| Python and Tk | the runtime and the window | PSF License |

VLC itself is **not** bundled: install it separately from videolan.org if you want the preview player.
