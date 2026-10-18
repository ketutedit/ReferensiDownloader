from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch {label!r} expected exactly one match, found {count}.")
    return text.replace(old, new, 1)


def patch_core(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''def _download_once(
    url: str,
    output_dir: str,
    height: int | None,
    container: str,
    audio_only: bool,
    progress_cb: Callable[[dict[str, Any]], None] | None,
    player_clients: list[str] | None = None,
    editing_compatible: bool = False,
    cookie_browser: str | None = None,
    playlist_index: int | None = None,
    filename_prefix: str = "",
) -> None:
''',
        '''def _clip_filename_timestamp(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}"


def _download_once(
    url: str,
    output_dir: str,
    height: int | None,
    container: str,
    audio_only: bool,
    progress_cb: Callable[[dict[str, Any]], None] | None,
    player_clients: list[str] | None = None,
    editing_compatible: bool = False,
    cookie_browser: str | None = None,
    playlist_index: int | None = None,
    filename_prefix: str = "",
    time_range: tuple[float, float] | None = None,
) -> None:
''',
        "add time range support to _download_once",
    )

    text = replace_once(
        text,
        '''    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    temp_root: Path | None = None
''',
        '''    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    if time_range is not None:
        start_time, end_time = time_range
        clip_label = (
            f"Clip {_clip_filename_timestamp(start_time)} "
            f"to {_clip_filename_timestamp(end_time)} - "
        )
        filename_prefix = f"{filename_prefix}{clip_label}"

    temp_root: Path | None = None
''',
        "label clipped output filenames",
    )

    text = replace_once(
        text,
        '''    opts.update(_youtube_engine_options(url, player_clients))
    opts.update(_cookie_options(cookie_browser))
    if playlist_index is not None:
''',
        '''    opts.update(_youtube_engine_options(url, player_clients))
    opts.update(_cookie_options(cookie_browser))
    if time_range is not None:
        from yt_dlp.utils import download_range_func

        start_time, end_time = time_range
        # Python API equivalent of yt-dlp's --download-sections "*START-END".
        # Force keyframes at the trim boundaries for frame-accurate segment edges.
        opts["download_ranges"] = download_range_func(None, [(start_time, end_time)])
        opts["force_keyframes_at_cuts"] = True

    if playlist_index is not None:
''',
        "configure yt-dlp section downloading",
    )

    text = replace_once(
        text,
        '''def download_media(
    url: str,
    output_dir: str,
    height: int | None,
    container: str,
    audio_only: bool,
    editing_compatible: bool = False,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cookie_browser: str | None = "auto",
    playlist_index: int | None = None,
    filename_prefix: str = "",
) -> None:
''',
        '''def download_media(
    url: str,
    output_dir: str,
    height: int | None,
    container: str,
    audio_only: bool,
    editing_compatible: bool = False,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cookie_browser: str | None = "auto",
    playlist_index: int | None = None,
    filename_prefix: str = "",
    time_range: tuple[float, float] | None = None,
) -> None:
''',
        "add time range to public download API",
    )

    text = replace_once(
        text,
        '''    if yt_dlp is None:
        raise RuntimeError("yt-dlp belum terpasang.")
    if editing_compatible and not audio_only and shutil.which("ffmpeg") is None:
''',
        '''    if yt_dlp is None:
        raise RuntimeError("yt-dlp belum terpasang.")
    if time_range is not None:
        start_time, end_time = time_range
        if start_time < 0 or end_time <= start_time:
            raise ValueError("Rentang waktu tidak valid: End harus lebih besar dari Start.")
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("FFmpeg diperlukan untuk memotong video berdasarkan rentang waktu.")
    if editing_compatible and not audio_only and shutil.which("ffmpeg") is None:
''',
        "validate range and ensure ffmpeg exists",
    )

    # Pass the range through each retry path in download_media. The named
    # keyword is kept optional so all pre-existing callers behave unchanged.
    start = text.index("def download_media(")
    prefix, body = text[:start], text[start:]
    needle = "filename_prefix=filename_prefix,"
    count = body.count(needle)
    if count < 1:
        raise RuntimeError("Patch 'propagate time_range' found no download_media call sites.")
    body = body.replace(needle, "filename_prefix=filename_prefix, time_range=time_range,")
    text = prefix + body

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print(f"core.py time-range patch passed syntax check; propagated through {count} download attempt(s).")


def patch_app(source_root: Path) -> None:
    path = source_root / "app.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''class AnalyzeWorker(QObject):
''',
        '''def _parse_timecode(value: str) -> float:
    """Parse seconds, MM:SS, or HH:MM:SS into seconds."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Isi kedua kolom Start dan End.")
    parts = raw.split(":")
    if len(parts) > 3 or any(part.strip() == "" for part in parts):
        raise ValueError("Format waktu harus SS, MM:SS, atau HH:MM:SS.")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            tail_seconds = float(parts[1])
            if minutes < 0 or not (0 <= tail_seconds < 60):
                raise ValueError
            seconds = minutes * 60 + tail_seconds
        else:
            hours = int(parts[0])
            minutes = int(parts[1])
            tail_seconds = float(parts[2])
            if hours < 0 or not (0 <= minutes < 60) or not (0 <= tail_seconds < 60):
                raise ValueError
            seconds = hours * 3600 + minutes * 60 + tail_seconds
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Format waktu tidak valid. Gunakan SS, MM:SS, atau HH:MM:SS.") from None
    if not (seconds >= 0 and seconds < float("inf")):
        raise ValueError("Waktu harus berupa angka positif yang valid.")
    return seconds


def _format_timecode(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class AnalyzeWorker(QObject):
''',
        "add timecode parser and display formatter",
    )

    text = replace_once(
        text,
        '''        self.audio_only = QCheckBox("Audio only (MP3)"); self.audio_only.setMinimumHeight(30); self.audio_only.toggled.connect(self._audio_toggled); sl.addWidget(self.audio_only)
''',
        '''        # Optional clip range: unchecked by default, preserving full-download behavior.
        trrow = QHBoxLayout()
        trlabel = QLabel("Time Range"); trlabel.setFixedWidth(86)
        self.time_range_enabled = QCheckBox("Download only this segment")
        self.time_range_enabled.setToolTip("Potong satu video berdasarkan waktu. Format: MM:SS atau HH:MM:SS.")
        self.time_range_start = QLineEdit(); self.time_range_start.setPlaceholderText("Start 00:35:44")
        self.time_range_end = QLineEdit(); self.time_range_end.setPlaceholderText("End 00:36:00")
        self.time_range_start.setToolTip("Contoh: 35:44 atau 00:35:44")
        self.time_range_end.setToolTip("Contoh: 36:00 atau 00:36:00")
        self.time_range_start.setMaximumWidth(180); self.time_range_end.setMaximumWidth(180)
        self.time_range_start.setEnabled(False); self.time_range_end.setEnabled(False)
        self.time_range_enabled.toggled.connect(self._time_range_toggled)
        trrow.addWidget(trlabel); trrow.addWidget(self.time_range_enabled)
        trrow.addWidget(QLabel("Start")); trrow.addWidget(self.time_range_start, 1)
        trrow.addWidget(QLabel("End")); trrow.addWidget(self.time_range_end, 1)
        sl.addLayout(trrow)

        self.audio_only = QCheckBox("Audio only (MP3)"); self.audio_only.setMinimumHeight(30); self.audio_only.toggled.connect(self._audio_toggled); sl.addWidget(self.audio_only)
''',
        "add optional clip-range controls",
    )

    text = replace_once(
        text,
        '''    def _browser_changed(self, *_):
        self.settings.setValue("cookie_browser", self.browser_session.currentData())
''',
        '''    def _time_range_toggled(self, enabled: bool):
        self.time_range_start.setEnabled(bool(enabled))
        self.time_range_end.setEnabled(bool(enabled))

    def _browser_changed(self, *_):
        self.settings.setValue("cookie_browser", self.browser_session.currentData())
''',
        "enable and disable timecode inputs",
    )

    text = replace_once(
        text,
        '''        all_items = self._post_item_is_all()
        item = self._selected_media_item()
        if not all_items and item is None:
            return

        out = self.output_edit.text().strip() or str(default_download_dir())
''',
        '''        all_items = self._post_item_is_all()
        item = self._selected_media_item()
        if not all_items and item is None:
            return

        time_range = None
        if self.time_range_enabled.isChecked():
            if all_items:
                QMessageBox.warning(
                    self, "Time Range",
                    "Time Range hanya bisa dipakai untuk satu video. Pilih satu video, bukan All Items.",
                )
                return
            if item is None or item.media_type != "video":
                QMessageBox.warning(self, "Time Range", "Time Range hanya tersedia untuk media video, bukan foto.")
                return
            try:
                start_time = _parse_timecode(self.time_range_start.text())
                end_time = _parse_timecode(self.time_range_end.text())
            except ValueError as exc:
                QMessageBox.warning(self, "Time Range", str(exc))
                return
            if end_time <= start_time:
                QMessageBox.warning(self, "Time Range", "End harus lebih besar daripada Start.")
                return
            duration = item.duration or self.media.duration
            if duration and end_time > float(duration) + 0.25:
                QMessageBox.warning(
                    self, "Time Range",
                    f"End ({_format_timecode(end_time)}) melebihi durasi video ({_format_timecode(float(duration))}).",
                )
                return
            time_range = (start_time, end_time)

        out = self.output_edit.text().strip() or str(default_download_dir())
''',
        "validate range before starting a worker",
    )

    text = replace_once(
        text,
        '''        self.download_btn.setEnabled(False); self.analyze_btn.setEnabled(False); self.progress.setValue(0)
''',
        '''        if time_range is not None:
            self.status.setText(
                f"Starting segment download • {_format_timecode(time_range[0])}–{_format_timecode(time_range[1])}…"
            )

        self.download_btn.setEnabled(False); self.analyze_btn.setEnabled(False); self.progress.setValue(0)
''',
        "show active range in status",
    )

    text = replace_once(
        text,
        '''            post_total_items=self.media.total_items,
        )
''',
        '''            post_total_items=self.media.total_items,
            time_range=time_range,
        )
''',
        "pass range into DownloadWorker",
    )

    # DownloadWorker receives the optional range and sends it through both the
    # single-video path and selected Instagram-video path.
    text = replace_once(
        text,
        '''        cookie_browser, playlist_index=None, media_items=None, post_total_items=1,
    ):
''',
        '''        cookie_browser, playlist_index=None, media_items=None, post_total_items=1,
        time_range=None,
    ):
''',
        "extend DownloadWorker constructor",
    )

    text = replace_once(
        text,
        '''        self.post_total_items = max(1, int(post_total_items or 1))
''',
        '''        self.post_total_items = max(1, int(post_total_items or 1))
        self.time_range = time_range
''',
        "store range on worker",
    )

    text = replace_once(
        text,
        '''                    cookie_browser=self.cookie_browser, playlist_index=playlist_index,
                    filename_prefix=prefix,
                )
            except Exception:
                # gallery-dl gives us a direct Instagram media URL during
''',
        '''                    cookie_browser=self.cookie_browser, playlist_index=playlist_index,
                    filename_prefix=prefix, time_range=self.time_range,
                )
            except Exception:
                # Segment mode must not fall back to streaming the entire direct
                # URL, because that bypasses the requested time range.
                if self.time_range is not None:
                    raise
                # gallery-dl gives us a direct Instagram media URL during
''',
        "propagate range and preserve clip semantics on Instagram",
    )

    text = replace_once(
        text,
        '''                download_media(
                    *self.args, progress_cb=hook, cookie_browser=self.cookie_browser,
                    playlist_index=self.playlist_index,
                )
''',
        '''                download_media(
                    *self.args, progress_cb=hook, cookie_browser=self.cookie_browser,
                    playlist_index=self.playlist_index, time_range=self.time_range,
                )
''',
        "propagate range for normal video download",
    )

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("app.py time-range patch passed syntax check.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_time_range.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not (source_root / "core.py").is_file() or not (source_root / "app.py").is_file():
        raise FileNotFoundError(f"Expected core.py and app.py under {source_root}")
    patch_core(source_root)
    patch_app(source_root)
    print("Time Range feature patch complete.")


if __name__ == "__main__":
    main()
