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
        raise SystemExit("Usage: patch_core_windows_instagram.py SOURCE_ROOT")

    source_root = Path(sys.argv[1]).resolve()
    core_path = source_root / "core.py"
    if not core_path.is_file():
        raise FileNotFoundError(f"core.py not found: {core_path}")

    text = core_path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''def _browser_candidates(selection: str | None) -> list[str]:
    selection = (selection or "auto").strip().lower()
    if selection in {"", "none", "disabled", "off"}:
        return []
    if selection != "auto":
        return [selection]

    # Safari cookies are macOS-only. Chromium/Firefox cookie extraction is
    # supported by yt-dlp/gallery-dl on Windows as well.
    if sys.platform == "darwin":
        ordered = ["chrome", "brave", "edge", "firefox", "safari"]
    elif os.name == "nt":
        ordered = ["chrome", "brave", "edge", "firefox"]
    else:
        ordered = ["chrome", "brave", "edge", "firefox"]
    installed = [b for b in ordered if _browser_installed(b)]
    return installed or ordered


''',
        '''def _browser_candidates(selection: str | None) -> list[str]:
    selection = (selection or "auto").strip().lower()
    if selection in {"", "none", "disabled", "off"}:
        return []
    if selection != "auto":
        return [selection]

    # Safari cookies are macOS-only. Chromium/Firefox cookie extraction is
    # supported by yt-dlp/gallery-dl on Windows as well.
    if sys.platform == "darwin":
        ordered = ["chrome", "brave", "edge", "firefox", "safari"]
    elif os.name == "nt":
        ordered = ["chrome", "brave", "edge", "firefox"]
    else:
        ordered = ["chrome", "brave", "edge", "firefox"]
    # Automatic must still try each browser's standard profile path. A profile
    # can be valid even when the app's lightweight directory check misses it
    # (custom installation, custom user-data directory, or a delayed profile).
    # gallery-dl will report a clear error for browsers that are unavailable.
    return ordered


def _browser_profile_candidates(browser: str) -> list[str | None]:
    """Try the browser default first, then existing Windows user profiles.

    A logged-in Instagram session may live in a non-default Edge/Chrome
    profile. gallery-dl accepts a profile name or an absolute profile path.
    """
    candidates: list[str | None] = [None]
    if os.name != "nt":
        return candidates

    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    roaming = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    roots = {
        "chrome": local / "Google" / "Chrome" / "User Data",
        "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
        "edge": local / "Microsoft" / "Edge" / "User Data",
        "firefox": roaming / "Mozilla" / "Firefox" / "Profiles",
    }
    root = roots.get(browser)
    if root is None or not root.is_dir():
        return candidates

    try:
        profiles = sorted(root.iterdir(), key=lambda p: (p.name.lower() != "default", p.name.lower()))
    except OSError:
        return candidates

    for profile in profiles:
        if not profile.is_dir():
            continue
        if browser == "firefox":
            has_database = (profile / "cookies.sqlite").is_file()
        else:
            has_database = (
                (profile / "Network" / "Cookies").is_file()
                or (profile / "Cookies").is_file()
            )
        if has_database:
            candidates.append(str(profile))

    return candidates


''',
        "enumerate browser profiles",
    )

    text = replace_once(
        text,
        '''def _gallery_cookie_tuple(browser: str | None) -> tuple[str, None, None, None, str] | None:
    if not browser:
        return None
    return (browser, None, None, None, ".instagram.com")
''',
        '''def _gallery_cookie_tuple(
    browser: str | None, profile: str | None = None,
) -> tuple[str, str | None, None, None, str] | None:
    if not browser:
        return None
    return (browser, profile, None, None, ".instagram.com")
''',
        "pass selected browser profile into gallery-dl",
    )

    text = replace_once(
        text,
        '''def _gallery_instagram_once(url: str, cookie_browser: str | None = None) -> list[MediaItem]:
''',
        '''def _gallery_instagram_once(
    url: str,
    cookie_browser: str | None = None,
    cookie_profile: str | None = None,
) -> list[MediaItem]:
''',
        "accept profile while extracting Instagram media",
    )

    text = replace_once(
        text,
        '''    gdl_config.clear()
    gdl_config.set(("extractor", "instagram"), "videos", "merged")
    gdl_config.set(("extractor", "instagram"), "previews", False)
    gdl_config.set(("extractor", "instagram"), "sleep-request", 0.0)
    cookie_value = _gallery_cookie_tuple(cookie_browser)
    if cookie_value:
        gdl_config.set((), "cookies", cookie_value)

    task = gdl_job.DataJob(url)
    task.run()
    rows = list(getattr(task, "data", []) or [])
''',
        '''    gdl_config.clear()
    gdl_config.set(("extractor", "instagram"), "api", "rest")
    gdl_config.set(("extractor", "instagram"), "videos", "merged")
    gdl_config.set(("extractor", "instagram"), "previews", False)
    gdl_config.set(("extractor", "instagram"), "sleep-request", 0.0)

    # gallery-dl defaults Instagram profile extraction to posts only. Set the
    # matching category explicitly for direct Story/Reel/Highlight links.
    path = (urlparse(url).path or "").lower()
    if path.startswith("/stories/"):
        include = "stories,highlights"
    elif path.startswith("/highlights/") or path.rstrip("/").endswith("/highlights"):
        include = "highlights"
    elif path.startswith("/reel/") or path.startswith("/reels/"):
        include = "reels"
    else:
        include = "posts"
    gdl_config.set(("extractor", "instagram"), "include", include)

    # gallery-dl defaults user ID lookup to topsearch + profile HTML scraping.
    # Both can fail when Instagram serves a login/challenge page on Windows.
    # Try the authenticated web_profile_info endpoint first, then retain the
    # original strategies as fallbacks.
    gdl_config.set(("extractor", "instagram"), "user-strategy", "info,web,search")
    gdl_config.set(("extractor", "instagram"), "user-cache", False)

    cookie_value = _gallery_cookie_tuple(cookie_browser, cookie_profile)
    if cookie_value:
        gdl_config.set((), "cookies", cookie_value)

    task = gdl_job.DataJob(url)
    task.run()
    task_error = getattr(task, "exception", None)
    rows = list(getattr(task, "data", []) or [])
''',
        "explicit Instagram media categories and capture DataJob exception",
    )

    text = replace_once(
        text,
        '''    items.sort(key=lambda item: item.slide_index)
    if not items:
        raise RuntimeError("Instagram tidak mengembalikan media foto/video yang bisa diunduh.")
    return items
''',
        '''    items.sort(key=lambda item: item.slide_index)
    if not items:
        # DataJob stores extractor failures in .exception instead of raising
        # from run(). Preserve the real cause; otherwise cookie/profile/API
        # failures look like a valid post that simply contains no media.
        if task_error is not None:
            details = clean_error(
                f"{type(task_error).__name__}: {task_error}",
                fallback="gallery-dl gagal mengambil media Instagram.",
            )
            raise RuntimeError(f"gallery-dl Instagram: {details}") from task_error
        raise RuntimeError("Instagram tidak mengembalikan media foto/video yang bisa diunduh.")
    return items
''',
        "surface gallery-dl's real exception",
    )

    text = replace_once(
        text,
        '''def _gallery_instagram_media(url: str, cookie_browser: str | None = "auto") -> tuple[list[MediaItem], str | None]:
    """Try Instagram anonymously, then with the chosen browser session."""
    explicit = (cookie_browser or "auto").strip().lower()
    if explicit not in {"auto", "", "none", "disabled", "off"}:
        try:
            return _gallery_instagram_once(url, explicit), explicit
        except Exception as exc:
            raise RuntimeError(clean_error(exc)) from exc

    first_error: Exception | None = None
    try:
        return _gallery_instagram_once(url), None
    except Exception as exc:
        first_error = exc

    errors: list[tuple[str, Exception]] = []
    for browser in _browser_candidates(cookie_browser):
        try:
            return _gallery_instagram_once(url, browser), browser
        except Exception as exc:
            errors.append((browser, exc))
    if errors:
        raise RuntimeError(_friendly_cookie_error(errors)) from first_error
    raise RuntimeError(clean_error(first_error or "Instagram media extraction gagal."))
''',
        '''def _gallery_instagram_media(url: str, cookie_browser: str | None = "auto") -> tuple[list[MediaItem], str | None]:
    """Try Instagram anonymously, then browser cookies and detected profiles."""
    explicit = (cookie_browser or "auto").strip().lower()
    if explicit not in {"auto", "", "none", "disabled", "off"}:
        errors: list[tuple[str, Exception]] = []
        for profile in _browser_profile_candidates(explicit):
            try:
                return _gallery_instagram_once(url, explicit, profile), explicit
            except Exception as exc:
                label = explicit if not profile else f"{explicit} ({Path(profile).name})"
                errors.append((label, exc))
        if errors:
            raise RuntimeError(_friendly_cookie_error(errors)) from errors[0][1]
        raise RuntimeError("Instagram gagal dianalisis menggunakan browser yang dipilih.")

    first_error: Exception | None = None
    try:
        return _gallery_instagram_once(url), None
    except Exception as exc:
        first_error = exc

    errors: list[tuple[str, Exception]] = []
    for browser in _browser_candidates(cookie_browser):
        for profile in _browser_profile_candidates(browser):
            try:
                return _gallery_instagram_once(url, browser, profile), browser
            except Exception as exc:
                label = browser if not profile else f"{browser} ({Path(profile).name})"
                errors.append((label, exc))
    if errors:
        raise RuntimeError(_friendly_cookie_error(errors)) from first_error
    raise RuntimeError(clean_error(first_error or "Instagram media extraction gagal."))
''',
        "try all detected Windows browser profiles",
    )

    text = replace_once(
        text,
        '''def _friendly_cookie_error(errors: list[tuple[str, Exception]]) -> str:
    if not errors:
        return (
            "Website meminta login. Pilih browser yang sudah login pada menu Website Login "
            "lalu coba lagi."
        )
    details = []
    for browser, exc in errors[:3]:
        text = clean_error(exc).replace("\\n", " ")
        details.append(f"{browser.title()}: {text[:180]}")
    return (
        "Website meminta session login dan aplikasi belum bisa membaca session browser yang cocok. "
        "Pastikan kamu sudah login ke website tersebut di browser yang dipilih, lalu buka/refresh website "
        "sekali di browser dan coba Analyze lagi.\\n\\n" + "\\n".join(details)
    )
''',
        '''def _friendly_cookie_error(errors: list[tuple[str, Exception]]) -> str:
    if not errors:
        return (
            "Website meminta login. Pilih browser yang sudah login pada menu Website Login "
            "lalu coba lagi."
        )
    details = []
    seen_browsers: set[str] = set()
    for browser, exc in errors:
        base_browser = browser.split(" (", 1)[0].lower()
        if base_browser in seen_browsers:
            continue
        seen_browsers.add(base_browser)
        message = clean_error(exc).replace("\\n", " ")
        details.append(f"{browser.title()}: {message[:220]}")
        if len(details) >= 4:
            break
    detail_text = "\\n".join(details)
    return (
        "Instagram belum mengembalikan media. Aplikasi sudah mencoba sesi browser dan profile yang tersedia. "
        "Jika akunmu login di Chrome, pilih Chrome secara langsung pada menu Website Login lalu Analyze lagi. "
        "Pastikan Chrome dapat membuka media tersebut. Jika tetap gagal, klik tombol Import cookies.txt pada baris Website Login, "
        "pilih file cookies.txt format Netscape yang diekspor dari browser yang sudah login, lalu Analyze lagi. "
        "Jangan bagikan file cookie kepada siapa pun. Postingan privat hanya bisa dibuka jika akun tersebut memang punya akses.\\n\\n" + detail_text
    )
''',
        "deduplicate and clarify browser errors",
    )

    core_path.write_text(text, encoding="utf-8")
    compile(text, str(core_path), "exec")
    print("Windows Instagram patch applied and core.py syntax check passed.")
    print("Changes: per-URL Instagram categories, browser-profile retries, and real gallery-dl errors.")


if __name__ == "__main__":
    main()
