from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_windows_tiktok_photo.py SOURCE_ROOT")

    root = Path(sys.argv[1]).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(root))

    import app
    import core
    from gallery_dl import extractor, job as gdl_job

    photo_url = "https://www.tiktok.com/@vijayadesta_/photo/7698159655771491605"
    found = extractor.find(photo_url)
    assert found is not None, "The installed gallery-dl extractor does not recognize TikTok /photo/ URLs."
    assert "TiktokPostExtractor" in type(found).__name__, type(found).__name__

    # Simulate gallery-dl DataJob results to test the UI adapter without network.
    fake_urls = [
        "https://p16-sign.tiktokcdn.com/tos-useast2a-p-0068-euttp/one.jpeg~tplv-photomode-image.jpeg",
        "https://p16-sign.tiktokcdn.com/tos-useast2a-p-0068-euttp/two.jpeg~tplv-photomode-image.jpeg",
        "https://p16-sign.tiktokcdn.com/tos-useast2a-p-0068-euttp/three.jpeg~tplv-photomode-image.jpeg",
    ]
    fake_meta = [
        {"type": "image", "title": "Sample slideshow", "user": "vijayadesta_", "id": "7698159655771491605", "extension": "jpeg", "num": i, "width": 1080, "height": 1920}
        for i in range(1, 4)
    ]

    class FakeDataJob:
        def __init__(self, url):
            assert url == photo_url
            self.data_urls = list(fake_urls)
            self.data_meta = [dict(row) for row in fake_meta]
            self.data_post = [{"id": "7698159655771491605", "user": "vijayadesta_"}]
            self.exception = None

        def run(self):
            return 0

    original_data_job = gdl_job.DataJob
    gdl_job.DataJob = FakeDataJob
    try:
        media = core.analyze_tiktok_photo(photo_url, "none")
    finally:
        gdl_job.DataJob = original_data_job

    assert media.extractor == "TikTok Photo Carousel", media.extractor
    assert media.total_items == 3, media.total_items
    assert media.uploader == "vijayadesta_", media.uploader
    assert len(media.items) == 3, len(media.items)
    assert media.items[0].slide_index == 1
    assert media.items[1].slide_index == 2
    assert media.items[2].media_type == "photo"
    assert media.items[0].direct_url == fake_urls[0]
    assert media.items[0].raw.get("_tiktok_photo_direct") is True
    assert media.items[0].raw.get("extension") == "jpg"

    marker = object()
    original_analyze = core.analyze_tiktok_photo
    core.analyze_tiktok_photo = lambda url, cookie_browser="auto": marker
    try:
        assert app._analyze_url_with_tiktok_photo_fallback(photo_url, "auto") is marker
    finally:
        core.analyze_tiktok_photo = original_analyze

    app_source = (root / "app.py").read_text(encoding="utf-8")
    core_source = (root / "core.py").read_text(encoding="utf-8")
    assert "_analyze_url_with_tiktok_photo_fallback(self.url, self.cookie_browser)" in app_source
    assert 'if item.raw.get("_tiktok_photo_direct"):' in app_source
    assert 'folder_parts = ["TikTok Photo", owner_name]' in app_source
    assert "download_direct_item(" in app_source
    assert 'gdl_config.set(("extractor", "tiktok"), "photos", True)' in core_source
    assert 'gdl_config.set(("extractor", "tiktok"), "videos", False)' in core_source

    print("TIKTOK_PHOTO_EXTRACTOR_MATCH_TEST=PASS")
    print("TIKTOK_PHOTO_ADAPTER_TEST=PASS")
    print("TIKTOK_PHOTO_ANALYZE_ROUTING_TEST=PASS")
    print("TIKTOK_PHOTO_DIRECT_DOWNLOAD_ROUTE_TEST=PASS")


if __name__ == "__main__":
    main()
