from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch {label!r} expected one exact match, found {count}.")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_core_windows_smart_mp4.py SOURCE_ROOT")

    source_root = Path(sys.argv[1]).resolve()
    core_path = source_root / "core.py"
    if not core_path.is_file():
        raise FileNotFoundError(f"core.py not found: {core_path}")

    text = core_path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''def clean_error(error: Exception | str) -> str:
    text = ANSI_RE.sub("", str(error)).strip()
    text = re.sub(r"\\s*ERROR:\\s*", "", text, count=1, flags=re.IGNORECASE)
    return text or "Terjadi error yang tidak diketahui."
''',
        '''def clean_error(
    error: Exception | str,
    fallback: str = "Terjadi error yang tidak diketahui.",
) -> str:
    text = ANSI_RE.sub("", str(error or "")).strip()
    text = re.sub(r"\\s*ERROR:\\s*", "", text, count=1, flags=re.IGNORECASE)
    return text or fallback
''',
        "preserve useful error messages",
    )

    text = replace_once(
        text,
        '''            video_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
''',
        '''            # Windows CPUs can run out of resources on 4K/8K conversions with
            # libx264's automatic thread count. Keep quality (CRF 18) while using
            # a faster preset and a bounded number of encoder threads.
            video_args = [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-threads", "4", "-pix_fmt", "yuv420p",
            ]
''',
        "bound H.264 encoding resources on Windows",
    )

    text = replace_once(
        text,
        '''    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        bufsize=1, universal_newlines=True,
    )
    try:
        if proc.stdout:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in {"out_time_us", "out_time_ms"} and duration:
                    try:
                        seconds = float(value) / 1_000_000.0
                        pct = max(0.0, min(100.0, seconds / duration * 100.0))
                        if progress_cb:
                            progress_cb({"status": status, "percent": pct})
                    except ValueError:
                        pass
        stderr = proc.stderr.read() if proc.stderr else ""
        code = proc.wait()
    except Exception:
        proc.kill()
        raise

    if code != 0:
        destination.unlink(missing_ok=True)
        msg = clean_error(stderr) or f"FFmpeg berhenti dengan kode {code}."
        raise RuntimeError(f"Pemrosesan Smart Editing MP4 gagal: {msg}")
''',
        '''    # Merge FFmpeg diagnostics into the progress stream so stderr cannot fill
    # its pipe while the worker is reading progress from stdout. Keep non-progress
    # lines for a useful error if conversion fails.
    progress_keys = {
        "frame", "fps", "stream_0_0_q", "bitrate", "total_size",
        "out_time_us", "out_time_ms", "out_time", "dup_frames",
        "drop_frames", "speed", "progress",
    }
    diagnostics: list[str] = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        bufsize=1, universal_newlines=True,
    )
    try:
        if proc.stdout:
            for line in proc.stdout:
                stripped = line.strip()
                key, separator, value = stripped.partition("=")
                if key in {"out_time_us", "out_time_ms"} and duration:
                    try:
                        seconds = float(value) / 1_000_000.0
                        pct = max(0.0, min(100.0, seconds / duration * 100.0))
                        if progress_cb:
                            progress_cb({"status": status, "percent": pct})
                    except ValueError:
                        pass
                elif stripped and (not separator or key not in progress_keys):
                    diagnostics.append(stripped)
        code = proc.wait()
    except Exception:
        proc.kill()
        raise

    if code != 0:
        destination.unlink(missing_ok=True)
        msg = clean_error("\\n".join(diagnostics), fallback="")
        if not msg:
            msg = (
                f"FFmpeg berhenti dengan kode {code} tanpa pesan diagnostik. "
                "Windows mungkin menghentikan proses karena RAM atau ruang disk tidak cukup. "
                "Coba tutup aplikasi lain, pastikan ruang disk tersedia, atau pilih resolusi "
                "lebih rendah / Mode Original / Source Codec."
            )
        raise RuntimeError(f"Pemrosesan Smart Editing MP4 gagal: {msg}")
''',
        "capture FFmpeg diagnostics and explain empty failures",
    )

    core_path.write_text(text, encoding="utf-8")
    compile(text, str(core_path), "exec")
    print("Windows Smart Editing patch applied and core.py syntax check passed.")
    print("Changes: bounded H.264 threads, safer preset, merged FFmpeg output, meaningful failures.")


if __name__ == "__main__":
    main()
