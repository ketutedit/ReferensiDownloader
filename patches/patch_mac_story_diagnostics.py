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
            normalized_url = (self.url or "").strip().lower()
            if "facebook.com/stories/" in normalized_url:
                # Use the local authenticated-session extractor for Facebook
                # Story URLs. It reads browser cookies only on this computer.
                from core import analyze_facebook_story
                self.done.emit(analyze_facebook_story(self.url, self.cookie_browser))
                return
            self.done.emit(analyze_url(self.url, self.cookie_browser))
        except Exception as e:
            self.error.emit(str(e))
''',
        "route Facebook Story to the authenticated page extractor",
    )

    compile(text, str(app_path), "exec")
    app_path.write_text(text, encoding="utf-8")
    print("Facebook Story diagnostic patch applied and app.py syntax check passed.")


if __name__ == "__main__":
    main()
