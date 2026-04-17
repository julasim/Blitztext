from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import keyboard as kb

from config.defaults import PROVIDER_LABELS, PROVIDER_DEFAULT_MODELS
from config import settings as settings_mod


# --- Design tokens ---
C_BG        = "#FFFFFF"
C_TEXT      = "#0A0A0A"
C_MUTED     = "#8A8A8A"
C_FAINT     = "#B8B8B8"
C_HAIRLINE  = "#ECECEC"
C_SURFACE   = "#F7F7F7"
C_SURFACE_H = "#F1F1F1"
C_ACCENT    = "#0A0A0A"
C_ON_ACCENT = "#FFFFFF"


class HotkeyBadge(QPushButton):
    """A clickable badge that captures a new hotkey combination."""

    hotkey_changed = pyqtSignal(str)

    def __init__(self, current_hotkey: str, parent=None):
        super().__init__(parent)
        self._hotkey = current_hotkey
        self._listening = False
        self._pressed_keys: set[str] = set()
        self.setFixedHeight(30)
        self.setMinimumWidth(130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._normal_style())
        self._update_label()
        self.clicked.connect(self._start_listening)

    def _normal_style(self) -> str:
        return (
            f"HotkeyBadge {{ background-color: {C_SURFACE}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; padding: 2px 14px; font-family: 'Segoe UI'; font-size: 12px; "
            f"  color: {C_TEXT}; letter-spacing: 0.3px; }}"
            f"HotkeyBadge:hover {{ background-color: {C_SURFACE_H}; border-color: #DDD; }}"
        )

    def _listening_style(self) -> str:
        return (
            f"HotkeyBadge {{ background-color: {C_BG}; border: 1px solid {C_TEXT}; "
            f"  border-radius: 6px; padding: 2px 14px; font-family: 'Segoe UI'; font-size: 12px; "
            f"  color: {C_TEXT}; letter-spacing: 0.3px; }}"
        )

    def _update_label(self) -> None:
        display = (self._hotkey
                   .replace("+", "  ")
                   .replace("ctrl", "Strg")
                   .replace("alt", "Alt")
                   .replace("shift", "Umsch"))
        # Title-case single letters
        parts = display.split()
        parts = [p.upper() if len(p) == 1 else p for p in parts]
        self.setText("  ".join(parts))

    def _start_listening(self) -> None:
        if self._listening:
            return
        self._listening = True
        self._pressed_keys.clear()
        self.setText("Taste drücken …")
        self.setStyleSheet(self._listening_style())
        self._hook = kb.hook(self._on_key_event)

    _NORMALIZE = {
        "strg": "ctrl", "steuerung": "ctrl",
        "left ctrl": "ctrl", "right ctrl": "ctrl",
        "umschalt": "shift", "umsch": "shift",
        "left shift": "shift", "right shift": "shift",
        "left alt": "alt", "right alt": "alt",
    }
    _MODIFIER_CANONICAL = {"ctrl", "alt", "shift"}

    def _on_key_event(self, event) -> None:
        if not self._listening:
            return

        key_name = event.name.lower()
        normalized = self._NORMALIZE.get(key_name, key_name)

        if event.event_type == "down":
            self._pressed_keys.add(normalized)
            return

        if normalized in self._MODIFIER_CANONICAL:
            return

        try:
            kb.unhook(self._hook)
        except Exception:
            pass
        self._listening = False

        modifiers = sorted(k for k in self._pressed_keys if k in self._MODIFIER_CANONICAL)
        final_key = normalized
        self._pressed_keys.clear()

        combo_parts = modifiers + [final_key]
        if len(combo_parts) < 2:
            self._update_label()
            self.setStyleSheet(self._normal_style())
            return

        new_hotkey = "+".join(combo_parts)
        self._hotkey = new_hotkey
        self._update_label()
        self.setStyleSheet(self._normal_style())
        self.hotkey_changed.emit(new_hotkey)

    def stop_listening(self) -> None:
        if self._listening:
            try:
                kb.unhook(self._hook)
            except Exception:
                pass
            self._listening = False
            self._pressed_keys.clear()
            self._update_label()
            self.setStyleSheet(self._normal_style())

    @property
    def hotkey(self) -> str:
        return self._hotkey

    def set_hotkey(self, hotkey: str) -> None:
        self._hotkey = hotkey
        self._update_label()


class Toggle(QPushButton):
    """Minimal monochrome toggle — pure greyscale, no accent color."""

    def __init__(self, enabled: bool = False, parent=None):
        super().__init__(parent)
        self._enabled = enabled
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(enabled)
        self._refresh()
        self.clicked.connect(self._flip)

    def _flip(self) -> None:
        self._enabled = not self._enabled
        self.setChecked(self._enabled)
        self._refresh()

    def _refresh(self) -> None:
        if self._enabled:
            self.setStyleSheet(
                f"QPushButton {{ background-color: {C_TEXT}; border: none; border-radius: 11px; }}"
                f"QPushButton::after {{ content: ''; }}"
            )
            self.setText("")
        else:
            self.setStyleSheet(
                f"QPushButton {{ background-color: #DADADA; border: none; border-radius: 11px; }}"
            )
            self.setText("")

    def paintEvent(self, event):
        # Draw the knob on top of the base styled button
        super().paintEvent(event)
        from PyQt6.QtGui import QPainter, QColor, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.setPen(Qt.PenStyle.NoPen)
        knob_d = 18
        y = (self.height() - knob_d) // 2
        x = (self.width() - knob_d - 2) if self._enabled else 2
        p.drawEllipse(x, y, knob_d, knob_d)
        p.end()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled = enabled
        self.setChecked(enabled)
        self._refresh()


def _hairline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setStyleSheet(f"color: {C_HAIRLINE}; background-color: {C_HAIRLINE};")
    line.setFixedHeight(1)
    return line


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {C_FAINT}; margin-top: 18px; margin-bottom: 8px;")
    return lbl


class SettingsWindow(QWidget):
    """Settings window for VoiceType."""

    settings_saved = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config)
        # Load all provider keys up-front so switching providers is instant
        self._provider_keys: dict[str, str] = {
            p: settings_mod.get_provider_key(p) for p in PROVIDER_LABELS
        }
        # Track dirty edits of the currently shown key
        self._key_edits: dict[str, str] = {}
        self.setWindowTitle("VoiceType – Einstellungen")
        self.setFixedWidth(460)
        self.setWindowFlags(Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowTitleHint)
        self.setStyleSheet(
            f"QWidget {{ font-family: 'Segoe UI'; font-size: 13px; "
            f"  background-color: {C_BG}; color: {C_TEXT}; }}"
            f"QLabel {{ color: {C_TEXT}; }}"
            f"QLineEdit {{ background-color: {C_BG}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; padding: 6px 10px; color: {C_TEXT}; "
            f"  selection-background-color: {C_TEXT}; selection-color: {C_ON_ACCENT}; }}"
            f"QLineEdit:focus {{ border-color: #B0B0B0; }}"
            f"QComboBox {{ background-color: {C_BG}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; padding: 6px 10px; color: {C_TEXT}; }}"
            f"QComboBox:hover {{ border-color: #DDD; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {C_BG}; color: {C_TEXT}; "
            f"  border: 1px solid {C_HAIRLINE}; selection-background-color: {C_SURFACE}; "
            f"  selection-color: {C_TEXT}; padding: 4px; }}"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(32, 28, 32, 24)

        # Title
        title = QLabel("VoiceType")
        f = QFont("Segoe UI", 16, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.3)
        title.setFont(f)
        title.setStyleSheet(f"color: {C_TEXT};")
        layout.addWidget(title)

        subtitle = QLabel("Einstellungen")
        subtitle.setStyleSheet(f"color: {C_MUTED}; font-size: 12px; margin-top: 2px;")
        layout.addWidget(subtitle)

        # --- HOTKEYS ---
        layout.addWidget(_section_label("HOTKEYS"))

        self._badge1 = HotkeyBadge(self._config.get("hotkey_mode1", "ctrl+alt+1"))
        layout.addLayout(self._hotkey_row("Direkt", "1 : 1 wie gesprochen", self._badge1))
        layout.addWidget(_hairline())

        self._badge2 = HotkeyBadge(self._config.get("hotkey_mode2", "ctrl+alt+2"))
        layout.addLayout(self._hotkey_row("Aufgeräumt", "Füllwörter entfernt, geglättet", self._badge2))
        layout.addWidget(_hairline())

        self._badge3 = HotkeyBadge(self._config.get("hotkey_mode3", "ctrl+alt+3"))
        layout.addLayout(self._hotkey_row("Förmlich", "Professionell umformuliert", self._badge3))

        # --- PROVIDER ---
        layout.addWidget(_section_label("LLM PROVIDER"))

        self._provider_combo = QComboBox()
        # Order: show the most common first
        self._provider_order = ["openai", "anthropic", "gemini", "openrouter", "ollama"]
        for p in self._provider_order:
            self._provider_combo.addItem(PROVIDER_LABELS[p], userData=p)
        current_provider = self._config.get("llm_provider", "openrouter")
        if current_provider in self._provider_order:
            self._provider_combo.setCurrentIndex(self._provider_order.index(current_provider))
        self._provider_combo.setFixedWidth(240)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addLayout(self._field_row("Anbieter", self._provider_combo))
        layout.addWidget(_hairline())

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setFixedWidth(240)
        self._api_key_input.textEdited.connect(self._on_key_edited)
        layout.addLayout(self._field_row("API-Key", self._api_key_input))
        layout.addWidget(_hairline())

        self._llm_model_input = QLineEdit()
        self._llm_model_input.setFixedWidth(240)
        self._llm_model_input.setText(self._config.get("llm_model", ""))
        layout.addLayout(self._field_row("Modell", self._llm_model_input))

        # Initialize field visibility/placeholders for the current provider
        self._on_provider_changed()

        # --- ALLGEMEIN ---
        layout.addWidget(_section_label("ALLGEMEIN"))

        self._language_combo = QComboBox()
        self._language_combo.addItems(["Deutsch", "Englisch", "Automatisch"])
        self._language_combo.setFixedWidth(240)
        lang_map = {"de": "Deutsch", "en": "Englisch", "auto": "Automatisch"}
        current_lang = lang_map.get(self._config.get("language", "de"), "Deutsch")
        self._language_combo.setCurrentText(current_lang)
        layout.addLayout(self._field_row("Sprache", self._language_combo))
        layout.addWidget(_hairline())

        self._autostart_toggle = Toggle(self._config.get("start_with_windows", True))
        layout.addLayout(self._field_row("Mit Windows starten", self._autostart_toggle))

        # --- Footer ---
        layout.addSpacing(28)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setFixedSize(96, 34)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_BG}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; color: {C_TEXT}; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {C_SURFACE}; border-color: #DDD; }}"
        )
        cancel_btn.clicked.connect(self.close)
        footer.addWidget(cancel_btn)

        save_btn = QPushButton("Speichern")
        save_btn.setFixedSize(110, 34)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_ACCENT}; color: {C_ON_ACCENT}; "
            f"  border: none; border-radius: 6px; font-size: 13px; font-weight: 500; }}"
            f"QPushButton:hover {{ background-color: #1F1F1F; }}"
            f"QPushButton:pressed {{ background-color: #2A2A2A; }}"
        )
        save_btn.clicked.connect(self._save)
        footer.addWidget(save_btn)
        layout.addLayout(footer)

    def _hotkey_row(self, title: str, subtitle: str, badge: HotkeyBadge) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 10)
        left = QVBoxLayout()
        left.setSpacing(1)

        lbl = QLabel(title)
        f = QFont("Segoe UI", 12, QFont.Weight.Medium)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {C_TEXT};")
        left.addWidget(lbl)

        sub = QLabel(subtitle)
        sub.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        left.addWidget(sub)

        row.addLayout(left)
        row.addStretch()
        row.addWidget(badge)
        return row

    def _field_row(self, label_text: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 10)
        lbl = QLabel(label_text)
        f = QFont("Segoe UI", 12)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {C_TEXT};")
        lbl.setFixedWidth(170)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(widget)
        return row

    def _current_provider(self) -> str:
        return self._provider_combo.currentData() or "openrouter"

    def _on_key_edited(self, text: str) -> None:
        """Remember any edits made to the key field for the currently shown provider."""
        self._key_edits[self._current_provider()] = text

    def _on_provider_changed(self, *_args) -> None:
        """Update placeholder and API-key field for the selected provider."""
        provider = self._current_provider()

        default_model = PROVIDER_DEFAULT_MODELS.get(provider, "")
        self._llm_model_input.setPlaceholderText(default_model)

        shown_key = self._key_edits.get(provider, self._provider_keys.get(provider, ""))
        self._api_key_input.blockSignals(True)
        self._api_key_input.setText(shown_key)
        self._api_key_input.blockSignals(False)

    def closeEvent(self, event) -> None:
        for badge in (self._badge1, self._badge2, self._badge3):
            try:
                badge.stop_listening()
            except Exception:
                pass
        super().closeEvent(event)

    def _save(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        hotkeys = [self._badge1.hotkey, self._badge2.hotkey, self._badge3.hotkey]
        if len(set(hotkeys)) < 3:
            QMessageBox.warning(self, "Konflikt", "Jeder Modus braucht einen eigenen Hotkey.")
            return

        for i, hk in enumerate(hotkeys, 1):
            parts = [p.strip() for p in hk.split("+")]
            if len(parts) < 2:
                QMessageBox.warning(self, "Ungültiger Hotkey",
                                    f"Hotkey für Modus {i} braucht mindestens eine Zusatztaste + Taste.")
                return
            try:
                kb.parse_hotkey(hk)
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "Ungültiger Hotkey",
                                    f"Hotkey für Modus {i} ist ungültig: {hk}")
                return

        # Capture any pending edit in the key field for the current provider
        current = self._current_provider()
        self._key_edits[current] = self._api_key_input.text().strip()

        lang_map = {"Deutsch": "de", "Englisch": "en", "Automatisch": "auto"}
        result = {
            "hotkey_mode1": self._badge1.hotkey,
            "hotkey_mode2": self._badge2.hotkey,
            "hotkey_mode3": self._badge3.hotkey,
            "llm_provider": current,
            "llm_model": self._llm_model_input.text().strip(),
            "language": lang_map.get(self._language_combo.currentText(), "de"),
            "start_with_windows": self._autostart_toggle.enabled,
            "provider_keys": dict(self._key_edits),
        }
        self.settings_saved.emit(result)
        self.close()
