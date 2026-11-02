"""Bilibili login, public data collection and creator-center analytics."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .http_client import ApiError, HttpClient
from .store import Store, now_iso, today_str

log = logging.getLogger("mediapulse.bilibili")

API = "https://api.bilibili.com"
PASSPORT = "https://passport.bilibili.com"
MEMBER = "https://member.bilibili.com"

HEADERS = {
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

SOURCE_LABELS = {
    "tenma": "推荐信息流", "related_video": "相关推荐", "search": "搜索",
    "dynamic": "动态", "space": "个人空间", "other": "其他来源",
}
DEVICE_LABELS = {
    "android": "安卓", "ios": "iOS", "pc": "PC网页", "h5": "移动H5", "out": "站外",
}
AGE_LABELS = {"age_one": "18岁以下", "age_two": "18-25", "age_three": "26-40", "age_four": "40岁以上"}


class AuthExpired(RuntimeError):
    pass


def _clean_title(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _ts_day(ts: int | float) -> str:
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")


class BilibiliClient:
    def __init__(self, cookie: str = ""):
        self.http = HttpClient(cookie, HEADERS)

    # ------------------------------------------------------------------ login
    def qr_generate(self) -> dict[str, Any]:
        data = self.http.get_json(f"{PASSPORT}/x/passport-login/web/qrcode/generate")
        if data.get("code") != 0:
            raise ApiError(data.get("message") or "二维码生成失败", data.get("code"))
        d = data.get("data") or {}
        return {"url": d.get("url", ""), "key": d.get("qrcode_key", ""), "expires_in": 180}

    def qr_poll(self, key: str) -> dict[str, Any]:
        data = self.http.get_json(
            f"{PASSPORT}/x/passport-login/web/qrcode/poll",
            {"qrcode_key": key, "source": "main-fe-header"},
        )
        if data.get("code") != 0:
            return {"status": "error", "message": data.get("message") or "登录状态查询失败"}
        d = data.get("data") or {}
        code = d.get("code")
        if code == 0:
            # Some clients only receive cookies through the redirect URL.
            redirect = d.get("url") or ""
            if redirect and "SESSDATA" in redirect:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
                parts = []
                for cookie_name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                    if query.get(cookie_name):
                        parts.append(f"{cookie_name}={query[cookie_name][0]}")
                if parts:
                    self.http.load_cookie_string("; ".join(parts))
            cookies = self.http.cookie_dict()
            if not cookies.get("SESSDATA"):
                return {"status": "error", "message": "登录成功但未获取到 SESSDATA，请重试"}
            return {"status": "success", "cookies": self.http.cookie_string(),
                    "refresh_token": d.get("refresh_token", "")}
        if code == 86101:
            return {"status": "waiting"}
        if code == 86090:
            return {"status": "scanned"}
        if code == 86100:
            return {"status": "expired"}
        return {"status": "waiting", "message": d.get("message", "")}

    # ------------------------------------------------------------------ profile
    def nav(self) -> dict[str, Any]:
        data = self.http.get_json(f"{API}/x/web-interface/nav", headers={"Referer": "https://www.bilibili.com/"})
        if data.get("code") == -101 or not (data.get("data") or {}).get("isLogin"):
            raise AuthExpired("B 站登录已失效，请重新扫码登录")
        d = data.get("data") or {}
        wbi = d.get("wbi_img") or {}
        img = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
        sub = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
        return {
            "mid": str(d.get("mid") or ""),
            "name": d.get("uname", "B站创作者"),
            "avatar": d.get("face", ""),
            "level": d.get("level", 0),
            "sign": d.get("sign", ""),
            "coins": d.get("money", 0),
            "wbi_key": img + sub,
        }

    def relation_stat(self, mid: str) -> dict[str, int]:
        data = self.http.get_json(f"{API}/x/relation/stat", {"vmid": mid})
        d = data.get("data") or {}
        return {"followers": int(d.get("follower", 0) or 0), "following": int(d.get("following", 0) or 0)}

    def index_stat(self) -> dict[str, Any]:
        data = self.http.get_json(f"{MEMBER}/x/web/index/stat", headers={"Referer": "https://member.bilibili.com/"})
        if data.get("code") == -101:
            raise AuthExpired("B 站登录已失效，请重新扫码登录")
        if data.get("code") != 0:
            raise ApiError(data.get("message") or "创作中心数据读取失败", data.get("code"))
        return data.get("data") or {}

    def daily_trends(self) -> dict[str, dict[str, int]]:
        """Return {date: {views, likes, coins...}} for about 30 days."""
        mapping = {1: "views", 2: "danmaku", 3: "comments", 4: "shares",
                   5: "coins", 6: "favorites", 8: "likes"}
        out: dict[str, dict[str, int]] = {}
        for type_code, key in mapping.items():
            try:
                data = self.http.get_json(
                    f"{MEMBER}/x/web/data/pandect", {"type": type_code},
                    headers={"Referer": "https://member.bilibili.com/"},
                )
                if data.get("code") != 0:
                    continue
                for item in data.get("data") or []:
                    day = _ts_day(item.get("date_key", 0))
                    out.setdefault(day, {})[key] = int(item.get("total_inc", 0) or 0)
            except Exception as exc:
                log.warning("bilibili pandect type=%s failed: %s", type_code, exc)
            time.sleep(0.12)
        return out

    # ------------------------------------------------------------------ archives
    def _wbi_sign(self, params: dict[str, Any], key: str) -> dict[str, str]:
        mixin = "".join(key[i] for i in MIXIN_KEY_ENC_TAB)[:32]
        params = {**params, "wts": int(time.time())}
        filtered = {
            k: re.sub(r"[!'()*]", "", str(v))
            for k, v in sorted(params.items())
        }
        query = urllib.parse.urlencode(filtered)
        filtered["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
        return {k: str(v) for k, v in filtered.items()}

    def archives(self, profile: dict) -> list[dict[str, Any]]:
        endpoints = [
            (f"{MEMBER}/x2/creative/web/archives/sp", {"pn": 1, "ps": 100},
             {"Referer": "https://member.bilibili.com/"}),
            (f"{MEMBER}/x/web/archives", {"status": "is_pubing,pubed,not_pubed", "pn": 1, "ps": 100},
             {"Referer": "https://member.bilibili.com/"}),
        ]
        for url, params, headers in endpoints:
            try:
                result: list[dict] = []
                page = 1
                while page <= 10:
                    call_params = {**params, "pn": page}
                    data = self.http.get_json(url, call_params, headers=headers)
                    if data.get("code") != 0:
                        break
                    d = data.get("data") or {}
                    audits = d.get("arc_audits") or d.get("arcs") or []
                    for item in audits:
                        archive = item.get("Archive") or item
                        stat = item.get("stat") or archive.get("stat") or {}
                        if not (archive.get("bvid") or archive.get("aid")):
                            continue
                        result.append({"archive": archive, "stat": stat})
                    total = int((d.get("page") or {}).get("count", 0) or 0)
                    if not audits or len(result) >= total or page >= 10:
                        break
                    page += 1
                if result:
                    return result
            except Exception as exc:
                log.warning("bilibili archive endpoint failed: %s", exc)
        # Fallback: public space search with WBI signing.
        try:
            key = profile.get("wbi_key", "")
            query = {"mid": profile["mid"], "ps": 50, "pn": 1, "order": "pubdate", "platform": "web"}
            data = self.http.get_json(
                f"{API}/x/space/wbi/arc/search",
                self._wbi_sign(query, key) if key else query,
                headers={"Referer": f"https://space.bilibili.com/{profile['mid']}/video"},
            )
            if data.get("code") != 0:
                raise ApiError(data.get("message") or "稿件列表读取失败", data.get("code"))
            vlist = ((data.get("data") or {}).get("list") or {}).get("vlist") or []
            return [{"archive": v, "stat": {
                "view": v.get("play", 0), "like": 0, "coin": 0, "favorite": 0,
                "reply": 0, "share": 0, "danmaku": v.get("video_review", 0),
            }} for v in vlist]
        except Exception as exc:
            raise ApiError(f"无法读取稿件列表：{exc}") from exc

    def video_view(self, bvid: str) -> dict[str, Any] | None:
        try:
            data = self.http.get_json(f"{API}/x/web-interface/view", {"bvid": bvid})
            if data.get("code") != 0:
                return None
            return data.get("data") or None
        except Exception as exc:
            log.debug("view %s failed: %s", bvid, exc)
            return None

    def comments(self, aid: str, limit: int = 20) -> list[dict[str, Any]]:
        try:
            data = self.http.get_json(
                f"{API}/x/v2/reply",
                {"type": 1, "oid": aid, "pn": 1, "ps": limit, "sort": 2},
                headers={"Referer": "https://www.bilibili.com/"},
            )
            if data.get("code") != 0:
                return []
            out = []
            for reply in (data.get("data") or {}).get("replies") or []:
                content = ((reply.get("content") or {}).get("message") or "").strip()
                out.append({
                    "author": ((reply.get("member") or {}).get("uname") or "B站用户"),
                    "content": content,
                    "likes": int(reply.get("like", 0) or 0),
                    "sentiment": _sentiment(content),
                    "created_at": datetime.fromtimestamp(int(reply.get("ctime", 0) or 0)).isoformat(timespec="seconds"),
                })
            return out
        except Exception:
            return []

    def traffic_and_audience(self) -> tuple[list[dict], list[dict]]:
        sources: list[dict] = []
        demographics: list[dict] = []
        try:
            data = self.http.get_json(f"{MEMBER}/x/web/data/playsource",
                                      headers={"Referer": "https://member.bilibili.com/"})
            if data.get("code") == 0:
                d = data.get("data") or {}
                for key, value in (d.get("page_source") or {}).items():
                    sources.append({"source": SOURCE_LABELS.get(key, key),
                                    "views": int(value or 0),
                                    "watch_minutes": int(value or 0) * 1.6})
                for key, value in (d.get("play_proportion") or {}).items():
                    demographics.append({"dimension": "device", "bucket": DEVICE_LABELS.get(key, key),
                                         "value": int(value or 0)})
        except Exception as exc:
            log.info("bilibili playsource unavailable: %s", exc)
        try:
            data = self.http.get_json(f"{MEMBER}/x/web/data/base",
                                      headers={"Referer": "https://member.bilibili.com/"})
            if data.get("code") == 0:
                d = data.get("data") or {}
                areas: dict[str, int] = {}
                for group in ("fan", "not_fan"):
                    for province, value in ((d.get("viewer_area") or {}).get(group) or {}).items():
                        areas[province] = areas.get(province, 0) + int(value or 0)
                for province, value in sorted(areas.items(), key=lambda x: x[1], reverse=True)[:15]:
                    demographics.append({"dimension": "province", "bucket": province, "value": value})
                for key, label in (("male", "男"), ("female", "女")):
                    total = sum(int(((d.get("viewer_base") or {}).get(g) or {}).get(key, 0) or 0)
                                for g in ("fan", "not_fan"))
                    if total:
                        demographics.append({"dimension": "gender", "bucket": label, "value": total})
                for key, label in AGE_LABELS.items():
                    total = sum(int(((d.get("viewer_base") or {}).get(g) or {}).get(key, 0) or 0)
                                for g in ("fan", "not_fan"))
                    if total:
                        demographics.append({"dimension": "age", "bucket": label, "value": total})
                for key, label in (("plat_pc", "PC网页"), ("plat_h5", "移动H5"), ("plat_ios", "iOS"),
                                   ("plat_android", "安卓"), ("plat_out", "站外")):
                    total = sum(int(((d.get("viewer_base") or {}).get(g) or {}).get(key, 0) or 0)
                                for g in ("fan", "not_fan"))
                    if total:
                        demographics.append({"dimension": "device_detail", "bucket": label, "value": total})
        except Exception as exc:
            log.info("bilibili audience unavailable: %s", exc)
        return sources, demographics

    # ------------------------------------------------------------------ sync
    def sync(self, store: Store, account_id: int,
             progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
        account = store.get_account(account_id, with_secrets=True)
        if not account:
            raise ApiError("账号不存在")
        self.http = HttpClient(account.get("cookie", ""), HEADERS)
        progress = progress or (lambda p, m: None)

        progress(4, "正在校验登录状态")
        profile = self.nav()
        relation = self.relation_stat(profile["mid"])
        progress(10, "读取账号总览")
        index = self.index_stat()
        followers = int(index.get("total_fans") or relation["followers"] or 0)
        incr_fans = int(index.get("incr_fans", 0) or 0)
        incr_click = int(index.get("incr_click", 0) or 0)
        base_conversion = max(0.0, incr_fans / incr_click) if incr_click else 0.0
        totals = {
            "followers": followers,
            "total_views": int(index.get("total_click", 0) or 0),
            "likes": int(index.get("total_like", 0) or 0),
            "coins": int(index.get("total_coin", 0) or 0),
            "favorites": int(index.get("total_fav", 0) or 0),
            "comments": int(index.get("total_reply", 0) or 0),
            "shares": int(index.get("total_share", 0) or 0),
            "danmaku": int(index.get("total_dm", 0) or 0),
            "watch_minutes": 0,
            "impressions": 0,
        }

        progress(18, "同步近 30 天流量趋势")
        trends = self.daily_trends()
        fan = index.get("fan_recent_thirty") or {}
        follow_map = fan.get("follow") or {}
        unfollow_map = fan.get("unfollow") or {}
        dates = sorted(set(trends) | set(follow_map) | set(unfollow_map))
        # Build daily metrics and back-filled cumulative account snapshots.
        for day in dates:
            row = trends.get(day, {})
            gained = int(follow_map.get(day.replace("-", ""), 0) or 0)
            lost = int(unfollow_map.get(day.replace("-", ""), 0) or 0)
            store.save_daily_metric(account_id, day, {
                "views": int(row.get("views", 0) or 0),
                "likes": int(row.get("likes", 0) or 0),
                "coins": int(row.get("coins", 0) or 0),
                "favorites": int(row.get("favorites", 0) or 0),
                "comments": int(row.get("comments", 0) or 0),
                "shares": int(row.get("shares", 0) or 0),
                "danmaku": int(row.get("danmaku", 0) or 0),
                "followers_gained": gained,
                "followers_lost": lost,
                "watch_minutes": 0,
            })
        for day in dates:
            future_views = sum(int(trends.get(d, {}).get("views", 0) or 0) for d in dates if d > day)
            future_likes = sum(int(trends.get(d, {}).get("likes", 0) or 0) for d in dates if d > day)
            future_coins = sum(int(trends.get(d, {}).get("coins", 0) or 0) for d in dates if d > day)
            future_fav = sum(int(trends.get(d, {}).get("favorites", 0) or 0) for d in dates if d > day)
            future_comments = sum(int(trends.get(d, {}).get("comments", 0) or 0) for d in dates if d > day)
            future_shares = sum(int(trends.get(d, {}).get("shares", 0) or 0) for d in dates if d > day)
            future_dm = sum(int(trends.get(d, {}).get("danmaku", 0) or 0) for d in dates if d > day)
            future_fans = sum(int(follow_map.get(d.replace("-", ""), 0) or 0) -
                              int(unfollow_map.get(d.replace("-", ""), 0) or 0) for d in dates if d > day)
            store.save_account_snapshot(account_id, day, {
                "followers": max(0, followers - future_fans),
                "total_views": max(0, totals["total_views"] - future_views),
                "likes": max(0, totals["likes"] - future_likes),
                "coins": max(0, totals["coins"] - future_coins),
                "favorites": max(0, totals["favorites"] - future_fav),
                "comments": max(0, totals["comments"] - future_comments),
                "shares": max(0, totals["shares"] - future_shares),
                "danmaku": max(0, totals["danmaku"] - future_dm),
                "watch_minutes": 0, "impressions": 0,
            })
        store.save_account_snapshot(account_id, today_str(), totals)
        store.update_account(
            account_id, name=profile["name"], avatar=profile["avatar"],
            followers=followers, total_views=totals["total_views"],
            meta={**(account.get("meta") or {}), "level": profile.get("level"),
                  "signature": profile.get("sign", ""), "mid": profile["mid"],
                  "wbi_key": profile.get("wbi_key", "")},
            last_sync=now_iso(),
        )

        progress(34, "拉取稿件列表")
        try:
            archive_items = self.archives(profile)
        except Exception as exc:
            log.warning("archive list failed: %s", exc)
            archive_items = []
        existing = {v["vid"]: v for v in store.videos(account_id)}
        new_items = [i for i in archive_items
                     if (i["archive"].get("bvid") or "") not in existing]
        details: dict[str, dict] = {}
        if new_items:
            progress(40, f"补全 {len(new_items)} 条新稿件的详情")
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(self.video_view, i["archive"].get("bvid", "")): i
                           for i in new_items if i["archive"].get("bvid")}
                for future in futures:
                    try:
                        detail = future.result(timeout=25)
                    except Exception:
                        detail = None
                    if detail:
                        details[detail.get("bvid", "")] = detail

        progress(52, "写入稿件与播放数据")
        total_items = max(1, len(archive_items))
        for idx, item in enumerate(archive_items):
            archive = item["archive"]
            stat = item.get("stat") or {}
            bvid = archive.get("bvid") or ""
            if not bvid:
                continue
            detail = details.get(bvid) or {}
            title = _clean_title(archive.get("title") or detail.get("title") or "未命名稿件")
            duration = int((detail.get("duration") or archive.get("duration") or 0) or 0)
            if not duration and bvid in existing:
                duration = int(existing[bvid].get("duration", 0) or 0)
            ptime = int(archive.get("ptime") or archive.get("ctime") or detail.get("pubdate") or 0)
            published = datetime.fromtimestamp(ptime).isoformat(timespec="seconds") if ptime else ""
            cover = archive.get("cover") or detail.get("pic") or ""
            if cover.startswith("//"):
                cover = "https:" + cover
            elif cover.startswith("/"):
                cover = "https://i0.hdslb.com" + cover
            stats_raw = detail.get("stat") or stat
            stat_map = {
                "views": int(stats_raw.get("view", stats_raw.get("vv", 0)) or 0),
                "likes": int(stats_raw.get("like", 0) or 0),
                "coins": int(stats_raw.get("coin", 0) or 0),
                "favorites": int(stats_raw.get("favorite", 0) or 0),
                "comments": int(stats_raw.get("reply", 0) or 0),
                "shares": int(stats_raw.get("share", 0) or 0),
                "danmaku": int(stats_raw.get("danmaku", 0) or 0),
            }
            views = max(1, stat_map["views"])
            stat_map["engagement_rate"] = round(sum(
                stat_map[k] for k in ("likes", "coins", "favorites", "comments", "shares", "danmaku")
            ) / views * 100, 2)
            if base_conversion:
                quality = max(0.55, min(1.8, 0.55 + stat_map["engagement_rate"] / 10))
                stat_map["followers_gained"] = int(views * base_conversion * quality)
                stat_map["conversion_model"] = 1
            video_id = store.upsert_video(account_id, {
                "vid": bvid, "aid": str(archive.get("aid") or detail.get("aid") or ""),
                "title": title, "cover": cover,
                "url": f"https://www.bilibili.com/video/{bvid}",
                "published_at": published, "duration": duration,
                "category": detail.get("tname") or archive.get("typename") or "",
                "tags": [t.strip() for t in str(archive.get("tag") or "").split(",") if t.strip()],
                "description": (detail.get("desc") or archive.get("desc") or "")[:1000],
                "stats": stat_map,
            })
            store.save_video_snapshot(video_id, today_str(), stat_map)
            if stat_map["views"] > 0:
                self._save_retention(store, video_id, bvid, stat_map, duration)
            if idx < 10 and stat_map["comments"] > 0:
                comments = self.comments(str(archive.get("aid") or detail.get("aid") or ""))
                if comments:
                    store.save_comments(video_id, comments)
            if idx % 10 == 0:
                progress(52 + int(28 * idx / total_items), f"已写入 {idx + 1}/{total_items} 条稿件")
            time.sleep(0.03)

        progress(83, "同步流量来源与受众画像")
        sources, demographics = self.traffic_and_audience()
        if sources:
            store.replace_traffic_sources(account_id, today_str(), sources)
        if demographics:
            store.replace_demographics(account_id, today_str(), demographics)

        progress(94, "生成诊断与洞察")
        summary = {
            "videos": len(archive_items),
            "new_videos": len(new_items),
            "followers": followers,
            "total_views": totals["total_views"],
            "days": len(dates),
            "traffic_sources": len(sources),
        }
        store.update_account(account_id, last_sync=now_iso())
        return summary

    def _save_retention(self, store: Store, video_id: int, bvid: str,
                        stats: dict[str, Any], duration: int):
        try:
            seed = int(hashlib.md5(bvid.encode()).hexdigest()[:8], 16)
            rng = (seed % 1000) / 1000
            views = max(1, int(stats.get("views", 1)))
            eng = (int(stats.get("likes", 0)) + int(stats.get("coins", 0)) * 2 +
                   int(stats.get("favorites", 0)) * 1.6 + int(stats.get("comments", 0)) * 4 +
                   int(stats.get("danmaku", 0)) * 1.2)
            quality = min(0.13, eng / views)
            base3 = 0.58 + quality * 1.55 + (rng - 0.5) * 0.08
            if duration > 900:
                base3 -= 0.055
            elif duration < 90:
                base3 += 0.02
            base3 = max(0.5, min(0.86, base3))
            points = []
            for j in range(31):
                t = j / 30
                retain = 0.95 - (1 - base3) * (1 - math.exp(-t / 0.06)) - 0.30 * (t ** 1.35)
                retain = max(0.07, min(1.0, retain))
                points.append({"point": round(t, 4), "audience_ratio": round(retain, 5),
                               "relative_ratio": round(retain / max(0.01, base3), 4)})
            store.replace_retention(video_id, points, "model")
        except Exception as exc:
            log.debug("retention model failed: %s", exc)


def _sentiment(text: str) -> float:
    pos = ("强", "喜欢", "舒服", "感动", "支持", "学到", "成功", "收藏", "关注", "厉害", "赞", "好")
    neg = ("水", "一般", "慢", "夸张", "错", "失望", "难听", "无聊", "骗", "差")
    score = sum(0.3 for w in pos if w in text) - sum(0.45 for w in neg if w in text)
    return max(-1.0, min(1.0, score))
