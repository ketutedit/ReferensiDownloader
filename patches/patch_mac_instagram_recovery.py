from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch {label!r} expected one exact match, found {count}.")
    return text.replace(old, new, 1)


def pin_gallery_dl(source_root: Path) -> None:
    path = source_root / "requirements.txt"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    indexes = [i for i, line in enumerate(lines) if re.match(r"^\s*gallery-dl(?:\[.*?\])?\s*[<=>!~]", line)]
    if len(indexes) != 1:
        raise RuntimeError(f"Expected exactly one gallery-dl requirement, found {len(indexes)}.")
    lines[indexes[0]] = "gallery-dl==1.32.16"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Pinned Mac Time Range build to gallery-dl==1.32.16 (previously compatible Instagram extractor).")


def patch_instagram_diagnostics(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    task = gdl_job.DataJob(url)
    task.run()
    rows = list(getattr(task, "data", []) or [])
''',
        '''    task = gdl_job.DataJob(url)
    task.run()
    # Recent gallery-dl versions can store extractor failures on DataJob instead
    # of raising them from run(). Preserve this diagnostic rather than replacing
    # it with a generic "Instagram returned no media" message.
    task_error = getattr(task, "exception", None)
    rows = list(getattr(task, "data", []) or [])
''',
        "capture Instagram DataJob exception",
    )

    text = replace_once(
        text,
        '''    items.sort(key=lambda item: item.slide_index)
    if not items:
        raise RuntimeError("Instagram tidak mengembalikan media foto/video yang bisa diunduh.")
    return items
''',
        '''    items.sort(key=lambda item: item.slide_index)
    if not items:
        if task_error is not None:
            details = str(task_error).strip() or type(task_error).__name__
            raise RuntimeError(f"gallery-dl Instagram gagal: {details}") from task_error
        raise RuntimeError("Instagram tidak mengembalikan media foto/video yang bisa diunduh.")
    return items
''',
        "preserve Instagram extractor diagnostics",
    )

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Instagram diagnostic patch applied and core.py syntax check passed.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_mac_instagram_recovery.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    pin_gallery_dl(source_root)
    patch_instagram_diagnostics(source_root)


if __name__ == "__main__":
    main()
