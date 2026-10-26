from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Patch {label!r} expected exactly one match, found {count}. No changes written."
        )
    return text.replace(old, new, 1)


INSTAGRAM_DOWNLOAD_FOLDER_HELPER = r'''
def _instagram_download_all_folder(
    url: str,
    output_dir: str,
    media_items,
    total_items: int,
) -> str:
    """Return a dedicated destination only for Instagram Download All collections."""
    import re
    from pathlib import Path
    from urllib.parse import unquote, urlparse

    parsed = urlparse((url or "").strip())
    if (parsed.hostname or "").lower() not in {"instagram.com", "www.instagram.com"}:
        return output_dir

    parts = [unquote(part) for part in (parsed.path or "").split("/") if part]
    lowered = [part.lower() for part in parts]
    is_story = bool(parts) and (
        lowered[0] == "stories" or "highlights" in lowered
    )
    is_carousel = bool(parts) and lowered[0] == "p" and int(total_items or 0) > 1

    if is_story:
        kind = "Instagram Story"
    elif is_carousel:
        kind = "Instagram Carousel"
    else:
        # Single media and unrelated Instagram URLs keep their existing path.
        return output_dir

    items = list(media_items or [])
    owner_name = next(
        (
            str(getattr(item, "uploader", "") or "").strip()
            for item in items
            if str(getattr(item, "uploader", "") or "").strip()
        ),
        "",
    )

    if not owner_name:
        if lowered[0] == "stories" and len(parts) > 1 and lowered[1] != "highlights":
            owner_name = parts[1]
        elif "highlights" in lowered and lowered[0] != "stories":
            owner_name = parts[0]
        else:
            owner_name = "Instagram"

    identifier = ""
    if is_carousel and len(parts) > 1:
        identifier = parts[1]
    elif is_story:
        if lowered[0] == "stories" and len(parts) > 2:
            identifier = parts[2]
        elif "highlights" in lowered:
            highlight_index = lowered.index("highlights")
            if len(parts) > highlight_index + 1:
                identifier = parts[highlight_index + 1]

    folder_parts = [kind, owner_name]
    if identifier:
        folder_parts.append(identifier)

    folder_name = " - ".join(folder_parts)
    folder_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", folder_name)
    folder_name = re.sub(r"\s+", " ", folder_name).strip(" ._")[:120]
    if not folder_name or folder_name in {".", ".."}:
        folder_name = kind

    folder_path = Path(output_dir).expanduser() / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    return str(folder_path)


'''


def patch_app(source_root: Path) -> None:
    path = source_root / "app.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "def _parse_timecode(value: str) -> float:\n",
        INSTAGRAM_DOWNLOAD_FOLDER_HELPER + "def _parse_timecode(value: str) -> float:\n",
        "insert Instagram Download All destination helper",
    )

    text = replace_once(
        text,
        '''            post_total_items=self.media.total_items,
            time_range=time_range,
        )
''',
        '''            post_total_items=self.media.total_items,
            time_range=time_range,
            download_all=all_items,
        )
''',
        "pass explicit Download All state",
    )

    text = replace_once(
        text,
        '''        cookie_browser, playlist_index=None, media_items=None, post_total_items=1,
        time_range=None,
    ):
''',
        '''        cookie_browser, playlist_index=None, media_items=None, post_total_items=1,
        time_range=None, download_all=False,
    ):
''',
        "accept explicit Download All state",
    )

    text = replace_once(
        text,
        '''        self.post_total_items = max(1, int(post_total_items or 1))
        self.time_range = time_range
''',
        '''        self.post_total_items = max(1, int(post_total_items or 1))
        self.time_range = time_range
        self.download_all = bool(download_all)
        if self.download_all:
            self.output_dir = _instagram_download_all_folder(
                url, output_dir, media_items, self.post_total_items
            )
''',
        "route Instagram Download All into a dedicated folder",
    )

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Instagram Download All folder patch applied; app.py syntax check passed.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_windows_instagram_download_all.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    patch_app(source_root)


if __name__ == "__main__":
    main()
