"""统一数据模型与 SQLite 持久化。

所有平台的采集器都输出 FetchResult，存储层负责落库与历史快照，
分析层只面向 Dataset（pandas DataFrame 集合），不关心数据来源。
"""
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from .config import app_dir

# 稿件标准字段。缺失的指标用 None，分析时自动跳过。
VIDEO_COLUMNS = [
    "video_id", "title", "url", "publish_time", "duration", "category", "tags",
    "views", "likes", "coins", "favorites", "comments", "shares", "danmaku",
    "avg_view_duration",   # 平均观看时长（秒）
    "avg_view_pct",        # 平均观看进度 / 完播率（0-1）
    "bounce_3s",           # 前 3 秒跳出率（0-1）
    "subs_gained",         # 该视频带来的涨粉
    "subs_lost",
    "impressions",         # 曝光量
    "ctr",                 # 封面点击率（0-1）
]
NUMERIC_COLUMNS = VIDEO_COLUMNS[4:5] + VIDEO_COLUMNS[7:]

PLATFORM_NAMES = {"bilibili": "哔哩哔哩", "youtube": "YouTube"}


@dataclass
class FetchResult:
    platform: str
    account_id: str
    name: str
    followers: int | None = None
    total_views: int | None = None
    total_likes: int | None = None
    avatar: str = ""
    videos: list = field(default_factory=list)       # list[dict]，键为 VIDEO_COLUMNS
    daily: list = field(default_factory=list)        # list[dict]，必须含 date
    breakdowns: dict = field(default_factory=dict)   # 维度名 -> {标签: 数值}
    retention: dict = field(default_factory=dict)    # video_id -> [[进度0-1, 留存比例]]
    comments: dict = field(default_factory=dict)     # video_id -> [评论文本]
    notes: list = field(default_factory=list)        # 采集过程中的提示（缺失权限等）


@dataclass
class Dataset:
    key: str
    platform: str
    account_id: str
    name: str
    is_demo: bool
    videos: pd.DataFrame
    account_snaps: pd.DataFrame
    video_snaps: pd.DataFrame
    daily: pd.DataFrame
    breakdowns: dict
    retention: dict
    comments: dict
    notes: list = field(default_factory=list)

    @property
    def platform_name(self) -> str:
        return PLATFORM_NAMES.get(self.platform, self.platform)


def account_key(platform: str, account_id: str) -> str:
    return f"{platform}:{account_id}"


class Storage:
    def __init__(self, path=None):
        self.path = str(path or app_dir() / "mediainsight.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._init()

    def _init(self):
        c = self._conn
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts(
                key TEXT PRIMARY KEY, platform TEXT, account_id TEXT, name TEXT,
                avatar TEXT, is_demo INTEGER DEFAULT 0, is_competitor INTEGER DEFAULT 0,
                created_at TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS account_snaps(
                key TEXT, ts TEXT, followers INTEGER, total_views INTEGER,
                total_likes INTEGER, video_count INTEGER);
            CREATE TABLE IF NOT EXISTS videos(
                key TEXT, video_id TEXT, data TEXT, updated_at TEXT,
                PRIMARY KEY(key, video_id));
            CREATE TABLE IF NOT EXISTS video_snaps(
                key TEXT, video_id TEXT, ts TEXT, views INTEGER, likes INTEGER,
                comments INTEGER, coins INTEGER, favorites INTEGER, shares INTEGER);
            CREATE TABLE IF NOT EXISTS daily(
                key TEXT, date TEXT, data TEXT, PRIMARY KEY(key, date));
            CREATE TABLE IF NOT EXISTS blobs(
                key TEXT, kind TEXT, data TEXT, PRIMARY KEY(key, kind));
            CREATE INDEX IF NOT EXISTS ix_vs ON video_snaps(key, video_id, ts);
            CREATE INDEX IF NOT EXISTS ix_as ON account_snaps(key, ts);
            """
        )
        c.commit()

    # ------------------------------------------------------------------ 写入
    def save(self, r: FetchResult, is_demo=False, is_competitor=False, ts: str | None = None) -> str:
        key = account_key(r.platform, r.account_id)
        now = ts or datetime.now().isoformat(timespec="seconds")
        with self._lock:
            c = self._conn
            row = c.execute("SELECT created_at FROM accounts WHERE key=?", (key,)).fetchone()
            c.execute(
                "INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?,?,?,?,?)",
                (key, r.platform, r.account_id, r.name, r.avatar, int(is_demo),
                 int(is_competitor), row[0] if row else now, now),
            )
            c.execute(
                "INSERT INTO account_snaps VALUES(?,?,?,?,?,?)",
                (key, now, r.followers, r.total_views, r.total_likes, len(r.videos)),
            )
            for v in r.videos:
                vid = str(v["video_id"])
                old = c.execute("SELECT data FROM videos WHERE key=? AND video_id=?", (key, vid)).fetchone()
                merged = json.loads(old[0]) if old else {}
                # 新数据中为 None 的字段不覆盖旧值（例如导入的完播率）
                merged.update({k: val for k, val in v.items() if val is not None})
                c.execute("INSERT OR REPLACE INTO videos VALUES(?,?,?,?)",
                          (key, vid, json.dumps(merged, ensure_ascii=False, default=str), now))
                c.execute(
                    "INSERT INTO video_snaps VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, vid, now, v.get("views"), v.get("likes"), v.get("comments"),
                     v.get("coins"), v.get("favorites"), v.get("shares")),
                )
            for d in r.daily:
                date = str(d["date"])[:10]
                old = c.execute("SELECT data FROM daily WHERE key=? AND date=?", (key, date)).fetchone()
                merged = json.loads(old[0]) if old else {}
                merged.update({k: val for k, val in d.items() if val is not None})
                merged["date"] = date
                c.execute("INSERT OR REPLACE INTO daily VALUES(?,?,?)",
                          (key, date, json.dumps(merged, ensure_ascii=False)))
            for kind, data in (("breakdowns", r.breakdowns), ("retention", r.retention),
                               ("comments", r.comments), ("notes", r.notes)):
                if data:
                    self._merge_blob(key, kind, data)
            c.commit()
        return key

    def _merge_blob(self, key, kind, data):
        old = self._conn.execute("SELECT data FROM blobs WHERE key=? AND kind=?", (key, kind)).fetchone()
        if kind == "notes":
            merged = data
        else:
            merged = json.loads(old[0]) if old else {}
            merged.update(data)
        self._conn.execute("INSERT OR REPLACE INTO blobs VALUES(?,?,?)",
                           (key, kind, json.dumps(merged, ensure_ascii=False)))

    def update_videos(self, key: str, updates: dict) -> int:
        """按 video_id 合并外部导入的字段，返回更新条数。"""
        n = 0
        with self._lock:
            for vid, fields in updates.items():
                row = self._conn.execute("SELECT data FROM videos WHERE key=? AND video_id=?",
                                         (key, vid)).fetchone()
                if not row:
                    continue
                data = json.loads(row[0])
                data.update({k: v for k, v in fields.items() if v is not None})
                self._conn.execute("UPDATE videos SET data=? WHERE key=? AND video_id=?",
                                   (json.dumps(data, ensure_ascii=False, default=str), key, vid))
                n += 1
            self._conn.commit()
        return n

    def set_competitor(self, key: str, flag: bool):
        with self._lock:
            self._conn.execute("UPDATE accounts SET is_competitor=? WHERE key=?", (int(flag), key))
            self._conn.commit()

    def delete_account(self, key: str):
        with self._lock:
            for t in ("accounts", "account_snaps", "videos", "video_snaps", "daily", "blobs"):
                self._conn.execute(f"DELETE FROM {t} WHERE key=?", (key,))
            self._conn.commit()

    # ------------------------------------------------------------------ 读取
    def list_accounts(self, competitors: bool | None = None) -> list[dict]:
        q = "SELECT key, platform, account_id, name, is_demo, is_competitor, updated_at FROM accounts"
        rows = self._conn.execute(q + " ORDER BY updated_at DESC").fetchall()
        out = [dict(zip(["key", "platform", "account_id", "name", "is_demo", "is_competitor",
                         "updated_at"], r)) for r in rows]
        if competitors is not None:
            out = [a for a in out if bool(a["is_competitor"]) == competitors]
        return out

    def load(self, key: str) -> Dataset | None:
        c = self._conn
        acc = c.execute("SELECT platform, account_id, name, is_demo FROM accounts WHERE key=?",
                        (key,)).fetchone()
        if not acc:
            return None
        rows = c.execute("SELECT data FROM videos WHERE key=?", (key,)).fetchall()
        videos = pd.DataFrame([json.loads(r[0]) for r in rows])
        for col in VIDEO_COLUMNS:
            if col not in videos.columns:
                videos[col] = None
        if not videos.empty:
            videos["publish_time"] = pd.to_datetime(videos["publish_time"], errors="coerce")
            for col in NUMERIC_COLUMNS:
                videos[col] = pd.to_numeric(videos[col], errors="coerce")
            videos = videos.sort_values("publish_time", ascending=False).reset_index(drop=True)

        snaps = pd.read_sql_query(
            "SELECT ts, followers, total_views, total_likes, video_count FROM account_snaps "
            "WHERE key=? ORDER BY ts", c, params=(key,))
        snaps["ts"] = pd.to_datetime(snaps["ts"], errors="coerce")
        vsnaps = pd.read_sql_query(
            "SELECT video_id, ts, views, likes, comments, coins, favorites, shares FROM video_snaps "
            "WHERE key=? ORDER BY ts", c, params=(key,))
        vsnaps["ts"] = pd.to_datetime(vsnaps["ts"], errors="coerce")
        drows = c.execute("SELECT data FROM daily WHERE key=? ORDER BY date", (key,)).fetchall()
        daily = pd.DataFrame([json.loads(r[0]) for r in drows])
        if not daily.empty:
            daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
            for col in daily.columns:
                if col != "date":
                    daily[col] = pd.to_numeric(daily[col], errors="coerce")
        blobs = {k: json.loads(d) for k, d in
                 c.execute("SELECT kind, data FROM blobs WHERE key=?", (key,)).fetchall()}
        return Dataset(
            key=key, platform=acc[0], account_id=acc[1], name=acc[2], is_demo=bool(acc[3]),
            videos=videos, account_snaps=snaps, video_snaps=vsnaps, daily=daily,
            breakdowns=blobs.get("breakdowns", {}), retention=blobs.get("retention", {}),
            comments=blobs.get("comments", {}), notes=blobs.get("notes", []),
        )
