from dataclasses import dataclass
from typing import Optional

import httpx


GITHUB_REPO = "julasim/Blitztext"
CURRENT_VERSION = "1.0.4"


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    notes: str  # markdown body from GitHub release


def check_for_update() -> Optional[UpdateInfo]:
    """Query GitHub Releases for a newer version. Returns None if none available."""
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=5,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        latest_version = data.get("tag_name", "").lstrip("v")
        if not latest_version or not _is_newer(latest_version, CURRENT_VERSION):
            return None

        # Pick the first .exe asset (the installer)
        download_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                download_url = asset.get("browser_download_url", "")
                break

        if not download_url:
            return None

        return UpdateInfo(
            version=latest_version,
            download_url=download_url,
            notes=data.get("body", "").strip(),
        )
    except Exception:
        return None


def _is_newer(latest: str, current: str) -> bool:
    """Semver comparison (major.minor.patch)."""
    try:
        l = [int(x) for x in latest.split(".")]
        c = [int(x) for x in current.split(".")]
        return l > c
    except (ValueError, IndexError):
        return False
