from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


# Design tokens (mirrored from settings_window)
C_BG       = "#FFFFFF"
C_TEXT     = "#0A0A0A"
C_MUTED    = "#8A8A8A"
C_HAIRLINE = "#ECECEC"
C_TRACK    = "#F2F2F2"
C_FILL     = "#0A0A0A"


class DownloadDialog(QDialog):
    """Minimal, refined dialog showing Whisper model download progress."""

    progress_updated = pyqtSignal(int, int, str)

    def __init__(self, model_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VoiceType")
        self.setFixedSize(480, 180)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
        )
        self.setStyleSheet(
            f"QDialog {{ background-color: {C_BG}; }}"
            f"QLabel {{ color: {C_TEXT}; font-family: 'Segoe UI'; }}"
            f"QProgressBar {{ background-color: {C_TRACK}; border: none; "
            f"  border-radius: 2px; height: 4px; text-align: center; }}"
            f"QProgressBar::chunk {{ background-color: {C_FILL}; border-radius: 2px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)

        # Section label (tiny, letter-spaced uppercase)
        section = QLabel("SPRACHMODELL")
        sf = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        sf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        section.setFont(sf)
        section.setStyleSheet(f"color: #B8B8B8;")
        layout.addWidget(section)

        layout.addSpacing(8)

        # Title
        self._header = QLabel(f"Whisper {model_name}")
        tf = QFont("Segoe UI", 16, QFont.Weight.DemiBold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.3)
        self._header.setFont(tf)
        self._header.setStyleSheet(f"color: {C_TEXT};")
        layout.addWidget(self._header)

        subtitle = QLabel("Einmaliger Download · Bitte warten")
        subtitle.setStyleSheet(f"color: {C_MUTED}; font-size: 12px; margin-top: 2px;")
        layout.addWidget(subtitle)

        layout.addSpacing(28)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate initially
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        layout.addWidget(self._bar)

        layout.addSpacing(10)

        self._status = QLabel("Verbinde …")
        self._status.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status)

        layout.addStretch()

        self._closed = False
        self.progress_updated.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)

    def report(self, bytes_done: int, bytes_total: int, status_text: str = "") -> None:
        if self._closed:
            return
        self.progress_updated.emit(bytes_done, bytes_total, status_text)

    def closeEvent(self, event) -> None:
        self._closed = True
        super().closeEvent(event)

    def _on_progress(self, bytes_done: int, bytes_total: int, status_text: str) -> None:
        if self._closed:
            return
        if bytes_total > 0:
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            percent = int(bytes_done * 100 / bytes_total)
            self._bar.setValue(percent)
            mb_done = bytes_done / 1_000_000
            mb_total = bytes_total / 1_000_000
            self._status.setText(f"{percent}%  ·  {mb_done:.1f} / {mb_total:.1f} MB")
        else:
            if status_text:
                self._status.setText(status_text)
