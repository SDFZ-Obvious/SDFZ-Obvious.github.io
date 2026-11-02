"""SQLite persistence layer for MediaPulse."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable

from .config import DB_PATH, DEFAULT_SETTINGS

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    uid TEXT NOT NULL,
    name TEXT NOT NULL,
    avatar TEXT DEFAULT '',
    cookie TEXT DEFAULT '',
    token TEXT DEFAULT '',
    meta TEXT DEFAULT '{}',
    followers INTEGER DEFAULT 0,
    total_views INTEGER DEFAULT 0,
    is_demo INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_sync TEXT DEFAULT '',
    UNIQUE(platform, uid)
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    vid TEXT NOT NULL,
    aid TEXT DEFAULT '',
    title TEXT NOT NULL,
    cover TEXT DEFAULT '',
    url TEXT DEFAULT '',
    published_at TEXT DEFAULT '',
    duration INTEGER DEFAULT 0,
    category TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    stats TEXT DEFAULT '{}',
    first_seen TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    UNIQUE(account_id, vid),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS video_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    favorites INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    danmaku INTEGER DEFAULT 0,
    followers_gained INTEGER,
    watch_minutes REAL,
    impressions INTEGER,
    ctr REAL,
    UNIQUE(video_id, day),
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    followers INTEGER DEFAULT 0,
    total_views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    favorites INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    danmaku INTEGER DEFAULT 0,
    watch_minutes REAL DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    UNIQUE(account_id, day),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    video_key TEXT NOT NULL DEFAULT '',
    views INTEGER DEFAULT 0,
    watch_minutes REAL DEFAULT 0,
    followers_gained INTEGER DEFAULT 0,
    followers_lost INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    favorites INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    danmaku INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    ctr REAL,
    avg_view_duration REAL,
    avg_view_pct REAL,
    UNIQUE(account_id, day, video_key),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retention (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    point REAL NOT NULL,
    audience_ratio REAL DEFAULT 0,
    relative_ratio REAL DEFAULT 0,
    source TEXT DEFAULT 'platform',
    UNIQUE(video_id, point),
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS traffic_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    period_end TEXT NOT NULL,
    source TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    watch_minutes REAL DEFAULT 0,
    UNIQUE(account_id, period_end, source),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS demographics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    period_end TEXT NOT NULL,
    dimension TEXT NOT NULL,
    bucket TEXT NOT NULL,
    value REAL DEFAULT 0,
    UNIQUE(account_id, period_end, dimension, bucket),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    author TEXT DEFAULT '',
    content TEXT DEFAULT '',
    likes INTEGER DEFAULT 0,
    sentiment REAL DEFAULT 0,
    created_at TEXT DEFAULT '',
    UNIQUE(video_id, author, content),
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    severity TEXT DEFAULT 'info',
    category TEXT DEFAULT '',
    title TEXT DEFAULT '',
    body TEXT DEFAULT '',
    metric TEXT DEFAULT '',
    action TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    result TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_account ON videos(account_id, published_at);
CREATE INDEX IF NOT EXISTS idx_vsnap_video ON video_snapshots(video_id, day);
CREATE INDEX IF NOT EXISTS idx_daily_account ON daily_metrics(account_id, day);
CREATE INDEX IF NOT EXISTS idx_retention_video ON retention(video_id, point);
"""

_LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Store:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        self.init_db()

    @contextmanager
    def conn(self):
        con = sqlite3.connect(self.path, timeout=45, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=NORMAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init_db(self):
        with _LOCK, self.conn() as con:
            con.executescript(_SCHEMA)
            for key, value in DEFAULT_SETTINGS.items():
                con.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (key, value),
                )

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, str]:
        with self.conn() as con:
            return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")}

    def get_setting(self, key: str, default: str = "") -> str:
        with self.conn() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_settings(self, values: dict[str, Any]):
        with _LOCK, self.conn() as con:
            for key, value in values.items():
                con.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(key), "" if value is None else str(value)),
                )

    # ------------------------------------------------------------------ accounts
    def list_accounts(self) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM accounts ORDER BY is_demo ASC, id ASC"
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["meta"] = self._json(item.get("meta"), {})
                item["has_cookie"] = bool(item.pop("cookie", ""))
                token_data = self._json(item.pop("token", ""), {})
                item["has_token"] = bool(
                    isinstance(token_data, dict) and
                    (token_data.get("access_token") or token_data.get("refresh_token"))
                )
                snap = con.execute(
                    "SELECT followers, total_views, watch_minutes FROM account_snapshots "
                    "WHERE account_id=? ORDER BY day DESC LIMIT 1",
                    (item["id"],),
                ).fetchone()
                if snap:
                    item["followers"] = snap["followers"]
                    item["total_views"] = snap["total_views"]
                result.append(item)
            return result

    def get_account(self, account_id: int, with_secrets: bool = False) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["meta"] = self._json(item.get("meta"), {})
        if not with_secrets:
            item.pop("cookie", None)
            item.pop("token", None)
        return item

    def find_account(self, platform: str, uid: str) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute(
                "SELECT * FROM accounts WHERE platform=? AND uid=?", (platform, str(uid))
            ).fetchone()
        return _row_to_dict(row)

    def create_account(
        self,
        platform: str,
        uid: str,
        name: str,
        avatar: str = "",
        cookie: str = "",
        token: dict | str | None = None,
        meta: dict | None = None,
        followers: int = 0,
        total_views: int = 0,
        is_demo: bool = False,
    ) -> int:
        token_text = token if isinstance(token, str) else json.dumps(token or {}, ensure_ascii=False)
        meta_text = json.dumps(meta or {}, ensure_ascii=False)
        with _LOCK, self.conn() as con:
            existing = con.execute(
                "SELECT id FROM accounts WHERE platform=? AND uid=?", (platform, str(uid))
            ).fetchone()
            if existing:
                con.execute(
                    "UPDATE accounts SET name=?, avatar=?, cookie=?, token=?, meta=?, "
                    "followers=?, total_views=?, last_sync=? WHERE id=?",
                    (
                        name, avatar, cookie, token_text, meta_text,
                        followers, total_views, now_iso(), existing["id"],
                    ),
                )
                return int(existing["id"])
            cur = con.execute(
                "INSERT INTO accounts(platform, uid, name, avatar, cookie, token, meta, "
                "followers, total_views, is_demo, created_at, last_sync) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    platform, str(uid), name, avatar, cookie, token_text, meta_text,
                    followers, total_views, 1 if is_demo else 0, now_iso(), now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def update_account(self, account_id: int, **fields):
        allowed = {"name", "avatar", "cookie", "token", "meta", "followers", "total_views",
                   "last_sync", "status"}
        parts, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"meta", "token"} and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"{key}=?")
            values.append(value)
        if not parts:
            return
        values.append(account_id)
        with _LOCK, self.conn() as con:
            con.execute(f"UPDATE accounts SET {', '.join(parts)} WHERE id=?", values)

    def delete_account(self, account_id: int):
        with _LOCK, self.conn() as con:
            con.execute("DELETE FROM accounts WHERE id=?", (account_id,))

    # ------------------------------------------------------------------ videos
    def upsert_video(self, account_id: int, video: dict[str, Any]) -> int:
        vid = str(video["vid"])
        tags = video.get("tags", [])
        tags_text = tags if isinstance(tags, str) else json.dumps(tags, ensure_ascii=False)
        stats_text = json.dumps(video.get("stats", {}), ensure_ascii=False)
        with _LOCK, self.conn() as con:
            row = con.execute(
                "SELECT id FROM videos WHERE account_id=? AND vid=?", (account_id, vid)
            ).fetchone()
            if row:
                con.execute(
                    "UPDATE videos SET aid=?, title=?, cover=?, url=?, published_at=?, "
                    "duration=?, category=?, tags=?, description=?, stats=?, updated_at=? WHERE id=?",
                    (
                        str(video.get("aid", "")), video.get("title", ""),
                        video.get("cover", ""), video.get("url", ""),
                        video.get("published_at", ""), int(video.get("duration", 0) or 0),
                        video.get("category", ""), tags_text,
                        video.get("description", ""), stats_text, now_iso(), row["id"],
                    ),
                )
                return int(row["id"])
            cur = con.execute(
                "INSERT INTO videos(account_id, vid, aid, title, cover, url, published_at, "
                "duration, category, tags, description, stats, first_seen, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id, vid, str(video.get("aid", "")), video.get("title", ""),
                    video.get("cover", ""), video.get("url", ""),
                    video.get("published_at", ""), int(video.get("duration", 0) or 0),
                    video.get("category", ""), tags_text, video.get("description", ""),
                    stats_text, now_iso(), now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def update_video_stats(self, video_id: int, **values):
        with _LOCK, self.conn() as con:
            row = con.execute("SELECT stats FROM videos WHERE id=?", (video_id,)).fetchone()
            if not row:
                return
            stats = self._json(row["stats"], {})
            stats.update(values)
            con.execute("UPDATE videos SET stats=?, updated_at=? WHERE id=?",
                        (json.dumps(stats, ensure_ascii=False), now_iso(), video_id))

    def videos(self, account_id: int) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM videos WHERE account_id=? ORDER BY published_at DESC",
                (account_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["tags"] = self._json(item.get("tags"), [])
            item["stats"] = self._json(item.get("stats"), {})
            result.append(item)
        return result

    def get_video(self, video_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["tags"] = self._json(item.get("tags"), [])
        item["stats"] = self._json(item.get("stats"), {})
        return item

    _SNAPSHOT_SQL = (
        "INSERT INTO video_snapshots(video_id, day, views, likes, coins, favorites, "
        "comments, shares, danmaku, followers_gained, watch_minutes, impressions, ctr) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(video_id, day) DO UPDATE SET views=excluded.views, likes=excluded.likes, "
        "coins=excluded.coins, favorites=excluded.favorites, comments=excluded.comments, "
        "shares=excluded.shares, danmaku=excluded.danmaku, "
        "followers_gained=COALESCE(excluded.followers_gained, video_snapshots.followers_gained), "
        "watch_minutes=COALESCE(excluded.watch_minutes, video_snapshots.watch_minutes), "
        "impressions=COALESCE(excluded.impressions, video_snapshots.impressions), "
        "ctr=COALESCE(excluded.ctr, video_snapshots.ctr)"
    )

    def save_video_snapshot(self, video_id: int, day: str, stats: dict[str, Any]):
        self.save_video_snapshots(video_id, [(day, stats)])

    def save_video_snapshots(self, video_id: int, rows: Iterable[tuple[str, dict[str, Any]]]):
        payload = []
        for day, stats in rows:
            payload.append((
                video_id, day, int(stats.get("views", 0) or 0),
                int(stats.get("likes", 0) or 0), int(stats.get("coins", 0) or 0),
                int(stats.get("favorites", 0) or 0), int(stats.get("comments", 0) or 0),
                int(stats.get("shares", 0) or 0), int(stats.get("danmaku", 0) or 0),
                stats.get("followers_gained"), stats.get("watch_minutes"),
                stats.get("impressions"), stats.get("ctr"),
            ))
        if not payload:
            return
        with _LOCK, self.conn() as con:
            con.executemany(self._SNAPSHOT_SQL, payload)

    def video_snapshots(self, video_id: int, limit: int = 400) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM video_snapshots WHERE video_id=? ORDER BY day ASC", (video_id,)
            ).fetchall()
        return [dict(r) for r in rows][-limit:]

    def all_video_snapshots(self, account_id: int) -> dict[int, list[dict[str, Any]]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT s.* FROM video_snapshots s JOIN videos v ON v.id=s.video_id "
                "WHERE v.account_id=? ORDER BY s.day ASC",
                (account_id,),
            ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(int(row["video_id"]), []).append(dict(row))
        return grouped

    # ------------------------------------------------------------------ account snapshots / daily
    def save_account_snapshot(self, account_id: int, day: str, data: dict[str, Any]):
        with _LOCK, self.conn() as con:
            con.execute(
                "INSERT INTO account_snapshots(account_id, day, followers, total_views, likes, "
                "coins, favorites, comments, shares, danmaku, watch_minutes, impressions) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(account_id, day) DO UPDATE SET followers=excluded.followers, "
                "total_views=excluded.total_views, likes=excluded.likes, coins=excluded.coins, "
                "favorites=excluded.favorites, comments=excluded.comments, shares=excluded.shares, "
                "danmaku=excluded.danmaku, watch_minutes=excluded.watch_minutes, "
                "impressions=excluded.impressions",
                (
                    account_id, day, int(data.get("followers", 0) or 0),
                    int(data.get("total_views", 0) or 0), int(data.get("likes", 0) or 0),
                    int(data.get("coins", 0) or 0), int(data.get("favorites", 0) or 0),
                    int(data.get("comments", 0) or 0), int(data.get("shares", 0) or 0),
                    int(data.get("danmaku", 0) or 0), float(data.get("watch_minutes", 0) or 0),
                    int(data.get("impressions", 0) or 0),
                ),
            )
            con.execute(
                "UPDATE accounts SET followers=?, total_views=?, last_sync=? WHERE id=?",
                (
                    int(data.get("followers", 0) or 0), int(data.get("total_views", 0) or 0),
                    now_iso(), account_id,
                ),
            )

    def account_snapshots(self, account_id: int) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM account_snapshots WHERE account_id=? ORDER BY day ASC",
                (account_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_daily_metric(self, account_id: int, day: str, data: dict[str, Any],
                          video_key: str = ""):
        fields = [
            "views", "watch_minutes", "followers_gained", "followers_lost", "likes",
            "coins", "favorites", "comments", "shares", "danmaku", "impressions", "ctr",
            "avg_view_duration", "avg_view_pct",
        ]
        values = [data.get(f) for f in fields]
        with _LOCK, self.conn() as con:
            con.execute(
                "INSERT INTO daily_metrics(account_id, day, video_key, " + ", ".join(fields) + ") "
                "VALUES(?,?,?," + ",".join("?" for _ in fields) + ") "
                "ON CONFLICT(account_id, day, video_key) DO UPDATE SET "
                + ", ".join(f"{f}=excluded.{f}" for f in fields),
                [account_id, day, video_key, *values],
            )

    def daily_metrics(self, account_id: int, video_key: str = "") -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM daily_metrics WHERE account_id=? AND video_key=? ORDER BY day ASC",
                (account_id, video_key),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ retention etc
    def replace_retention(self, video_id: int, points: Iterable[dict[str, Any]], source: str = "platform"):
        with _LOCK, self.conn() as con:
            con.execute("DELETE FROM retention WHERE video_id=?", (video_id,))
            for p in points:
                con.execute(
                    "INSERT OR REPLACE INTO retention(video_id, point, audience_ratio, "
                    "relative_ratio, source) VALUES(?,?,?,?,?)",
                    (
                        video_id, float(p.get("point", 0)), float(p.get("audience_ratio", 0) or 0),
                        float(p.get("relative_ratio", 0) or 0), source,
                    ),
                )

    def retention(self, video_id: int) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM retention WHERE video_id=? ORDER BY point ASC", (video_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def replace_traffic_sources(self, account_id: int, period_end: str,
                                sources: Iterable[dict[str, Any]]):
        with _LOCK, self.conn() as con:
            con.execute(
                "DELETE FROM traffic_sources WHERE account_id=? AND period_end=?",
                (account_id, period_end),
            )
            for source in sources:
                con.execute(
                    "INSERT INTO traffic_sources(account_id, period_end, source, views, watch_minutes) "
                    "VALUES(?,?,?,?,?)",
                    (
                        account_id, period_end, str(source.get("source", "")),
                        int(source.get("views", 0) or 0), float(source.get("watch_minutes", 0) or 0),
                    ),
                )

    def traffic_sources(self, account_id: int) -> list[dict[str, Any]]:
        with self.conn() as con:
            row = con.execute(
                "SELECT MAX(period_end) AS p FROM traffic_sources WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if not row or not row["p"]:
                return []
            rows = con.execute(
                "SELECT * FROM traffic_sources WHERE account_id=? AND period_end=? "
                "ORDER BY views DESC",
                (account_id, row["p"]),
            ).fetchall()
        return [dict(r) for r in rows]

    def replace_demographics(self, account_id: int, period_end: str,
                             items: Iterable[dict[str, Any]]):
        with _LOCK, self.conn() as con:
            con.execute(
                "DELETE FROM demographics WHERE account_id=? AND period_end=?",
                (account_id, period_end),
            )
            for item in items:
                con.execute(
                    "INSERT INTO demographics(account_id, period_end, dimension, bucket, value) "
                    "VALUES(?,?,?,?,?)",
                    (
                        account_id, period_end, item["dimension"], str(item["bucket"]),
                        float(item.get("value", 0) or 0),
                    ),
                )

    def demographics(self, account_id: int) -> list[dict[str, Any]]:
        with self.conn() as con:
            row = con.execute(
                "SELECT MAX(period_end) AS p FROM demographics WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if not row or not row["p"]:
                return []
            rows = con.execute(
                "SELECT * FROM demographics WHERE account_id=? AND period_end=?",
                (account_id, row["p"]),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_comments(self, video_id: int, comments: Iterable[dict[str, Any]]):
        with _LOCK, self.conn() as con:
            con.execute("DELETE FROM comments WHERE video_id=?", (video_id,))
            for c in comments:
                con.execute(
                    "INSERT OR IGNORE INTO comments(video_id, author, content, likes, sentiment, "
                    "created_at) VALUES(?,?,?,?,?,?)",
                    (
                        video_id, c.get("author", ""), c.get("content", "")[:1200],
                        int(c.get("likes", 0) or 0), float(c.get("sentiment", 0) or 0),
                        c.get("created_at", ""),
                    ),
                )

    def comments(self, video_id: int, limit: int = 60) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM comments WHERE video_id=? ORDER BY likes DESC LIMIT ?",
                (video_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ insights
    def replace_insights(self, account_id: int, insights: list[dict[str, Any]]):
        with _LOCK, self.conn() as con:
            con.execute("DELETE FROM insights WHERE account_id=?", (account_id,))
            for item in insights:
                con.execute(
                    "INSERT INTO insights(account_id, severity, category, title, body, metric, "
                    "action, created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        account_id, item.get("severity", "info"), item.get("category", ""),
                        item.get("title", ""), item.get("body", ""), item.get("metric", ""),
                        item.get("action", ""), now_iso(),
                    ),
                )

    def insights(self, account_id: int) -> list[dict[str, Any]]:
        order = "CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 WHEN 'opportunity' THEN 2 ELSE 3 END"
        with self.conn() as con:
            rows = con.execute(
                f"SELECT * FROM insights WHERE account_id=? ORDER BY {order}, id", (account_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ jobs
    def create_job(self, kind: str, account_id: int | None = None, message: str = "") -> int:
        with _LOCK, self.conn() as con:
            cur = con.execute(
                "INSERT INTO jobs(account_id, kind, status, progress, message, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (account_id, kind, "queued", 0, message, now_iso(), now_iso()),
            )
            return int(cur.lastrowid)

    def update_job(self, job_id: int, **fields):
        allowed = {"status", "progress", "message", "result"}
        parts, values = [], []
        for key, value in fields.items():
            if key in allowed:
                parts.append(f"{key}=?")
                values.append(value)
        parts.append("updated_at=?")
        values.extend([now_iso(), job_id])
        with _LOCK, self.conn() as con:
            con.execute(f"UPDATE jobs SET {', '.join(parts)} WHERE id=?", values)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.conn() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_dict(row)

    def recent_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.conn() as con:
            rows = con.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _json(text: Any, default: Any) -> Any:
        if isinstance(text, (dict, list)):
            return text
        try:
            return json.loads(text or "")
        except Exception:
            return default
