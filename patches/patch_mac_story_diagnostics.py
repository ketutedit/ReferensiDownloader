from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch {label!r} expected exactly one match, found {count}.")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_mac_story_diagnostics.py SOURCE_ROOT")

    source_root = Path(sys.argv[1]).resolve()
    app_path = source_root / "app.py"
    if not app_path.is_file():
        raise FileNotFoundError(f"app.py not found: {app_path}")

    text = app_path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    def run(self):
        try: self.done.emit(analyze_url(self.url, self.cookie_browser))
        except Exception as e: self.error.emit(str(e))
''',
        '''    def run(self):
        try:
            # The bundled yt-dlp and gallery-dl extractors do not implement
            # direct Facebook /stories/ URL handling. Facebook redirects those
            # links to login.php when the request is unauthenticated, after
            # which yt-dlp reports a misleading generic Unsupported URL.
            # Show the known limitation clearly instead of hiding it as a
            # browser-cookie failure. Regular Facebook videos/posts are unchanged.
            normalized_url = (self.url or "").strip().lower()
            if "facebook.com/stories/" in normalized_url:
                self.error.emit(
                    "Facebook Story URL belum didukung oleh extractor bawaan. "
                    "Link /stories/... dialihkan Facebook ke halaman login.php dan "
                    "yt-dlp/gallery-dl belum bisa mengekstrak Story langsung. "
                    "Ini berbeda dari video, Reel, atau post Facebook biasa; "
                    "mengganti browser atau mengimpor cookies.txt saja belum cukup."
                )
                return
            self.done.emit(analyze_url(self.url, self.cookie_browser))
        except Exception as e:
            self.error.emit(str(e))
''',
        "give accurate Facebook Story support diagnostics",
    )

    compile(text, str(app_path), "exec")
    app_path.write_text(text, encoding="utf-8")
    print("Facebook Story diagnostic patch applied and app.py syntax check passed.")


if __name__ == "__main__":
    main()
