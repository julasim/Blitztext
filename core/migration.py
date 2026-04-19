"""One-time migration from the VoiceType-era names to Blitztext.

Safe to run on every launch: every step is idempotent (detects whether
migration already happened and silently no-ops in that case).

Call ``migrate_all()`` from ``main.py`` BEFORE the log is initialised
or any settings are read, so that logs land in the new folder and
settings read from the new location from the very first line.
"""

import os
import sys


OLD_NAME = "VoiceType"
NEW_NAME = "Blitztext"

# Keep in sync with ui.settings_window.PROVIDERS — listed here literally
# so migration can run before ui.* is imported (avoids Qt-pulling on startup).
PROVIDERS = ("openai", "anthropic", "gemini", "openrouter", "ollama")


def migrate_appdata_folder() -> None:
    """Rename ``%APPDATA%\\VoiceType`` → ``%APPDATA%\\Blitztext`` if needed,
    and rename the inner log file ``voicetype.log`` → ``blitztext.log``.

    No-op if:
    - ``%APPDATA%`` isn't set, or
    - The new folder already exists (migration already ran, or clean install), or
    - The old folder doesn't exist (fresh install).
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    old = os.path.join(appdata, OLD_NAME)
    new = os.path.join(appdata, NEW_NAME)
    try:
        if not os.path.exists(new) and os.path.exists(old):
            os.rename(old, new)
    except OSError:
        # Folder in use / permission denied — fall through to log rename,
        # and let the app create a fresh Blitztext folder alongside if needed.
        return

    old_log = os.path.join(new, "voicetype.log")
    new_log = os.path.join(new, "blitztext.log")
    try:
        if os.path.exists(old_log) and not os.path.exists(new_log):
            os.rename(old_log, new_log)
    except OSError:
        pass


def migrate_keyring() -> None:
    """Move every stored API key from service=VoiceType → service=Blitztext.

    Leaves the new service untouched if a value already exists there
    (prefers the newer write on subsequent launches).
    """
    try:
        import keyring
    except Exception:
        return
    for provider in PROVIDERS:
        key_name = f"{provider}_api_key"
        try:
            old_val = keyring.get_password(OLD_NAME, key_name)
        except Exception:
            old_val = None
        if not old_val:
            continue
        try:
            existing = keyring.get_password(NEW_NAME, key_name)
        except Exception:
            existing = None
        if not existing:
            try:
                keyring.set_password(NEW_NAME, key_name, old_val)
            except Exception:
                # couldn't copy — leave the old entry in place so we try again
                # next launch. Don't delete it.
                continue
        try:
            keyring.delete_password(OLD_NAME, key_name)
        except Exception:
            pass


def migrate_autostart() -> None:
    """Remove the old HKCU\\...\\Run\\VoiceType registry value (if present).

    The new ``Blitztext`` value is (re)written on every launch by
    ``settings.set_autostart()`` when running as the frozen .exe, so here
    we only clean up the obsolete entry.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, OLD_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:
        pass


def migrate_all() -> None:
    """Run every migration. Safe to call unconditionally at each startup."""
    migrate_appdata_folder()
    migrate_keyring()
    migrate_autostart()
