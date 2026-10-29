from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_windows_instagram_story_engine.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))
    import core

    story_url = "https://www.instagram.com/stories/creator.name/1234567890/"
    post_url = "https://www.instagram.com/p/ABC123/"
    assert core._is_instagram_story_url(story_url)
    assert core._is_instagram_story_url("https://www.instagram.com/creator.name/highlights")
    assert not core._is_instagram_story_url(post_url)

    media_url = "https://scontent.cdninstagram.com/v/t51.2885-15/story-test.jpg?token=private"
    metadata = {"type": "image", "username": "creator.name", "extension": "jpg"}
    output = json.dumps([[2, {"username": "creator.name"}], [3, media_url, metadata]])
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr="")

    original_ensure = core._ensure_gallery_dl_story_binary
    core._ensure_gallery_dl_story_binary = lambda: r"C:\fake\gallery-dl-story.exe"
    try:
        with tempfile.TemporaryDirectory(prefix="rd-story-cookies-") as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch("subprocess.run", return_value=completed) as run:
                rows = core._gallery_instagram_story_cli_rows(
                    story_url, cookie_file=str(cookie_file)
                )
            assert rows == [(2, {"username": "creator.name"}), (3, media_url, metadata)], rows
            args = run.call_args.args[0]
            assert args[0] == r"C:\fake\gallery-dl-story.exe"
            assert "--dump-json" in args and "--no-download" in args
            assert "--cookies" in args and str(cookie_file) in args

        with patch("subprocess.run", return_value=completed) as run:
            rows = core._gallery_instagram_story_cli_rows(
                story_url, "chrome", r"C:\Users\demo\AppData\Local\Google\Chrome\User Data\Profile 1"
            )
        args = run.call_args.args[0]
        cookie_index = args.index("--cookies-from-browser")
        assert args[cookie_index + 1] == "chrome/.instagram.com:Profile 1", args[cookie_index + 1]
        assert rows[1][1] == media_url
    finally:
        core._ensure_gallery_dl_story_binary = original_ensure

    print("INSTAGRAM_STORY_URL_ROUTING_TEST=PASS")
    print("INSTAGRAM_STORY_CLI_JSON_PARSE_TEST=PASS")
    print("INSTAGRAM_STORY_COOKIES_FILE_TEST=PASS")
    print("INSTAGRAM_STORY_BROWSER_PROFILE_TEST=PASS")


if __name__ == "__main__":
    main()
