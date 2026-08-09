"""Version metadata for dicodePing Version 3 (v2rayN stack migration).

Version 3 is a pre-release that replaces the legacy Python networking
wrapper with a proper v2rayN-based integration layer and introduces
a completely redesigned modern UI.
"""
from __future__ import annotations

# Version 3 metadata
VERSION = "3.0.0-pre.1"
RELEASE_VERSION = "3.0.0"
BUILD_TYPE = "pre-release"

# Platform targets (4 platforms)
SUPPORTED_PLATFORMS = ("windows", "linux", "macos", "android")

# v2rayN library version
V2RAYN_VERSION = "7.24.5"

# Core versions
XRAY_VERSION = "26.7.11"
WINTUN_VERSION = "0.14.1"

# Subscription source (unchanged from v2)
DEFAULT_SUBSCRIPTION_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt"
DEFAULT_SUBSCRIPTION_FALLBACK = "https://cdn.jsdelivr.net/gh/mcodersir/DicodeConfigChecker@main/sub.txt"
DEFAULT_SUBSCRIPTION_MIRRORS = (
    DEFAULT_SUBSCRIPTION_URL,
    "https://api.github.com/repos/mcodersir/DicodeConfigChecker/contents/sub.txt?ref=main",
    "https://github.com/mcodersir/DicodeConfigChecker/raw/refs/heads/main/sub.txt",
    DEFAULT_SUBSCRIPTION_FALLBACK,
    "https://fastly.jsdelivr.net/gh/mcodersir/DicodeConfigChecker@main/sub.txt",
)

# App metadata
APP_ID = "ir.dicode.dicodePing"
APP_NAME = "dicodePing"
PRODUCT_NAME_FA = "dicodePing"
VERSION_CODE = 62  # Android version code (continues from v2.0.6)

# Build configuration
MIN_PYTHON_VERSION = (3, 10)
REQUIRES_ADMIN = True  # TUN mode requires administrator/root
