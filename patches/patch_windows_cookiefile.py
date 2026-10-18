from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch {label!r} expected one exact match, found {count}.")
    return text.replace(old, new, 1)


def patch_core(source_root: Path) -> None:
    path = source_root / "core.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''def _cookie_options(browser: str | None) -> dict[str, Any]:
    if not browser:
        return {}
    # yt-dlp Python API expects the parsed CLI shape:
    # (browser_name, profile, keyring, container)
    return {"cookiesfrombrowser": (browser, None, None, None)}
''',
        '''def _cookie_options(browser: str | None) -> dict[str, Any]:
    if not browser:
        return {}
    if browser.startswith("cookiesfile:"):
        cookie_path = browser[len("cookiesfile:"):].strip()
        if not cookie_path or not Path(cookie_path).is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Pilih ulang file cookie lokal.")
        return {"cookiefile": cookie_path}
    # yt-dlp Python API expects the parsed CLI shape:
    # (browser_name, profile, keyring, container)
    return {"cookiesfrombrowser": (browser, None, None, None)}
''',
        "support Netscape cookies.txt in yt-dlp",
    )

    text = replace_once(
        text,
        '''def _gallery_instagram_once(
    url: str,
    cookie_browser: str | None = None,
    cookie_profile: str | None = None,
) -> list[MediaItem]:
''',
        '''def _gallery_instagram_once(
    url: str,
    cookie_browser: str | None = None,
    cookie_profile: str | None = None,
    cookie_file: str | None = None,
) -> list[MediaItem]:
''',
        "accept local cookie file for gallery-dl",
    )

    text = replace_once(
        text,
        '''    cookie_value = _gallery_cookie_tuple(cookie_browser, cookie_profile)
    if cookie_value:
        gdl_config.set((), "cookies", cookie_value)

    task = gdl_job.DataJob(url)
''',
        '''    if cookie_file:
        if not Path(cookie_file).is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Pilih ulang file cookie lokal.")
        # gallery-dl accepts a Netscape/Mozilla-format cookies.txt path.
        # The file remains on this computer; it is never uploaded anywhere.
        gdl_config.set((), "cookies", cookie_file)
    else:
        cookie_value = _gallery_cookie_tuple(cookie_browser, cookie_profile)
        if cookie_value:
            gdl_config.set((), "cookies", cookie_value)

    task = gdl_job.DataJob(url)
''',
        "use local cookie file in gallery-dl",
    )

    text = replace_once(
        text,
        '''    explicit = (cookie_browser or "auto").strip().lower()
    if explicit not in {"auto", "", "none", "disabled", "off"}:
''',
        '''    explicit = (cookie_browser or "auto").strip().lower()
    if explicit.startswith("cookiesfile:"):
        cookie_file = explicit[len("cookiesfile:"):].strip()
        if not cookie_file or not Path(cookie_file).is_file():
            raise RuntimeError("File cookies.txt tidak ditemukan. Klik Import cookies.txt lalu pilih ulang file.")
        return _gallery_instagram_once(url, cookie_file=cookie_file), explicit

    if explicit not in {"auto", "", "none", "disabled", "off"}:
''',
        "route explicit cookiesfile choice",
    )

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("Core cookie-file patch passed syntax check.")


def patch_app(source_root: Path) -> None:
    path = source_root / "app.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        self.browser_session.setToolTip("Dipakai hanya jika website meminta login/rate-limit. Password tidak dibaca atau disimpan oleh aplikasi.")
        brow.addWidget(blab); brow.addWidget(self.browser_session, 1); sl.addLayout(brow)
''',
        '''        self.browser_session.setToolTip("Dipakai hanya jika website meminta login/rate-limit. Password tidak dibaca atau disimpan oleh aplikasi.")
        self.cookie_file_path = ""
        self.cookie_file_btn = QPushButton("Import cookies.txt")
        self.cookie_file_btn.setMinimumHeight(42)
        self.cookie_file_btn.setToolTip("Gunakan file cookies.txt lokal bila sesi browser tidak terbaca.")
        self.cookie_file_btn.clicked.connect(self._choose_cookie_file)
        self.cookie_file_clear_btn = QPushButton("×")
        self.cookie_file_clear_btn.setFixedSize(34, 42)
        self.cookie_file_clear_btn.setToolTip("Hapus pilihan cookies.txt dan kembali ke sesi browser.")
        self.cookie_file_clear_btn.setEnabled(False)
        self.cookie_file_clear_btn.clicked.connect(self._clear_cookie_file)
        brow.addWidget(blab); brow.addWidget(self.browser_session, 1); brow.addWidget(self.cookie_file_btn); brow.addWidget(self.cookie_file_clear_btn); sl.addLayout(brow)
''',
        "add cookies.txt controls to Website Login row",
    )

    text = replace_once(
        text,
        '''        browser = str(self.browser_session.currentData() or "auto")
        self.settings.setValue("cookie_browser", browser)
        self.thread = QThread(); worker = AnalyzeWorker(url, browser); worker.moveToThread(self.thread)
''',
        '''        browser = str(self.browser_session.currentData() or "auto")
        self.settings.setValue("cookie_browser", browser)
        if self.cookie_file_path:
            browser = "cookiesfile:" + self.cookie_file_path
        self.thread = QThread(); worker = AnalyzeWorker(url, browser); worker.moveToThread(self.thread)
''',
        "send local cookie file to analyzer without persisting path",
    )

    text = replace_once(
        text,
        '''    def browse(self):
        path=QFileDialog.getExistingDirectory(self, "Choose download folder", self.output_edit.text())
''',
        '''    def _choose_cookie_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose local Instagram cookies.txt",
            "",
            "Netscape cookies file (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as cookie_file:
                preview = cookie_file.read(8192)
        except OSError as exc:
            QMessageBox.warning(self, "Cookie file", f"Tidak bisa membaca file: {exc}")
            return
        # A Netscape cookie jar has tab-delimited rows; don't display or log
        # cookie values because they are private session credentials.
        if not any(line.count(chr(9)) >= 6 for line in preview.splitlines() if line and not line.startswith("#")):
            QMessageBox.warning(
                self,
                "Format cookies.txt",
                "File ini tidak terlihat seperti cookies.txt format Netscape. "
                "Ekspor cookie lokal dalam format Netscape/Mozilla, lalu pilih file tersebut.",
            )
            return
        self.cookie_file_path = path
        self.cookie_file_btn.setText("cookies.txt loaded")
        self.cookie_file_btn.setToolTip("File cookie lokal aktif: " + path)
        self.cookie_file_clear_btn.setEnabled(True)

    def _clear_cookie_file(self):
        self.cookie_file_path = ""
        self.cookie_file_btn.setText("Import cookies.txt")
        self.cookie_file_btn.setToolTip("Gunakan file cookies.txt lokal bila sesi browser tidak terbaca.")
        self.cookie_file_clear_btn.setEnabled(False)

    def browse(self):
        path=QFileDialog.getExistingDirectory(self, "Choose download folder", self.output_edit.text())
''',
        "add local cookie selection and clear handlers",
    )

    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("App cookie-file UI patch passed syntax check.")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_windows_cookiefile.py SOURCE_ROOT")
    source_root = Path(sys.argv[1]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root not found: {source_root}")
    patch_core(source_root)
    patch_app(source_root)


if __name__ == "__main__":
    main()
