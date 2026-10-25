from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_instagram_download_folders.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))

    import app

    item = SimpleNamespace(uploader="creator.name")

    with tempfile.TemporaryDirectory(prefix="referensi-instagram-folders-") as temporary:
        base = Path(temporary)

        carousel = Path(
            app._instagram_download_all_folder(
                "https://www.instagram.com/p/ABC123/",
                str(base),
                [item, item, item],
                3,
            )
        )
        assert carousel.is_dir(), carousel
        assert carousel.parent == base, carousel
        assert carousel.name == "Instagram Carousel - creator.name - ABC123", carousel.name

        # A single-photo Instagram post is not a carousel and should keep the
        # configured output directory instead of creating an unnecessary folder.
        single_post = app._instagram_download_all_folder(
            "https://www.instagram.com/p/SINGLE123/",
            str(base),
            [item],
            1,
        )
        assert single_post == str(base), single_post

        story = Path(
            app._instagram_download_all_folder(
                "https://www.instagram.com/stories/creator.name/987654321/",
                str(base),
                [item, item],
                2,
            )
        )
        assert story.is_dir(), story
        assert story.parent == base, story
        assert story.name == "Instagram Story - creator.name - 987654321", story.name

        # All Items on a Highlights URL should also be grouped separately.
        highlight = Path(
            app._instagram_download_all_folder(
                "https://www.instagram.com/creator.name/highlights/555777/",
                str(base),
                [item, item],
                2,
            )
        )
        assert highlight.is_dir(), highlight
        assert highlight.name == "Instagram Story - creator.name - 555777", highlight.name

        # Non-Instagram links must never be rerouted by this helper.
        facebook_url = "https://www.facebook.com/watch/?v=12345"
        assert app._instagram_download_all_folder(
            facebook_url, str(base), [item, item], 2
        ) == str(base)

    app_source = (root / "app.py").read_text(encoding="utf-8")
    assert "download_all=all_items" in app_source
    assert "self.download_all = bool(download_all)" in app_source
    assert "self.output_dir = _instagram_download_all_folder(" in app_source

    print("INSTAGRAM_CAROUSEL_DOWNLOAD_ALL_FOLDER_TEST=PASS")
    print("INSTAGRAM_SINGLE_POST_FOLDER_GUARD_TEST=PASS")
    print("INSTAGRAM_STORY_DOWNLOAD_ALL_FOLDER_TEST=PASS")
    print("INSTAGRAM_HIGHLIGHTS_DOWNLOAD_ALL_FOLDER_TEST=PASS")
    print("INSTAGRAM_NON_INSTAGRAM_FOLDER_GUARD_TEST=PASS")
    print("INSTAGRAM_DOWNLOAD_ALL_STATE_WIRING_TEST=PASS")


if __name__ == "__main__":
    main()
