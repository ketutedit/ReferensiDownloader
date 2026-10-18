from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch {label!r} expected exactly one match, found {count}.")
    return text.replace(old, new, 1)


FACEBOOK_STORY_HELPERS = r'''
def _decode_facebook_json_string(value: str) -> str:
    """Decode a string value copied from Facebook's JSON/HTML response."""
    import html
    import json

    try:
        decoded = json.loads('"' + value + '"')
    except Exception:
        decoded = (
            value.replace(r"\/", "/")
            .replace(r"\u0026", "&")
            .replace(r"\u003d", "=")
            .replace(r"\u003D", "=")
            .replace(r"\u0025", "%")
            .replace(r"\u003a", ":")
            .replace(r"\u003A", ":")
            .replace(r"\u002f", "/")
            .replace(r"\u002F", "/")
        )
    return html.unescape(str(decoded)).replace(r"\/", "/").strip()


def _facebook_story_meta_tags(page: str) -> dict[str, str]:
    import html
    import re

    result: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", page, flags=re.IGNORECASE):
        attrs: dict[str, str] = {}
        for match in re.finditer(
            r"""([a-zA-Z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
            tag,
        ):
            name = match.group(1).lower()
            value = next((v for v in match.groups()[1:] if v is not None), "")
            attrs[name] = html.unescape(value)
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and attrs.get("content"):
            result[key] = attrs["content"]
    return result


def _parse_facebook_story_page(page: str) -> dict[str, Any] | None:
    """Find a direct Facebook CDN media URL in an authenticated Story page."""
    import html
    import re
    from urllib.parse import urlparse

    if not page:
        return None

    page = html.unescape(page)
    meta = _facebook_story_meta_tags(page)
    title_match = re.search(r"<title[^>]*>(.*?)</title\s*>", page, re.I | re.S)
    title = re.sub(r"\s+", " ", html.unescape(title_match.group(1))).strip() if title_match else ""
    if title.lower() in {"facebook", "log in to facebook", "login"}:
        title = ""

    def decode_match(raw: str) -> str:
        url = _decode_facebook_json_string(raw)
        return url.strip().rstrip("\\").replace("&amp;", "&")

    def valid_media_url(url: str, media_type: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if not (host.endswith("fbcdn.net") or host.endswith("facebook.com")):
            return False
        path = parsed.path.lower()
        if media_type == "video":
            return (
                ".mp4" in path
                or ".m4v" in path
                or ("video" in path and "fbcdn.net" in host)
            )
        return (
            host.endswith("fbcdn.net")
            and not path.endswith((".js", ".css", ".html"))
        )

    video_patterns = (
        r'"playable_url_quality_hd"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"browser_native_hd_url"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"playable_url"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"browser_native_sd_url"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"video_url"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"playable_url"\s*:\s*\{\s*"url"\s*:\s*"((?:\\.|[^"\\])*)"',
    )
    video_url = None
    for pattern in video_patterns:
        for match in re.finditer(pattern, page, re.I):
            candidate = decode_match(match.group(1))
            if valid_media_url(candidate, "video"):
                video_url = candidate
                break
        if video_url:
            break

    if not video_url:
        for key in ("og:video", "og:video:url", "og:video:secure_url"):
            candidate = _decode_facebook_json_string(meta.get(key, ""))
            if valid_media_url(candidate, "video"):
                video_url = candidate
                break

    thumbnail = ""
    for key in ("og:image", "og:image:url", "twitter:image"):
        candidate = _decode_facebook_json_string(meta.get(key, ""))
        if valid_media_url(candidate, "photo"):
            thumbnail = candidate
            break

    if video_url:
        duration = None
        for pattern in (
            r'"playable_duration_in_ms"\s*:\s*(\d+)',
            r'"video_duration_in_ms"\s*:\s*(\d+)',
        ):
            match = re.search(pattern, page, re.I)
            if match:
                duration = max(0, int(int(match.group(1)) / 1000))
                break
        if duration is None:
            match = re.search(r'"video_duration"\s*:\s*(\d+(?:\.\d+)?)', page, re.I)
            if match:
                duration = max(0, int(float(match.group(1))))
        return {
            "direct_url": video_url,
            "media_type": "video",
            "extension": "mp4",
            "thumbnail": thumbnail or None,
            "title": title or "Facebook Story",
            "duration": duration,
            "raw": {"_facebook_story_direct": True, "extension": "mp4"},
        }

    image_patterns = (
        r'"image"\s*:\s*\{.{0,1200}?"uri"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"display_url"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"photo_image"\s*:\s*\{.{0,1200}?"uri"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"uri"\s*:\s*"((?:\\.|[^"\\])*)"',
    )
    candidates: list[str] = []
    for pattern in image_patterns:
        for match in re.finditer(pattern, page, re.I | re.S):
            candidate = decode_match(match.group(1))
            if valid_media_url(candidate, "photo") and candidate not in candidates:
                candidates.append(candidate)
        if candidates and pattern.startswith(r'"image"'):
            break

    image_url = thumbnail or (candidates[0] if candidates else "")
    if image_url and valid_media_url(image_url, "photo"):
        final_path = urlparse(image_url).path
        filename = final_path.rsplit("/", 1)[-1]
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        if extension not in {"jpg", "jpeg", "png", "webp", "gif"}:
            extension = "jpg"
        return {
            "direct_url": image_url,
            "media_type": "photo",
            "extension": extension,
            "thumbnail": image_url,
            "title": title or "Facebook Story",
            "duration": None,
            "raw": {"_facebook_story_direct": True, "extension": extension},
        }
    return None


def analyze_facebook_story(
    url: str, cookie_browser: str | None = "auto",
) -> MediaInfo:
    """Best-effort extraction of one Facebook Story through a logged-in browser session.

    Cookies are read locally through gallery-dl or a user-selected Netscape
    cookies.txt file. Cookie contents are never uploaded or logged.
    """
    import http.cookiejar
    import os
    import re
    import sys
    import urllib.error
    import urllib.parse
    import urllib.request

    explicit = (cookie_browser or "auto").strip()
    if explicit.lower().startswith("cookiesfile:"):
        cookie_path = explicit[len("cookiesfile:"):].strip()
        if not cookie_path or not Path(cookie_path).is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Klik Import cookies.txt lalu pilih ulang file.")
        candidates = [("cookiesfile:" + cookie_path, None)]
    elif explicit.lower() not in {"", "auto", "none", "disabled", "off"}:
        candidates = [(explicit.lower(), None)]
    elif sys.platform == "darwin":
        candidates = [(name, None) for name in ("safari", "chrome", "brave")]
    elif os.name == "nt":
        candidates = [(name, None) for name in ("edge", "chrome", "brave", "firefox")]
    else:
        candidates = [(name, None) for name in ("chrome", "brave", "firefox")]

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("URL Facebook Story tidak valid.")
    if "facebook.com" not in parsed.netloc.lower() or "/stories/" not in parsed.path.lower():
        raise RuntimeError("URL bukan Facebook Story.")

    page_urls = [url.strip()]
    if parsed.netloc.lower() != "m.facebook.com":
        page_urls.append(urllib.parse.urlunparse(parsed._replace(netloc="m.facebook.com")))

    errors: list[str] = []
    for browser, _ in candidates:
        jar = http.cookiejar.CookieJar()
        try:
            if browser.startswith("cookiesfile:"):
                path = browser[len("cookiesfile:"):]
                file_jar = http.cookiejar.MozillaCookieJar(path)
                file_jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in file_jar:
                    if "facebook.com" in cookie.domain.lower():
                        jar.set_cookie(cookie)
            else:
                from gallery_dl import cookies as gdl_cookies
                browser_cookies = gdl_cookies.load_cookies(
                    (browser, None, None, None, ".facebook.com")
                )
                for cookie in browser_cookies:
                    jar.set_cookie(cookie)

            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            media = None
            last_final_url = ""
            for page_url in page_urls:
                request = urllib.request.Request(
                    page_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                                  "image/avif,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
                        "Cache-Control": "no-cache",
                        "Referer": "https://www.facebook.com/",
                    },
                )
                try:
                    with opener.open(request, timeout=25) as response:
                        last_final_url = response.geturl()
                        page = response.read(30 * 1024 * 1024).decode("utf-8", errors="replace")
                except urllib.error.HTTPError as exc:
                    errors.append(f"{browser.title()}: Facebook HTTP {exc.code}")
                    continue
                except Exception as exc:
                    errors.append(f"{browser.title()}: {type(exc).__name__}: {exc}")
                    continue

                if re.search(r"/login(?:\.php|/|\?)", last_final_url, re.I):
                    errors.append(
                        f"{browser.title()}: Facebook mengalihkan ke login. "
                        "Pastikan akun bisa membuka Story tersebut di browser ini, atau impor cookies.txt."
                    )
                    continue

                media = _parse_facebook_story_page(page)
                if media:
                    break

            if media:
                media_type = str(media["media_type"])
                title = str(media["title"] or "Facebook Story")
                extension = str(media.get("extension") or "mp4")
                duration = media.get("duration")
                qualities = [QualityOption("Best Available", None)] if media_type == "video" else []
                raw = dict(media.get("raw") or {})
                raw.update({
                    "source_url": url,
                    "extension": extension,
                    "_facebook_story_direct": True,
                })
                item = MediaItem(
                    slide_index=1,
                    title=title,
                    uploader="Facebook",
                    duration=duration,
                    thumbnail=media.get("thumbnail"),
                    qualities=qualities,
                    raw=raw,
                    media_type=media_type,
                    direct_url=str(media["direct_url"]),
                    width=None,
                    height=None,
                )
                return MediaInfo(
                    title=title,
                    uploader="Facebook",
                    duration=duration,
                    webpage_url=url,
                    thumbnail=media.get("thumbnail"),
                    extractor="Facebook Story",
                    qualities=qualities,
                    raw=raw,
                    auth_browser=browser,
                    items=[item],
                    total_items=1,
                )

            errors.append(
                f"{browser.title()}: halaman Story terbuka, tetapi URL media langsung tidak ditemukan."
            )
        except Exception as exc:
            errors.append(f"{browser.title()}: {type(exc).__name__}: {exc}")

    details = "\n".join(errors[:5])
    raise RuntimeError(
        "Facebook Story belum bisa diekstrak dari halaman yang diterima. "
        "Facebook bisa mengalihkan Story ke halaman login atau merender media setelah JavaScript. "
        "Coba pilih browser yang sedang login, refresh Story di browser itu, atau impor cookies.txt. "
        "Jika tetap gagal, halaman yang diterima belum memuat URL media yang bisa dibaca downloader."
        + (("\n\n" + details) if details else "")
    )


'''


def patch_core(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''def analyze_url(url: str, cookie_browser: str | None = "auto") -> MediaInfo:
''',
        FACEBOOK_STORY_HELPERS + '''def analyze_url(url: str, cookie_browser: str | None = "auto") -> MediaInfo:
''',
        "insert Facebook Story parser and analyzer",
    )
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Facebook Story extractor helper inserted; core.py syntax check passed.")


def patch_app_download(source_root: Path) -> None:
    path = source_root / "app.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            if item.media_type == "photo":
                download_direct_item(
                    item, self.output_dir, editing_compatible=False,
                    progress_cb=hook, include_slide_prefix=self.post_total_items > 1,
                )
                continue

            # For an All Items download every video uses Best Available. For a
''',
        '''            if item.media_type == "photo":
                download_direct_item(
                    item, self.output_dir, editing_compatible=False,
                    progress_cb=hook, include_slide_prefix=self.post_total_items > 1,
                )
                continue

            # Facebook Story analysis already has a direct CDN URL. Avoid
            # sending the unsupported /stories/ URL to yt-dlp first.
            if item.raw.get("_facebook_story_direct"):
                download_direct_item(
                    item, self.output_dir, editing_compatible=self.editing_compatible,
                    progress_cb=hook, include_slide_prefix=False,
                )
                continue

            # For an All Items download every video uses Best Available. For a
''',
        "route Facebook Story direct media to direct downloader",
    )
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Facebook Story direct download routing inserted; app.py syntax check passed.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_mac_facebook_story.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    patch_core(source_root)
    patch_app_download(source_root)


if __name__ == "__main__":
    main()
