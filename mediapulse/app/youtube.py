"""YouTube OAuth, Data API and Analytics API collection."""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .http_client import ApiError, HttpClient
from .store import Store, now_iso, today_str

log = logging.getLogger("mediapulse.youtube")

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2"

TRAFFIC_LABELS = {
    "YT_SEARCH": "YouTube 搜索", "SUGGESTED_VIDEO": "推荐视频", "BROWSE": "浏览功能",
    "EXT_URL": "外部链接", "PLAYLIST": "播放列表", "NOTIFICATION": "通知",
    "NO_LINK_OTHER": "其他", "YT_CHANNEL": "频道页", "YT_OTHER_PAGE": "其他页面",
    "SHORTS_FEED": "Shorts 推荐流", "LIVE": "直播", "ADVERTISING": "广告",
    "END_SCREEN": "片尾推荐", "HASHTAGS": "话题标签", "PRODUCT_PAGE": "产品页",
}

COUNTRY_LABELS = {
    "US": "美国", "GB": "英国", "CA": "加拿大", "DE": "德国", "AU": "澳大利亚",
    "IN": "印度", "NL": "荷兰", "FR": "法国", "JP": "日本", "BR": "巴西",
    "KR": "韩国", "SG": "新加坡", "MY": "马来西亚", "PH": "菲律宾", "ID": "印度尼西亚",
    "TH": "泰国", "VN": "越南", "TW": "中国台湾", "HK": "中国香港", "CN": "中国大陆",
    "ES": "西班牙", "IT": "意大利", "MX": "墨西哥", "AR": "阿根廷", "CL": "智利",
    "CO": "哥伦比亚", "PL": "波兰", "SE": "瑞典", "NO": "挪威", "DK": "丹麦",
    "FI": "芬兰", "IE": "爱尔兰", "PT": "葡萄牙", "RU": "俄罗斯", "UA": "乌克兰",
    "TR": "土耳其", "SA": "沙特阿拉伯", "AE": "阿联酋", "ZA": "南非", "NG": "尼日利亚",
    "NZ": "新西兰", "CH": "瑞士", "AT": "奥地利", "BE": "比利时", "IL": "以色列",
}


def parse_client_config(raw: str | dict) -> dict[str, str]:
    if isinstance(raw, dict):
        data = raw
    else:
        text = (raw or "").strip()
        if not text:
            raise ValueError("请粘贴 Google OAuth 客户端 JSON")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式错误：{exc}") from exc
    if "installed" in data:
        data = data["installed"]
    elif "web" in data:
        data = data["web"]
    client_id = data.get("client_id", "")
    client_secret = data.get("client_secret", "")
    if not client_id or not client_secret:
        raise ValueError("客户端 JSON 中缺少 client_id 或 client_secret")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "token_uri": data.get("token_uri") or TOKEN_URL,
        "project_id": data.get("project_id", ""),
    }


def build_auth_url(client: dict[str, str], redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(client: dict[str, str], code: str, redirect_uri: str) -> dict[str, Any]:
    http = HttpClient()
    payload = http.post_form(client.get("token_uri", TOKEN_URL), {
        "code": code,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    if "error" in payload:
        raise ApiError(payload.get("error_description") or payload["error"])
    token = {
        "access_token": payload.get("access_token", ""),
        "refresh_token": payload.get("refresh_token", ""),
        "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)) - 60,
        "scope": payload.get("scope", ""),
        "token_type": payload.get("token_type", "Bearer"),
        **client,
    }
    return token


def _parse_duration(value: str) -> int:
    match = re.match(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    days, hours, minutes, seconds = (int(x or 0) for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


class YouTubeClient:
    def __init__(self, token: dict[str, Any] | None = None):
        self.token = token or {}
        self.http = HttpClient(headers={"Accept": "application/json"})
        self._refreshed = False

    # ------------------------------------------------------------------ auth
    def _ensure_token(self):
        if self.token.get("access_token") and int(self.token.get("expires_at", 0)) > time.time():
            return
        if not self.token.get("refresh_token"):
            raise ApiError("YouTube 授权已过期，请重新登录")
        http = HttpClient()
        payload = http.post_form(self.token.get("token_uri", TOKEN_URL), {
            "client_id": self.token.get("client_id", ""),
            "client_secret": self.token.get("client_secret", ""),
            "refresh_token": self.token["refresh_token"],
            "grant_type": "refresh_token",
        })
        if "error" in payload:
            raise ApiError(payload.get("error_description") or "YouTube token 刷新失败")
        self.token["access_token"] = payload.get("access_token", "")
        self.token["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600)) - 60
        self._refreshed = True

    def _headers(self) -> dict[str, str]:
        self._ensure_token()
        return {"Authorization": f"Bearer {self.token.get('access_token', '')}"}

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.http.get_json(url, params, headers=self._headers(), retries=2)

    # ------------------------------------------------------------------ data api
    def channel(self) -> dict[str, Any]:
        data = self._get(f"{DATA_API}/channels", {
            "part": "snippet,statistics,contentDetails,brandingSettings",
            "mine": "true",
        })
        items = data.get("items") or []
        if not items:
            raise ApiError("未找到 YouTube 频道，请确认账号已创建频道")
        return items[0]

    def uploads(self, playlist_id: str) -> list[str]:
        ids: list[str] = []
        page_token = ""
        while True:
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"{DATA_API}/playlistItems", params)
            for item in data.get("items") or []:
                vid = ((item.get("contentDetails") or {}).get("videoId") or "")
                if vid:
                    ids.append(vid)
            page_token = data.get("nextPageToken", "")
            if not page_token or len(ids) >= 500:
                break
        return ids

    def videos(self, ids: list[str]) -> list[dict[str, Any]]:
        result = []
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            data = self._get(f"{DATA_API}/videos", {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "maxResults": 50,
            })
            result.extend(data.get("items") or [])
        return result

    def comments(self, video_id: str, limit: int = 20) -> list[dict[str, Any]]:
        try:
            data = self._get(f"{DATA_API}/commentThreads", {
                "part": "snippet", "videoId": video_id, "maxResults": limit,
                "order": "relevance", "textFormat": "plainText",
            })
        except Exception:
            return []
        out = []
        for item in data.get("items") or []:
            snippet = ((item.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
            text = snippet.get("textDisplay", "")
            out.append({
                "author": snippet.get("authorDisplayName", "YouTube 用户"),
                "content": text,
                "likes": int(snippet.get("likeCount", 0) or 0),
                "sentiment": _sentiment(text),
                "created_at": snippet.get("publishedAt", ""),
            })
        return out

    # ------------------------------------------------------------------ analytics
    def report(self, start: date, end: date, metrics: str, dimensions: str = "",
               filters: str = "", sort: str = "", max_results: int = 0) -> dict[str, Any]:
        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "metrics": metrics,
        }
        if dimensions:
            params["dimensions"] = dimensions
        if filters:
            params["filters"] = filters
        if sort:
            params["sort"] = sort
        if max_results:
            params["maxResults"] = max_results
        return self._get(f"{ANALYTICS_API}/reports", params)

    @staticmethod
    def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        headers = [h.get("name", "") for h in data.get("columnHeaders") or []]
        rows = []
        for row in data.get("rows") or []:
            rows.append({name: value for name, value in zip(headers, row)})
        return rows

    # ------------------------------------------------------------------ sync
    def sync(self, store: Store, account_id: int,
             progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
        account = store.get_account(account_id, with_secrets=True)
        if not account:
            raise ApiError("账号不存在")
        self.token = json.loads(account.get("token") or "{}")
        progress = progress or (lambda p, m: None)

        progress(4, "读取 YouTube 频道信息")
        channel = self.channel()
        snippet = channel.get("snippet") or {}
        stats = channel.get("statistics") or {}
        uploads_playlist = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads", "")
        channel_id = channel.get("id", "")
        followers = int(stats.get("subscriberCount", 0) or 0)
        total_views = int(stats.get("viewCount", 0) or 0)
        thumbs = snippet.get("thumbnails") or {}
        avatar = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        store.update_account(
            account_id, uid=channel_id, name=snippet.get("title", "YouTube Channel"),
            avatar=avatar, followers=followers, total_views=total_views,
            meta={**(account.get("meta") or {}), "signature": snippet.get("description", "")[:300],
                  "country": snippet.get("country", ""), "custom_url": snippet.get("customUrl", "")},
        )

        progress(12, "同步视频列表")
        video_ids = self.uploads(uploads_playlist) if uploads_playlist else []
        videos_raw = self.videos(video_ids)
        progress(22, f"写入 {len(videos_raw)} 条视频")
        video_map: dict[str, int] = {}
        existing = {v["vid"]: v for v in store.videos(account_id)}
        for item in videos_raw:
            vid = item.get("id", "")
            sn = item.get("snippet") or {}
            st = item.get("statistics") or {}
            cd = item.get("contentDetails") or {}
            video_stats = {
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
                "favorites": int(st.get("favoriteCount", 0) or 0),
                "coins": 0, "shares": 0, "danmaku": 0,
            }
            views = max(1, video_stats["views"])
            video_stats["engagement_rate"] = round(
                (video_stats["likes"] + video_stats["comments"]) / views * 100, 2
            )
            thumb = ((sn.get("thumbnails") or {}).get("high") or
                     (sn.get("thumbnails") or {}).get("medium") or {}).get("url", "")
            video_id = store.upsert_video(account_id, {
                "vid": vid, "aid": "", "title": sn.get("title", ""),
                "cover": thumb, "url": f"https://www.youtube.com/watch?v={vid}",
                "published_at": sn.get("publishedAt", ""),
                "duration": _parse_duration(cd.get("duration", "")),
                "category": sn.get("categoryId", ""),
                "tags": sn.get("tags") or [],
                "description": (sn.get("description") or "")[:1000],
                "stats": video_stats,
            })
            video_map[vid] = video_id
            store.save_video_snapshot(video_id, today_str(), video_stats)

        analytics_end = date.today() - timedelta(days=2)
        analytics_start = analytics_end - timedelta(days=89)
        progress(30, "同步单稿转粉数据")
        try:
            follower_data = self.report(
                analytics_start, analytics_end,
                "views,subscribersGained,subscribersLost", "video", sort="-views",
            )
            for row in self._rows(follower_data):
                vid = str(row.get("video", ""))
                if vid in video_map:
                    store.update_video_stats(
                        video_map[vid],
                        followers_gained=int(row.get("subscribersGained", 0) or 0),
                        followers_lost=int(row.get("subscribersLost", 0) or 0),
                        conversion_source="platform",
                    )
        except Exception as exc:
            log.info("per-video subscribers unavailable: %s", exc)

        progress(32, "同步 90 天 Analytics 日数据")
        daily = self._analytics_daily(analytics_start, analytics_end)
        for day, row in daily.items():
            store.save_daily_metric(account_id, day, row)
        impressions = self._analytics_impressions(analytics_start, analytics_end)
        for day, row in impressions.items():
            if day in daily:
                merged = {**daily[day], **row}
                store.save_daily_metric(account_id, day, merged)
                daily[day] = merged

        # Back-fill account snapshots from the current totals.
        all_days = sorted(daily)
        for day in all_days:
            future_views = sum(int(daily[d].get("views", 0) or 0) for d in all_days if d > day)
            future_fans = sum(int(daily[d].get("followers_gained", 0) or 0) -
                              int(daily[d].get("followers_lost", 0) or 0) for d in all_days if d > day)
            store.save_account_snapshot(account_id, day, {
                "followers": max(0, followers - future_fans),
                "total_views": max(0, total_views - future_views),
                "likes": 0, "coins": 0, "favorites": 0, "comments": 0, "shares": 0,
                "danmaku": 0, "watch_minutes": 0, "impressions": 0,
            })
        store.save_account_snapshot(account_id, today_str(), {
            "followers": followers, "total_views": total_views,
            "likes": 0, "coins": 0, "favorites": 0, "comments": 0, "shares": 0,
            "danmaku": 0, "watch_minutes": 0,
            "impressions": sum(int(r.get("impressions", 0) or 0) for r in impressions.values()),
        })

        progress(48, "按视频同步 90 天表现")
        self._video_daily(store, account_id, analytics_start, analytics_end, video_map, videos_raw)

        progress(68, "读取受众留存曲线")
        top = sorted(videos_raw, key=lambda v: int((v.get("statistics") or {}).get("viewCount", 0) or 0),
                     reverse=True)[:12]
        for item in top:
            vid = item.get("id", "")
            if not vid:
                continue
            try:
                data = self.report(
                    analytics_start, analytics_end,
                    "audienceWatchRatio,relativeRetentionPerformance",
                    "elapsedVideoTimeRatio", f"video=={vid}",
                )
                points = []
                for row in self._rows(data):
                    points.append({
                        "point": float(row.get("elapsedVideoTimeRatio", 0) or 0),
                        "audience_ratio": float(row.get("audienceWatchRatio", 0) or 0),
                        "relative_ratio": float(row.get("relativeRetentionPerformance", 0) or 0),
                    })
                if points and vid in video_map:
                    store.replace_retention(video_map[vid], points, "platform")
            except Exception as exc:
                log.info("retention failed for %s: %s", vid, exc)
            time.sleep(0.15)

        progress(80, "同步流量来源与受众画像")
        self._traffic(store, account_id, analytics_start, analytics_end)
        self._demographics(store, account_id, analytics_start, analytics_end)

        progress(90, "同步观众评论")
        recent = sorted(videos_raw, key=lambda v: (v.get("snippet") or {}).get("publishedAt", ""),
                        reverse=True)[:8]
        for item in recent:
            vid = item.get("id", "")
            if not vid or vid not in video_map:
                continue
            comments = self.comments(vid)
            if comments:
                store.save_comments(video_map[vid], comments)

        store.update_account(
            account_id, followers=followers, total_views=total_views,
            last_sync=now_iso(), status="active",
        )
        if self._refreshed:
            store.update_account(account_id, token=self.token)
        return {
            "videos": len(videos_raw), "new_videos": len([v for v in video_map if v not in existing]),
            "followers": followers, "total_views": total_views, "days": len(daily),
            "traffic_sources": 0,
        }

    def _analytics_daily(self, start: date, end: date) -> dict[str, dict[str, Any]]:
        metrics = ("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                   "subscribersGained,subscribersLost,likes,comments,shares")
        out: dict[str, dict[str, Any]] = {}
        try:
            data = self.report(start, end, metrics, "day", sort="day")
        except Exception as exc:
            raise ApiError(f"YouTube Analytics 读取失败：{exc}") from exc
        for row in self._rows(data):
            day = str(row.get("day", ""))[:10]
            if not day:
                continue
            out[day] = {
                "views": int(row.get("views", 0) or 0),
                "watch_minutes": float(row.get("estimatedMinutesWatched", 0) or 0),
                "avg_view_duration": float(row.get("averageViewDuration", 0) or 0),
                "avg_view_pct": float(row.get("averageViewPercentage", 0) or 0),
                "followers_gained": int(row.get("subscribersGained", 0) or 0),
                "followers_lost": int(row.get("subscribersLost", 0) or 0),
                "likes": int(row.get("likes", 0) or 0),
                "comments": int(row.get("comments", 0) or 0),
                "shares": int(row.get("shares", 0) or 0),
            }
        return out

    def _analytics_impressions(self, start: date, end: date) -> dict[str, dict[str, Any]]:
        try:
            data = self.report(start, end, "impressions,impressionClickThroughRate", "day", sort="day")
        except Exception as exc:
            log.info("impressions unavailable: %s", exc)
            return {}
        out = {}
        for row in self._rows(data):
            day = str(row.get("day", ""))[:10]
            out[day] = {
                "impressions": int(row.get("impressions", 0) or 0),
                "ctr": round(float(row.get("impressionClickThroughRate", 0) or 0) * 100, 2),
            }
        return out

    def _video_daily(self, store: Store, account_id: int, start: date, end: date,
                     video_map: dict[str, int], videos_raw: list[dict]):
        try:
            data = self.report(
                start, end,
                "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                "subscribersGained,subscribersLost,likes,comments,shares",
                "day,video", sort="day",
            )
        except Exception as exc:
            log.info("per-video analytics unavailable: %s", exc)
            return
        grouped: dict[str, list[dict]] = {}
        for row in self._rows(data):
            vid = row.get("video", "")
            if vid in video_map:
                grouped.setdefault(vid, []).append({
                    **row, "day": str(row.get("day", ""))[:10],
                })
        current = {}
        for item in videos_raw:
            st = item.get("statistics") or {}
            current[item.get("id", "")] = {
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
            }
        for vid, rows in grouped.items():
            rows.sort(key=lambda r: r["day"])
            days = [r["day"] for r in rows]
            for idx, row in enumerate(rows):
                future_views = sum(int(x.get("views", 0) or 0) for x in rows[idx + 1:])
                future_likes = sum(int(x.get("likes", 0) or 0) for x in rows[idx + 1:])
                future_comments = sum(int(x.get("comments", 0) or 0) for x in rows[idx + 1:])
                total = current.get(vid, {})
                store.save_video_snapshot(video_map[vid], row["day"], {
                    "views": max(0, int(total.get("views", 0) or 0) - future_views),
                    "likes": max(0, int(total.get("likes", 0) or 0) - future_likes),
                    "comments": max(0, int(total.get("comments", 0) or 0) - future_comments),
                    "watch_minutes": float(row.get("estimatedMinutesWatched", 0) or 0),
                })
                store.save_daily_metric(account_id, row["day"], {
                    "views": int(row.get("views", 0) or 0),
                    "watch_minutes": float(row.get("estimatedMinutesWatched", 0) or 0),
                    "followers_gained": int(row.get("subscribersGained", 0) or 0),
                    "followers_lost": int(row.get("subscribersLost", 0) or 0),
                    "likes": int(row.get("likes", 0) or 0),
                    "comments": int(row.get("comments", 0) or 0),
                    "shares": int(row.get("shares", 0) or 0),
                    "avg_view_duration": float(row.get("averageViewDuration", 0) or 0),
                    "avg_view_pct": float(row.get("averageViewPercentage", 0) or 0),
                }, video_key=vid)


    def _traffic(self, store: Store, account_id: int, start: date, end: date):
        try:
            data = self.report(start, end, "views,estimatedMinutesWatched",
                               "insightTrafficSourceType", sort="-views")
            rows = self._rows(data)
            sources = [{
                "source": TRAFFIC_LABELS.get(row.get("insightTrafficSourceType", ""),
                                              row.get("insightTrafficSourceType", "")),
                "views": int(row.get("views", 0) or 0),
                "watch_minutes": float(row.get("estimatedMinutesWatched", 0) or 0),
            } for row in rows]
            if sources:
                store.replace_traffic_sources(account_id, today_str(), sources)
        except Exception as exc:
            log.info("traffic sources failed: %s", exc)

    def _demographics(self, store: Store, account_id: int, start: date, end: date):
        items: list[dict[str, Any]] = []
        configs = [
            ("ageGroup", "age", {}),
            ("gender", "gender", {"male": "男", "female": "女"}),
            ("country", "country", COUNTRY_LABELS),
        ]
        for dimension, target, labels in configs:
            try:
                data = self.report(start, end, "viewerPercentage", dimension, sort="-viewerPercentage")
                for row in self._rows(data):
                    bucket = str(row.get(dimension, ""))
                    items.append({"dimension": target,
                                  "bucket": labels.get(bucket, bucket),
                                  "value": round(float(row.get("viewerPercentage", 0) or 0), 2)})
            except Exception as exc:
                log.info("demographic %s failed: %s", dimension, exc)
            time.sleep(0.1)
        try:
            data = self.report(
                start, end, "views", "insightTrafficSourceDetail",
                "insightTrafficSourceType==YT_SEARCH", sort="-views", max_results=15,
            )
            for row in self._rows(data):
                items.append({"dimension": "search_term",
                              "bucket": str(row.get("insightTrafficSourceDetail", ""))[:80],
                              "value": int(row.get("views", 0) or 0)})
        except Exception as exc:
            log.info("search terms failed: %s", exc)
        if items:
            store.replace_demographics(account_id, today_str(), items)


def _sentiment(text: str) -> float:
    pos = ("great", "best", "love", "awesome", "insane", "thanks", "helpful", "amazing",
           "underrated", "subscribed", "worked", "clean", "excellent")
    neg = ("bad", "worst", "boring", "wrong", "mistake", "slow", "disagree", "hate",
           "clickbait", "disappointed", "terrible")
    low = text.lower()
    score = sum(0.3 for w in pos if w in low) - sum(0.4 for w in neg if w in low)
    return max(-1.0, min(1.0, score))
