from __future__ import annotations

import re
import sys
from pathlib import Path


def pin_gallery_dl(source_root: Path) -> None:
    path = source_root / "requirements.txt"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    indexes = [
        i for i, line in enumerate(lines)
        if re.match(r"^\s*gallery-dl(?:\[.*?\])?\s*[<=>!~]", line)
    ]
    if len(indexes) != 1:
        raise RuntimeError(
            f"Expected exactly one gallery-dl requirement, found {len(indexes)}."
        )
    lines[indexes[0]] = "gallery-dl==1.32.16"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Pinned Mac build to gallery-dl==1.32.16 to preserve the tested carousel extractor.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_mac_instagram_recovery.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    pin_gallery_dl(source_root)


if __name__ == "__main__":
    main()
