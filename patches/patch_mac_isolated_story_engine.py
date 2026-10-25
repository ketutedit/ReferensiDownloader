from __future__ import annotations

import sys
from pathlib import Path


HELPERS = r'''

def _is_instagram_story_url(url: str) -> bool:
    """Return True only for Instagram Story/Highlight URLs.

    Posts, Reels, and carousel URLs must keep using the existing embedded
    gallery-dl 1.32.16 extractor path.
    """
    from urllib.parse import urlparse

    parsed = urlparse((url or "").strip())
    if (parsed.hostname or "").lower() not in {"instagram.com", "www.instagram.com"}:
        return False
    path = (parsed.path or "").lower()
    return path.startswith("/stories/") or path.rstrip("/").endswith("/highlights")


def _ensure_gallery_dl_story_binary() -> str:
    """Get the official macOS gallery-dl daily binary, refreshing every 48 hours.

    This binary is intentionally separate from the pinned Python gallery-dl
    dependency. Only Instagram Story/Highlight URLs use it, so post/reel/
    carousel extraction remains unchanged.
    """
    import hashlib
    import json
    import os
    import platform
    import shutil
    import tempfile
    import time
    import urllib.request

    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        raise RuntimeError("Mesin Story gallery-dl saat ini hanya disiapkan untuk macOS Apple Silicon.")

    root = (
        Path.home()
        / "Library"
        / "Application Support"
        / "Referensi Downloader"
        / "engines"
    )
    binary_path = root / "gallery-dl-story"
    state_path = root / "gallery-dl-story.json"
    root.mkdir(parents=True, exist_ok=True)

    now = time.time()
    cached_state = {}
    try:
        cached_state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    # Avoid an API/network check on every Story request. The latest verified
    # release is checked at first use and at most once every two days.
    checked_at = cached_state.get("checked_at", 0)
    if (
        binary_path.is_file()
        and os.access(binary_path, os.X_OK)
        and isinstance(checked_at, (int, float))
        and now - checked_at < 48 * 60 * 60
    ):
        return str(binary_path)

    old_binary_is_usable = binary_path.is_file() and os.access(binary_path, os.X_OK)
    try:
        request = urllib.request.Request(
            "https://api.github.com/repos/gdl-org/builds/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "ReferensiDownloader-StoryEngine",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.loads(response.read().decode("utf-8"))

        asset = next(
            (
                entry for entry in (release.get("assets") or [])
                if entry.get("name") == "gallery-dl_macos"
            ),
            None,
        )
        if not asset:
            raise RuntimeError("Rilis gallery-dl resmi tidak menyediakan binary macOS.")

        download_url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "")
        tag = str(release.get("tag_name") or "")
        if (
            not download_url.startswith("https://github.com/gdl-org/builds/releases/download/")
            or not tag
        ):
            raise RuntimeError("Metadata rilis gallery-dl resmi tidak valid.")
        if not digest.startswith("sha256:"):
            raise RuntimeError("Rilis gallery-dl tidak menyediakan SHA-256 untuk verifikasi binary.")

        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": "ReferensiDownloader-StoryEngine"},
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(100 * 1024 * 1024 + 1)
        if not data or len(data) > 100 * 1024 * 1024:
            raise RuntimeError("Ukuran binary gallery-dl tidak valid.")

        actual_digest = hashlib.sha256(data).hexdigest()
        expected_digest = digest.partition(":")[2].lower()
        if actual_digest != expected_digest:
            raise RuntimeError("Verifikasi SHA-256 binary gallery-dl gagal.")

        fd, temporary_name = tempfile.mkstemp(prefix=".gallery-dl-story-", dir=str(root))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(temporary_name, 0o755)

            # Validate that the downloaded executable can start before replacing
            # the last-known-good binary.
            check = __import__("subprocess").run(
                [temporary_name, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if check.returncode != 0:
                raise RuntimeError("Binary gallery-dl terunduh tetapi gagal dijalankan.")

            os.replace(temporary_name, binary_path)
        finally:
            try:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
            except OSError:
                pass

        state_tmp = state_path.with_suffix(".json.tmp")
        state_tmp.write_text(
            json.dumps(
                {"tag": tag, "checked_at": now, "sha256": actual_digest},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(state_tmp, state_path)
        return str(binary_path)

    except Exception as exc:
        # An update outage must not disable an already downloaded verified
        # version. If this is the first run, show the real, useful failure.
        if old_binary_is_usable:
            try:
                state_path.write_text(
                    json.dumps({**cached_state, "checked_at": now, "update_error": str(exc)[:240]}),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return str(binary_path)
        raise RuntimeError(
            "Tidak bisa menyiapkan mesin Instagram Story gallery-dl dari rilis resmi. "
            f"Detail: {type(exc).__name__}: {exc}"
        ) from exc


def _gallery_instagram_story_cli_rows(
    url: str,
    cookie_browser: str | None = None,
    cookie_profile: str | None = None,
    cookie_file: str | None = None,
) -> list[tuple[Any, ...]]:
    """Read Story metadata with the separate daily gallery-dl CLI.

    The CLI emits the same per-media metadata objects as gallery-dl's DataJob.
    The caller continues through the existing MediaItem mapping/download flow.
    No Story files are downloaded by this subprocess.
    """
    import json
    import re
    import subprocess
    from pathlib import Path

    binary = _ensure_gallery_dl_story_binary()
    args = [
        binary,
        "--config-ignore",
        "--no-colors",
        "--quiet",
        "--dump-json",
        "--no-download",
        "--retries", "1",
        "--sleep-request", "0.5-1.0",
        "-o", "extractor.instagram.api=rest",
        "-o", "extractor.instagram.videos=merged",
        "-o", "extractor.instagram.previews=false",
        "-o", "extractor.instagram.include=stories,highlights",
    ]

    if cookie_file:
        cookie_path = Path(cookie_file).expanduser()
        if not cookie_path.is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Pilih ulang file cookie lokal.")
        args.extend(["--cookies", str(cookie_path)])
    else:
        browser = (cookie_browser or "").strip().lower()
        if browser and browser not in {"auto", "none", "disabled", "off"}:
            browser_spec = browser + "/.instagram.com"
            if cookie_profile:
                browser_spec += ":" + str(cookie_profile)
            # gallery-dl syntax is BROWSER[/DOMAIN][:PROFILE]. Keep the cookie
            # source local; no browser cookie or session is uploaded anywhere.
            args.extend(["--cookies-from-browser", browser_spec])

    args.extend(["--", url])
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Instagram Story gagal dianalisis: gallery-dl melewati batas waktu 120 detik.") from exc
    except Exception as exc:
        raise RuntimeError(f"Instagram Story gagal menjalankan gallery-dl: {type(exc).__name__}: {exc}") from exc

    # gallery-dl --dump-json emits the whole DataJob result list as a single
    # pretty-printed JSON array by default. Its elements are message tuples:
    # [3, url, metadata], [2, metadata], [6, url, metadata], or [-1, error].
    # Parsing each output line as a standalone object silently discarded
    # every media row and displayed a random JSON tail as the UI error.
    rows: list[tuple[Any, ...]] = []
    stdout = (completed.stdout or "").strip()
    decoded = None
    if stdout:
        try:
            decoded = json.loads(stdout)
        except Exception:
            # Tolerate JSONL output as a fallback.
            decoded_rows = []
            for line in stdout.splitlines():
                try:
                    decoded_rows.append(json.loads(line))
                except Exception:
                    continue
            decoded = decoded_rows

    if isinstance(decoded, list):
        for value in decoded:
            if isinstance(value, (list, tuple)) and value:
                # Convert JSON arrays into tuples, matching gallery_dl.job.DataJob.data.
                rows.append(tuple(value))
            elif isinstance(value, dict) and value.get("url"):
                rows.append((3, str(value["url"]), value))
    elif isinstance(decoded, dict) and decoded.get("url"):
        rows.append((3, str(decoded["url"]), decoded))

    # Preserve the DataJob protocol so the existing MediaItem mapper handles
    # directory metadata, queued extractors, and direct media URLs consistently.
    if rows and not any(row and row[0] == -1 for row in rows):
        return rows

    error_rows = [
        row[-1] for row in rows
        if row and row[0] == -1 and isinstance(row[-1], dict)
    ]
    if error_rows:
        error = error_rows[0]
        err_name = str(error.get("error") or "AbortExtraction")
        err_message = str(error.get("message") or "Story extractor gagal.")
        # Do not expose signed CDN URLs or session/query tokens.
        err_message = re.sub(r"https?://\S+", "[URL]", err_message)
        raise RuntimeError(f"gallery-dl Instagram Story: {err_name}: {err_message[:500]}")

    detail = (completed.stderr or stdout).strip()
    # Avoid showing signed CDN URLs/query tokens in a GUI error dialog.
    detail = re.sub(r"https?://\S+", "[URL]", detail)
    detail = detail[-700:]
    if completed.returncode != 0:
        raise RuntimeError(
            "Instagram Story gagal diambil oleh gallery-dl "
            f"(kode {completed.returncode}). {detail or 'Tidak ada detail dari extractor.'}"
        )
    raise RuntimeError(
        "gallery-dl tidak mengembalikan pesan media Instagram Story yang valid. "
        f"{detail or 'Pastikan akun dapat melihat Story tersebut dan sesi login masih aktif.'}"
    )

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Patch {label!r} expected exactly one match, found {count}."
        )
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_mac_isolated_story_engine.py SOURCE_ROOT")

    source_root = Path(sys.argv[1]).resolve()
    core_path = source_root / "core.py"
    if not core_path.is_file():
        raise FileNotFoundError(f"core.py not found: {core_path}")

    text = core_path.read_text(encoding="utf-8")

    # Insert Story-only helpers immediately before the already patched
    # _gallery_instagram_once. This is deliberately after the stable Python
    # gallery-dl integration is prepared by patch_core_mac_instagram.py.
    anchor = '''def _gallery_instagram_once(
    url: str,
    cookie_browser: str | None = None,
    cookie_profile: str | None = None,
    cookie_file: str | None = None,
) -> list[MediaItem]:
'''
    if text.count(anchor) != 1:
        raise RuntimeError(
            "Instagram Story engine patch expected the macOS Instagram extractor "
            f"signature once, found {text.count(anchor)}. No files were changed."
        )
    text = text.replace(anchor, HELPERS + "\n" + anchor, 1)

    # Only Story and Highlight URLs switch to the official daily binary.
    # Existing post/reel/carousel URLs continue through the pinned Python package.
    old = '''    task = gdl_job.DataJob(url)
    task.run()
    task_error = getattr(task, "exception", None)
    rows = list(getattr(task, "data", []) or [])
'''
    new = '''    if _is_instagram_story_url(url):
        rows = _gallery_instagram_story_cli_rows(
            url, cookie_browser, cookie_profile, cookie_file
        )
        task_error = None
    else:
        task = gdl_job.DataJob(url)
        task.run()
        task_error = getattr(task, "exception", None)
        rows = list(getattr(task, "data", []) or [])
'''
    text = replace_once(
        text,
        old,
        new,
        "isolate daily gallery-dl binary to Story/Highlight URLs",
    )

    compile(text, str(core_path), "exec")
    core_path.write_text(text, encoding="utf-8")
    print("Isolated Instagram Story engine patch applied; core.py syntax check passed.")
    print("Only /stories/ and /highlights URLs use the daily binary; post/reel/carousel remain on the pinned Python engine.")


if __name__ == "__main__":
    main()
