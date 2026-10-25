from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_instagram_story_engine.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))

    import core

    assert core._is_instagram_story_url("https://www.instagram.com/stories/example/") is True
    assert core._is_instagram_story_url("https://www.instagram.com/stories/example/123456/") is True
    assert core._is_instagram_story_url("https://www.instagram.com/stories/highlights/12345/") is True
    assert core._is_instagram_story_url("https://www.instagram.com/example/highlights/") is True

    # Critical isolation guard: posts, reels, and carousel URLs must not
    # select the Story-only daily binary.
    assert core._is_instagram_story_url("https://www.instagram.com/p/ABC123/") is False
    assert core._is_instagram_story_url("https://www.instagram.com/reel/ABC123/") is False
    assert core._is_instagram_story_url("https://www.instagram.com/reels/ABC123/") is False
    assert core._is_instagram_story_url("https://www.facebook.com/stories/example/12345/") is False

    row = {
        "category": "instagram",
        "subcategory": "stories",
        "username": "example",
        "media_id": "123456",
        "url": "https://scontent.cdninstagram.com/story.mp4?sig=fixture",
        "filename": "example_123456.mp4",
        "extension": "mp4",
        "width": 720,
        "height": 1280,
        "duration": 12,
    }

    with patch.object(core, "_ensure_gallery_dl_story_binary", return_value="/tmp/gallery-dl-story"):
        with patch(
            "subprocess.run",
            return_value=CompletedProcess(
                args=["gallery-dl"],
                returncode=0,
                stdout=json.dumps([[3, row["url"], row]], indent=2),
                stderr="",
            ),
        ) as run:
            rows = core._gallery_instagram_story_cli_rows(
                "https://www.instagram.com/stories/example/123456/",
                cookie_browser="chrome",
            )

    assert rows == [(3, row["url"], row)], rows
    command = run.call_args.args[0]
    assert command[0] == "/tmp/gallery-dl-story", command
    assert "--dump-json" in command
    assert "--no-download" in command
    assert "--config-ignore" in command
    assert "--cookies-from-browser" in command
    cookie_index = command.index("--cookies-from-browser")
    assert command[cookie_index + 1] == "chrome/.instagram.com", command[cookie_index + 1]
    assert command[-2] == "--" and command[-1].startswith("https://www.instagram.com/stories/")

    # The subprocess error must be useful without leaking signed CDN URLs.
    with patch.object(core, "_ensure_gallery_dl_story_binary", return_value="/tmp/gallery-dl-story"):
        with patch(
            "subprocess.run",
            return_value=CompletedProcess(
                args=["gallery-dl"],
                returncode=1,
                stdout="",
                stderr="Login required: https://instagram.com/stories/example/?token=private",
            ),
        ):
            try:
                core._gallery_instagram_story_cli_rows(
                    "https://www.instagram.com/stories/example/",
                    cookie_browser="chrome",
                )
            except RuntimeError as exc:
                message = str(exc)
                assert "gallery-dl" in message
                assert "https://instagram.com/" not in message
                assert "token=private" not in message
            else:
                raise AssertionError("Story CLI failures should be returned as a clear error.")

    # DataJob failures are encoded as a tuple in stdout with exit code 0.
    # They should preserve the actual authentication reason instead of being
    # mistaken for a successful extraction with no media.
    auth_failure = [[-1, {
        "error": "AbortExtraction",
        "message": "Failed to load API data ('Unauthorized logged out query.')",
    }]]
    with patch.object(core, "_ensure_gallery_dl_story_binary", return_value="/tmp/gallery-dl-story"):
        with patch(
            "subprocess.run",
            return_value=CompletedProcess(
                args=["gallery-dl"],
                returncode=0,
                stdout=json.dumps(auth_failure, indent=2),
                stderr="",
            ),
        ):
            try:
                core._gallery_instagram_story_cli_rows(
                    "https://www.instagram.com/stories/example/",
                    cookie_browser="brave",
                )
            except RuntimeError as exc:
                assert "Unauthorized logged out query" in str(exc), str(exc)
            else:
                raise AssertionError("DataJob authentication errors must be surfaced.")

    # Verify the patched extractor selects the standalone engine only for
    # Story/Highlight URLs and retains the embedded DataJob path for everything else.
    source = (root / "core.py").read_text(encoding="utf-8")
    assert "if _is_instagram_story_url(url):" in source
    assert "rows = _gallery_instagram_story_cli_rows(" in source
    assert "url, cookie_browser, cookie_profile, cookie_file" in source
    assert "task = gdl_job.DataJob(url)" in source

    # This package remains deliberately pinned for existing post/reel/carousel
    # extraction. The new daily binary lives in the per-user app support folder.
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "gallery-dl==1.32.16" in requirements, requirements

    print("INSTAGRAM_STORY_ENGINE_ROUTE_ISOLATION_TEST=PASS")
    print("INSTAGRAM_STORY_ENGINE_JSON_METADATA_TEST=PASS")
    print("INSTAGRAM_STORY_ENGINE_AUTH_ERROR_TEST=PASS")
    print("INSTAGRAM_STORY_ENGINE_LOCAL_COOKIE_ARGS_TEST=PASS")
    print("INSTAGRAM_STORY_ENGINE_ERROR_REDACTION_TEST=PASS")
    print("INSTAGRAM_NON_STORY_ENGINE_PIN_PRESERVED_TEST=PASS")


if __name__ == "__main__":
    main()
