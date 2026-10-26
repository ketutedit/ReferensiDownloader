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
        raise SystemExit("Usage: test_windows_time_range.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    import shutil

    binary_dir = root / "vendor" / "bin"

    def locate_binary(name: str) -> Path | None:
        suffix = ".exe" if os.name == "nt" else ""
        candidates = [
            binary_dir / (name + suffix),
            root / "bin" / (name + suffix),
            root / "vendor" / (name + suffix),
            root / (name + suffix),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        discovered = shutil.which(name)
        return Path(discovered) if discovered else None

    ffmpeg = locate_binary("ffmpeg")
    ffprobe = locate_binary("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise RuntimeError(
            "Bundled FFmpeg/FFprobe not found. "
            "Expected vendor/bin/ffmpeg.exe and vendor/bin/ffprobe.exe (Windows)."
        )
    bin_dir = ffmpeg.parent
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))

    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit
    qt_app = QApplication.instance() or QApplication([])

    import core
    import app
    import yt_dlp
    from yt_dlp.utils import download_range_func

    assert app._parse_timecode("35:44") == 2144
    assert app._parse_timecode("00:35:44") == 2144
    assert app._parse_timecode("36:00") == 2160
    assert app._parse_timecode("90") == 90
    assert app._format_timecode(2144) == "00:35:44"

    # The time fields use an input mask so separators stay fixed while users
    # can type just the six digits. Analyze should populate End from the source
    # video duration and reset Start to zero.
    start_edit = QLineEdit()
    end_edit = QLineEdit()
    for edit in (start_edit, end_edit):
        edit.setInputMask("00:00:00;_")
        edit.setText("00:00:00")
    dummy_window = SimpleNamespace(time_range_start=start_edit, time_range_end=end_edit)
    app.MainWindow._set_time_range_defaults(
        dummy_window, SimpleNamespace(duration=635.8, items=[])
    )
    assert start_edit.text() == "00:00:00"
    assert end_edit.text() == "00:10:35", end_edit.text()
    start_edit.setCursorPosition(0)
    QTest.keyClicks(start_edit, "000822")
    assert start_edit.text() == "00:08:22", start_edit.text()
    assert app._parse_timecode(start_edit.text()) == 502
    # If MediaInfo has no duration, the first media item duration is used.
    app.MainWindow._set_time_range_defaults(
        dummy_window,
        SimpleNamespace(duration=0, items=[SimpleNamespace(duration=130.5)]),
    )
    assert end_edit.text() == "00:02:10", end_edit.text()

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

        class QuietRangeHandler(SimpleHTTPRequestHandler):
            """Minimal single-file HTTP server with byte-range support for FFmpeg."""
            def __init__(self, *args, directory=None, **kwargs):
                self._range_length = None
                super().__init__(*args, directory=directory, **kwargs)

            def log_message(self, *_):
                pass

            def send_head(self):
                self._range_length = None
                path = self.translate_path(self.path)
                if os.path.isdir(path):
                    return super().send_head()
                try:
                    source = open(path, "rb")
                except OSError:
                    self.send_error(404, "File not found")
                    return None

                size = os.fstat(source.fileno()).st_size
                range_header = self.headers.get("Range")
                start, end = 0, size - 1
                status = 200
                if range_header:
                    match = __import__("re").fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                    if not match or (not match.group(1) and not match.group(2)):
                        source.close()
                        self.send_error(416, "Invalid byte range")
                        return None
                    if not match.group(1):
                        length = min(int(match.group(2)), size)
                        start = max(0, size - length)
                    else:
                        start = int(match.group(1))
                        end = int(match.group(2)) if match.group(2) else size - 1
                    end = min(end, size - 1)
                    if start >= size or start > end:
                        source.close()
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return None
                    status = 206
                    self._range_length = end - start + 1
                    source.seek(start)
                else:
                    self._range_length = None

                self.send_response(status)
                self.send_header("Content-Type", self.guess_type(path))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(self._range_length if status == 206 else size))
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Last-Modified", self.date_time_string(os.path.getmtime(path)))
                self.end_headers()
                return source

            def copyfile(self, source, outputfile):
                remaining = self._range_length
                if remaining is None:
                    return super().copyfile(source, outputfile)
                while remaining > 0:
                    block = source.read(min(64 * 1024, remaining))
                    if not block:
                        break
                    outputfile.write(block)
                    remaining -= len(block)

        handler = partial(QuietRangeHandler, directory=str(base))
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
    print("TIME_RANGE_INPUT_MASK_TEST=PASS")
    print("TIME_RANGE_AUTO_DURATION_TEST=PASS")
    print("TIME_RANGE_YTDLP_OPTIONS_TEST=PASS")
    print(f"TIME_RANGE_CLIP_INTEGRATION_TEST=PASS duration={duration:.3f}s file={output.name}")


if __name__ == "__main__":
    main()
