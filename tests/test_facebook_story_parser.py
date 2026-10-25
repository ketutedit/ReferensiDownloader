from __future__ import annotations

import json
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
    assert video["owner_name"] == "Test Account", video.get("owner_name")
    assert video["direct_url"] == (
        "https://video.xx.fbcdn.net/v/t42.1790-2/story-hd.mp4?oh=hd&oe=def"
    ), video["direct_url"]
    assert video["duration"] == 16, video["duration"]
    assert video["thumbnail"] == (
        "https://scontent.xx.fbcdn.net/v/t39.30808-6/thumb.jpg?x=1"
    ), video["thumbnail"]
    assert video["raw"]["_facebook_story_direct"] is True
    variants = video["variants"]
    expected_streams = {
        "story-hd.mp4?oh=hd&oe=def",
        "story-sd.mp4?oh=sd&oe=def",
        "playable-standard.mp4?oh=sd2&oe=def",
    }
    assert len(variants) == 3, variants
    assert all(item["tier"] == "Stream" for item in variants), variants
    assert all(item["label"].startswith("Stream ") for item in variants), variants
    assert all(item["selector_height"] for item in variants), variants
    assert len({item["selector_height"] for item in variants}) == len(variants), variants
    assert expected_streams == {
        next((suffix for suffix in expected_streams if item["url"].endswith(suffix)), "")
        for item in variants
    }, variants

    # Regression fixture: do not infer a stream's quality from its field name.
    # All distinct direct stream URLs should remain selectable, regardless of tag.
    quality_tagged_page = r'''
        <html><head><title>Quality-tagged Story</title></head><body>
        <script type="application/json">
        {
          "width":360,"height":640,
          "hd_src_no_ratelimit":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-low.mp4?efg=eyJ2ZW5jb2RlX3RhZyI6ImRhc2hfc2RfcHIifQ%3D%3D\u0026oe=low",
          "sd_width":360,"sd_height":640,
          "sd_src_no_ratelimit":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-sd.mp4?efg=eyJ2ZW5jb2RlX3RhZyI6ImRhc2hfc2RfcHIifQ%3D%3D\u0026oe=sd",
          "original_width":1080,"original_height":1920,
          "playable_url_quality_hd":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-real-hd.mp4?efg=eyJ2ZW5jb2RlX3RhZyI6ImRhc2hfaGRfcHIifQ%3D%3D\u0026oe=hd",
          "playable_url":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/playable-standard.mp4?efg=eyJ2ZW5jb2RlX3RhZyI6ImRhc2hfc2RfcHIifQ%3D%3D\u0026oe=standard",
          "facebook_internal_field_x":"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-extra.mp4?token=extra"
        }
        </script></body></html>
    '''
    quality_tagged = core._parse_facebook_story_page(quality_tagged_page)
    assert quality_tagged is not None, "Quality-tagged Story fixture was not parsed."
    assert "story-low.mp4" in quality_tagged["direct_url"], quality_tagged["direct_url"]
    tagged_urls = [item["url"] for item in quality_tagged["variants"]]
    assert len(tagged_urls) == 5, tagged_urls
    for expected_name in (
        "story-low.mp4",
        "story-sd.mp4",
        "story-real-hd.mp4",
        "playable-standard.mp4",
        "story-extra.mp4",
    ):
        assert any(expected_name in candidate for candidate in tagged_urls), tagged_urls
    assert all(item["tier"] == "Stream" for item in quality_tagged["variants"]), quality_tagged["variants"]
    assert len(set(tagged_urls)) == len(tagged_urls), tagged_urls

    # When alternate Facebook frontends expose different payloads, merge every
    # unique URL instead of returning as soon as the first frontend has media.
    page_one = {
        "media_type": "video",
        "direct_url": "https://video.xx.fbcdn.net/story-low.mp4",
        "title": "Facebook Story",
        "variants": [{
            "url": "https://video.xx.fbcdn.net/story-low.mp4",
            "tier": "Stream", "rank": 1, "label": "Stream 1",
            "width": 360, "height": 640, "selector_height": 640, "extension": "mp4",
        }],
    }
    page_two = {
        "media_type": "video",
        "direct_url": "https://video.xx.fbcdn.net/story-hd.mp4",
        "title": "Facebook Story",
        "variants": [
            {
                "url": "https://video.xx.fbcdn.net/story-low.mp4",
                "tier": "Stream", "rank": 2, "label": "Stream 1",
                "width": 360, "height": 640, "selector_height": 640, "extension": "mp4",
            },
            {
                "url": "https://video.xx.fbcdn.net/story-hd.mp4",
                "tier": "Stream", "rank": 1, "label": "Stream 2",
                "width": 1080, "height": 1920, "selector_height": 1280, "extension": "mp4",
            },
        ],
    }
    merged = core._merge_facebook_story_media_candidates([page_one, page_two])
    assert merged is not None and merged["media_type"] == "video", merged
    assert merged["direct_url"] == "https://video.xx.fbcdn.net/story-low.mp4", merged
    merged_urls = [item["url"] for item in merged["variants"]]
    assert merged_urls == [
        "https://video.xx.fbcdn.net/story-low.mp4",
        "https://video.xx.fbcdn.net/story-hd.mp4",
    ], merged_urls
    assert [item["label"] for item in merged["variants"]] == [
        "Stream 1 • 360×640", "Stream 2 • 1080×1920",
    ], merged["variants"]
    assert merged["raw"]["_facebook_story_stream_count"] == 2, merged["raw"]
    assert core._facebook_story_owner_name(
        '<html><head><meta property="og:title" content="Bambang Pamungkas | Facebook">'
        '<title>Bambang Pamungkas\'s Story | Facebook</title></head></html>'
    ) == "Bambang Pamungkas"

    # Regression fixture: the authenticated Story GraphQL response may expose
    # progressive HD/SD renditions that do not appear in the first HTML shell.
    story_id = "UzpfSVNDOjEyMzQ1Njc4OTA="
    graphql_payload = {
        "data": {
            "nodes": [{
                "unified_stories": {
                    "edges": [{
                        "node": {
                            "id": story_id,
                            "story_card_info": {"story_card_id": story_id},
                            "attachments": [{
                                "media": {
                                    "videoDeliveryResponseFragment": {
                                        "videoDeliveryResponseResult": {
                                            "progressive_urls": [
                                                {
                                                    "progressive_url": "https://video.xx.fbcdn.net/story-sd.mp4?key=sd",
                                                    "metadata": {"quality": "SD", "width": 360, "height": 640},
                                                },
                                                {
                                                    "progressive_url": "https://video.xx.fbcdn.net/story-hd.mp4?key=hd",
                                                    "metadata": {"quality": "HD", "width": 1080, "height": 1920},
                                                },
                                                {
                                                    "progressive_url": "https://video.xx.fbcdn.net/story-hd.mp4?key=hd",
                                                    "metadata": {"quality": "HD", "width": 1080, "height": 1920},
                                                },
                                            ],
                                        }
                                    }
                                }
                            }],
                        }
                    }]
                }
            }]
        }
    }
    graphql_media = core._parse_facebook_story_graphql_response(
        json.dumps(graphql_payload), story_id
    )
    assert graphql_media is not None, "Story GraphQL payload was not parsed."
    assert len(graphql_media["variants"]) == 2, graphql_media["variants"]
    assert graphql_media["variants"][0]["url"].endswith("story-sd.mp4?key=sd"), graphql_media["variants"]
    assert graphql_media["variants"][1]["url"].endswith("story-hd.mp4?key=hd"), graphql_media["variants"]
    assert graphql_media["variants"][1]["width"] == 1080, graphql_media["variants"][1]
    assert graphql_media["variants"][1]["height"] == 1920, graphql_media["variants"][1]

    # GraphQL requests must stay local and pass tokens from the selected logged-in
    # session, not log them or hand them to a third-party API.
    from urllib.parse import parse_qs
    class FakeCookie:
        name = "c_user"
        value = "100200"
    class FakeResponse:
        status_code = 200
        text = json.dumps(graphql_payload)
        def close(self):
            pass
    class FakeSession:
        def post(self, endpoint, data, headers, timeout, allow_redirects):
            assert endpoint == "https://www.facebook.com/api/graphql/", endpoint
            body = parse_qs(data.decode("utf-8"))
            assert body["__user"] == ["100200"], body
            assert body["fb_dtsg"] == ["fixture-token"], body
            assert body["doc_id"] == ["9340191609394579"], body
            assert "StoriesViewerBucketPrefetcherMultiBucketsQuery" in body["fb_api_req_friendly_name"], body
            assert json.loads(body["variables"][0])["bucketIDs"] == ["123456"], body
            return FakeResponse()
    fetched_graphql = core._fetch_facebook_story_graphql_media(
        ['"DTSGInitialData",[],{"token":"fixture-token"}'],
        f"https://www.facebook.com/stories/123456/{story_id}/",
        [FakeCookie()],
        browser_session=FakeSession(),
    )
    assert fetched_graphql is not None, "Authenticated Story GraphQL fallback did not return media."
    assert len(fetched_graphql["variants"]) == 2, fetched_graphql["variants"]

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
    core_source = (root / "core.py").read_text(encoding="utf-8")
    assert 'item.direct_url = str(selected_variant["url"])' not in app_source
    assert "from dataclasses import replace as _replace_media_item" in app_source
    assert "item, direct_url=selected_url, raw=selected_raw" in app_source

    # Download All appears at the top of the Facebook Story menu and creates
    # an isolated, sanitized output folder based on the Story owner's display name.
    assert 'QualityOption("Download All", -1)' in core_source
    assert "qualities.insert(0, QualityOption(\"Download All\", -1))" in core_source
    assert "if requested_height == -1:" in app_source
    assert "for stream_index, variant in enumerate(streams, start=1):" in app_source
    assert 'stream_raw["media_id"] = f"FBStoryStream_{stream_index:03d}"' in app_source
    assert "Download All selesai sebagian" in app_source
    assert 'message or "Download selesai • Siap di-import ke editor"' in app_source
    assert '"_facebook_story_owner_name": str(media.get("owner_name") or "").strip() or None' in core_source
    assert 'owner_name = str(item.raw.get("_facebook_story_owner_name") or "").strip()' in app_source
    assert 'stream_output_dir = _Path(self.output_dir) / folder_name' in app_source
    assert 'stream_item.direct_url, stream_output_path, None, self.container' in app_source
    assert 'stream_item, stream_output_path,' in app_source

    print("FACEBOOK_STORY_VIDEO_PARSE_TEST=PASS")
    print("FACEBOOK_STORY_QUALITY_VARIANTS_TEST=PASS")
    print("FACEBOOK_STORY_THUMBNAIL_TEST=PASS")
    print("FACEBOOK_STORY_PHOTO_PARSE_TEST=PASS")
    print("FACEBOOK_LOGIN_PAGE_REJECTION_TEST=PASS")


if __name__ == "__main__":
    main()
