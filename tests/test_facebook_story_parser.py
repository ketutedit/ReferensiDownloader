from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_facebook_story_parser.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))

    import core

    video_page = r'''
        <html><head>
        <title>Story by Test Account</title>
        <meta property="og:image" content="https://scontent.xx.fbcdn.net/v/t39.30808-6/thumb.jpg?x=1">
        </head><body><script type="application/json">
        {
          "width":720,"height":1280,
          "hd_src_no_ratelimit":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-hd.mp4?oh=hd\u0026oe=def",
          "sd_width":360,"sd_height":640,
          "sd_src_no_ratelimit":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-sd.mp4?oh=sd\u0026oe=def",
          "playable_url":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/playable-standard.mp4?oh=sd2\u0026oe=def",
          "playable_duration_in_ms":16000
        }
        </script></body></html>
    '''
    video = core._parse_facebook_story_page(video_page)
    assert video is not None, "Video Story fixture was not parsed."
    assert video["media_type"] == "video", video
    assert video["direct_url"] == (
        "https://video.xx.fbcdn.net/v/t42.1790-2/story-hd.mp4?oh=hd&oe=def"
    ), video["direct_url"]
    assert video["duration"] == 16, video["duration"]
    assert video["thumbnail"] == (
        "https://scontent.xx.fbcdn.net/v/t39.30808-6/thumb.jpg?x=1"
    ), video["thumbnail"]
    assert video["raw"]["_facebook_story_direct"] is True
    variants = video["variants"]
    assert len(variants) == 2, variants
    assert variants[0]["tier"] == "HD", variants
    assert variants[0]["width"] == 720 and variants[0]["height"] == 1280, variants[0]
    assert variants[0]["selector_height"] == 1280, variants[0]
    assert variants[0]["label"] == "HD • 720×1280", variants[0]
    assert variants[1]["tier"] == "SD", variants
    assert variants[1]["width"] == 360 and variants[1]["height"] == 640, variants[1]
    assert variants[1]["selector_height"] == 640, variants[1]
    assert variants[1]["label"] == "SD • 360×640", variants[1]

    photo_page = r'''
        <html><head><title>Story image</title>
        <meta property="og:image" content="https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/story.jpg?x=1&amp;y=2">
        </head><body></body></html>
    '''
    photo = core._parse_facebook_story_page(photo_page)
    assert photo is not None, "Photo Story fixture was not parsed."
    assert photo["media_type"] == "photo", photo
    assert photo["direct_url"] == (
        "https://scontent.xx.fbcdn.net/v/t39.30808-6/story.jpg?x=1&y=2"
    ), photo["direct_url"]

    login_page = """
        <html><head><title>Log in to Facebook</title></head>
        <body><form action="/login.php"></form></body></html>
    """
    assert core._parse_facebook_story_page(login_page) is None

    # Regression guard: the download path must replace immutable MediaItem
    # instances instead of assigning directly to a frozen field.
    app_source = (root / "app.py").read_text(encoding="utf-8")
    assert 'item.direct_url = str(selected_variant["url"])' not in app_source
    assert "from dataclasses import replace as _replace_media_item" in app_source
    assert "item, direct_url=selected_url, raw=selected_raw" in app_source

    print("FACEBOOK_STORY_VIDEO_PARSE_TEST=PASS")
    print("FACEBOOK_STORY_QUALITY_VARIANTS_TEST=PASS")
    print("FACEBOOK_STORY_THUMBNAIL_TEST=PASS")
    print("FACEBOOK_STORY_PHOTO_PARSE_TEST=PASS")
    print("FACEBOOK_LOGIN_PAGE_REJECTION_TEST=PASS")


if __name__ == "__main__":
    main()
