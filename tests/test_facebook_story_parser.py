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
        {"playable_url_quality_hd":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/123456.mp4?oh=abc\u0026oe=def",
         "playable_duration_in_ms":16000}
        </script></body></html>
    '''
    video = core._parse_facebook_story_page(video_page)
    assert video is not None, "Video Story fixture was not parsed."
    assert video["media_type"] == "video", video
    assert video["direct_url"] == (
        "https://video.xx.fbcdn.net/v/t42.1790-2/123456.mp4?oh=abc&oe=def"
    ), video["direct_url"]
    assert video["duration"] == 16, video["duration"]
    assert video["raw"]["_facebook_story_direct"] is True

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

    print("FACEBOOK_STORY_VIDEO_PARSE_TEST=PASS")
    print("FACEBOOK_STORY_PHOTO_PARSE_TEST=PASS")
    print("FACEBOOK_LOGIN_PAGE_REJECTION_TEST=PASS")


if __name__ == "__main__":
    main()
