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
    assert not single.get("videos"), single

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
    assert not multi.get("videos"), multi

    mixed_photo_video_page = r'''
        <html><head>
        <title>Foto dan video | Facebook</title>
        <meta property="og:title" content="Bambang Pamungkas | Facebook">
        <meta property="og:image" content="https://scontent.xx.fbcdn.net/v/t39.30808-6/video-thumb.jpg?stp=dst-jpg_s1080x1080">
        </head><body><script type="application/json">
        {
          "attachments": [
            {
              "media": {
                "photo_image": {
                  "uri": "https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/real-photo.jpg?stp=dst-jpg_s1080x1080"
                }
              }
            },
            {
              "video_id": "778899",
              "browser_native_hd_url": "https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/real-video.mp4?sig=hd",
              "sd_src": "https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/real-video-sd.mp4?sig=sd",
              "video_thumbnail": {
                "uri": "https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/video-thumb.jpg?stp=dst-jpg_s1080x1080"
              },
              "playable_duration_in_ms": 12000
            }
          ]
        }
        </script></body></html>
    '''
    mixed = core._parse_facebook_post_page(mixed_photo_video_page)
    assert mixed is not None, "Mixed photo/video post was not parsed."
    mixed_photo_urls = [photo["url"] for photo in mixed["photos"]]
    assert len(mixed_photo_urls) == 1, mixed_photo_urls
    assert any("real-photo.jpg" in url for url in mixed_photo_urls), mixed_photo_urls
    assert not any("video-thumb.jpg" in url for url in mixed_photo_urls), mixed_photo_urls
    mixed_videos = mixed.get("videos") or []
    assert len(mixed_videos) == 1, mixed_videos
    assert "real-video.mp4" in mixed_videos[0]["url"], mixed_videos
    assert mixed_videos[0]["url"].endswith("?sig=hd"), mixed_videos
    assert mixed_videos[0]["duration"] == 12, mixed_videos

    video_only_page = r'''
        <html><head>
        <title>Video post | Facebook</title>
        <meta property="og:title" content="Bambang Pamungkas | Facebook">
        <meta property="og:image" content="https://scontent.xx.fbcdn.net/v/t39.30808-6/video-only-thumb.jpg?stp=dst-jpg_s1080x1080">
        </head><body><script type="application/json">
        {
          "video_id": "990011",
          "playable_url": "https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/video-only.mp4?sig=only",
          "video_thumbnail": {
            "uri": "https:\/\/scontent.xx.fbcdn.net\/v\/t39.30808-6\/video-only-thumb.jpg?stp=dst-jpg_s1080x1080"
          }
        }
        </script></body></html>
    '''
    video_only = core._parse_facebook_post_page(video_only_page)
    assert video_only is not None, "Video-only Facebook post was not parsed."
    assert not video_only["photos"], video_only["photos"]
    assert len(video_only.get("videos") or []) == 1, video_only
    assert "video-only.mp4" in video_only["videos"][0]["url"], video_only

    bad_host_page = r'''
        <html><head>
        <meta property="og:image" content="https://example.com/not-facebook.jpg">
        </head><body></body></html>
    '''
    assert core._parse_facebook_post_page(bad_host_page) is None

    app_source = (root / "app.py").read_text(encoding="utf-8")
    assert "self.done.emit(_analyze_url_with_facebook_post_fallback(self.url, self.cookie_browser))" in app_source
    assert "from core import analyze_facebook_post" in app_source
    assert "except Exception as primary_error:" in app_source
    assert '"pfbid" in normalized_url or "/share/p/" in normalized_url' in app_source
    # Existing photo-only downloads stay routed to the same per-post folder.
    assert 'if item.raw.get("_facebook_post_direct"):' in app_source
    assert 'folder_parts = ["Facebook Post", owner_name]' in app_source
    assert 'photo_output_path = _Path(self.output_dir) / folder_name' in app_source
    # Mixed-post video items must be downloaded as direct videos into that same folder.
    assert 'if item.raw.get("_facebook_post_direct_video"):' in app_source
    assert 'video_output_path = _Path(self.output_dir) / folder_name' in app_source
    assert "download_direct_item(" in app_source

    core_source = (root / "core.py").read_text(encoding="utf-8")
    assert 'for video in result.get("videos") or []:' in core_source
    assert '"_facebook_post_direct_video": True' in core_source
    assert 'media_type="video"' in core_source

    print("FACEBOOK_POST_SINGLE_PHOTO_TEST=PASS")
    print("FACEBOOK_POST_MULTI_PHOTO_TEST=PASS")
    print("FACEBOOK_POST_AVATAR_FILTER_TEST=PASS")
    print("FACEBOOK_POST_MIXED_PHOTO_VIDEO_TEST=PASS")
    print("FACEBOOK_POST_VIDEO_THUMBNAIL_FILTER_TEST=PASS")
    print("FACEBOOK_POST_VIDEO_ONLY_TEST=PASS")
    print("FACEBOOK_POST_FALLBACK_ROUTING_TEST=PASS")


if __name__ == "__main__":
    main()
