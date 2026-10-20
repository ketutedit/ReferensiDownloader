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
          width:1080,height:1920,
          hd_src_no_ratelimit:"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-hd.mp4?oh=hd\u0026oe=def",
          "sd_width":360,"sd_height":640,
          sd_src_no_ratelimit:"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/story-sd.mp4?oh=sd\u0026oe=def",
          playable_url:"https:\/\/video.xx.fbcdn.net\/v\/t42.1790-2\/playable-standard.mp4?oh=sd2\u0026oe=def",
          playable_duration_in_ms:16000
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
    assert variants[0]["url"] == (
        "https://video.xx.fbcdn.net/v/t42.1790-2/story-hd.mp4?oh=hd&oe=def"
    ), variants[0]
    assert variants[0]["width"] is None and variants[0]["height"] is None, variants[0]
    assert variants[0]["selector_height"] == 1280, variants[0]
    assert variants[0]["label"] == "HD • Highest available", variants[0]
    assert variants[1]["tier"] == "SD", variants
    assert variants[1]["url"] == (
        "https://video.xx.fbcdn.net/v/t42.1790-2/story-sd.mp4?oh=sd&oe=def"
    ), variants[1]
    assert variants[1]["width"] == 360 and variants[1]["height"] == 640, variants[1]
    assert variants[1]["selector_height"] == 640, variants[1]
    assert variants[1]["label"] == "SD • 360×640", variants[1]
    # Global width:1080,height:1920 describes Story canvas; it must never be
    # misrepresented as the decoded dimensions of the SD-only URL.
    assert "1080×1920" not in variants[0]["label"]

    # Regression test: MediaItem is immutable. Selecting a quality must use a
    # copied item with a copied raw dict rather than assigning item.direct_url.
    from dataclasses import replace
    from dataclasses import FrozenInstanceError

    item = core.MediaItem(
        slide_index=1,
        title="Facebook Story",
        uploader="Facebook",
        duration=16,
        thumbnail=video["thumbnail"],
        qualities=[core.QualityOption(v["label"], v["selector_height"]) for v in variants],
        raw={"_facebook_story_direct": True, "_facebook_story_variants": variants},
        media_type="video",
        direct_url=video["direct_url"],
        width=720,
        height=1280,
    )
    original_url = item.direct_url
    selected_variant = next(v for v in variants if v["tier"] == "SD")
    selected_raw = dict(item.raw)
    selected_raw["extension"] = selected_variant["extension"]
    selected_raw["_selected_story_quality"] = selected_variant["label"]
    selected_item = replace(
        item,
        direct_url=selected_variant["url"],
        raw=selected_raw,
        height=selected_variant.get("height") or item.height,
        width=selected_variant.get("width") or item.width,
    )
    assert selected_item.direct_url == selected_variant["url"]
    assert item.direct_url == original_url, "Selecting a quality mutated the original MediaItem."
    assert selected_item.raw is not item.raw, "Quality copy must have an independent raw dict."
    try:
        item.direct_url = selected_variant["url"]
    except (FrozenInstanceError, AttributeError):
        immutable_assignment_blocked = True
    else:
        immutable_assignment_blocked = False
    assert immutable_assignment_blocked, "Test fixture should preserve frozen MediaItem behavior."

    app_source = (root / "app.py").read_text(encoding="utf-8")
    assert 'item.direct_url = str(selected_variant["url"])' not in app_source
    assert "selected_item = replace(" in app_source

    # Reproduce a Facebook page whose only HD options are embedded in a DASH
    # manifest. The Story canvas can be 1080x1920 while progressive URL is SD;
    # Quality must come from real DASH representations instead.
    from urllib.parse import quote
    from tempfile import TemporaryDirectory

    story_url = (
        "https://www.facebook.com/stories/1419311178178521/"
        "UzpfSVNDOjEwNTMzNDMyNDQ0MDA2MTY=/?view_single=false"
    )
    mpd = '''<?xml version="1.0" encoding="UTF-8"?>
    <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"
         mediaPresentationDuration="PT16S" minBufferTime="PT1S">
      <Period id="p0" duration="PT16S">
        <AdaptationSet id="video" contentType="video" mimeType="video/mp4" segmentAlignment="true">
          <Representation id="v360" mimeType="video/mp4" codecs="avc1.4D401E"
                          bandwidth="180000" width="360" height="640" frameRate="30">
            <BaseURL>https://video.xx.fbcdn.net/story-v360.mp4?sig=sd</BaseURL>
          </Representation>
          <Representation id="v540" mimeType="video/mp4" codecs="avc1.4D401F"
                          bandwidth="360000" width="540" height="960" frameRate="30">
            <BaseURL>https://video.xx.fbcdn.net/story-v540.mp4?sig=mid</BaseURL>
          </Representation>
          <Representation id="v720" mimeType="video/mp4" codecs="avc1.4D4020"
                          bandwidth="770000" width="720" height="1280" frameRate="30">
            <BaseURL>https://video.xx.fbcdn.net/story-v720.mp4?sig=hd</BaseURL>
          </Representation>
        </AdaptationSet>
        <AdaptationSet id="audio" contentType="audio" mimeType="audio/mp4">
          <Representation id="a1" mimeType="audio/mp4" codecs="mp4a.40.2" bandwidth="96000">
            <BaseURL>https://video.xx.fbcdn.net/story-audio.m4a?sig=audio</BaseURL>
          </Representation>
        </AdaptationSet>
      </Period>
    </MPD>'''
    encoded_mpd = quote(mpd, safe="")
    dash_page = (
        '<html><head><title>Facebook Story</title></head><body>'
        '<script type="application/json">{"dash_manifest_xml_string":"'
        + encoded_mpd
        + '"}</script></body></html>'
    )
    dash_formats = core._extract_facebook_story_dash_formats(dash_page, story_url)
    assert dash_formats, "DASH manifest should produce video/audio formats."
    assert any(str(f.get("acodec") or "").lower() != "none" and not f.get("height") for f in dash_formats), dash_formats

    dash_variants = core._facebook_story_dash_variants(dash_formats)
    dash_heights = [v["height"] for v in dash_variants]
    assert dash_heights == [1280, 960, 640], dash_variants
    assert dash_variants[0]["width"] == 720, dash_variants[0]
    assert dash_variants[0]["label"] == "1280p • 720×1280", dash_variants[0]
    assert dash_variants[0]["format_id"] in {str(f.get("format_id")) for f in dash_formats}

    merged_story = core._apply_facebook_story_dash_formats(dash_page, video, dash_formats)
    assert merged_story is not None and merged_story["media_type"] == "video", merged_story
    assert [v["height"] for v in merged_story["variants"]][:3] == [1280, 960, 640], merged_story
    assert merged_story["variants"][0]["format_id"] == dash_variants[0]["format_id"]
    assert merged_story["direct_url"] == dash_variants[0]["url"]

    # Mock the downloader to prove choosing HD uses its actual DASH format ID,
    # includes the matching audio track, and applies Facebook's media User-Agent.
    captured = {}
    class FakeYoutubeDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def process_ie_result(self, info_dict, download=True):
            captured["info"] = info_dict
            captured["download"] = download
            return info_dict

    original_youtube_dl = core.yt_dlp.YoutubeDL
    core.yt_dlp.YoutubeDL = FakeYoutubeDL
    try:
        with TemporaryDirectory(prefix="fb-story-dash-test-") as out_dir:
            core.download_facebook_story_dash_format(
                title="Facebook Story Test",
                source_url=story_url,
                thumbnail=video["thumbnail"],
                duration=16,
                formats=dash_formats,
                selected_format_id=dash_variants[0]["format_id"],
                output_dir=out_dir,
                container="mp4",
                audio_only=False,
                editing_compatible=False,
            )
    finally:
        core.yt_dlp.YoutubeDL = original_youtube_dl

    assert captured["opts"]["format"] == (
        f'{dash_variants[0]["format_id"]}+bestaudio/{dash_variants[0]["format_id"]}'
    ), captured["opts"]["format"]
    assert captured["download"] is True
    selected_format = next(
        f for f in captured["info"]["formats"]
        if str(f.get("format_id")) == dash_variants[0]["format_id"]
    )
    assert selected_format["http_headers"]["User-Agent"] == "facebookexternalhit/1.1"
    assert selected_format["height"] == 1280

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
    print("FACEBOOK_STORY_QUALITY_VARIANTS_TEST=PASS")
    print("FACEBOOK_STORY_THUMBNAIL_TEST=PASS")
    print("FACEBOOK_STORY_IMMUTABLE_QUALITY_SELECTION_TEST=PASS")
    print("FACEBOOK_STORY_DASH_MANIFEST_PARSE_TEST=PASS")
    print("FACEBOOK_STORY_DASH_VARIANTS_TEST=PASS")
    print("FACEBOOK_STORY_DASH_DOWNLOAD_SELECTOR_TEST=PASS")
    print("FACEBOOK_STORY_PHOTO_PARSE_TEST=PASS")
    print("FACEBOOK_LOGIN_PAGE_REJECTION_TEST=PASS")


if __name__ == "__main__":
    main()
