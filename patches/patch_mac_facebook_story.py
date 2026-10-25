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
    decoded_text = html.unescape(str(decoded))
    # Facebook sometimes emits one JSON-escape layer and sometimes two.
    # Normalize both forms after json.loads so escaped query separators do not
    # remain literal "\u0026" text in the signed media URL.
    for _ in range(2):
        decoded_text = (
            decoded_text.replace(r"\/", "/")
            .replace(r"\u0026", "&")
            .replace(r"\u003d", "=")
            .replace(r"\u003D", "=")
            .replace(r"\u0025", "%")
            .replace(r"\u003a", ":")
            .replace(r"\u003A", ":")
            .replace(r"\u002f", "/")
            .replace(r"\u002F", "/")
        )
    return decoded_text.strip()


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


def _facebook_story_owner_name(page: str) -> str | None:
    """Best-effort display name for the owner of the Facebook Story."""
    import html
    import re

    meta = _facebook_story_meta_tags(page)
    candidates = [
        meta.get("og:title", ""),
        meta.get("twitter:title", ""),
        meta.get("title", ""),
    ]
    title_match = re.search(r"<title[^>]*>(.*?)</title\s*>", page or "", re.I | re.S)
    if title_match:
        candidates.append(title_match.group(1))

    # Facebook's serialized Story data can contain the author independently
    # of the page title. Limit matches to Story owner/actor objects instead of
    # taking the first generic "name" on the entire page.
    owner_patterns = (
        r'"story_bucket_owner"\s*:\s*\{.{0,1200}?"name"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"story_owner"\s*:\s*\{.{0,1200}?"name"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"owner"\s*:\s*\{.{0,1200}?"name"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"actors"\s*:\s*\[\s*\{.{0,800}?"name"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"profile_name"\s*:\s*"((?:\\.|[^"\\])*)"',
    )
    for pattern in owner_patterns:
        match = re.search(pattern, page or "", re.I | re.S)
        if match:
            candidates.append(match.group(1))

    for value in candidates:
        name = html.unescape(str(value or "")).strip()
        if not name:
            continue
        name = re.sub(r"\s+", " ", name)
        # Remove a site suffix before interpreting the actual profile title.
        name = re.sub(r"\s*[|•–—-]\s*Facebook(?:\s*-\s*log in or sign up)?\s*$", "", name, flags=re.I)
        name = re.sub(r"\s*-\s*Facebook\s*$", "", name, flags=re.I)
        name = re.sub(r"\s*\|\s*Facebook\s*$", "", name, flags=re.I).strip()

        patterns = (
            r"^Story\s+by\s+(.+?)\s*$",
            r"^(.+?)['’]s\s+(?:Facebook\s+)?Stories?\s*$",
            r"^(.+?)\s+(?:shared|added)\s+(?:a\s+)?(?:new\s+)?Story\s*$",
            r"^(.+?)\s+on\s+Facebook\s*$",
        )
        for pattern in patterns:
            match = re.match(pattern, name, re.I)
            if match:
                name = match.group(1).strip()
                break

        name = re.sub(r"^(?:Facebook\s+)?Stories?(?:\s+Viewer)?$", "", name, flags=re.I).strip()
        if name.lower() in {
            "", "facebook", "log in to facebook", "login", "watch", "story",
            "facebook stories", "stories", "your story",
        }:
            continue
        if len(name) > 100:
            continue
        return name
    return None


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
    owner_name = _facebook_story_owner_name(page)

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
    # Treat every valid media URL as a separate selectable stream. Facebook's
    # field names are not reliable quality guarantees, so we deliberately do
    # not collapse candidates into only one guessed HD and one guessed SD URL.
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
        ("browser_native_url", "Best", 50),
    )

    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def add_video_candidate(raw_url: str, source: str, position: int, declared_tier: str = "Best") -> None:
        candidate = decode_match(raw_url)
        if not valid_media_url(candidate, "video") or candidate in seen_urls:
            return

        # Dimensions are hints only. They are shown if the page exposes them,
        # but do not decide whether the stream is kept or how it's labelled.
        dimension_tier = "SD" if declared_tier == "SD" else "HD"
        width, height = dimensions_near(position, dimension_tier)
        candidates.append({
            "url": candidate,
            "source": source,
            "position": position,
            "width": width,
            "height": height,
        })
        seen_urls.add(candidate)

    for field, declared_tier, _rank in field_specs:
        pattern = re.compile(
            r'"' + re.escape(field) + r'"\s*:\s*"((?:\\.|[^"\\])*)"',
            re.I,
        )
        for match in pattern.finditer(page):
            add_video_candidate(match.group(1), field, match.start(), declared_tier)

    # Also scan all quoted strings for direct progressive MP4/M4V URLs, even
    # when Facebook changes the JSON field name. This deliberately excludes
    # HLS/DASH manifests and non-video CDN assets; those require a separate
    # audio/video-aware path and should not be mislabeled as standalone MP4s.
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"', page):
        raw_value = match.group(1)
        candidate = decode_match(raw_value)
        try:
            candidate_path = urlparse(candidate).path.lower()
        except Exception:
            continue
        if not candidate_path.endswith((".mp4", ".m4v")):
            continue
        add_video_candidate(raw_value, "generic_mp4_url", match.start(), "Best")

    # Some templates wrap playable_url in an object rather than a string.
    # Check these even if direct string fields were already found.
    nested_pattern = re.compile(
        r'"playable_url"\s*:\s*\{\s*"url"\s*:\s*"((?:\\.|[^"\\])*)"',
        re.I,
    )
    for match in nested_pattern.finditer(page):
        add_video_candidate(match.group(1), "playable_url.url", match.start(), "Best")

    # Open Graph video metadata can be an additional stream, so keep it too
    # when it is distinct from the URLs found in the JSON fields.
    for key in ("og:video", "og:video:url", "og:video:secure_url"):
        candidate = decode_match(meta.get(key, ""))
        if candidate and valid_media_url(candidate, "video") and candidate not in seen_urls:
            candidates.append({
                "url": candidate,
                "source": key,
                "position": len(page) + len(candidates),
                "width": None,
                "height": None,
            })
            seen_urls.add(candidate)

    # Preserve document order: the first discovered stream is the initial
    # selection, while all distinct URLs remain available in the quality menu.
    candidates.sort(key=lambda item: int(item["position"]))
    variants_by_tier: dict[str, dict[str, Any]] = {}
    used_selector_heights: set[int] = set()
    for index, candidate in enumerate(candidates, start=1):
        width, height = candidate.get("width"), candidate.get("height")
        fallback_height = 1280 if index == 1 else 640
        selector_height = int(height or fallback_height)
        if selector_height in used_selector_heights:
            selector_height = fallback_height
            while selector_height in used_selector_heights:
                selector_height += 1
        used_selector_heights.add(selector_height)

        label = f"Stream {index}"
        if width and height:
            label += f" • {width}×{height}"

        # Internal tier is intentionally generic: these are separate stream
        # candidates, not a claim that the source field really means HD or SD.
        variants_by_tier[f"stream_{index:03d}"] = {
            "url": candidate["url"],
            "tier": "Stream",
            "rank": len(candidates) - index + 1,
            "label": label,
            "width": width,
            "height": height,
            "selector_height": selector_height,
            "extension": "mp4",
            "source_field": candidate["source"],
        }

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

    variants = sorted(
        variants_by_tier.values(),
        key=lambda item: item["rank"],
        reverse=True,
    )
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
            "owner_name": owner_name,
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
            "owner_name": owner_name,
            "duration": None,
            "variants": [],
            "width": None,
            "height": None,
            "raw": {"_facebook_story_direct": True, "extension": extension},
        }
    return None


def _parse_facebook_story_graphql_response(
    response_text: str, story_id: str,
) -> dict[str, Any] | None:
    """Extract progressive video renditions from Facebook's Story GraphQL payload."""
    import base64
    import json
    import re
    from urllib.parse import urlparse

    if not response_text or not story_id:
        return None

    def normalize_id(value: Any) -> str:
        return str(value or "").strip()

    def id_matches(story_node: dict[str, Any]) -> bool:
        target = normalize_id(story_id)
        info = story_node.get("story_card_info") or {}
        possible = [
            normalize_id(story_node.get("id")),
            normalize_id(info.get("story_card_id")),
            normalize_id(story_node.get("story_id")),
            normalize_id(story_node.get("legacy_story_id")),
        ]
        if any(candidate and (candidate == target or target in candidate) for candidate in possible):
            return True
        for candidate in possible:
            if not candidate:
                continue
            try:
                decoded = base64.b64decode(candidate + "=" * ((4 - len(candidate) % 4) % 4)).decode(
                    "utf-8", errors="ignore"
                )
                if target in decoded:
                    return True
            except Exception:
                pass
        try:
            decoded_target = base64.b64decode(target + "=" * ((4 - len(target) % 4) % 4)).decode(
                "utf-8", errors="ignore"
            )
            return any(candidate and candidate in decoded_target for candidate in possible)
        except Exception:
            return False

    documents: list[Any] = []
    for line in response_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("for (;;);"):
            line = line[len("for (;;);"):].strip()
        try:
            documents.append(json.loads(line))
        except Exception:
            continue
    if not documents:
        try:
            documents.append(json.loads(response_text.strip().removeprefix("for (;;);")))
        except Exception:
            return None

    story_nodes: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            stories = value.get("unified_stories")
            if isinstance(stories, dict):
                edges = stories.get("edges")
                if isinstance(edges, list):
                    for edge in edges:
                        node = edge.get("node") if isinstance(edge, dict) else None
                        if isinstance(node, dict) and id_matches(node):
                            story_nodes.append(node)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for document in documents:
        walk(document)

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    owner_name: str | None = None
    for story_node in story_nodes:
        # Story owner names appear under different shapes across GraphQL revisions.
        for owner_key in ("story_bucket_owner", "story_owner", "owner", "actors", "story_card_info"):
            owner_value = story_node.get(owner_key)
            if isinstance(owner_value, list):
                owner_value = next((entry for entry in owner_value if isinstance(entry, dict)), None)
            if isinstance(owner_value, dict):
                candidate_name = str(
                    owner_value.get("name")
                    or owner_value.get("display_name")
                    or owner_value.get("profile_name")
                    or ""
                ).strip()
                if candidate_name and candidate_name.lower() not in {"facebook", "stories"}:
                    owner_name = candidate_name
                    break
        if owner_name:
            break

    for story_node in story_nodes:
        for attachment in story_node.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            media = attachment.get("media") or {}
            delivery = (
                media.get("videoDeliveryResponseFragment") or {}
            ).get("videoDeliveryResponseResult") or {}
            progressive = delivery.get("progressive_urls") or []
            for row in progressive:
                if not isinstance(row, dict):
                    continue
                direct_url = str(row.get("progressive_url") or row.get("url") or "").strip()
                if not direct_url or direct_url in seen:
                    continue
                try:
                    parsed = urlparse(direct_url)
                except Exception:
                    continue
                host = (parsed.hostname or "").lower()
                if (
                    parsed.scheme not in {"http", "https"}
                    or not host.endswith(("fbcdn.net", "fbsbx.com"))
                    or not parsed.path.lower().endswith((".mp4", ".m4v"))
                ):
                    continue
                metadata = row.get("metadata") or {}
                width = metadata.get("width") or row.get("width")
                height = metadata.get("height") or row.get("height")
                if not width or not height:
                    resolution = str(metadata.get("resolution") or "")
                    size_match = re.match(r"(\d{2,5})\s*[x×]\s*(\d{2,5})", resolution, re.I)
                    if size_match:
                        width, height = int(size_match.group(1)), int(size_match.group(2))
                seen.add(direct_url)
                variants.append({
                    "url": direct_url,
                    "tier": "Stream",
                    "rank": 0,
                    "label": "GraphQL Stream",
                    "width": int(width) if width else None,
                    "height": int(height) if height else None,
                    "selector_height": int(height or 1280),
                    "extension": "mp4",
                    "source_field": "graphql.progressive_urls",
                })

    if not variants:
        return None

    return {
        "direct_url": variants[0]["url"],
        "media_type": "video",
        "extension": "mp4",
        "thumbnail": None,
        "title": "Facebook Story",
        "owner_name": owner_name,
        "duration": None,
        "variants": variants,
        "width": variants[0].get("width"),
        "height": variants[0].get("height"),
        "raw": {"_facebook_story_direct": True, "_facebook_story_graphql": True},
    }


def _fetch_facebook_story_graphql_media(
    response_texts: list[str],
    url: str,
    cookie_jar: Any,
    browser_session: Any = None,
    urllib_opener: Any = None,
) -> dict[str, Any] | None:
    """Ask Facebook's logged-in Story bucket query for progressive renditions.

    Cookies and the request token stay local to the app. This helper is a
    supplemental extraction method; HTML parsing remains the fallback.
    """
    import re
    import urllib.parse
    import urllib.request
    from html import unescape

    try:
        parsed = urllib.parse.urlparse(url.strip())
        path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        if "stories" not in path_parts:
            return None
        index = path_parts.index("stories")
        if len(path_parts) <= index + 2:
            return None
        bucket_id = path_parts[index + 1]
        story_id = path_parts[index + 2]
        if not bucket_id or not story_id:
            return None

        user_id = next(
            (str(cookie.value) for cookie in cookie_jar if cookie.name == "c_user"),
            "",
        )
        if not user_id:
            return None

        token = ""
        token_patterns = (
            r'name=["\']fb_dtsg["\'][^>]*value=["\']([^"\']+)',
            r'"DTSGInitialData",\[\],\{"token":"([^"]+)"',
            r'"fb_dtsg"\s*:\s*"([^"]+)"',
            r'"token"\s*:\s*"([^"]+)"',
        )
        for page in response_texts:
            for pattern in token_patterns:
                match = re.search(pattern, page, re.I)
                if match:
                    token = unescape(match.group(1))
                    if token:
                        break
            if token:
                break
        if not token:
            return None

        variables = {
            "bucketIDs": [bucket_id],
            "scale": 2,
            "blur": 10,
            "shouldEnableArmadilloStoryReply": True,
            "shouldEnableLiveInStories": True,
            "feedbackSource": 65,
            "useDefaultActor": False,
            "feedLocation": "COMET_MEDIA_VIEWER",
            "focusCommentID": None,
            "shouldDeferLoad": False,
            "isStoriesArchive": False,
            "__relay_internal__pv__IsWorkUserrelayprovider": False,
        }
        body = urllib.parse.urlencode({
            "av": user_id,
            "__aaid": "0",
            "__user": user_id,
            "__a": "1",
            "__req": "t",
            "fb_dtsg": token,
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "StoriesViewerBucketPrefetcherMultiBucketsQuery",
            "variables": __import__("json").dumps(variables, separators=(",", ":")),
            "server_timestamps": "true",
            "doc_id": "9340191609394579",
        }).encode("utf-8")
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.facebook.com",
            "Referer": url,
            "X-Fb-Friendly-Name": "StoriesViewerBucketPrefetcherMultiBucketsQuery",
        }

        response_text = ""
        endpoint = "https://www.facebook.com/api/graphql/"
        if browser_session is not None:
            response = browser_session.post(
                endpoint, data=body, headers=headers, timeout=25, allow_redirects=True
            )
            status = int(response.status_code)
            response_text = str(response.text or "")
            try:
                response.close()
            except Exception:
                pass
            if status < 200 or status >= 300:
                return None
        elif urllib_opener is not None:
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            with urllib_opener.open(request, timeout=25) as response:
                response_text = response.read(20 * 1024 * 1024).decode("utf-8", errors="replace")
        else:
            return None

        return _parse_facebook_story_graphql_response(response_text, story_id)
    except Exception:
        # The query is an optional fallback. Do not replace a successful HTML
        # parse with an opaque error, and never log request tokens or cookies.
        return None


def _merge_facebook_story_media_candidates(
    media_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Merge media discovered from several Facebook page frontends.

    Facebook can return different media payloads for www, m, and mbasic
    frontends. A successful low-resolution parse from one host must not stop
    extraction from the other hosts.
    """
    usable = [
        media for media in media_candidates
        if isinstance(media, dict) and media.get("media_type") in {"video", "photo"}
    ]
    videos = [media for media in usable if media.get("media_type") == "video"]
    if not videos:
        return dict(usable[0]) if usable else None

    # Keep the first video payload for stable title/thumbnail metadata, but
    # pool all distinct direct streams discovered on every page frontend.
    merged = dict(videos[0])
    merged["owner_name"] = next(
        (
            str(media.get("owner_name")).strip()
            for media in usable
            if str(media.get("owner_name") or "").strip()
        ),
        None,
    )
    variants: list[dict[str, Any]] = []
    variant_by_url: dict[str, dict[str, Any]] = {}
    for media in videos:
        media_variants = list(media.get("variants") or [])
        if not media_variants and media.get("direct_url"):
            media_variants = [{
                "url": str(media["direct_url"]),
                "tier": "Stream",
                "rank": 0,
                "label": "Stream",
                "width": media.get("width"),
                "height": media.get("height"),
                "selector_height": int(media.get("height") or 1280),
                "extension": str(media.get("extension") or "mp4"),
            }]
        for variant in media_variants:
            stream_url = str(variant.get("url") or "").strip()
            if not stream_url:
                continue
            prior = variant_by_url.get(stream_url)
            if prior is not None:
                # If the same URL appeared with richer dimension metadata on
                # another frontend, retain the metadata rather than duplicate it.
                for dim in ("width", "height"):
                    if not prior.get(dim) and variant.get(dim):
                        prior[dim] = variant[dim]
                continue
            copied = dict(variant)
            copied["url"] = stream_url
            variant_by_url[stream_url] = copied
            variants.append(copied)

    if variants:
        for index, variant in enumerate(variants, start=1):
            variant["tier"] = "Stream"
            variant["rank"] = len(variants) - index + 1
            width, height = variant.get("width"), variant.get("height")
            variant["label"] = (
                f"Stream {index} • {width}×{height}"
                if width and height else f"Stream {index}"
            )
            # Assign an initial unique key even when several frontends report
            # the same resolution. The caller also normalizes these for UI use.
            variant["selector_height"] = 10000 + index
            variant["extension"] = str(variant.get("extension") or "mp4")

        merged["variants"] = variants
        merged["direct_url"] = variants[0]["url"]
        merged["width"] = variants[0].get("width")
        merged["height"] = variants[0].get("height")
        merged["raw"] = dict(merged.get("raw") or {})
        merged["raw"]["_facebook_story_direct"] = True
        merged["raw"]["_facebook_story_stream_count"] = len(variants)

    return merged


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
    for host in (
        "www.facebook.com",
        "m.facebook.com",
        "mbasic.facebook.com",
        "web.facebook.com",
        "touch.facebook.com",
    ):
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

            media_results: list[dict[str, Any]] = []
            page_sources: list[str] = []
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

                page_sources.append(page)
                parsed_media = _parse_facebook_story_page(page)
                if parsed_media:
                    media_results.append(parsed_media)
                    # Keep scanning all frontends; one low-resolution result
                    # is not proof that the other page variants have no better
                    # stream metadata.
                    continue

                if status_code >= 400:
                    # Do not dump response bodies; some contain account-related
                    # page data. Report only the HTTP status and host.
                    response_host = urllib.parse.urlparse(last_final_url).hostname or "Facebook"
                    errors.append(
                        f"{browser.title()}: {response_host} HTTP {status_code} "
                        "(permintaan halaman ditolak)"
                    )
                    continue

            # HTML parsing can expose only the low-resolution preview. Ask
            # Facebook's authenticated Story bucket query for the progressive
            # renditions as a supplemental source before finalizing the menu.
            graphql_media = _fetch_facebook_story_graphql_media(
                page_sources,
                url,
                jar,
                browser_session=browser_session,
                urllib_opener=opener,
            )
            if graphql_media:
                media_results.append(graphql_media)

            media = _merge_facebook_story_media_candidates(media_results)

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

                # This extra action is limited to Facebook Story videos. Keep
                # normal per-stream choices unchanged and append a sentinel
                # option so the worker can download every discovered stream.
                if media_type == "video" and variants:
                    qualities.insert(0, QualityOption("Download All", -1))

                raw = dict(media.get("raw") or {})
                raw.update({
                    "source_url": url,
                    "extension": extension,
                    "_facebook_story_direct": True,
                    "_facebook_story_variants": variants,
                    "_facebook_story_owner_name": str(media.get("owner_name") or "").strip() or None,
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

                # "Download All" is a Facebook-Story-only sentinel value.
                # Download each distinct direct stream to a deterministic,
                # stream-numbered filename. Do not select or infer quality.
                if requested_height == -1:
                    from dataclasses import replace as _replace_media_item
                    streams = [
                        variant for variant in variants
                        if isinstance(variant, dict) and str(variant.get("url") or "").strip()
                    ]
                    stream_count = len(streams)
                    if not stream_count:
                        raise RuntimeError("Facebook Story tidak memiliki stream video untuk diunduh.")

                    completed_streams = 0
                    failed_streams: list[int] = []
                    for stream_index, variant in enumerate(streams, start=1):
                        selected_url = str(variant["url"]).strip()
                        stream_label = str(variant.get("label") or f"Stream {stream_index}")
                        stream_raw = dict(item.raw or {})
                        stream_raw["extension"] = str(variant.get("extension") or "mp4")
                        stream_raw["_selected_story_quality"] = stream_label
                        stream_raw["media_id"] = f"FBStoryStream_{stream_index:03d}"
                        stream_item = _replace_media_item(
                            item, direct_url=selected_url, raw=stream_raw,
                            width=variant.get("width") or item.width,
                            height=variant.get("height") or item.height,
                        )

                        def stream_hook(
                            d, _stream_index=stream_index, _stream_label=stream_label,
                            _stream_item=stream_item,
                        ):
                            local_pct, status_text = self._event_to_local(d, _stream_item)
                            fraction = max(0.0, min(100.0, float(local_pct))) / 100.0
                            overall_pct = ((_stream_index - 1 + fraction) / stream_count) * 100.0
                            self.progress.emit(
                                overall_pct,
                                f"Stream {_stream_index}/{stream_count} • {_stream_label} • {status_text}",
                            )

                        try:
                            if self.time_range is not None or self.audio_only:
                                download_media(
                                    stream_item.direct_url, self.output_dir, None, self.container,
                                    self.audio_only, self.editing_compatible,
                                    progress_cb=stream_hook, cookie_browser=None,
                                    time_range=self.time_range,
                                    filename_prefix=f"Stream {stream_index:03d} - ",
                                )
                            else:
                                download_direct_item(
                                    stream_item, self.output_dir,
                                    editing_compatible=self.editing_compatible,
                                    progress_cb=stream_hook, include_slide_prefix=False,
                                )
                            completed_streams += 1
                        except Exception:
                            # A stale/invalid signed URL should not prevent the
                            # remaining stream candidates from being attempted.
                            failed_streams.append(stream_index)
                            self.progress.emit(
                                (stream_index / stream_count) * 100.0,
                                f"Stream {stream_index}/{stream_count} gagal • {stream_label}",
                            )
                            continue

                    if completed_streams == 0:
                        raise RuntimeError(
                            f"Download All gagal: 0 dari {stream_count} stream berhasil diunduh."
                        )
                    if failed_streams:
                        self.completion_message = (
                            f"Download All selesai sebagian • {completed_streams}/{stream_count} stream berhasil "
                            f"• {len(failed_streams)} gagal"
                        )
                    else:
                        self.completion_message = (
                            f"Download All selesai • {completed_streams} stream berhasil diunduh"
                        )
                    self.progress.emit(100.0, self.completion_message)
                    continue

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
                    # MediaItem is immutable; create a replacement instead of
                    # assigning to item.direct_url (which raises FrozenInstanceError).
                    from dataclasses import replace as _replace_media_item
                    selected_url = str(selected_variant["url"])
                    selected_raw = dict(item.raw or {})
                    selected_raw["extension"] = str(
                        selected_variant.get("extension") or "mp4"
                    )
                    selected_raw["_selected_story_quality"] = str(
                        selected_variant.get("label") or "Best Available"
                    )
                    item = _replace_media_item(
                        item, direct_url=selected_url, raw=selected_raw
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
    text = replace_once(
        text,
        '''    def _download_done(self):
        self.progress.setValue(100); self.status.setText("Download selesai • Siap di-import ke editor")
''',
        '''    def _download_done(self):
        worker = getattr(self, "_worker", None)
        message = getattr(worker, "completion_message", None)
        self.progress.setValue(100)
        self.status.setText(message or "Download selesai • Siap di-import ke editor")
''',
        "show Download All stream completion summary",
    )

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Facebook Story Download All routing inserted; app.py syntax check passed.")


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
