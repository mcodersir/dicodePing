from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "ir.dicode.dicodePing"
APP_NAME = "dicodePing"
PRODUCT_NAME_FA = "dicodePing"
VERSION = "0.1.3"
DEFAULT_SUBSCRIPTION_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt"
DEFAULT_SUBSCRIPTION_FALLBACK = "https://cdn.jsdelivr.net/gh/mcodersir/DicodeConfigChecker@main/sub.txt"
XRAY_VERSION = "26.7.11"
XRAY_RELEASE_BASE = f"https://github.com/XTLS/Xray-core/releases/download/v{XRAY_VERSION}"
WINTUN_VERSION = "0.14.1"
WINTUN_URL = f"https://www.wintun.net/builds/wintun-{WINTUN_VERSION}.zip"
WINTUN_SHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
HEALTH_URLS = (
    "http://www.gstatic.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://api.github.com/zen",
)
MAX_SAVED_SERVERS = 160
MAX_DISCOVERY_CONFIGS = 800
MAX_CUSTOM_SUBSCRIPTIONS = 20
PING_ATTEMPTS = 2
PING_TIMEOUT = 1.25
GEO_CACHE_TTL_DAYS = 7

IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parents[1]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT)).resolve() if IS_FROZEN else APP_ROOT
ASSET_DIR = BUNDLE_ROOT / "assets"
BUNDLED_CORE_DIR = BUNDLE_ROOT / "core"


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = user_data_dir()
RUNTIME_DIR = DATA_DIR / "runtime"
CACHE_DIR = DATA_DIR / "cache"
CORE_DIR = DATA_DIR / "core"
SERVERS_FILE = DATA_DIR / "servers.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
GEO_CACHE_FILE = CACHE_DIR / "geo.json"
PID_FILE = RUNTIME_DIR / "xray-owned.json"
LOG_FILE = DATA_DIR / "dicodePing.log"

for _path in (RUNTIME_DIR, CACHE_DIR, CORE_DIR):
    _path.mkdir(parents=True, exist_ok=True)
