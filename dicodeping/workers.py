from __future__ import annotations

import os
import subprocess
import time

from PySide6.QtCore import QThread, Signal

from .constants import HEALTH_URLS
from .diagnostics import get_logger
from .discovery import discover_config_entries
from .i18n import tr
from .models import ServerRecord, SourceDefinition
from .net import is_any_url_reachable_parallel
from .protocols import blob_to_config
from .service import ServerService
from .xray import TUN_NAME, XrayManager

LOGGER = get_logger("workers")


def