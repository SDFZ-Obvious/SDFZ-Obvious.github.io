"""哔哩哔哩数据采集：扫码登录、公开数据、创作中心数据、评论。"""
import hashlib
import json
import time
import urllib.parse
from datetime import datetime
from functools import reduce

import requests

from .config import app_dir
from .storage import FetchResult

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

# 创作中心 data/pandect 的 type 与指标对应
PANDECT_TYPES = {1: "views", 2: "danmaku", 3: "comments", 4: "shares",
                 5: "coins", 6: "favorites", 8: "likes"}

QR_WAITING, QR_SCANNED, QR_EXPIRED, QR_OK = 86101, 86090, 86038, 0


class BiliError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"[{code}] {msg}")
        self.code = code


class BilibiliClient:
    def __init__(self, log=print):
        self.log = log
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/",
                               "Origin": "https://www.bilibili.com"})
        self.cookie_file = app_dir() / "credentials" / "bilibili_cookies.json"
        self._wbi_key = None
        self._load_cookies()

    # ------------------------------------------------------------ cookie
    def _load_cookies(self):
        if self.cookie_file.exists():
            try:
                for k, v in json.loads(self.cookie_file.read_text(encoding="utf-8")).items():
                    self.s.cookies.set(k, v, domain=".bilibili.com")
            except (OSError, ValueError):
                pass

    def save_cookies(self):
        data = {c.name: c.value for c in self.s.cookies}
        self.cookie_file.write_text(json.dumps(data), encoding="utf-8")

    def logout(self):
        self.s.cookies.clear()
        if self.cookie_file.exists():
            self.cookie_file.unlink()

    def set_cookie_string(self, raw: str):
        """支持粘贴浏览器中复制的 Cookie 字符串（至少包含 SESSDATA）。"""
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                self.s.cookies.set(k.strip(), v.strip(), domain=".bilibili.com")
        self.save_cookies()

    def _ensure_buvid(self):
        if self.s.cookies.get("buvid3"):
            return
        try:
            d = self._get("https://api.bilibili.com/x/frontend/finger/spi")
            self.s.cookies.set("buvid3", d.get("b_3", ""), domain=".bilibili.com")
            self.s.cookies.set("buvid4", d.get("b_4", ""), domain=".bilibili.com")
        except Exception:  # noqa: BLE001 - 非关键步骤
            pass

    # ------------------------------------------------------------ 请求
    def _get(self, url, params=None, wbi=False, retries=2):
        params = dict(params or {})
        if wbi:
            params = self._wbi_sign(params)
        last = None
        for i in range(retries + 1):
            try:
                r = self.s.get(url, params=params, timeout=15)
                r.raise_for_status()
                j = r.json()
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(1 + i)
                continue
            if j.get("code", 0) != 0:
                raise BiliError(j.get("code"), j.get("message") or j.get("msg") or "")
            return j.get("data") if "data" in j else j.get("result")
        raise BiliError(-1, f"网络错误: {last}")

    def _wbi_sign(self, params):
        if not self._wbi_key:
            d = self.s.get("https://api.bilibili.com/x/web-interface/nav", timeout=15).json()["data"]
            img = d["wbi_img"]["img_url"].rsplit("/", 1)[1].split(".")[0]
            sub = d["wbi_img"]["sub_url"].rsplit("/", 1)[1].split(".")[0]
            orig = img + sub
            self._wbi_key = reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]
        params["wts"] = int(time.time())
        params = dict(sorted(params.items()))
        params = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
        query = urllib.parse.urlencode(params)
        params["w_rid"] = hashlib.md5((query + self._wbi_key).encode()).hexdigest()
        return params

    # ------------------------------------------------------------ 登录
    def qr_generate(self):
        d = self._get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
        return d["url"], d["qrcode_key"]

    def qr_poll(self, key):
        d = self._get("https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                      {"qrcode_key": key})
        code = d.get("code")
        if code == QR_OK:
            self.save_cookies()
        return code, d.get("message", "")

    def nav(self):
        try:
            return self._get("https://api.bilibili.com/x/web-interface/nav")
        except BiliError as e:
            if e.code == -101:
                return {"isLogin": False}
            raise

    def logged_in_user(self):
        d = self.nav()
        if d.get("isLogin"):
            return {"mid": str(d["mid"]), "name": d.get("uname", ""), "face": d.get("face", "")}
        return None

    # ------------------------------------------------------------ 采集
    def fetch(self, mid=None, own=True, max_videos=200, fetch_comments=True,
              comment_videos=8, progress=lambda p, msg: None) -> FetchResult:
        """mid 为空时采集当前登录账号；own=False 时只用公开接口（竞品追踪）。"""
        self._ensure_buvid()
        notes = []
        if mid is None:
            user = self.logged_in_user()
            if not user:
                raise BiliError(-101, "未登录，请先扫码登录 B 站")
            mid, name, face = user["mid"], user["name"], user["face"]
        else:
            card = self._get("https://api.bilibili.com/x/web-interface/card", {"mid": mid})
            name, face = card["card"]["name"], card["card"].get("face", "")
        progress(0.03, f"账号：{name}")

        rel = self._safe(self._get, "https://api.bilibili.com/x/relation/stat", {"vmid": mid})
        followers = rel.get("follower") if rel else None
        up = self._safe(self._get, "https://api.bilibili.com/x/space/upstat", {"mid": mid}) or {}
        total_views = (up.get("archive") or {}).get("view")
        total_likes = up.get("likes")

        # 1) 稿件列表
        listing = {}
        if own:
            listing = self._creator_archives(max_videos, progress)
            if not listing:
                notes.append("创作中心稿件列表获取失败，改用公开空间接口。")
        if not listing:
            listing = self._space_archives(mid, max_videos, progress)
        if not listing:
            listing = self._keyword_archives(mid, max_videos, progress)
        bvids = list(listing.keys())[:max_videos]
        if not bvids:
            notes.append("没有获取到任何稿件。若账号有稿件，可能触发了风控，请稍后重试。")

        # 2) 稿件详情（统一的统计口径）
        videos = []
        for i, bvid in enumerate(bvids):
            progress(0.15 + 0.55 * i / max(len(bvids), 1), f"读取稿件 {i + 1}/{len(bvids)}")
            v = self._video_detail(bvid, listing.get(bvid, {}), with_tags=i < 120)
            if v:
                videos.append(v)
            time.sleep(0.12)

        result = FetchResult(platform="bilibili", account_id=str(mid), name=name,
                             followers=followers, total_views=total_views,
                             total_likes=total_likes, avatar=face, videos=videos, notes=notes)
        if total_views is None:
            result.total_views = sum(v["views"] or 0 for v in videos)

        # 3) 创作中心深度数据（仅自己的账号）
        if own:
            progress(0.72, "读取创作中心数据（完播率、趋势）…")
            self._creator_extras(result)

        # 4) 热门视频评论
        if fetch_comments and videos:
            top = sorted(videos, key=lambda v: v["views"] or 0, reverse=True)[:comment_videos]
            for i, v in enumerate(top):
                progress(0.85 + 0.13 * i / len(top), f"读取评论 {i + 1}/{len(top)}")
                texts = self._comments(v["_aid"])
                if texts:
                    result.comments[v["video_id"]] = texts
                time.sleep(0.2)
        for v in videos:
            v.pop("_aid", None)
        progress(1.0, "完成")
        return result

    def _safe(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except BiliError as e:
            self.log(f"B站接口失败 {a[0] if a else ''}: {e}")
            return None

    def _creator_archives(self, max_videos, progress):
        out, pn = {}, 1
        while len(out) < max_videos:
            d = self._safe(self._get, "https://member.bilibili.com/x/web/archives",
                           {"status": "is_pubing,pubed,not_pubed", "pn": pn, "ps": 50,
                            "coop": 1, "interactive": 1})
            items = (d or {}).get("arc_audits") or []
            if not items:
                break
            for it in items:
                arc = it.get("Archive") or it.get("archive") or {}
                bvid = arc.get("bvid")
                if bvid and arc.get("state", 0) >= 0:
                    out[bvid] = {"tags": arc.get("tag", "")}
            progress(0.05 + 0.1 * min(len(out) / max_videos, 1), f"已发现稿件 {len(out)} 个")
            total = ((d.get("page") or {}).get("count")) or 0
            if pn * 50 >= total:
                break
            pn += 1
        return out

    def _space_archives(self, mid, max_videos, progress):
        out, pn = {}, 1
        while len(out) < max_videos:
            params = {"mid": mid, "ps": 40, "pn": pn, "order": "pubdate", "platform": "web",
                      "web_location": 1550101, "dm_img_list": "[]",
                      "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
                      "dm_cover_img_str": "QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgRGlyZWN0M0QxMSk",
                      "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}'}
            try:
                d = self._get("https://api.bilibili.com/x/space/wbi/arc/search", params, wbi=True)
            except BiliError as e:
                self.log(f"空间稿件列表失败: {e}")
                break
            vlist = ((d.get("list") or {}).get("vlist")) or []
            if not vlist:
                break
            for v in vlist:
                out[v["bvid"]] = {}
            progress(0.05 + 0.1 * min(len(out) / max_videos, 1), f"已发现稿件 {len(out)} 个")
            if pn * 40 >= ((d.get("page") or {}).get("count") or 0):
                break
            pn += 1
            time.sleep(0.5)
        return out

    def _keyword_archives(self, mid, max_videos, progress):
        """备用稿件列表接口：不走 WBI 风控校验。"""
        out, pn = {}, 1
        while len(out) < max_videos:
            d = self._safe(self._get, "https://api.bilibili.com/x/series/recArchivesByKeywords",
                           {"mid": mid, "keywords": "", "ps": 50, "pn": pn, "orderby": "pubdate"})
            arcs = (d or {}).get("archives") or []
            if not arcs:
                break
            for v in arcs:
                out[v["bvid"]] = {}
            progress(0.05 + 0.1 * min(len(out) / max_videos, 1), f"已发现稿件 {len(out)} 个")
            if pn * 50 >= ((d.get("page") or {}).get("total") or 0):
                break
            pn += 1
            time.sleep(0.4)
        return out

    def _video_detail(self, bvid, hint, with_tags=True):
        try:
            d = self._get("https://api.bilibili.com/x/web-interface/view", {"bvid": bvid})
        except BiliError as e:
            self.log(f"稿件 {bvid} 读取失败: {e}")
            return None
        st = d.get("stat", {})
        tags = hint.get("tags", "")
        if with_tags and not tags:
            t = self._safe(self._get, "https://api.bilibili.com/x/tag/archive/tags", {"bvid": bvid})
            if t:
                tags = ",".join(x.get("tag_name", "") for x in t)
        return {
            "video_id": bvid, "_aid": d.get("aid"),
            "title": d.get("title", ""),
            "url": f"https://www.bilibili.com/video/{bvid}",
            "publish_time": datetime.fromtimestamp(d.get("pubdate", 0)).isoformat(),
            "duration": d.get("duration"),
            "category": d.get("tname", ""),
            "tags": tags,
            "views": st.get("view"), "likes": st.get("like"), "coins": st.get("coin"),
            "favorites": st.get("favorite"), "comments": st.get("reply"),
            "shares": st.get("share"), "danmaku": st.get("danmaku"),
        }

    def _creator_extras(self, r: FetchResult):
        by_id = {v["video_id"]: v for v in r.videos}
        # 稿件完播率 / 平均播放时长
        d = self._safe(self._get, "https://member.bilibili.com/x/web/data/playanalysis",
                       {"copyright": 0})
        items = []
        if isinstance(d, dict):
            for val in d.values():
                if isinstance(val, list):
                    items.extend(x for x in val if isinstance(x, dict))
        got = 0
        for it in items:
            v = by_id.get(it.get("bvid"))
            if not v:
                continue
            rate = it.get("rate")
            if isinstance(rate, (int, float)) and rate > 0:
                v["avg_view_pct"] = rate / 10000 if rate > 100 else (rate / 100 if rate > 1 else rate)
                got += 1
            if it.get("avg_duration"):
                v["avg_view_duration"] = it["avg_duration"]
        if not got:
            r.notes.append("未获取到 B 站完播率数据（接口无权限或已变更），可在“导入后台数据”中导入创作中心导出的表格补全完播率、3秒跳出率、涨粉。")

        # 30 日趋势
        daily = {}
        for t, metric in PANDECT_TYPES.items():
            d = self._safe(self._get, "https://member.bilibili.com/x/web/data/pandect", {"type": t})
            for row in d or []:
                if not isinstance(row, dict) or "date_key" not in row:
                    continue
                date = datetime.fromtimestamp(row["date_key"]).strftime("%Y-%m-%d")
                daily.setdefault(date, {"date": date})[metric] = row.get("total_inc")
            time.sleep(0.15)
        stat = self._safe(self._get, "https://member.bilibili.com/x/web/index/stat") or {}
        fans30 = stat.get("fan_recent_thirty") or {}
        if isinstance(fans30, dict):
            for k, val in fans30.items():
                if isinstance(val, dict):   # {"follow": {date: n}, "unfollow": {...}}
                    metric = "subs_gained" if "follow" == k else ("subs_lost" if k == "unfollow" else None)
                    if metric:
                        for date, n in val.items():
                            daily.setdefault(str(date)[:10], {"date": str(date)[:10]})[metric] = n
        r.daily = sorted(daily.values(), key=lambda x: x["date"])
        if not r.daily:
            r.notes.append("未获取到 B 站 30 日趋势数据；程序会通过多次刷新的历史快照自行积累趋势。")

    def _comments(self, aid):
        if not aid:
            return []
        d = self._safe(self._get, "https://api.bilibili.com/x/v2/reply",
                       {"type": 1, "oid": aid, "sort": 1, "ps": 20, "pn": 1})
        replies = (d or {}).get("replies") or []
        return [x.get("content", {}).get("message", "") for x in replies if x.get("content")]
