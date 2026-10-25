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
        normalized_url = (self.url or "").strip().lower()
        try:
            if "facebook.com/stories/" in normalized_url:
                # Story extraction is isolated from the normal post/reel path.
                from core import analyze_facebook_story
                self.done.emit(analyze_facebook_story(self.url, self.cookie_browser))
                return

            try:
                self.done.emit(analyze_url(self.url, self.cookie_browser))
                return
            except Exception as primary_error:
                # Only if regular extraction fails, try the local-session
                # photo parser for Facebook pfbid/share-post URLs. Successful
                # video/reel and other post paths stay on the original engine.
                is_facebook_post = (
                    "facebook.com" in normalized_url
                    and ("pfbid" in normalized_url or "/share/p/" in normalized_url)
                )
                if not is_facebook_post:
                    raise

                try:
                    from core import analyze_facebook_post
                    self.done.emit(analyze_facebook_post(self.url, self.cookie_browser))
                    return
                except Exception as fallback_error:
                    raise RuntimeError(
                        str(primary_error)
                        + "\\n\\nFacebook Post photo fallback: "
                        + str(fallback_error)
                    ) from fallback_error
        except Exception as e:
            self.error.emit(str(e))
''',
        "route Facebook Story and pfbid photo fallback",
    )

    compile(text, str(app_path), "exec")
    app_path.write_text(text, encoding="utf-8")
    print("Facebook Story and Facebook Post fallback routing applied; app.py syntax check passed.")


if __name__ == "__main__":
    main()
