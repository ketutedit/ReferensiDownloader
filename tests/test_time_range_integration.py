from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=True)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_time_range_integration.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    bin_dir = root / "vendor" / "bin"
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe = bin_dir / "ffprobe"
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise RuntimeError("Bundled FFmpeg/FFprobe not found after macOS packaging.")

    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    sys.path.insert(0, str(root))

    import core
    import app
    import yt_dlp
    from yt_dlp.utils import download_range_func

    assert app._parse_timecode("35:44") == 2144
    assert app._parse_timecode("00:35:44") == 2144
    assert app._parse_timecode("36:00") == 2160
    assert app._parse_timecode("90") == 90
    assert app._format_timecode(2144) == "00:35:44"

    # Exercise Referensi Downloader's actual option builder with a fake YDL,
    # and assert the range is forwarded as expected without a network request.
    captured: dict = {}

    class FakeYDL:
        def __init__(self, opts):
            captured.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def download(self, urls):
            captured["urls"] = list(urls)
            return 0

    original_ydl = core.yt_dlp.YoutubeDL
    core.yt_dlp.YoutubeDL = FakeYDL
    try:
        with tempfile.TemporaryDirectory(prefix="rd-range-options-") as temp:
            core._download_once(
                "https://example.com/sample.mp4",
                temp,
                None,
                "mp4",
                False,
                None,
                time_range=(2144.0, 2160.0),
            )
    finally:
        core.yt_dlp.YoutubeDL = original_ydl

    assert "download_ranges" in captured, "time range did not reach yt-dlp options"
    assert captured.get("force_keyframes_at_cuts") is True
    assert "Clip 00-35-44 to 00-36-00 - " in captured["outtmpl"]["default"]
    selected = list(captured["download_ranges"]({"duration": 3000}, None))
    assert selected == [{"start_time": 2144.0, "end_time": 2160.0}], selected

    # Integration check using a generated 12-second video served over local
    # HTTP: download only seconds 3-6 and verify the produced media is ~3 sec.
    with tempfile.TemporaryDirectory(prefix="rd-range-integration-") as temp:
        base = Path(temp)
        input_path = base / "synthetic-source.mp4"
        output_dir = base / "output"
        output_dir.mkdir()
        run([
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
            "-t", "12", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(input_path),
        ])

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        handler = partial(QuietHandler, directory=str(base))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/synthetic-source.mp4"
            options = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "outtmpl": str(output_dir / "clip.%(ext)s"),
                "ffmpeg_location": str(bin_dir),
                "download_ranges": download_range_func(None, [(3.0, 6.0)]),
                "force_keyframes_at_cuts": True,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                code = ydl.download([url])
            if code not in (None, 0):
                raise RuntimeError(f"yt-dlp returned {code} in range integration test.")

            outputs = [
                p for p in output_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
            ]
            if not outputs:
                raise RuntimeError("yt-dlp did not produce an output clip.")
            output = outputs[0]
            probe = run([
                str(ffprobe), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(output),
            ])
            duration = float(probe.stdout.strip())
            if not 2.4 <= duration <= 3.6:
                raise RuntimeError(f"Expected a ~3s clip, got {duration:.3f}s ({output.name}).")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    print("TIME_RANGE_PARSE_TEST=PASS")
    print("TIME_RANGE_YTDLP_OPTIONS_TEST=PASS")
    print(f"TIME_RANGE_CLIP_INTEGRATION_TEST=PASS duration={duration:.3f}s file={output.name}")


if __name__ == "__main__":
    main()
