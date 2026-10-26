from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Patch {label!r} expected exactly one match, found {count}. No files were changed."
        )
    return text.replace(old, new, 1)


MIXED_POST_PARSER = r'''
def _parse_facebook_post_page(page: str) -> dict[str, Any] | None:
    """Return photos and direct video attachments from a Facebook Post fallback page."""
    import html
    import re
    from urllib.parse import urlparse

    if not page:
        return None
    page = html.unescape(page)

    # Keep the established photo parser as the source of truth for ordinary
    # photo-only posts. This extension activates only when direct video URLs
    # are actually present in the serialized post data.
    legacy = _parse_facebook_post_page_photos_only(page)
    meta = _facebook_story_meta_tags(page)

    priority = {
        "hd_src_no_ratelimit": 0,
        "hd_src": 1,
        "browser_native_hd_url": 2,
        "playable_url_quality_hd": 3,
        "playable_url_hd": 4,
        "sd_src_no_ratelimit": 5,
        "sd_src": 6,
        "browser_native_sd_url": 7,
        "playable_url_quality_sd": 8,
        "playable_url": 9,
        "video_url": 10,
        "browser_native_url": 11,
        "nested_video_url": 12,
        "mp4_url": 13,
        "og_video": 14,
    }
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    blocked_extensions = image_extensions | {".js", ".css", ".html", ".json", ".svg"}

    def decode_url(raw: str) -> str:
        return _decode_facebook_json_string(str(raw or "")).strip().rstrip("\\").replace("&amp;", "&")

    def is_cdn_video_url(raw: str) -> bool:
        candidate = decode_url(raw)
        try:
            parsed = urlparse(candidate)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        suffix = parsed.path.lower()
        if parsed.scheme not in {"http", "https"}:
            return False
        if not host.endswith(("fbcdn.net", "fbsbx.com", "facebook.com")):
            return False
        extension = ""
        tail = suffix.rsplit("/", 1)[-1]
        if "." in tail:
            extension = "." + tail.rsplit(".", 1)[-1]
        if extension in blocked_extensions:
            return False
        return True

    video_candidates: list[dict[str, Any]] = []
    seen_video_urls: set[str] = set()

    def add_video(raw_url: str, field: str, position: int) -> None:
        candidate = decode_url(raw_url)
        if not candidate or candidate in seen_video_urls or not is_cdn_video_url(candidate):
            return
        try:
            parsed = urlparse(candidate)
        except Exception:
            return

        # Direct video paths are sometimes extensionless; field provenance is
        # the primary signal. For unknown fields, only accept progressive MP4.
        extension = "." + parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path.rsplit("/", 1)[-1] else ""
        if field == "mp4_url" and extension not in {".mp4", ".m4v"}:
            return

        window = page[max(0, position - 1800):min(len(page), position + 1800)]
        video_id = ""
        id_matches = list(re.finditer(
            r'["\'](?:video_id|videoID|video_fbid|legacy_fbid)["\']\s*:\s*["\']?([A-Za-z0-9_-]{4,})',
            window,
            re.I,
        ))
        if id_matches:
            video_id = id_matches[-1].group(1)

        width = height = None
        for key, target in (("width", "width"), ("height", "height")):
            matches = list(re.finditer(r'["\']?' + key + r'["\']?\s*[:=]\s*(\d{2,5})', window, re.I))
            if matches:
                value = int(matches[-1].group(1))
                if 32 <= value <= 16384:
                    if target == "width":
                        width = value
                    else:
                        height = value

        duration = None
        for pattern in (
            r'["\']playable_duration_in_ms["\']\s*:\s*(\d+)',
            r'["\']video_duration_in_ms["\']\s*:\s*(\d+)',
        ):
            match = re.search(pattern, window, re.I)
            if match:
                duration = max(0, int(int(match.group(1)) / 1000))
                break

        video_candidates.append({
            "url": candidate,
            "field": field,
            "priority": priority.get(field, 99),
            "position": int(position),
            "video_id": video_id,
            "width": width,
            "height": height,
            "duration": duration,
            "thumbnail": decode_url(meta.get("og:image") or meta.get("og:image:url") or ""),
        })
        seen_video_urls.add(candidate)

    fields = (
        "hd_src_no_ratelimit",
        "hd_src",
        "browser_native_hd_url",
        "playable_url_quality_hd",
        "playable_url_hd",
        "sd_src_no_ratelimit",
        "sd_src",
        "browser_native_sd_url",
        "playable_url_quality_sd",
        "playable_url",
        "video_url",
        "browser_native_url",
    )
    for field in fields:
        pattern = re.compile(
            r'["\']' + re.escape(field) + r'["\']\s*:\s*["\']((?:\\.|[^"\'\\])*)["\']',
            re.I,
        )
        for match in pattern.finditer(page):
            add_video(match.group(1), field, match.start())

    # Some page versions wrap playable_url in an object instead of a string.
    nested_pattern = re.compile(
        r'["\'](?:playable_url|browser_native_hd_url|browser_native_sd_url|video_url)["\']\s*:\s*\{.{0,2600}?["\'](?:uri|url)["\']\s*:\s*["\']((?:\\.|[^"\'\\])*)["\']',
        re.I | re.S,
    )
    for match in nested_pattern.finditer(page):
        add_video(match.group(1), "nested_video_url", match.start())

    # Metadata video URLs can be useful when the page hides the attachment
    # object's normal field names. Prefer these only after the structured scan.
    if not video_candidates:
        for key in ("og:video", "og:video:url", "og:video:secure_url"):
            raw_url = meta.get(key, "")
            if raw_url:
                position = page.find(raw_url)
                add_video(raw_url, "og_video", max(0, position))

    # Final fallback for direct MP4/M4V links whose JSON key changed.
    for match in re.finditer(r'["\']((?:\\.|[^"\'\\])*)["\']', page, re.I):
        raw_value = match.group(1)
        decoded = decode_url(raw_value)
        try:
            parsed = urlparse(decoded)
        except Exception:
            continue
        if parsed.path.lower().endswith((".mp4", ".m4v")):
            add_video(raw_value, "mp4_url", match.start())

    if not video_candidates:
        return legacy

    # Group neighboring HD/SD URLs belonging to the same serialized video
    # attachment, selecting the best available URL per group rather than
    # exposing separate quality variants as separate videos.
    candidates = sorted(video_candidates, key=lambda item: item["position"])
    groups: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        selected_group = None
        for group in reversed(groups[-4:]):
            last = group[-1]
            left_id = str(candidate.get("video_id") or "")
            right_id = str(last.get("video_id") or "")
            if left_id and right_id and left_id != right_id:
                continue
            if left_id and right_id and left_id == right_id:
                selected_group = group
                break
            if candidate["position"] - last["position"] <= 4500:
                selected_group = group
                break
        if selected_group is None:
            groups.append([candidate])
        else:
            selected_group.append(candidate)

    videos: list[dict[str, Any]] = []
    for group in groups:
        chosen = min(group, key=lambda item: (item["priority"], item["position"]))
        videos.append({
            "url": chosen["url"],
            "extension": "mp4",
            "video_id": chosen.get("video_id") or "",
            "width": chosen.get("width"),
            "height": chosen.get("height"),
            "duration": chosen.get("duration"),
            "thumbnail": chosen.get("thumbnail") or "",
        })
    videos.sort(key=lambda item: next(
        candidate["position"] for candidate in candidates if candidate["url"] == item["url"]
    ))

    if legacy:
        title = str(legacy.get("title") or "Facebook Post")
        owner_name = str(legacy.get("owner_name") or "")
        photos = list(legacy.get("photos") or [])
    else:
        title_match = re.search(r"<title[^>]*>(.*?)</title\s*>", page, re.I | re.S)
        title = re.sub(r"\s+", " ", html.unescape(title_match.group(1))).strip() if title_match else ""
        if title.lower() in {"facebook", "log in to facebook", "login"}:
            title = ""
        title = title or re.sub(r"\s+", " ", meta.get("og:title", "")).strip() or "Facebook Post"
        owner_name = str(_facebook_story_owner_name(page) or "")
        photos = []

    # Do not turn a video's poster into a separate downloadable photo. Keep
    # explicitly attached photo_image/full_image URLs, and discard metadata or
    # thumbnail-only images whenever a video attachment is detected.
    preview_urls: set[str] = set()
    for key in ("og:image", "og:image:url", "twitter:image", "og:video:thumbnail"):
        value = decode_url(meta.get(key, ""))
        if value:
            preview_urls.add(value)
    for pattern in (
        r'["\'](?:video_thumbnail_url|thumbnail_url|thumbnail_src|poster_url|preferred_thumbnail)["\']\s*:\s*["\']((?:\\.|[^"\'\\])*)["\']',
        r'["\'](?:video_thumbnail|preferred_thumbnail|thumbnail|poster)["\']\s*:\s*\{.{0,1800}?["\']uri["\']\s*:\s*["\']((?:\\.|[^"\'\\])*)["\']',
    ):
        for match in re.finditer(pattern, page, re.I | re.S):
            value = decode_url(match.group(1))
            if value:
                preview_urls.add(value)

    explicit_photo_urls: set[str] = set()
    photo_patterns = (
        r'["\'](?:photo_image|full_image|large_image|original_image)["\']\s*:\s*\{.{0,2200}?["\']uri["\']\s*:\s*["\']((?:\\.|[^"\'\\])*)["\']',
        r'["\'](?:photo_uri|photo_url|large_image_url|original_image_url)["\']\s*:\s*["\']((?:\\.|[^"\'\\])*)["\']',
    )
    for pattern in photo_patterns:
        for match in re.finditer(pattern, page, re.I | re.S):
            context = page[max(0, match.start() - 900):match.start()].lower()
            if re.search(r"video_thumbnail|playable_url|browser_native|hd_src|sd_src|poster_url|video_id", context[-900:]):
                continue
            value = decode_url(match.group(1))
            try:
                parsed = urlparse(value)
            except Exception:
                continue
            host = (parsed.hostname or "").lower()
            if parsed.scheme in {"http", "https"} and host.endswith(("fbcdn.net", "fbsbx.com")):
                if any(parsed.path.lower().endswith(ext) for ext in image_extensions):
                    explicit_photo_urls.add(value)

    photos = [
        photo for photo in photos
        if str(photo.get("url") or "") not in preview_urls
        or str(photo.get("url") or "") in explicit_photo_urls
    ]

    # Keep the preview for UI display, but only use attachment URLs for actual
    # downloads. If this is a video-only post, photos remains empty.
    thumbnail = (
        str(photos[0].get("url") or "")
        if photos else str(videos[0].get("thumbnail") or "")
    )
    return {
        "title": title,
        "owner_name": owner_name,
        "thumbnail": thumbnail,
        "photos": photos,
        "videos": videos,
    }


'''


def patch_core(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "def _parse_facebook_post_page(page: str) -> dict[str, Any] | None:\n",
        "def _parse_facebook_post_page_photos_only(page: str) -> dict[str, Any] | None:\n",
        "preserve existing photo parser",
    )
    text = replace_once(
        text,
        "def analyze_facebook_post(\n",
        MIXED_POST_PARSER + "def analyze_facebook_post(\n",
        "add mixed photo/video page parser",
    )

    old_merge = '''            # Merge results across page frontends; direct signed URLs remain local.
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

'''
    new_merge = '''            # Merge the locally extracted attachments from Facebook's page variants.
            # Signed CDN URLs stay on-device and are never sent to a remote service.
            photo_map: dict[str, dict[str, Any]] = {}
            video_map: dict[str, dict[str, Any]] = {}
            for result in discovered:
                for photo in result.get("photos") or []:
                    photo_url = str(photo.get("url") or "")
                    if photo_url:
                        photo_map.setdefault(photo_url, photo)
                for video in result.get("videos") or []:
                    video_url = str(video.get("url") or "")
                    if not video_url:
                        continue
                    # Different Facebook frontends can return the same signed
                    # video path with different query tokens. Deduplicate on path.
                    try:
                        parsed_video = urllib.parse.urlparse(video_url)
                        video_key = parsed_video.path or video_url
                    except Exception:
                        video_key = video_url
                    video_map.setdefault(video_key, video)
            photos = [photo for photo in photo_map.values() if photo.get("url")]
            videos = [video for video in video_map.values() if video.get("url")]

            if photos or videos:
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
                        slide_index=len(items) + 1,
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

                for index, video in enumerate(videos, start=1):
                    video_url = str(video["url"])
                    raw = {
                        "source_url": url,
                        "extension": "mp4",
                        "media_id": "FBPostVideo_" + format(index, "03d"),
                        "_facebook_post_direct": True,
                        "_facebook_post_direct_video": True,
                    }
                    items.append(MediaItem(
                        slide_index=len(items) + 1,
                        title=title + " Video " + format(index, "03d"),
                        uploader=uploader,
                        duration=video.get("duration"),
                        thumbnail=str(video.get("thumbnail") or (photos[0]["url"] if photos else "")),
                        qualities=[],
                        raw=raw,
                        media_type="video",
                        direct_url=video_url,
                        width=video.get("width"),
                        height=video.get("height"),
                    ))

                first_thumbnail = (
                    str(photos[0]["url"]) if photos
                    else str(videos[0].get("thumbnail") or "")
                )
                return MediaInfo(
                    title=title,
                    uploader=uploader,
                    duration=None,
                    webpage_url=url,
                    thumbnail=first_thumbnail or None,
                    extractor="Facebook Post Media",
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

'''
    text = replace_once(text, old_merge, new_merge, "merge mixed Facebook Post media")

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Facebook Post mixed photo/video parser inserted; core.py syntax check passed.")


def patch_app(source_root: Path) -> None:
    path = source_root / "app.py"
    text = path.read_text(encoding="utf-8")

    anchor = '''            # Facebook Story analysis already has a direct CDN URL. Avoid
            # sending the unsupported /stories/ URL to yt-dlp first.
            if item.raw.get("_facebook_story_direct"):
'''
    replacement = r'''            # Facebook Post fallback video URLs are already direct CDN streams.
            # Keep them beside their sibling photos in the same post-specific folder.
            if item.raw.get("_facebook_post_direct_video"):
                import re as _re
                from pathlib import Path as _Path
                from urllib.parse import urlparse as _urlparse
                from dataclasses import replace as _replace_media_item

                source_url = str(item.raw.get("source_url") or "")
                owner_name = str(item.uploader or "").strip() or "Facebook"
                post_match = _re.search(r"pfbid[A-Za-z0-9]+", source_url, _re.I)
                if post_match:
                    post_identifier = post_match.group(0)
                else:
                    url_parts = [
                        part for part in _urlparse(source_url).path.split("/") if part
                    ]
                    share_pos = next(
                        (index for index, part in enumerate(url_parts) if part.lower() == "p"),
                        -1,
                    )
                    post_identifier = (
                        url_parts[share_pos + 1]
                        if share_pos >= 0 and len(url_parts) > share_pos + 1
                        else ""
                    )

                folder_parts = ["Facebook Post", owner_name]
                if post_identifier:
                    folder_parts.append(post_identifier)
                folder_name = " - ".join(folder_parts)
                folder_name = _re.sub(r'[<>:"/\\\\|?*\x00-\x1f]+', "_", folder_name)
                folder_name = _re.sub(r"\s+", " ", folder_name).strip(" ._")[:120]
                if not folder_name or folder_name in {".", ".."}:
                    folder_name = "Facebook Post"
                video_output_path = _Path(self.output_dir) / folder_name
                video_output_path.mkdir(parents=True, exist_ok=True)

                video_raw = dict(item.raw or {})
                video_raw["extension"] = "mp4"
                item = _replace_media_item(item, raw=video_raw)
                download_direct_item(
                    item,
                    str(video_output_path),
                    editing_compatible=self.editing_compatible,
                    progress_cb=hook,
                    include_slide_prefix=self.post_total_items > 1,
                )
                continue

            # Facebook Story analysis already has a direct CDN URL. Avoid
            # sending the unsupported /stories/ URL to yt-dlp first.
            if item.raw.get("_facebook_story_direct"):
'''
    text = replace_once(text, anchor, replacement, "add direct Facebook Post video route")

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Facebook Post direct-video download route inserted; app.py syntax check passed.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_mac_facebook_mixed_post.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not (source_root / "core.py").is_file() or not (source_root / "app.py").is_file():
        raise FileNotFoundError(f"Expected core.py and app.py under {source_root}")
    patch_core(source_root)
    patch_app(source_root)


if __name__ == "__main__":
    main()
