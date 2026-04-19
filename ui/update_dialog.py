from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


# Design tokens (same as the rest of the app)
C_BG        = "#FFFFFF"
C_TEXT      = "#0A0A0A"
C_MUTED     = "#8A8A8A"
C_FAINT     = "#B8B8B8"
C_HAIRLINE  = "#ECECEC"
C_SURFACE   = "#F7F7F7"
C_ACCENT    = "#0A0A0A"
C_ON_ACCENT = "#FFFFFF"


class UpdateDialog(QDialog):
    """Premium-feeling update prompt with release notes and an Update button."""

    # Emitted when the user clicks "Jetzt updaten". Main app connects this to
    # start the download flow.
    update_requested = pyqtSignal()

    # Emitted with (bytes_done, bytes_total) from the download thread
    download_progress = pyqtSignal(int, int)

    def __init__(self, new_version: str, current_version: str, notes: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Blitztext")
        self.setFixedSize(520, 460)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(
            f"QDialog {{ background-color: {C_BG}; }}"
            f"QLabel {{ color: {C_TEXT}; font-family: 'Segoe UI'; }}"
            f"QTextBrowser {{ background-color: {C_SURFACE}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; padding: 14px; color: {C_TEXT}; "
            f"  font-family: 'Segoe UI'; font-size: 12px; }}"
            f"QProgressBar {{ background-color: {C_SURFACE}; border: none; "
            f"  border-radius: 2px; height: 4px; }}"
            f"QProgressBar::chunk {{ background-color: {C_ACCENT}; border-radius: 2px; }}"
        )

        self._download_progress_visible = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(0)

        # Section label
        section = QLabel("UPDATE VERFÜGBAR")
        sf = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        sf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        section.setFont(sf)
        section.setStyleSheet(f"color: {C_FAINT};")
        layout.addWidget(section)

        layout.addSpacing(8)

        # Title
        title = QLabel(f"Blitztext {new_version}")
        tf = QFont("Segoe UI", 18, QFont.Weight.DemiBold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.3)
        title.setFont(tf)
        title.setStyleSheet(f"color: {C_TEXT};")
        layout.addWidget(title)

        subtitle = QLabel(f"Du nutzt {current_version}")
        subtitle.setStyleSheet(f"color: {C_MUTED}; font-size: 12px; margin-top: 2px;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Release notes
        notes_label = QLabel("Neu in dieser Version")
        nlf = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        nlf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        notes_label.setFont(nlf)
        notes_label.setStyleSheet(f"color: {C_FAINT};")
        layout.addWidget(notes_label)

        layout.addSpacing(8)

        self._notes_view = QTextBrowser()
        self._notes_view.setOpenExternalLinks(True)
        # Render a best-effort HTML version of the markdown body
        self._notes_view.setHtml(self._render_notes(notes))
        layout.addWidget(self._notes_view, 1)

        layout.addSpacing(14)

        # Download progress (hidden until update starts)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        layout.addSpacing(14)

        # Footer buttons
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch()

        self._later_btn = QPushButton("Später")
        self._later_btn.setFixedSize(96, 34)
        self._later_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._later_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_BG}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; color: {C_TEXT}; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {C_SURFACE}; border-color: #DDD; }}"
        )
        self._later_btn.clicked.connect(self.close)
        footer.addWidget(self._later_btn)

        self._update_btn = QPushButton("Jetzt updaten")
        self._update_btn.setFixedSize(140, 34)
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_ACCENT}; color: {C_ON_ACCENT}; "
            f"  border: none; border-radius: 6px; font-size: 13px; font-weight: 500; }}"
            f"QPushButton:hover {{ background-color: #1F1F1F; }}"
            f"QPushButton:disabled {{ background-color: #666; }}"
        )
        self._update_btn.clicked.connect(self._on_update_clicked)
        footer.addWidget(self._update_btn)

        layout.addLayout(footer)

        self.download_progress.connect(self._on_download_progress, Qt.ConnectionType.QueuedConnection)

    def _render_notes(self, markdown_text: str) -> str:
        """Minimal markdown → HTML for release-note readability.

        We don't pull in a full markdown lib; this handles the patterns GitHub
        releases most commonly use: headers, bullet lists, bold, and links.
        """
        if not markdown_text:
            return f"<p style='color: {C_MUTED};'>Keine Details verfügbar.</p>"

        import html as _html
        import re

        out_lines = []
        for line in markdown_text.splitlines():
            line = line.rstrip()
            if not line:
                out_lines.append("<br>")
                continue

            escaped = _html.escape(line)

            # Headers
            m = re.match(r"^(#{1,3})\s+(.*)", line)
            if m:
                level = len(m.group(1))
                text = _html.escape(m.group(2))
                size = {1: 14, 2: 13, 3: 12}[level]
                out_lines.append(
                    f"<div style='font-weight: 600; font-size: {size}px; "
                    f"margin-top: 10px; margin-bottom: 4px;'>{text}</div>"
                )
                continue

            # Bullets
            m = re.match(r"^\s*[-*]\s+(.*)", line)
            if m:
                text = _html.escape(m.group(1))
                text = self._inline(text)
                out_lines.append(f"<div style='margin: 2px 0;'>•&nbsp;&nbsp;{text}</div>")
                continue

            # Normal paragraph
            out_lines.append(f"<div style='margin: 4px 0;'>{self._inline(escaped)}</div>")

        return "".join(out_lines)

    def _inline(self, text: str) -> str:
        """Inline markdown replacements: **bold**, *italic*, `code`, [link](url).

        Bold runs FIRST so its `**…**` markers don't get consumed by the italic
        rule (which only matches single `*`). The italic regex uses a negative
        lookaround on ``*`` to be robust even if the text happens to contain
        unpaired asterisks.
        """
        import re
        # Bold: **text**
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        # Italic: *text*  (after bold so its markers are already gone)
        text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
        # Inline code — use a font stack that reliably carries Unicode glyphs
        # like ⌃⌥⇧ (Cascadia Mono / Consolas / Segoe UI Emoji all cover them).
        text = re.sub(
            r"`(.+?)`",
            r"<code style=\"font-family: 'Cascadia Mono', 'Consolas', 'Segoe UI', monospace; "
            r"background:#EFEFEF; padding:1px 4px; border-radius:3px;\">\1</code>",
            text,
        )
        # Links [text](url)
        text = re.sub(
            r"\[([^\]]+)\]\((https?://[^)]+)\)",
            r"<a href='\2' style='color:#0A0A0A;'>\1</a>",
            text,
        )
        return text

    # --- Update flow ---

    def _on_update_clicked(self) -> None:
        self._update_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._update_btn.setText("Wird geladen …")

        self._progress.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress_label.setText("Download wird gestartet …")
        self._download_progress_visible = True

        self.update_requested.emit()

    def report_progress(self, done: int, total: int) -> None:
        """Thread-safe: forward download bytes to the dialog."""
        self.download_progress.emit(done, total)

    def _on_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            if self._progress.maximum() == 0:
                self._progress.setRange(0, 100)
            pct = int(done * 100 / total)
            self._progress.setValue(pct)
            self._progress_label.setText(
                f"{pct}%  ·  {done/1_000_000:.1f} / {total/1_000_000:.1f} MB"
            )
        else:
            self._progress_label.setText(f"{done/1_000_000:.1f} MB …")

    def set_status(self, text: str) -> None:
        self._progress_label.setText(text)
