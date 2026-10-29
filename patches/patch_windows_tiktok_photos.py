from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Patch {label!r} expected exactly one match, found {count}. No changes written."
        )
    return text.replace(old, new, 1)


TIKTOK_PHOTO_CORE_HELPER = r'''

def analyze_tiktok_photo(
    url: str, cookie_browser: str | None = "auto",
) -> MediaInfo:
    """Analyze a TikTok photo/slideshow post through gallery-dl's native extractor."""
    import re
    from pathlib import Path
    from urllib.parse import urlparse
    from gallery_dl import config as gdl_config, job as gdl_job

    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    match = re.fullmatch(r"/@([^/]+)/photo/(\d+)/?", path, re.I)
    if (
        parsed.scheme not in {"http", "https"}
        or not (host == "tiktok.com" or host.endswith(".tiktok.com") or host == "tiktokv.com" or host.endswith(".tiktokv.com"))
        or not match
    ):
        raise RuntimeError("URL bukan TikTok Photo/Carousel dengan format /@akun/photo/ID.")

    owner_from_url, post_id = match.group(1), match.group(2)
    explicit = (cookie_browser or "auto").strip()
    explicit_lower = explicit.lower()
    attempts: list[tuple[str | None, str | None, str | None, str]] = []

    if explicit_lower.startswith("cookiesfile:"):
        cookie_file = explicit[len("cookiesfile:"):].strip()
        if not cookie_file or not Path(cookie_file).is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Klik Import cookies.txt lalu pilih ulang file.")
        attempts.append((None, None, cookie_file, "cookies.txt"))
    elif explicit_lower in {"none", "disabled", "off"}:
        attempts.append((None, None, None, "tanpa cookie"))
    elif explicit_lower not in {"", "auto"}:
        try:
            profiles = _browser_profile_candidates(explicit_lower)
        except Exception:
            profiles = [None]
        for profile in profiles or [None]:
            label = explicit_lower if not profile else f"{explicit_lower} ({Path(profile).name})"
            attempts.append((explicit_lower, profile, None, label))
        attempts.append((None, None, None, "tanpa cookie"))
    else:
        attempts.append((None, None, None, "tanpa cookie"))
        try:
            browsers = _browser_candidates("auto")
        except Exception:
            browsers = ["chrome", "edge", "brave", "firefox"]
        for browser in browsers:
            try:
                profiles = _browser_profile_candidates(browser)
            except Exception:
                profiles = [None]
            for profile in profiles or [None]:
                label = browser if not profile else f"{browser} ({Path(profile).name})"
                attempts.append((browser, profile, None, label))

    errors: list[str] = []
    for browser, profile, cookie_file, label in attempts:
        try:
            # Isolate TikTok extraction settings from other site handlers.
            gdl_config.clear()
            gdl_config.set(("extractor", "tiktok"), "photos", True)
            gdl_config.set(("extractor", "tiktok"), "videos", False)
            gdl_config.set(("extractor", "tiktok"), "audio", False)
            gdl_config.set(("extractor", "tiktok"), "covers", False)
            gdl_config.set(("extractor", "tiktok"), "subtitles", False)

            if cookie_file:
                gdl_config.set((), "cookies", cookie_file)
            elif browser:
                gdl_config.set((), "cookies", (
                    browser, profile, None, None, ".tiktok.com",
                ))

            task = gdl_job.DataJob(url)
            task.run()
            urls = list(getattr(task, "data_urls", []) or [])
            metadata_rows = list(getattr(task, "data_meta", []) or [])
            media_records: list[tuple[str, dict]] = []
            for index, media_url in enumerate(urls):
                if not isinstance(media_url, str) or not media_url.startswith(("http://", "https://")):
                    continue
                metadata = metadata_rows[index] if index < len(metadata_rows) else {}
                if not isinstance(metadata, dict):
                    metadata = {}
                if str(metadata.get("type") or "").lower() not in {"image", "photo"}:
                    continue
                media_records.append((media_url, metadata))

            if not media_records:
                task_error = getattr(task, "exception", None)
                detail = (
                    f"{type(task_error).__name__}: {task_error}"
                    if task_error is not None
                    else "gallery-dl tidak menemukan gambar pada postingan ini."
                )
                errors.append(f"{label}: {detail[:350]}")
                continue

            first_meta = media_records[0][1]
            author = str(first_meta.get("user") or owner_from_url or "TikTok")
            post_title = (
                str(first_meta.get("title") or first_meta.get("desc") or "").strip()
                or f"TikTok photo #{post_id}"
            )

            def safe_int(value):
                try:
                    return int(value) if value is not None else None
                except (TypeError, ValueError, OverflowError):
                    return None

            def image_extension(media_url: str, metadata: dict) -> str:
                extension = str(metadata.get("extension") or "").strip().lower().lstrip(".")
                if not extension:
                    filename = urlparse(media_url).path.rsplit("/", 1)[-1]
                    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                if extension == "jpeg":
                    extension = "jpg"
                if extension not in {"jpg", "png", "webp", "heic", "avif", "gif"}:
                    extension = "jpg"
                return extension

            items: list[MediaItem] = []
            for index, (media_url, metadata) in enumerate(media_records, start=1):
                extension = image_extension(media_url, metadata)
                raw = {
                    "source_url": url,
                    "extension": extension,
                    "media_id": f"TikTokPhoto_{post_id}_{index:03d}",
                    "_tiktok_photo_direct": True,
                }
                items.append(MediaItem(
                    slide_index=index,
                    title=f"{post_title} Photo {index:03d}" if len(media_records) > 1 else post_title,
                    uploader=str(metadata.get("user") or author),
                    duration=None,
                    thumbnail=media_url,
                    qualities=[],
                    raw=raw,
                    media_type="photo",
                    direct_url=media_url,
                    width=safe_int(metadata.get("width")),
                    height=safe_int(metadata.get("height")),
                ))

            return MediaInfo(
                title=post_title,
                uploader=author,
                duration=None,
                webpage_url=url,
                thumbnail=items[0].direct_url,
                extractor="TikTok Photo Carousel",
                qualities=[],
                raw={
                    "source_url": url,
                    "_tiktok_photo_direct": True,
                    "post_total_items": len(items),
                    "post_id": post_id,
                },
                auth_browser=("cookies.txt" if cookie_file else browser),
                items=items,
                total_items=len(items),
            )
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:300]}")

    raise RuntimeError(
        "TikTok Photo/Carousel gagal dianalisis melalui gallery-dl. "
        "Pastikan postingan bisa dibuka di browser. Jika TikTok meminta login, "
        "pilih browser yang sudah login atau impor cookies.txt lokal.\n"
        + "\n".join(errors[:5])
    )


'''


TIKTOK_PHOTO_APP_HELPER = r'''
def _analyze_url_with_tiktok_photo_fallback(url: str, cookie_browser: str | None = "auto"):
    """Route TikTok image posts to gallery-dl; keep existing fallback for other URLs."""
    import re
    from urllib.parse import urlparse

    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    photo_path = re.fullmatch(r"/@[^/]+/photo/\d+/?", parsed.path or "", re.I)
    is_tiktok = (
        host == "tiktok.com" or host.endswith(".tiktok.com")
        or host == "tiktokv.com" or host.endswith(".tiktokv.com")
    )
    if is_tiktok and photo_path:
        from core import analyze_tiktok_photo
        return analyze_tiktok_photo(url, cookie_browser)

    return _analyze_url_with_facebook_post_fallback(url, cookie_browser)


'''


def patch_core(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")
    anchor = 'def analyze_url(url: str, cookie_browser: str | None = "auto") -> MediaInfo:\n'
    text = replace_once(
        text, anchor, TIKTOK_PHOTO_CORE_HELPER + anchor,
        "insert TikTok Photo Carousel analyzer",
    )
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("TikTok Photo/Carousel core analyzer inserted; core.py syntax check passed.")


def patch_app(source_root: Path) -> None:
    path = source_root / "app.py"
    text = path.read_text(encoding="utf-8")

    if "_analyze_url_with_tiktok_photo_fallback(" not in text:
        import re
        class_match = re.search(r"(?m)^class\s+[A-Za-z_]\w*\s*(?:\([^\n]*\))?:", text)
        if not class_match:
            raise RuntimeError("Could not find a top-level application class for TikTok Photo fallback.")
        text = text[:class_match.start()] + TIKTOK_PHOTO_APP_HELPER + text[class_match.start():]

    text = replace_once(
        text,
        "self.done.emit(_analyze_url_with_facebook_post_fallback(self.url, self.cookie_browser))",
        "self.done.emit(_analyze_url_with_tiktok_photo_fallback(self.url, self.cookie_browser))",
        "route TikTok Photo analysis through gallery-dl",
    )

    anchor = '''            # Facebook Story analysis already has a direct CDN URL. Avoid
            # sending the unsupported /stories/ URL to yt-dlp first.
            if item.raw.get("_facebook_story_direct"):
'''
    replacement = r'''            # TikTok Photo/Carousel items already contain direct image CDN URLs.
            # Save all slides in one dedicated folder instead of sending /photo/
            # to yt-dlp, which currently rejects that URL format.
            if item.raw.get("_tiktok_photo_direct"):
                import re as _re
                from pathlib import Path as _Path
                from urllib.parse import urlparse as _urlparse

                source_url = str(item.raw.get("source_url") or "")
                owner_name = str(item.uploader or "").strip() or "TikTok"
                parsed_source = _urlparse(source_url)
                post_match = _re.search(r"/@([^/]+)/photo/(\d+)", parsed_source.path or "", _re.I)
                post_identifier = post_match.group(2) if post_match else str(
                    (item.raw or {}).get("post_id") or ""
                )
                folder_parts = ["TikTok Photo", owner_name]
                if post_identifier:
                    folder_parts.append(post_identifier)
                folder_name = " - ".join(folder_parts)
                folder_name = _re.sub(r'[<>:"/\\\\|?*\x00-\x1f]+', "_", folder_name)
                folder_name = _re.sub(r"\s+", " ", folder_name).strip(" ._")[:120]
                if not folder_name or folder_name in {".", ".."}:
                    folder_name = "TikTok Photo"
                photo_output_path = _Path(self.output_dir) / folder_name
                photo_output_path.mkdir(parents=True, exist_ok=True)
                download_direct_item(
                    item,
                    str(photo_output_path),
                    editing_compatible=self.editing_compatible,
                    progress_cb=hook,
                    include_slide_prefix=self.post_total_items > 1,
                )
                continue

            # Facebook Story analysis already has a direct CDN URL. Avoid
            # sending the unsupported /stories/ URL to yt-dlp first.
            if item.raw.get("_facebook_story_direct"):
'''
    text = replace_once(text, anchor, replacement, "route direct TikTok Photo downloads")

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("TikTok Photo analyzer and direct-download route integrated; app.py syntax check passed.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_windows_tiktok_photos.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not (source_root / "core.py").is_file() or not (source_root / "app.py").is_file():
        raise FileNotFoundError(f"Expected core.py and app.py under {source_root}")
    patch_core(source_root)
    patch_app(source_root)


if __name__ == "__main__":
    main()
