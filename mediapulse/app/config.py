"""Runtime paths and constants for MediaPulse."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MediaPulse"
APP_CN = "脉策"
VERSION = "1.0.0"
BUILD_DATE = "2026-11-02"

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    RESOURCE_DIR = BASE_DIR

WEB_DIR = RESOURCE_DIR / "web"
ICON_PATH = RESOURCE_DIR / "assets" / "mediapulse.ico"
REPORT_TEMPLATE = RESOURCE_DIR / "assets" / "report_template.html"


def _data_dir() -> Path:
    if os.environ.get("MEDIAPULSE_DATA_DIR"):
        return Path(os.environ["MEDIAPULSE_DATA_DIR"])
    if os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / APP_NAME
    return Path.home() / ".mediapulse"


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "mediapulse.db"
LOG_PATH = DATA_DIR / "mediapulse.log"
REPORT_DIR = DATA_DIR / "reports"
EXPORT_DIR = DATA_DIR / "exports"
CONFIG_PATH = DATA_DIR / "config.json"

for folder in (DATA_DIR, REPORT_DIR, EXPORT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

PLATFORM_LABELS = {"bilibili": "哔哩哔哩", "youtube": "YouTube"}

DEFAULT_SETTINGS = {
    "auto_sync_minutes": "60",
    "theme": "dark",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
    "llm_enabled": "0",
    "last_range": "30",
}
