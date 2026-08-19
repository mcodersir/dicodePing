from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "ir.dicode.dicodePing"
APP_NAME = "dicodePing"
PRODUCT_NAME_FA = "dicodePing"
VERSION = "3.0.0"
RELEASE_VERSION = "3.0.0-pre.6"

DEFAULT_SUBSCRIPTION_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt"
DEFAULT_SUBSCRIPTION_FALLBACK = "https://cdn.jsdelivr.net/gh/mcodersir/DicodeConfigChecker@main/sub.txt"
DEFAULT_SUBSCRIPTION_MIRRORS = (
    DEFAULT_SUBSCRIPTION_URL,
    "https://api.github.com/repos/mcodersir/DicodeConfigChecker/contents/sub.txt?ref=main",
    "https://github.com/mcodersir/DicodeConfigChecker/raw/refs/heads/main/sub.txt",
    DEFAULT_SUBSCRIPTION_FALLBACK,
    "https://fastly.jsdelivr.net/gh/mcodersir/DicodeConfigChecker@main/sub.txt",
)
MAX_CUSTOM_SUBSCRIPTIONS = 20

IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parents[1]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT)).resolve() if IS_FROZEN else APP_ROOT
ASSET_DIR = BUNDLE_ROOT / "assets"


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME / "v3"
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = user_data_dir()
CACHE_DIR = DATA_DIR / "cache"
SERVERS_FILE = DATA_DIR / "servers.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_FILE = DATA_DIR / "dicodePing.log"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
