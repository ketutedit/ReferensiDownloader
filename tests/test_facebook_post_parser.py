from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_facebook_post_parser.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))

    import core

    single_photo_page = r'''
        <html><head>
        <title>Bambang Pamungkas | Facebook</title>
        <meta property="og:title" content="Bambang Pamungkas | Facebook">
        <meta property="og:image" content="https://scontent.xx.fbcdn.net/v/t39.30808-6/main-photo.jpg?stp=dst-jpg_s1080x1080">
        </head><body></body></html>
    '''
    single = core._parse_facebook_post_page(single_photo_page)
    assert single is not None, "Single-photo Facebook post was not parsed."
    assert single["owner_name"] == "Bambang Pamungkas", single
    assert len(single["photos"]) == 1, single["photos"]
    assert single["photos"][0]["url"] == (
        "https://scontent.xx.fbcdn.net/v/t39.30808-6/main-photo.jpg?stp=dst-jpg_s1080x1080"
    ), single["photos"]

    multi_photo_page = r'''
        <html><head>
        <title>Photo Album | Facebook</title>
        <meta property="og:title" content="Bambang Pamungkas | Facebook">
        </head><body><script type="application/json">
        {
          "attachments": [
            {
              "media": {
                "photo_image": {
                  "uri": "https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/photo-one.jpg?stp=dst-jpg_s1080x1080"
                }
              }
            },
            {
              "media": {
                "photo_image": {
                  "uri": "https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/photo-two.jpg?stp=dst-jpg_s1080x1080"
                }
              }
            }
          ],
          "profile_pic": {
            "uri": "https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-1\/avatar.jpg?stp=dst-jpg_s100x100"
          }
        }
        </script></body></html>
    '''
    multi = core._parse_facebook_post_page(multi_photo_page)
    assert multi is not None, "Multi-photo Facebook post was not parsed."
    multi_urls = [photo["url"] for photo in multi["photos"]]
    assert len(multi_urls) == 2, multi_urls
    assert any("photo-one.jpg" in url for url in multi_urls), multi_urls
    assert any("photo-two.jpg" in url for url in multi_urls), multi_urls
    assert not any("avatar.jpg" in url for url in multi_urls), multi_urls

    bad_host_page = r'''
        <html><head>
        <meta property="og:image" content="https://example.com/not-facebook.jpg">
        </head><body></body></html>
    '''
    assert core._parse_facebook_post_page(bad_host_page) is None

    # The app should only invoke the custom photo fallback after the normal
    # Facebook post/video extractor raises, so existing successful paths remain.
    app_source = (root / "app.py").read_text(encoding="utf-8")
    assert "self.done.emit(analyze_url(self.url, self.cookie_browser))" in app_source
    assert "from core import analyze_facebook_post" in app_source
    assert "except Exception as primary_error:" in app_source
    assert '"pfbid" in normalized_url or "/share/p/" in normalized_url' in app_source
    # Facebook Post fallback photos, including single-photo Download All,
    # should route to a post-specific folder rather than the general download root.
    assert 'if item.raw.get("_facebook_post_direct"):' in app_source
    assert 'folder_parts = ["Facebook Post", owner_name]' in app_source
    assert 'photo_output_path = _Path(self.output_dir) / folder_name' in app_source

    print("FACEBOOK_POST_SINGLE_PHOTO_TEST=PASS")
    print("FACEBOOK_POST_MULTI_PHOTO_TEST=PASS")
    print("FACEBOOK_POST_AVATAR_FILTER_TEST=PASS")
    print("FACEBOOK_POST_FALLBACK_ROUTING_TEST=PASS")


if __name__ == "__main__":
    main()
