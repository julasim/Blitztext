from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFrame, QPlainTextEdit, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import keyboard as kb

from config.defaults import (
    PROVIDER_LABELS,
    PROVIDER_DEFAULT_MODELS,
    WHISPER_MODELS,
    DEFAULT_PROMPT_MODE2,
    DEFAULT_PROMPT_MODE3,
)
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
        # This runs on the `keyboard` library's internal thread. Any uncaught
        # exception here can crash the whole Python process, so wrap everything.
        try:
            self._on_key_event_impl(event)
        except Exception:
            # As a safety net: stop listening cleanly and revert the badge.
            self._listening = False
            try:
                kb.unhook(self._hook)
            except Exception:
                pass
            try:
                self._update_label()
                self.setStyleSheet(self._normal_style())
            except Exception:
                pass

    def _on_key_event_impl(self, event) -> None:
        if not self._listening:
            return

        # `event.name` can be None for some special/media keys — guard against it.
        name = getattr(event, "name", None)
        if not isinstance(name, str) or not name:
            return

        key_name = name.lower()
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
    """Settings window for Blitztext."""

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
        self.setWindowTitle("Blitztext – Einstellungen")
        self.setFixedSize(460, 680)
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
            # Scroll area: no border, soft thin scrollbar
            f"QScrollArea {{ border: none; background-color: {C_BG}; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}"
            f"QScrollBar::handle:vertical {{ background: #D0D0D0; border-radius: 4px; min-height: 24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: #B8B8B8; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        # Outer layout (the QWidget itself): scroll area on top, pinned footer below.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll, 1)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(0)
        layout.setContentsMargins(32, 28, 32, 8)
        scroll.setWidget(content)

        # Title
        title = QLabel("Blitztext")
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
        layout.addWidget(_hairline())

        self._badge4 = HotkeyBadge(self._config.get("hotkey_mode4", "ctrl+alt+4"))
        layout.addLayout(self._hotkey_row("Vorlesen", "Markierten Text vorlesen lassen", self._badge4))

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

        # --- LLM-PROMPTS ---
        # Editable system prompts that the LLM receives for modes 2 & 3.
        # A "Zurücksetzen" button next to each section restores the default.
        layout.addWidget(_section_label("LLM-PROMPTS"))

        self._prompt2_edit = self._build_prompt_editor(
            title="Blitztext+",
            subtitle="Geschrieben sprechen. (Modus 2)",
            initial=self._config.get("llm_prompt_mode2", DEFAULT_PROMPT_MODE2),
            default=DEFAULT_PROMPT_MODE2,
            layout=layout,
        )
        layout.addWidget(_hairline())
        self._prompt3_edit = self._build_prompt_editor(
            title="Blitztext $%&!",
            subtitle="Frust rein. Entspannt raus. (Modus 3)",
            initial=self._config.get("llm_prompt_mode3", DEFAULT_PROMPT_MODE3),
            default=DEFAULT_PROMPT_MODE3,
            layout=layout,
        )

        # --- TTS (Vorlesen) ---
        layout.addWidget(_section_label("VORLESEN"))

        # Voice dropdown — populated from the SAPI provider on the main thread.
        # Lazy import so settings.py stays independent of core.tts if someone
        # ever opens settings without the TTS dependency installed.
        from core.tts import list_voices
        voices = list_voices(self._config.get("tts_provider", "sapi"))

        self._tts_voice_combo = QComboBox()
        self._tts_voice_combo.setFixedWidth(240)
        self._tts_voice_combo.addItem("System-Standard", userData="")
        current_voice = self._config.get("tts_voice", "") or ""
        selected_idx = 0
        for i, v in enumerate(voices, start=1):
            label = v["name"]
            if v.get("language"):
                label = f"{v['name']}  ·  {v['language']}"
            self._tts_voice_combo.addItem(label, userData=v["id"])
            if v["id"] == current_voice:
                selected_idx = i
        self._tts_voice_combo.setCurrentIndex(selected_idx)
        layout.addLayout(self._field_row("Stimme", self._tts_voice_combo))
        layout.addWidget(_hairline())

        # Speed offset — show as a friendly labelled dropdown (−10..+10 maps to ~±80 wpm).
        self._tts_rate_combo = QComboBox()
        self._tts_rate_combo.setFixedWidth(240)
        _RATE_CHOICES = [
            (-6, "Deutlich langsamer"),
            (-3, "Langsamer"),
            (0,  "Normal"),
            (3,  "Schneller"),
            (6,  "Deutlich schneller"),
        ]
        current_rate = int(self._config.get("tts_rate", 0) or 0)
        selected_idx = 2  # default = "Normal"
        for i, (val, label) in enumerate(_RATE_CHOICES):
            self._tts_rate_combo.addItem(label, userData=val)
            if val == current_rate:
                selected_idx = i
        self._tts_rate_combo.setCurrentIndex(selected_idx)
        layout.addLayout(self._field_row("Tempo", self._tts_rate_combo))

        # --- ALLGEMEIN ---
        layout.addWidget(_section_label("ALLGEMEIN"))

        self._whisper_combo = QComboBox()
        for model_id, label in WHISPER_MODELS:
            self._whisper_combo.addItem(label, userData=model_id)
        self._whisper_combo.setFixedWidth(240)
        current_model = self._config.get("whisper_model", "medium")
        for i, (model_id, _label) in enumerate(WHISPER_MODELS):
            if model_id == current_model:
                self._whisper_combo.setCurrentIndex(i)
                break
        layout.addLayout(self._field_row("Sprachmodell", self._whisper_combo))
        layout.addWidget(_hairline())

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

        # Bottom padding inside the scrolled content so the last row isn't
        # flush against the footer hairline.
        layout.addSpacing(20)

        # --- Footer (pinned OUTSIDE the scroll area, always visible) ---
        footer_bar = QFrame()
        footer_bar.setStyleSheet(
            f"QFrame {{ background-color: {C_BG}; border-top: 1px solid {C_HAIRLINE}; }}"
        )
        footer = QHBoxLayout(footer_bar)
        footer.setContentsMargins(32, 14, 32, 14)
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

        # Attach footer to the OUTER layout (the scroll area sits above it).
        self.layout().addWidget(footer_bar)

    def _build_prompt_editor(
        self,
        title: str,
        subtitle: str,
        initial: str,
        default: str,
        layout: QVBoxLayout,
    ) -> QPlainTextEdit:
        """Append a labelled editable prompt section to ``layout``.

        Returns the QPlainTextEdit so the caller can read its final value in _save().
        The ``default`` string is captured in the reset-button's closure, so each
        editor resets to its own mode-specific default.
        """
        # Header row: mode title + subtitle on the left, reset button on the right
        header = QHBoxLayout()
        header.setContentsMargins(0, 12, 0, 4)

        left = QVBoxLayout()
        left.setSpacing(1)
        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {C_TEXT};")
        left.addWidget(lbl)
        sub = QLabel(subtitle)
        sub.setStyleSheet(f"color: {C_MUTED}; font-size: 11px;")
        left.addWidget(sub)
        header.addLayout(left)
        header.addStretch()

        reset_btn = QPushButton("Zurücksetzen")
        reset_btn.setFixedHeight(26)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_SURFACE}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; color: {C_TEXT}; font-size: 11px; padding: 0 10px; }}"
            f"QPushButton:hover {{ background-color: {C_SURFACE_H}; border-color: #DDD; }}"
        )
        header.addWidget(reset_btn)

        layout.addLayout(header)

        editor = QPlainTextEdit()
        editor.setPlainText(initial)
        editor.setFixedHeight(110)
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {C_BG}; border: 1px solid {C_HAIRLINE}; "
            f"  border-radius: 6px; padding: 8px 10px; color: {C_TEXT}; "
            f"  font-family: 'Segoe UI'; font-size: 12px; "
            f"  selection-background-color: {C_TEXT}; selection-color: {C_ON_ACCENT}; }}"
            f"QPlainTextEdit:focus {{ border-color: #B0B0B0; }}"
        )
        layout.addWidget(editor)

        # Bind the default to this specific editor via a closure
        reset_btn.clicked.connect(lambda _checked=False, e=editor, d=default: e.setPlainText(d))

        return editor

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
        for badge in (self._badge1, self._badge2, self._badge3, self._badge4):
            try:
                badge.stop_listening()
            except Exception:
                pass
        super().closeEvent(event)

    def _save(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        hotkeys = [self._badge1.hotkey, self._badge2.hotkey,
                   self._badge3.hotkey, self._badge4.hotkey]
        if len(set(hotkeys)) < 4:
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

        # If a user empties a prompt field, fall back to the default instead
        # of sending an empty system prompt to the LLM.
        prompt2 = self._prompt2_edit.toPlainText().strip() or DEFAULT_PROMPT_MODE2
        prompt3 = self._prompt3_edit.toPlainText().strip() or DEFAULT_PROMPT_MODE3

        lang_map = {"Deutsch": "de", "Englisch": "en", "Automatisch": "auto"}
        result = {
            "hotkey_mode1": self._badge1.hotkey,
            "hotkey_mode2": self._badge2.hotkey,
            "hotkey_mode3": self._badge3.hotkey,
            "hotkey_mode4": self._badge4.hotkey,
            "llm_provider": current,
            "llm_model": self._llm_model_input.text().strip(),
            "whisper_model": self._whisper_combo.currentData() or "medium",
            "language": lang_map.get(self._language_combo.currentText(), "de"),
            "start_with_windows": self._autostart_toggle.enabled,
            "provider_keys": dict(self._key_edits),
            "llm_prompt_mode2": prompt2,
            "llm_prompt_mode3": prompt3,
            "tts_voice": self._tts_voice_combo.currentData() or "",
            "tts_rate": self._tts_rate_combo.currentData() or 0,
        }
        self.settings_saved.emit(result)
        self.close()
