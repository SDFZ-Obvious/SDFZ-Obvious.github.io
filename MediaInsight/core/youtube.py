"""YouTube 数据采集：OAuth 登录（Data API v3 + Analytics API）或 API Key 公开模式。"""
import re
import time
from datetime import date, datetime, timedelta

from .config import app_dir
from .storage import FetchResult

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]

TRAFFIC_NAMES = {
    "YT_SEARCH": "YouTube 搜索", "SUGGESTED": "推荐视频", "BROWSE": "首页/浏览功能",
    "EXT_URL": "外部链接", "NO_LINK_OTHER": "直接/未知", "PLAYLIST": "播放列表",
    "SUBSCRIBER": "订阅内容", "NOTIFICATION": "通知", "CHANNEL": "频道页",
    "SHORTS": "Shorts 信息流", "YT_OTHER_PAGE": "其他 YouTube 页面", "END_SCREEN": "片尾画面",
    "ANNOTATION": "卡片/注释", "HASHTAGS": "话题标签", "SOUND_PAGE": "音频页面",
    "LIVE_REDIRECT": "直播跳转", "RELATED_VIDEO": "相关视频", "YT_PLAYLIST_PAGE": "播放列表页",
    "CAMPAIGN_CARD": "活动卡片", "PRODUCT_PAGE": "商品页", "VIDEO_REMIXES": "混剪",
}
DEVICE_NAMES = {"MOBILE": "手机", "DESKTOP": "电脑", "TABLET": "平板", "TV": "电视",
                "GAME_CONSOLE": "游戏机", "UNKNOWN_PLATFORM": "未知"}


def parse_iso_duration(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


class YouTubeClient:
    def __init__(self, log=print):
        self.log = log
        self.token_file = app_dir() / "credentials" / "youtube_token.json"
        self.creds = None
        self.api_key = ""

    # ------------------------------------------------------------ 登录
    def load_saved(self) -> bool:
        if not self.token_file.exists():
            return False
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_file.write_text(creds.to_json(), encoding="utf-8")
            self.creds = creds if creds.valid else None
        except Exception as e:  # noqa: BLE001
            self.log(f"YouTube 令牌加载失败: {e}")
            self.creds = None
        return self.creds is not None

    def login(self, client_secret_path: str):
        """打开浏览器完成 Google 授权。client_secret 需在 Google Cloud 控制台创建（桌面应用类型）。"""
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
        self.creds = flow.run_local_server(port=0, open_browser=True,
                                           authorization_prompt_message="",
                                           success_message="授权成功，可以关闭此页面并返回 MediaInsight。")
        self.token_file.write_text(self.creds.to_json(), encoding="utf-8")

    def logout(self):
        self.creds = None
        if self.token_file.exists():
            self.token_file.unlink()

    def _yt(self):
        from googleapiclient.discovery import build
        if self.creds:
            return build("youtube", "v3", credentials=self.creds, cache_discovery=False)
        if self.api_key:
            return build("youtube", "v3", developerKey=self.api_key, cache_discovery=False)
        raise RuntimeError("未登录 YouTube，也未设置 API Key")

    def _yta(self):
        from googleapiclient.discovery import build
        return build("youtubeAnalytics", "v2", credentials=self.creds, cache_discovery=False)

    # ------------------------------------------------------------ 采集
    def resolve_channel(self, ident: str) -> str:
        """支持频道 ID（UC…）、@handle 或频道链接。"""
        ident = ident.strip().rstrip("/")
        if "youtube.com/" in ident:
            ident = ident.split("youtube.com/")[1].split("?")[0]
            ident = ident.replace("channel/", "")
        if ident.startswith("UC") and len(ident) == 24:
            return ident
        handle = ident if ident.startswith("@") else "@" + ident
        res = self._yt().channels().list(part="id", forHandle=handle).execute()
        items = res.get("items") or []
        if not items:
            raise RuntimeError(f"找不到频道：{ident}")
        return items[0]["id"]

    def fetch(self, channel_id=None, own=True, max_videos=200, fetch_comments=True,
              comment_videos=8, retention_videos=15, progress=lambda p, m: None) -> FetchResult:
        yt = self._yt()
        q = {"part": "snippet,statistics,contentDetails"}
        if channel_id:
            q["id"] = channel_id
        else:
            q["mine"] = True
        items = yt.channels().list(**q).execute().get("items") or []
        if not items:
            raise RuntimeError("没有找到频道。请确认该 Google 账号已创建 YouTube 频道。")
        ch = items[0]
        cid, sn, st = ch["id"], ch["snippet"], ch.get("statistics", {})
        progress(0.05, f"频道：{sn['title']}")
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]

        ids, token = [], None
        while len(ids) < max_videos:
            res = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50,
                                          pageToken=token).execute()
            ids += [it["contentDetails"]["videoId"] for it in res.get("items", [])]
            token = res.get("nextPageToken")
            progress(0.05 + 0.1 * min(len(ids) / max_videos, 1), f"已发现视频 {len(ids)} 个")
            if not token:
                break
        ids = ids[:max_videos]

        videos = []
        for i in range(0, len(ids), 50):
            res = yt.videos().list(part="snippet,statistics,contentDetails",
                                   id=",".join(ids[i:i + 50])).execute()
            for v in res.get("items", []):
                s, vs = v["snippet"], v.get("statistics", {})
                pub = datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00")).astimezone()
                videos.append({
                    "video_id": v["id"], "title": s.get("title", ""),
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                    "publish_time": pub.replace(tzinfo=None).isoformat(),
                    "duration": parse_iso_duration(v["contentDetails"].get("duration", "")),
                    "category": s.get("categoryId", ""),
                    "tags": ",".join(s.get("tags", [])),
                    "views": int(vs.get("viewCount", 0)),
                    "likes": int(vs["likeCount"]) if "likeCount" in vs else None,
                    "comments": int(vs["commentCount"]) if "commentCount" in vs else None,
                })
            progress(0.15 + 0.2 * min((i + 50) / max(len(ids), 1), 1), "读取视频统计…")
        self._category_names(yt, videos)

        r = FetchResult(platform="youtube", account_id=cid, name=sn["title"],
                        followers=int(st["subscriberCount"]) if "subscriberCount" in st else None,
                        total_views=int(st.get("viewCount", 0)),
                        avatar=sn.get("thumbnails", {}).get("default", {}).get("url", ""),
                        videos=videos)
        r.total_likes = sum(v["likes"] or 0 for v in videos)

        if own and self.creds:
            try:
                self._analytics(r, retention_videos, progress)
            except Exception as e:  # noqa: BLE001
                r.notes.append(f"YouTube Analytics 数据获取失败：{e}")
        elif own:
            r.notes.append("API Key 模式仅能获取公开数据；登录 Google 账号后可获取留存、转粉、流量来源等深度数据。")

        if fetch_comments and videos:
            top = sorted(videos, key=lambda v: v["views"] or 0, reverse=True)[:comment_videos]
            for i, v in enumerate(top):
                progress(0.88 + 0.1 * i / len(top), f"读取评论 {i + 1}/{len(top)}")
                try:
                    res = yt.commentThreads().list(part="snippet", videoId=v["video_id"], maxResults=30,
                                                   order="relevance", textFormat="plainText").execute()
                    r.comments[v["video_id"]] = [
                        c["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for c in res.get("items", [])]
                except Exception:  # noqa: BLE001 - 评论关闭等情况
                    pass
        progress(1.0, "完成")
        return r

    def _category_names(self, yt, videos):
        cats = {v["category"] for v in videos if v["category"]}
        if not cats:
            return
        try:
            res = yt.videoCategories().list(part="snippet", id=",".join(cats), hl="zh-CN").execute()
            names = {c["id"]: c["snippet"]["title"] for c in res.get("items", [])}
            for v in videos:
                v["category"] = names.get(v["category"], v["category"])
        except Exception:  # noqa: BLE001
            pass

    def _analytics(self, r: FetchResult, retention_videos, progress):
        yta = self._yta()
        end = date.today()
        start = date(2005, 4, 1)
        recent = end - timedelta(days=90)

        def query(**kw):
            return yta.reports().query(ids="channel==MINE", endDate=end.isoformat(), **kw).execute()

        progress(0.4, "读取视频深度数据（观看时长、转粉）…")
        by_id = {v["video_id"]: v for v in r.videos}
        res = query(startDate=start.isoformat(), dimensions="video", sort="-views", maxResults=200,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                            "subscribersGained,subscribersLost,likes,comments,shares")
        cols = [h["name"] for h in res.get("columnHeaders", [])]
        for row in res.get("rows", []):
            d = dict(zip(cols, row))
            v = by_id.get(d["video"])
            if v:
                v["avg_view_duration"] = d["averageViewDuration"]
                v["avg_view_pct"] = d["averageViewPercentage"] / 100
                v["subs_gained"] = d["subscribersGained"]
                v["subs_lost"] = d["subscribersLost"]
                v["shares"] = d["shares"]

        progress(0.5, "读取每日趋势…")
        res = query(startDate=(end - timedelta(days=365)).isoformat(), dimensions="day", sort="day",
                    metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,likes,comments,shares")
        cols = [h["name"] for h in res.get("columnHeaders", [])]
        for row in res.get("rows", []):
            d = dict(zip(cols, row))
            r.daily.append({"date": d["day"], "views": d["views"], "watch_minutes": d["estimatedMinutesWatched"],
                            "subs_gained": d["subscribersGained"], "subs_lost": d["subscribersLost"],
                            "likes": d["likes"], "comments": d["comments"], "shares": d["shares"]})

        progress(0.58, "读取流量来源与受众…")
        dims = {"traffic": ("insightTrafficSourceType", "views", TRAFFIC_NAMES),
                "device": ("deviceType", "views", DEVICE_NAMES),
                "country": ("country", "views", {}),
                "subscribed": ("subscribedStatus", "views", {"SUBSCRIBED": "已订阅", "UNSUBSCRIBED": "未订阅"}),
                "playback": ("insightPlaybackLocationType", "views", {
                    "WATCH": "YouTube 观看页", "EMBEDDED": "外部嵌入", "BROWSE": "浏览页",
                    "CHANNEL": "频道页", "SHORTS": "Shorts", "SEARCH": "搜索页", "MOBILE": "移动端",
                    "YT_OTHER": "其他"})}
        for name, (dim, metric, mapping) in dims.items():
            try:
                extra = {"maxResults": 15} if dim == "country" else {}
                res = query(startDate=recent.isoformat(), dimensions=dim, metrics=metric,
                            sort=f"-{metric}", **extra)
                r.breakdowns[name] = {mapping.get(row[0], row[0]): row[1] for row in res.get("rows", [])}
            except Exception as e:  # noqa: BLE001
                self.log(f"维度 {dim} 获取失败: {e}")
        try:
            res = query(startDate=recent.isoformat(), dimensions="ageGroup,gender", metrics="viewerPercentage")
            age, gender = {}, {}
            for a, g, pct in res.get("rows", []):
                a = a.replace("age", "").replace("-", "–") + " 岁"
                age[a] = age.get(a, 0) + pct
                gname = {"male": "男", "female": "女"}.get(g, "其他")
                gender[gname] = gender.get(gname, 0) + pct
            if age:
                r.breakdowns["age"] = dict(sorted(age.items()))
                r.breakdowns["gender"] = gender
        except Exception as e:  # noqa: BLE001
            self.log(f"受众画像获取失败: {e}")

        # 留存曲线：每个视频单独查询
        top = sorted(r.videos, key=lambda v: v["views"] or 0, reverse=True)[:retention_videos]
        for i, v in enumerate(top):
            progress(0.62 + 0.25 * i / max(len(top), 1), f"读取留存曲线 {i + 1}/{len(top)}")
            try:
                res = query(startDate=start.isoformat(), dimensions="elapsedVideoTimeRatio",
                            metrics="audienceWatchRatio", filters=f"video=={v['video_id']}")
                curve = [[row[0], row[1]] for row in res.get("rows", [])]
                if curve:
                    r.retention[v["video_id"]] = curve
                    # 由留存曲线估算前 3 秒流失（Analytics API 不直接提供跳出率）
                    dur = v.get("duration") or 0
                    if dur > 0:
                        target = min(3 / dur, 1.0)
                        point = min(curve, key=lambda c: abs(c[0] - target))
                        v["bounce_3s"] = max(0.0, min(1.0, 1 - point[1]))
            except Exception as e:  # noqa: BLE001
                self.log(f"留存曲线失败 {v['video_id']}: {e}")
            time.sleep(0.05)
