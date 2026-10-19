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
    """Extract available SD/HD Story video URLs and a preview image from page source."""
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
        is_facebook_cdn = host.endswith(("fbcdn.net", "fbsbx.com"))
        if not (is_facebook_cdn or host.endswith("facebook.com")):
            return False
        path = parsed.path.lower()
        if media_type == "video":
            return (
                ".mp4" in path
                or ".m4v" in path
                or (is_facebook_cdn and not path.endswith((".js", ".css", ".html", ".json", ".jpg", ".jpeg", ".png", ".webp")))
            )
        return (
            is_facebook_cdn
            and not path.endswith((".js", ".css", ".html", ".json", ".mp4", ".m4v"))
        )

    def dimensions_near(position: int, tier: str) -> tuple[int | None, int | None]:
        left = max(0, position - 2400)
        right = min(len(page), position + 3000)
        window = page[left:right]
        local_pos = position - left

        if tier == "SD":
            pairs = (
                ("sd_width", "sd_height"),
                ("video_sd_width", "video_sd_height"),
                ("low_width", "low_height"),
                ("width_sd", "height_sd"),
            )
        else:
            pairs = (
                ("hd_width", "hd_height"),
                ("original_width", "original_height"),
                ("video_width", "video_height"),
                ("width", "height"),
            )

        def nearest_number(key: str):
            pattern = re.compile(
                r"""["']?""" + re.escape(key) + r"""["']?\s*[:=]\s*(\d{2,5})""",
                re.I,
            )
            matches = list(pattern.finditer(window))
            if not matches:
                return None
            return min(matches, key=lambda match: abs(match.start() - local_pos))

        for width_key, height_key in pairs:
            width_match = nearest_number(width_key)
            height_match = nearest_number(height_key)
            if width_match is None or height_match is None:
                continue
            if abs(width_match.start() - height_match.start()) > 2400:
                continue
            width = int(width_match.group(1))
            height = int(height_match.group(1))
            if 32 <= width <= 16384 and 32 <= height <= 16384:
                return width, height
        return None, None

    # Facebook commonly exposes both HD and SD streams in one object. The
    # previous parser only returned the first URL and missed hd_src variants
    # used by several Story page templates.
    field_specs = (
        ("hd_src_no_ratelimit", "HD", 120),
        ("hd_src", "HD", 115),
        ("browser_native_hd_url", "HD", 110),
        ("playable_url_quality_hd", "HD", 105),
        ("playable_url_hd", "HD", 100),
        ("sd_src_no_ratelimit", "SD", 90),
        ("sd_src", "SD", 85),
        ("browser_native_sd_url", "SD", 80),
        ("playable_url_quality_sd", "SD", 75),
        ("playable_url", "Best", 60),
        ("video_url", "Best", 55),
    )
    variants_by_tier: dict[str, dict[str, Any]] = {}
    seen_urls: set[str] = set()
    for field, tier, rank in field_specs:
        if tier in variants_by_tier:
            continue
        pattern = re.compile(
            r'"' + re.escape(field) + r'"\s*:\s*"((?:\\.|[^"\\])*)"',
            re.I,
        )
        for match in pattern.finditer(page):
            candidate = decode_match(match.group(1))
            if not valid_media_url(candidate, "video") or candidate in seen_urls:
                continue
            width, height = dimensions_near(match.start(), tier)
            fallback_key = 1280 if tier in {"HD", "Best"} else 640
            selector_height = height if height else fallback_key
            if any(v["selector_height"] == selector_height for v in variants_by_tier.values()):
                selector_height = fallback_key
            if width and height:
                label = f"{tier} • {width}×{height}" if tier != "Best" else f"Best Available • {width}×{height}"
            elif tier == "HD":
                label = "HD • Highest available"
            elif tier == "SD":
                label = "SD • Standard"
            else:
                label = "Best Available"
            variants_by_tier[tier] = {
                "url": candidate,
                "tier": tier,
                "rank": rank,
                "label": label,
                "width": width,
                "height": height,
                "selector_height": int(selector_height),
                "extension": "mp4",
            }
            seen_urls.add(candidate)
            break

    # Some templates wrap the playable URL in an object rather than storing a
    # string directly.
    if "Best" not in variants_by_tier:
        nested_pattern = re.compile(
            r'"playable_url"\s*:\s*\{\s*"url"\s*:\s*"((?:\\.|[^"\\])*)"',
            re.I,
        )
        for match in nested_pattern.finditer(page):
            candidate = decode_match(match.group(1))
            if valid_media_url(candidate, "video") and candidate not in seen_urls:
                width, height = dimensions_near(match.start(), "Best")
                variants_by_tier["Best"] = {
                    "url": candidate,
                    "tier": "Best",
                    "rank": 50,
                    "label": f"Best Available • {width}×{height}" if width and height else "Best Available",
                    "width": width,
                    "height": height,
                    "selector_height": int(height or 1280),
                    "extension": "mp4",
                }
                seen_urls.add(candidate)
                break

    # Build the thumbnail independently from the video URL. The old parser
    # only tried og:image and therefore left preview empty on Story variants
    # that expose their poster as a JSON thumbnail/image URI.
    thumbnail = ""
    for key in ("og:image", "og:image:url", "twitter:image", "og:video:thumbnail"):
        candidate = decode_match(meta.get(key, ""))
        if valid_media_url(candidate, "photo"):
            thumbnail = candidate
            break

    thumbnail_patterns = (
        r'"(?:thumbnail_url|video_thumbnail_url|thumbnail_src|poster_url)"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"(?:video_thumbnail|preferred_thumbnail|thumbnail|image)"\s*:\s*\{.{0,1400}?"uri"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"display_url"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"image"\s*:\s*\{.{0,1400}?"uri"\s*:\s*"((?:\\.|[^"\\])*)"',
    )
    if not thumbnail:
        for pattern in thumbnail_patterns:
            for match in re.finditer(pattern, page, re.I | re.S):
                candidate = decode_match(match.group(1))
                if valid_media_url(candidate, "photo"):
                    thumbnail = candidate
                    break
            if thumbnail:
                break

    variants = sorted(variants_by_tier.values(), key=lambda item: item["rank"], reverse=True)
    if not variants:
        for key in ("og:video", "og:video:url", "og:video:secure_url"):
            candidate = decode_match(meta.get(key, ""))
            if valid_media_url(candidate, "video"):
                variants = [{
                    "url": candidate,
                    "tier": "Best",
                    "rank": 10,
                    "label": "Best Available",
                    "width": None,
                    "height": None,
                    "selector_height": 1280,
                    "extension": "mp4",
                }]
                break

    if variants:
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
        best = variants[0]
        return {
            "direct_url": best["url"],
            "media_type": "video",
            "extension": "mp4",
            "thumbnail": thumbnail or None,
            "title": title or "Facebook Story",
            "duration": duration,
            "variants": variants,
            "width": best.get("width"),
            "height": best.get("height"),
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
            "variants": [],
            "width": None,
            "height": None,
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

    # Facebook serves different web shells on www, mobile, and mbasic.
    # Keep the full Story path/query intact but try each normal public host.
    original_host = parsed.netloc.lower().split(":", 1)[0]
    page_urls = [url.strip()]
    for host in ("www.facebook.com", "m.facebook.com", "mbasic.facebook.com"):
        if host == original_host:
            continue
        candidate = urllib.parse.urlunparse(parsed._replace(netloc=host))
        if candidate not in page_urls:
            page_urls.append(candidate)

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

            # Facebook rejects some standard urllib requests with HTTP 400.
            # Prefer curl_cffi's browser TLS/client fingerprint and browser-like
            # navigation headers, but retain urllib as a compatibility fallback.
            request_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                          "image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": "https://www.facebook.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Upgrade-Insecure-Requests": "1",
            }
            try:
                from curl_cffi import requests as curl_requests
            except Exception:
                curl_requests = None

            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            browser_session = None
            if curl_requests is not None:
                try:
                    browser_session = curl_requests.Session(impersonate="chrome")
                    for cookie in jar:
                        try:
                            browser_session.cookies.set(
                                cookie.name,
                                cookie.value,
                                domain=cookie.domain,
                                path=cookie.path or "/",
                            )
                        except Exception:
                            # Some curl_cffi versions normalize cookie domains differently.
                            browser_session.cookies.set(cookie.name, cookie.value)
                except Exception as session_error:
                    errors.append(
                        f"{browser.title()}: curl_cffi browser session failed "
                        f"({type(session_error).__name__})"
                    )
                    browser_session = None

            media = None
            last_final_url = ""
            for page_url in page_urls:
                status_code = 200
                try:
                    if browser_session is not None:
                        response = browser_session.get(
                            page_url,
                            headers=request_headers,
                            timeout=25,
                            allow_redirects=True,
                        )
                        last_final_url = str(response.url)
                        status_code = int(response.status_code)
                        page = str(response.text or "")[:30 * 1024 * 1024]
                        try:
                            response.close()
                        except Exception:
                            pass
                    else:
                        request = urllib.request.Request(
                            page_url,
                            headers={
                                **request_headers,
                                "User-Agent": (
                                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/131.0.0.0 Safari/537.36"
                                ),
                            },
                        )
                        with opener.open(request, timeout=25) as response:
                            last_final_url = response.geturl()
                            status_code = int(getattr(response, "status", 200))
                            page = response.read(30 * 1024 * 1024).decode("utf-8", errors="replace")
                except urllib.error.HTTPError as exc:
                    status_code = int(exc.code)
                    last_final_url = str(exc.geturl() or page_url)
                    try:
                        page = exc.read(30 * 1024 * 1024).decode("utf-8", errors="replace")
                    except Exception:
                        page = ""
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

                if status_code >= 400:
                    # Do not dump response bodies; some contain account-related
                    # page data. Report only the HTTP status and host.
                    response_host = urllib.parse.urlparse(last_final_url).hostname or "Facebook"
                    errors.append(
                        f"{browser.title()}: {response_host} HTTP {status_code} "
                        "(permintaan halaman ditolak)"
                    )
                    continue

            if browser_session is not None:
                try:
                    browser_session.close()
                except Exception:
                    pass

            if media:
                media_type = str(media["media_type"])
                title = str(media["title"] or "Facebook Story")
                extension = str(media.get("extension") or "mp4")
                duration = media.get("duration")
                variants = list(media.get("variants") or [])
                if media_type == "video" and not variants and media.get("direct_url"):
                    variants = [{
                        "url": str(media["direct_url"]),
                        "tier": "Best",
                        "rank": 0,
                        "label": "Best Available",
                        "width": media.get("width"),
                        "height": media.get("height"),
                        "selector_height": int(media.get("height") or 1280),
                        "extension": extension,
                    }]

                qualities: list[QualityOption] = []
                used_selector_heights: set[int] = set()
                for variant in variants:
                    selector_height = int(variant.get("selector_height") or variant.get("height") or 1280)
                    if selector_height in used_selector_heights:
                        selector_height = 1280 if str(variant.get("tier")) == "HD" else 640
                        while selector_height in used_selector_heights:
                            selector_height += 1
                    used_selector_heights.add(selector_height)
                    variant["selector_height"] = selector_height
                    label = str(variant.get("label") or "Best Available")
                    qualities.append(QualityOption(label, selector_height))

                raw = dict(media.get("raw") or {})
                raw.update({
                    "source_url": url,
                    "extension": extension,
                    "_facebook_story_direct": True,
                    "_facebook_story_variants": variants,
                })
                best_variant = variants[0] if variants else {}
                selected_url = str(best_variant.get("url") or media["direct_url"])
                item = MediaItem(
                    slide_index=1,
                    title=title,
                    uploader="Facebook",
                    duration=duration,
                    thumbnail=media.get("thumbnail"),
                    qualities=qualities,
                    raw=raw,
                    media_type=media_type,
                    direct_url=selected_url,
                    width=best_variant.get("width") or media.get("width"),
                    height=best_variant.get("height") or media.get("height"),
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
                # Honor the Quality dropdown by choosing the matching direct
                # CDN URL. Previously this special path ignored self.height and
                # always downloaded the first (often SD) URL.
                variants = item.raw.get("_facebook_story_variants") or []
                selected_variant = None
                try:
                    requested_height = int(self.height) if self.height is not None else None
                except (TypeError, ValueError):
                    requested_height = None
                if requested_height is not None:
                    selected_variant = next(
                        (
                            variant for variant in variants
                            if int(variant.get("selector_height") or -1) == requested_height
                        ),
                        None,
                    )
                if selected_variant is None and variants:
                    selected_variant = variants[0]
                if selected_variant and selected_variant.get("url"):
                    item.direct_url = str(selected_variant["url"])
                    item.raw["extension"] = str(selected_variant.get("extension") or "mp4")
                    item.raw["_selected_story_quality"] = str(
                        selected_variant.get("label") or "Best Available"
                    )

                # Time Range and MP3 need yt-dlp/FFmpeg post-processing; use
                # the selected signed media URL directly, not the Story page.
                if self.time_range is not None or self.audio_only:
                    download_media(
                        item.direct_url, self.output_dir, None, self.container,
                        self.audio_only, self.editing_compatible,
                        progress_cb=hook, cookie_browser=None,
                        time_range=self.time_range,
                    )
                else:
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
