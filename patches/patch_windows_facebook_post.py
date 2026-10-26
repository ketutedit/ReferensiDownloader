from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if text.count(old) != 1:
        raise RuntimeError(
            f"Patch {label!r} expected exactly one match, found {text.count(old)}."
        )
    return text.replace(old, new, 1)


FACEBOOK_POST_HELPERS = r'''
def _parse_facebook_post_page(page: str) -> dict[str, Any] | None:
    """Collect photo attachment URLs from a Facebook post page."""
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
    if not title:
        title = re.sub(r"\s+", " ", meta.get("og:title", "")).strip()

    owner_name = _facebook_story_owner_name(page)
    photos: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_photo(raw_url: str, context: str = "", allow_preview: bool = False) -> None:
        candidate = _decode_facebook_json_string(str(raw_url or "")).strip().rstrip("\\")
        candidate = candidate.replace("&amp;", "&")
        try:
            parsed = urlparse(candidate)
        except Exception:
            return

        host = (parsed.hostname or "").lower()
        filename = parsed.path.rsplit("/", 1)[-1]
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if (
            parsed.scheme not in {"http", "https"}
            or not host.endswith(("fbcdn.net", "fbsbx.com"))
            or extension not in {"jpg", "jpeg", "png", "webp", "gif", "avif"}
        ):
            return

        context_lower = (context or "").lower()
        if not allow_preview and re.search(
            r"profile_pic|profile_picture|avatar|actor_profile|owner_profile|page_profile|group_icon|reaction_icon",
            context_lower[-800:],
        ):
            return

        width = height = None
        dimension_match = re.search(
            r"(?:^|[_-])s(\d{1,4})x(\d{1,4})(?:[_&]|$)",
            parsed.query.lower(),
        )
        if dimension_match:
            width, height = int(dimension_match.group(1)), int(dimension_match.group(2))

        if candidate in seen:
            return
        seen.add(candidate)
        photos.append({
            "url": candidate,
            "extension": "jpg" if extension == "jpeg" else extension,
            "width": width,
            "height": height,
            "tiny_preview": bool(width and height and max(width, height) <= 300),
        })

    # Facebook's Open Graph preview is often the only image available for a
    # single-photo post, so preserve it as a fallback candidate.
    for key in ("og:image", "og:image:url", "twitter:image"):
        value = meta.get(key)
        if value:
            add_photo(value, key, allow_preview=True)

    # Extract URLs from common photo attachment representations.
    structured_patterns = (
        r'"(?:photo_image|full_image|large_image|original_image|image)"\s*:\s*\{.{0,2200}?"uri"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"(?:display_url|image_uri|photo_uri|image_url|photo_url|large_image_url|original_image_url)"\s*:\s*"((?:\\.|[^"\\])*)"',
    )
    for pattern in structured_patterns:
        for match in re.finditer(pattern, page, re.I | re.S):
            context = page[max(0, match.start() - 800):match.start()]
            add_photo(match.group(1), context)

    # Deeper/nested attachment structures vary between Facebook page versions.
    for match in re.finditer(
        r'"(?:uri|url)"\s*:\s*"((?:\\.|[^"\\])*)"',
        page,
        re.I,
    ):
        context = page[max(0, match.start() - 1800):match.start()]
        if not re.search(
            r"photo|image|attachment|subattachments|comet_photo|media",
            context[-1400:],
            re.I,
        ):
            continue
        add_photo(match.group(1), context)

    # Some mobile layouts render actual <img src> tags instead of exposing all
    # photo sources in serialized JSON.
    for tag in re.findall(r"<img\b[^>]*>", page, re.I | re.S):
        match = re.search(
            r"""(?:src|data-src)\s*=\s*(?:"([^"]+)"|'([^']+)')""",
            tag,
            re.I,
        )
        if match:
            add_photo(next((value for value in match.groups() if value), ""), tag)

    if not photos:
        return None

    non_tiny = [photo for photo in photos if not photo["tiny_preview"]]
    if non_tiny:
        photos = non_tiny

    return {
        "title": title or "Facebook Post",
        "owner_name": owner_name,
        "thumbnail": photos[0]["url"],
        "photos": photos,
    }


def analyze_facebook_post(
    url: str, cookie_browser: str | None = "auto",
) -> MediaInfo:
    """Local-session fallback for Facebook pfbid posts containing photos."""
    import http.cookiejar
    import os
    import re
    import sys
    import urllib.error
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse((url or "").strip())
    normalized = parsed.path + "?" + parsed.query
    if (
        parsed.scheme not in {"http", "https"}
        or "facebook.com" not in (parsed.hostname or "").lower()
        or not re.search(r"pfbid|/share/p/", normalized, re.I)
    ):
        raise RuntimeError("URL bukan Facebook Post yang didukung fallback.")

    explicit = (cookie_browser or "auto").strip()
    if explicit.lower().startswith("cookiesfile:"):
        cookie_path = explicit[len("cookiesfile:"):].strip()
        if not cookie_path or not Path(cookie_path).is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Impor ulang cookies.txt lalu coba lagi.")
        browser_candidates = ["cookiesfile:" + cookie_path]
    elif explicit.lower() in {"", "auto"}:
        if sys.platform == "darwin":
            browser_candidates = ["safari", "chrome", "brave"]
        elif os.name == "nt":
            browser_candidates = ["edge", "chrome", "brave", "firefox"]
        else:
            browser_candidates = ["chrome", "brave", "firefox"]
    elif explicit.lower() in {"none", "disabled", "off"}:
        browser_candidates = ["none"]
    else:
        browser_candidates = [explicit.lower()]

    page_urls = [url.strip()]
    for host in (
        "www.facebook.com",
        "m.facebook.com",
        "mbasic.facebook.com",
        "web.facebook.com",
        "touch.facebook.com",
    ):
        candidate = urllib.parse.urlunparse(parsed._replace(netloc=host))
        if candidate not in page_urls:
            page_urls.append(candidate)

    errors: list[str] = []
    for browser in browser_candidates:
        jar = http.cookiejar.CookieJar()
        session = None
        try:
            if browser.startswith("cookiesfile:"):
                cookie_path = browser[len("cookiesfile:"):]
                file_jar = http.cookiejar.MozillaCookieJar(cookie_path)
                file_jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in file_jar:
                    if "facebook.com" in cookie.domain.lower():
                        jar.set_cookie(cookie)
            elif browser != "none":
                from gallery_dl import cookies as gdl_cookies
                for cookie in gdl_cookies.load_cookies(
                    (browser, None, None, None, ".facebook.com")
                ):
                    jar.set_cookie(cookie)

            try:
                from curl_cffi import requests as curl_requests
            except Exception:
                curl_requests = None

            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
                "Cache-Control": "no-cache",
                "Referer": "https://www.facebook.com/",
                "Upgrade-Insecure-Requests": "1",
            }
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            if curl_requests is not None:
                session = curl_requests.Session(impersonate="chrome")
                for cookie in jar:
                    try:
                        session.cookies.set(
                            cookie.name,
                            cookie.value,
                            domain=cookie.domain,
                            path=cookie.path or "/",
                        )
                    except Exception:
                        session.cookies.set(cookie.name, cookie.value)

            discovered: list[dict[str, Any]] = []
            for page_url in page_urls:
                try:
                    if session is not None:
                        response = session.get(
                            page_url, headers=headers, timeout=25, allow_redirects=True
                        )
                        final_url = str(response.url)
                        status = int(response.status_code)
                        page = str(response.text or "")[:30 * 1024 * 1024]
                        try:
                            response.close()
                        except Exception:
                            pass
                    else:
                        request = urllib.request.Request(
                            page_url,
                            headers={
                                **headers,
                                "User-Agent": (
                                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/131.0.0.0 Safari/537.36"
                                ),
                            },
                        )
                        with opener.open(request, timeout=25) as response:
                            final_url = response.geturl()
                            status = int(getattr(response, "status", 200))
                            page = response.read(30 * 1024 * 1024).decode("utf-8", errors="replace")
                except urllib.error.HTTPError as exc:
                    status = int(exc.code)
                    final_url = str(exc.geturl() or page_url)
                    try:
                        page = exc.read(30 * 1024 * 1024).decode("utf-8", errors="replace")
                    except Exception:
                        page = ""
                except Exception as exc:
                    errors.append(browser.title() + ": " + type(exc).__name__ + ": " + str(exc))
                    continue

                if re.search(r"/login(?:\.php|/|\?)", final_url, re.I):
                    errors.append(browser.title() + ": Facebook mengarahkan ke login.")
                    continue

                result = _parse_facebook_post_page(page)
                if result:
                    discovered.append(result)
                elif status >= 400:
                    final_host = urllib.parse.urlparse(final_url).hostname or "Facebook"
                    errors.append(browser.title() + ": " + final_host + " HTTP " + str(status))

            # Merge results across page frontends; direct signed URLs remain local.
            photo_map: dict[str, dict[str, Any]] = {}
            for result in discovered:
                for photo in result.get("photos") or []:
                    photo_map.setdefault(str(photo.get("url") or ""), photo)
            photos = [photo for photo in photo_map.values() if photo.get("url")]

            if photos:
                title = next(
                    (str(entry.get("title")) for entry in discovered if entry.get("title")),
                    "Facebook Post",
                )
                owner_name = next(
                    (str(entry.get("owner_name")) for entry in discovered if entry.get("owner_name")),
                    "",
                ).strip()
                uploader = owner_name or "Facebook"
                items: list[MediaItem] = []
                for index, photo in enumerate(photos, start=1):
                    photo_url = str(photo["url"])
                    extension = str(photo.get("extension") or "jpg")
                    raw = {
                        "source_url": url,
                        "extension": extension,
                        "media_id": "FBPostPhoto_" + format(index, "03d"),
                        "_facebook_post_direct": True,
                    }
                    items.append(MediaItem(
                        slide_index=index,
                        title=title + " Photo " + format(index, "03d"),
                        uploader=uploader,
                        duration=None,
                        thumbnail=photo_url,
                        qualities=[],
                        raw=raw,
                        media_type="photo",
                        direct_url=photo_url,
                        width=photo.get("width"),
                        height=photo.get("height"),
                    ))

                return MediaInfo(
                    title=title,
                    uploader=uploader,
                    duration=None,
                    webpage_url=url,
                    thumbnail=str(photos[0]["url"]),
                    extractor="Facebook Post Photos",
                    qualities=[],
                    raw={
                        "source_url": url,
                        "_facebook_post_direct": True,
                        "post_total_items": len(items),
                    },
                    auth_browser=browser,
                    items=items,
                    total_items=len(items),
                )

            summary = "\n".join(errors[:4])
            raise RuntimeError(
                "Facebook Post fallback belum menemukan URL foto pada halaman yang diterima. "
                "Pastikan browser yang dipilih sedang login dan bisa membuka postingan tersebut."
                + (("\n" + summary) if summary else "")
            )
        except Exception as exc:
            errors.append(browser.title() + ": " + type(exc).__name__ + ": " + str(exc))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    summary = "\n".join(errors[:4])
    raise RuntimeError(
        "Facebook Post fallback gagal mengambil foto dari postingan. "
        "Coba pilih browser yang sedang login atau impor cookies.txt."
        + (("\n" + summary) if summary else "")
    )


'''


def patch_core(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''def analyze_url(url: str, cookie_browser: str | None = "auto") -> MediaInfo:
'''
    text = replace_once(
        text,
        anchor,
        FACEBOOK_POST_HELPERS + anchor,
        "insert Facebook Post photo fallback",
    )
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Facebook Post photo fallback inserted; core.py syntax check passed.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_windows_facebook_post.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    patch_core(source_root)


if __name__ == "__main__":
    main()
