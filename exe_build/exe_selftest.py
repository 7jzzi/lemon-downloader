
# Throwaway test hook (build_exe.py --selftest only): with LEMON_SELFTEST=<out.txt> set, check the built-in
# helpers, do one real tiny download, write the result to that file and exit.
if os.environ.get("LEMON_SELFTEST"):
    _out = []
    try:
        _out.append(f"frozen={getattr(sys, 'frozen', False)} helpers_ready={helpers_ready()} yt_dlp={ytdlp_version()}")
        import yt_dlp
        _out.append(f"yt_dlp loaded from: {yt_dlp.__file__}")
        _ff = find_ffmpeg()
        _out.append(f"ffmpeg={_ff} exists={bool(_ff and os.path.exists(_ff))}")
        _out.append(f"js_runtime={find_js_runtime()}")
        if os.environ.get("LEMON_SELFTEST_DIR"):
            _d = Download(os.environ.get("LEMON_SELFTEST_URL", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
                          os.environ["LEMON_SELFTEST_DIR"], 360, audio=bool(os.environ.get("LEMON_SELFTEST_AUDIO")),
                          cookies=os.environ.get("LEMON_SELFTEST_COOKIES", ""))
            _d.run()
            _out.append(f"download error={_d.error} path={_d.path} exists={bool(_d.path and os.path.exists(_d.path))}")
    except BaseException:  # noqa: BLE001
        import traceback
        _out.append("CRASH " + traceback.format_exc())
    open(os.environ["LEMON_SELFTEST"], "w", encoding="utf-8").write("\n".join(_out))
    os._exit(0)

