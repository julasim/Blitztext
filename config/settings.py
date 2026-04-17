import json
import os
import sys
import keyring
from .defaults import DEFAULTS


def _config_dir() -> str:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = os.path.join(appdata, "VoiceType")
    os.makedirs(path, exist_ok=True)
    return path


def _config_path() -> str:
    return os.path.join(_config_dir(), "config.json")


def load() -> dict:
    """Load config from disk, falling back to defaults for missing keys."""
    cfg = dict(DEFAULTS)
    path = _config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            cfg.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict) -> None:
    """Write config to disk. Never includes the API key."""
    cfg.pop("api_key", None)
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _keyring_name(provider: str) -> str:
    return f"{provider}_api_key"


def get_provider_key(provider: str) -> str:
    """Retrieve an API key for a given LLM provider from the Windows Credential Manager."""
    try:
        return keyring.get_password("VoiceType", _keyring_name(provider)) or ""
    except Exception:
        return ""


def set_provider_key(provider: str, api_key: str) -> None:
    """Store an API key for a given LLM provider in the Windows Credential Manager."""
    try:
        keyring.set_password("VoiceType", _keyring_name(provider), api_key)
    except Exception:
        pass


def set_autostart(enabled: bool) -> None:
    """Add or remove a Windows registry entry for autostart."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            exe = sys.executable
            if getattr(sys, "frozen", False):
                exe = sys.executable  # PyInstaller exe
            winreg.SetValueEx(key, "VoiceType", 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, "VoiceType")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass
