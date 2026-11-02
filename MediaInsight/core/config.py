"""应用目录与设置的读写。"""
import json
import os
import sys
from pathlib import Path

DEFAULT_SETTINGS = {
    "auto_refresh_minutes": 0,        # 0 = 关闭自动监控
    "max_videos": 200,                # 每次抓取的最大稿件数
    "fetch_comments": True,           # 抓取热门视频评论用于评论洞察
    "comment_videos": 8,              # 抓取评论的视频数
    "retention_videos": 15,           # YouTube 抓取留存曲线的视频数
    "youtube_api_key": "",            # 公开数据模式 / 竞品追踪可选
    "youtube_client_secret": "",      # OAuth 客户端文件路径
    "last_account": "",
}


def app_dir() -> Path:
    """用户数据目录：Windows 为 %APPDATA%/MediaInsight。"""
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    p = Path(base) / "MediaInsight"
    p.mkdir(parents=True, exist_ok=True)
    (p / "credentials").mkdir(exist_ok=True)
    (p / "reports").mkdir(exist_ok=True)
    return p


def resource_path(rel: str) -> Path:
    """兼容 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    return Path(base) / rel


def load_settings() -> dict:
    f = app_dir() / "settings.json"
    data = dict(DEFAULT_SETTINGS)
    if f.exists():
        try:
            data.update(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return data


def save_settings(settings: dict) -> None:
    f = app_dir() / "settings.json"
    f.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
