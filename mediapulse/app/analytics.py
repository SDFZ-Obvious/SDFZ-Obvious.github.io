"""Analytics, scoring, forecasts and rule-based consulting insights."""
from __future__ import annotations

import math
import re
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from .store import Store

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DURATION_BUCKETS = [
    ("0-1 分钟", 0, 60),
    ("1-3 分钟", 60, 180),
    ("3-5 分钟", 180, 300),
    ("5-10 分钟", 300, 600),
    ("10-20 分钟", 600, 1200),
    ("20 分钟以上", 1200, 10**9),
]
BENCHMARKS = {
    "bilibili": {"engagement": 6.5, "conversion": 0.18, "retention3": 0.66},
    "youtube": {"engagement": 4.2, "conversion": 0.15, "retention3": 0.62},
}


# --------------------------------------------------------------------------- utils
def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default


def _pct(a: float, b: float) -> float:
    if not b:
        return 0.0
    return round((a - b) / abs(b) * 100, 1)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _parse_day(text: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_dt(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        parsed = _parse_day(text)
        return datetime.combine(parsed, datetime.min.time()).replace(hour=19) if parsed else None


def _fmt_int(value: float) -> str:
    return f"{int(round(value)):,}"


def _fmt_num(value: float) -> str:
    value = float(value or 0)
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.1f}万"
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:,.0f}"


def _linreg(ys: list[float]) -> tuple[float, float, float]:
    """Return slope, intercept, r2 for y against 0..n-1."""
    n = len(ys)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = cov / var if var else 0.0
    intercept = my - slope * mx
    pred = [slope * x + intercept for x in xs]
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, pred))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return slope, intercept, max(0.0, min(1.0, r2))


def _ema(values: list[float], alpha: float = 0.35) -> float:
    if not values:
        return 0.0
    out = values[0]
    for value in values[1:]:
        out = alpha * value + (1 - alpha) * out
    return out


def _range(days: int) -> tuple[date, date]:
    end = date.today()
    days = max(1, int(days))
    return end - timedelta(days=days - 1), end


def _feature_flags(title: str, platform: str) -> dict[str, bool]:
    low = title.lower()
    return {
        "number": bool(re.search(r"\d", title)),
        "question": ("?" in title or "？" in title or low.startswith(("why", "how", "what", "can ", "is "))),
        "bracket": any(mark in title for mark in ("【", "】", "[", "]", "｜", "|")),
        "emoji": bool(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", title)),
        "howto": any(word in low for word in ("教程", "指南", "攻略", "如何", "怎么", "how to", "guide", "tutorial")),
        "challenge": any(word in low for word in ("挑战", "实测", "我花", "我用", "i tried", "i built", "i spent", "testing")),
        "negative": any(word in low for word in ("别", "不要", "避坑", "错误", "why your", "stop", "mistake", "truth")),
    }


def _video_first7(video: dict, snaps: list[dict], today: date) -> float:
    published = _parse_day(video.get("published_at", ""))
    if not snaps:
        total = float(video.get("stats", {}).get("views", 0) or 0)
        if not published:
            return total
        age = max(1, (today - published).days + 1)
        return total * min(1.0, 7 / age) * (1.6 if age > 7 else 1.0)
    if published:
        window = [s for s in snaps if (d := _parse_day(s["day"])) and published <= d <= published + timedelta(days=7)]
        if window:
            return float(max(s["views"] for s in window))
        # No early snapshots: estimate from current totals and age.
        total = float(max(s["views"] for s in snaps))
        age = max(1, (today - published).days + 1)
        return total * min(1.0, 7 / age) * 1.5
    return float(max(s["views"] for s in snaps))


def _retention3(store: Store, video_id: int) -> float | None:
    points = store.retention(video_id)
    if not points:
        return None
    nearest = min(points, key=lambda p: abs(float(p["point"]) - 0.03))
    return float(nearest["audience_ratio"])


# --------------------------------------------------------------------------- overview
def build_dashboard(store: Store, account: dict[str, Any], days: int = 30) -> dict[str, Any]:
    days = max(7, min(365, int(days or 30)))
    start, end = _range(days)
    prev_start = start - timedelta(days=days)
    prev_end = start - timedelta(days=1)
    account_id = int(account["id"])
    platform = account["platform"]
    benchmark = BENCHMARKS.get(platform, BENCHMARKS["bilibili"])

    daily_all = store.daily_metrics(account_id)
    by_day = {row["day"]: row for row in daily_all}
    current_rows = [r for r in daily_all if start.isoformat() <= r["day"] <= end.isoformat()]
    prev_rows = [r for r in daily_all if prev_start.isoformat() <= r["day"] <= prev_end.isoformat()]
    snaps = store.account_snapshots(account_id)

    def snap_at(day: date) -> dict | None:
        eligible = [s for s in snaps if (_parse_day(s["day"]) or day) <= day]
        return eligible[-1] if eligible else (snaps[0] if snaps else None)

    latest_snap = snap_at(end)
    prev_snap = snap_at(prev_end)
    if not latest_snap and snaps:
        latest_snap = snaps[-1]
    followers = int(latest_snap["followers"]) if latest_snap else int(account.get("followers") or 0)
    prev_followers = int(prev_snap["followers"]) if prev_snap else followers
    total_views_all = int(latest_snap["total_views"]) if latest_snap else int(account.get("total_views") or 0)

    views = sum(int(r.get("views") or 0) for r in current_rows)
    prev_views = sum(int(r.get("views") or 0) for r in prev_rows)
    eng_keys = ("likes", "coins", "favorites", "comments", "shares", "danmaku")
    engagements = sum(sum(int(r.get(k) or 0) for k in eng_keys) for r in current_rows)
    prev_engagements = sum(sum(int(r.get(k) or 0) for k in eng_keys) for r in prev_rows)
    net_followers = followers - prev_followers
    prev_net = (int(prev_snap["followers"]) if prev_snap else followers) - (
        int(snap_at(prev_start - timedelta(days=1))["followers"]) if snaps else followers
    )
    gained = sum(int(r.get("followers_gained") or 0) for r in current_rows)
    lost = sum(int(r.get("followers_lost") or 0) for r in current_rows)
    watch_minutes = sum(float(r.get("watch_minutes") or 0) for r in current_rows)
    prev_watch_minutes = sum(float(r.get("watch_minutes") or 0) for r in prev_rows)
    impressions = sum(int(r.get("impressions") or 0) for r in current_rows)
    engagement_rate = _safe_div(engagements, views) * 100
    prev_engagement_rate = _safe_div(prev_engagements, prev_views) * 100
    conversion = _safe_div(net_followers, views) * 100
    prev_conversion = _safe_div(prev_net, prev_views) * 100

    all_videos = store.videos(account_id)
    all_snaps = store.all_video_snapshots(account_id)
    period_videos = [_video_period_metrics(v, all_snaps.get(int(v["id"]), []), start, end, today=end)
                     for v in all_videos]
    uploaded = [v for v in period_videos if v["published_date"] and start.isoformat() <= v["published_date"] <= end.isoformat()]
    avg_views_per_upload = _safe_div(views, max(1, len(uploaded)))

    # daily series (fill every day)
    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        key = day.isoformat()
        row = by_day.get(key, {})
        snap = snap_at(day)
        series.append({
            "date": key,
            "label": f"{day.month}/{day.day}",
            "views": int(row.get("views") or 0),
            "followers": int(snap["followers"]) if snap else 0,
            "net_followers": int(row.get("followers_gained") or 0) - int(row.get("followers_lost") or 0),
            "gained": int(row.get("followers_gained") or 0),
            "lost": int(row.get("followers_lost") or 0),
            "engagements": sum(int(row.get(k) or 0) for k in eng_keys),
            "likes": int(row.get("likes") or 0),
            "watch_minutes": round(float(row.get("watch_minutes") or 0), 1),
        })

    def spark(key: str, n: int = 14) -> list[float]:
        values = [float(r.get(key) or 0) for r in current_rows[-n:]]
        return [round(v, 1) for v in values]

    follower_spark = [s["followers"] for s in series[-14:]]
    kpi_specs = [
        ("followers", "总粉丝", followers, "", followers - prev_followers, _pct(followers, prev_followers),
         "up", "人", follower_spark),
        ("views", "周期播放", views, "", views, _pct(views, prev_views), "up", "次", spark("views")),
        ("engagement_rate", "互动率", round(engagement_rate, 2), "%", engagement_rate,
         round(engagement_rate - prev_engagement_rate, 2), "up", "pt", []),
        ("conversion", "转粉率", round(conversion, 2), "%", conversion,
         round(conversion - prev_conversion, 2), "up", "pt", []),
        ("net_followers", "净增粉丝", net_followers, "", net_followers,
         _pct(net_followers, prev_net) if prev_net else 0, "up", "人", spark("net_followers")),
        ("watch_hours", "观看时长", round(watch_minutes / 60, 1), "h", watch_minutes,
         _pct(watch_minutes, prev_watch_minutes) if prev_watch_minutes else 0, "up", "h", spark("watch_minutes")),
    ]
    kpis = []
    for key, label, value, unit, raw, delta, direction, delta_unit, sparkline in kpi_specs:
        kpis.append({
            "key": key, "label": label, "value": value, "unit": unit,
            "delta": delta, "direction": direction if delta else "flat",
            "delta_unit": delta_unit, "spark": sparkline,
            "hint": _kpi_hint(key, raw, platform, benchmark),
        })

    top_videos = sorted(period_videos, key=lambda v: (v["period_views"], v["total_views"]), reverse=True)[:10]
    for video in period_videos:
        video["retention3"] = _retention3(store, int(video["id"]))
    heatmap, best_slots = _heatmap(all_videos, all_snaps, end)
    duration_rows = _duration_analysis(store, period_videos, platform)
    cadence = _cadence(period_videos, end, days)
    forecast = _forecast(current_rows, followers, days)
    anomalies = _anomalies(current_rows, period_videos)
    title_patterns = _title_patterns(period_videos)
    tags = _tag_performance(period_videos)
    health = _health(account, kpis, engagement_rate, conversion, cadence, duration_rows,
                     benchmark, platform)
    funnel = _funnel(views, engagements, net_followers, impressions)
    sources = [_source_view(r) for r in store.traffic_sources(account_id)]
    if sources and views:
        source_total = sum(s["views"] for s in sources) or 1
        for source in sources:
            ratio = source["views"] / source_total
            source["views"] = int(views * ratio)
            source["watch_minutes"] = round(source["watch_minutes"] / source_total * views, 1)
    demographics = _demographics(store.demographics(account_id))
    insights = generate_insights(
        account, kpis, best_slots, duration_rows, tags, cadence, sources,
        anomalies, top_videos, platform, benchmark, days,
    )

    top_video = top_videos[0] if top_videos else None
    summary_bits = [
        f"过去 {days} 天共获得 **{_fmt_num(views)}** 次播放，互动率 **{engagement_rate:.2f}%**",
        f"净增粉丝 **{net_followers:+,}**，转粉率 **{conversion:.2f}%**",
    ]
    if best_slots:
        slot = best_slots[0]
        summary_bits.append(f"表现最好的发布时段是 **{slot['label']}**，首 7 日播放平均高出大盘 {slot['lift']:+.0f}%")
    if top_video:
        summary_bits.append(f"本周期增长引擎是《{top_video['title']}》，贡献 **{_fmt_num(top_video['period_views'])}** 次播放")
    if anomalies:
        summary_bits.append(f"检测到 **{len(anomalies)}** 个流量异常日，建议结合发布记录复盘")
    summary = "；".join(summary_bits) + "。"

    platform_note = (
        "B 站数据来自公开视频接口与创作中心（登录后）。平台未公开单稿转粉与逐秒留存，页面中的单稿转粉、"
        "播放完成率/3 秒跳出率均为互动模型估算，仅用于相对比较；流量来源与受众画像来自创作中心，通常 T+1 更新。"
        if platform == "bilibili"
        else "YouTube 数据来自 YouTube Data API 与 YouTube Analytics API。留存曲线、3 秒跳出率、流量来源为平台真实数据；"
        "指标可能存在 24-72 小时延迟。"
    )

    result = {
        "account": _public_account(account),
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat(),
                   "label": f"{start.month}月{start.day}日 - {end.month}月{end.day}日"},
        "kpis": kpis,
        "totals": {
            "followers": followers, "total_views": total_views_all, "views": views,
            "engagements": engagements, "net_followers": net_followers,
            "gained": gained, "lost": lost, "watch_hours": round(watch_minutes / 60, 1),
            "uploads": len(uploaded), "impressions": impressions,
            "avg_views_per_upload": int(avg_views_per_upload),
        },
        "series": series,
        "top_videos": top_videos,
        "heatmap": heatmap,
        "best_slots": best_slots,
        "duration": duration_rows,
        "cadence": cadence,
        "forecast": forecast,
        "anomalies": anomalies,
        "title_patterns": title_patterns,
        "tags": tags,
        "health": health,
        "funnel": funnel,
        "sources": sources,
        "demographics": demographics,
        "insights": insights,
        "summary": summary,
        "platform_note": platform_note,
        "retention_source": "model" if platform == "bilibili" else "platform",
    }
    return result


def _kpi_hint(key: str, value: float, platform: str, benchmark: dict) -> str:
    if key == "engagement_rate":
        return f"平台健康线约 {benchmark['engagement']:.1f}%"
    if key == "conversion":
        return f"优秀线约 {benchmark['conversion']:.2f}%（每千播约 {benchmark['conversion'] * 10:.1f} 人）"
    if key == "net_followers":
        return "净增 = 新增关注 - 取关"
    if key == "watch_hours":
        return "仅统计登录后可用的观看时长"
    if key == "followers":
        return "当前账号粉丝总量"
    if key == "views":
        return "所选周期内的新增播放"
    return ""


def _public_account(account: dict) -> dict:
    meta = account.get("meta") or {}
    return {
        "id": account["id"], "platform": account["platform"], "uid": account["uid"],
        "name": account["name"], "avatar": account.get("avatar", ""),
        "followers": account.get("followers", 0), "is_demo": bool(account.get("is_demo")),
        "last_sync": account.get("last_sync", ""), "signature": meta.get("signature", ""),
        "color": meta.get("color", ""),
    }


def _video_period_metrics(video: dict, snaps: list[dict], start: date, end: date, today: date) -> dict:
    stats = video.get("stats") or {}
    published = _parse_day(video.get("published_at", ""))
    period_rows = [s for s in snaps if (d := _parse_day(s["day"])) and start <= d <= end]
    base_rows = [s for s in snaps if (d := _parse_day(s["day"])) and d < start]
    latest = period_rows[-1] if period_rows else (base_rows[-1] if base_rows else None)
    baseline = base_rows[-1] if base_rows else None
    if latest:
        period_views = max(0, int(latest["views"]) - (int(baseline["views"]) if baseline else 0))
        period_likes = max(0, int(latest["likes"]) - (int(baseline["likes"]) if baseline else 0))
        period_comments = max(0, int(latest["comments"]) - (int(baseline["comments"]) if baseline else 0))
        period_followers = max(0, int(latest.get("followers_gained") or 0) -
                               (int(baseline.get("followers_gained") or 0) if baseline else 0))
    else:
        total = int(stats.get("views", 0) or 0)
        if published and published < start:
            age = max(1, (end - published).days + 1)
            ratio = min(1.0, ((end - start).days + 1) / age)
        else:
            ratio = 1.0
        period_views = int(total * ratio)
        period_likes = int(int(stats.get("likes", 0) or 0) * ratio)
        period_comments = int(int(stats.get("comments", 0) or 0) * ratio)
        period_followers = int(int(stats.get("followers_gained", 0) or 0) * ratio)
    total_views = int(stats.get("views", 0) or 0) or (int(latest["views"]) if latest else 0)
    views = max(1, total_views)
    eng = sum(int(stats.get(k, 0) or 0) for k in ("likes", "coins", "favorites", "comments", "shares", "danmaku"))
    engagement_rate = _safe_div(eng, views) * 100
    followers_gained = int(stats.get("followers_gained", 0) or 0)
    conversion = _safe_div(followers_gained, views) * 100
    spark = [int(s["views"]) for s in snaps[-20:]] if snaps else []
    return {
        "id": video["id"], "vid": video["vid"], "title": video["title"],
        "cover": video.get("cover", ""), "url": video.get("url", ""),
        "published_at": video.get("published_at", ""),
        "published_date": published.isoformat() if published else "",
        "duration": int(video.get("duration", 0) or 0),
        "category": video.get("category", ""), "tags": video.get("tags", []),
        "total_views": total_views, "period_views": period_views,
        "period_likes": period_likes, "period_comments": period_comments,
        "period_followers": period_followers,
        "likes": int(stats.get("likes", 0) or 0), "coins": int(stats.get("coins", 0) or 0),
        "favorites": int(stats.get("favorites", 0) or 0), "comments": int(stats.get("comments", 0) or 0),
        "shares": int(stats.get("shares", 0) or 0), "danmaku": int(stats.get("danmaku", 0) or 0),
        "engagement_rate": round(engagement_rate, 2),
        "conversion": round(conversion, 2), "followers_gained": followers_gained,
        "first7": int(_video_first7(video, snaps, today)),
        "spark": spark,
        "age_days": (today - published).days if published else None,
    }


def _heatmap(videos: list[dict], all_snaps: dict, today: date) -> tuple[list[dict], list[dict]]:
    cells: dict[tuple[int, int], list[dict]] = {}
    for video in videos:
        published = _parse_dt(video.get("published_at", ""))
        if not published:
            continue
        first7 = _video_first7(video, all_snaps.get(int(video["id"]), []), today)
        stats = video.get("stats") or {}
        views = max(1, int(stats.get("views", 0) or 0))
        eng = sum(int(stats.get(k, 0) or 0) for k in ("likes", "coins", "favorites", "comments", "shares", "danmaku"))
        cells.setdefault((published.weekday(), published.hour), []).append({
            "first7": first7, "engagement": eng / views * 100,
            "conversion": _safe_div(int(stats.get("followers_gained", 0) or 0), views) * 100,
            "title": video["title"],
        })
    values = [c["first7"] for group in cells.values() for c in group]
    overall = _median(values)
    matrix = []
    max_score = 0
    for weekday in range(7):
        for hour in range(24):
            group = cells.get((weekday, hour), [])
            if group:
                avg = _mean([c["first7"] for c in group])
                score = avg
                count = len(group)
            else:
                avg, score, count = 0, 0, 0
            max_score = max(max_score, score)
            matrix.append({"weekday": weekday, "hour": hour, "value": int(avg),
                           "count": count, "score": round(score, 1)})
    slots = []
    for (weekday, hour), group in cells.items():
        n = len(group)
        avg = _mean([c["first7"] for c in group])
        bayes = (sum(c["first7"] for c in group) + overall * 3) / (n + 3)
        slots.append({
            "weekday": weekday, "hour": hour,
            "label": f"{WEEKDAYS[weekday]} {hour:02d}:00",
            "avg_first7": int(avg), "count": n, "score": int(bayes),
            "lift": round((bayes / overall - 1) * 100, 1) if overall else 0,
            "engagement": round(_mean([c["engagement"] for c in group]), 2),
            "confidence": "高" if n >= 4 else ("中" if n >= 2 else "低"),
        })
    slots.sort(key=lambda s: (s["score"], s["count"]), reverse=True)
    return matrix, slots[:8]


def _duration_analysis(store: Store, videos: list[dict], platform: str) -> list[dict]:
    rows = []
    for label, low, high in DURATION_BUCKETS:
        group = [v for v in videos if low <= v["duration"] < high]
        if not group:
            rows.append({"label": label, "count": 0, "avg_views": 0, "engagement": 0,
                         "conversion": 0, "retention3": None})
            continue
        rets = []
        for v in group[:30]:
            r = _retention3(store, int(v["id"]))
            if r is not None:
                rets.append(r)
        rows.append({
            "label": label, "count": len(group),
            "avg_views": int(_mean([v["first7"] for v in group])),
            "engagement": round(_mean([v["engagement_rate"] for v in group]), 2),
            "conversion": round(_mean([v["conversion"] for v in group]), 2),
            "retention3": round(_mean(rets) * 100, 1) if rets else None,
            "bounce3": round((1 - _mean(rets)) * 100, 1) if rets else None,
            "platform": platform,
        })
    return rows


def _cadence(videos: list[dict], end: date, days: int) -> dict:
    dates = sorted(d for v in videos if v["published_date"] and
                   (d := _parse_day(v["published_date"])) and d <= end)
    recent = [d for d in dates if d >= end - timedelta(days=days)]
    if len(recent) >= 2:
        gaps = [(b - a).days for a, b in zip(recent, recent[1:])]
        avg_gap = _mean(gaps)
        sd = statistics.pstdev(gaps) if len(gaps) > 1 else 0
        consistency = _clamp(100 - sd * 4.5 - max(0, avg_gap - 7) * 3.0)
    else:
        gaps, avg_gap, sd, consistency = [], 0, 0, 20 if recent else 0
    weeks = max(1, days / 7)
    per_week = len(recent) / weeks
    weekday_counts = [sum(1 for d in recent if d.weekday() == i) for i in range(7)]
    best_weekday = max(range(7), key=lambda i: weekday_counts[i]) if recent else 0
    return {
        "uploads": len(recent), "per_week": round(per_week, 2),
        "avg_gap": round(avg_gap, 1), "gap_sd": round(sd, 1),
        "consistency": round(consistency, 0),
        "weekday_counts": weekday_counts, "best_weekday": WEEKDAYS[best_weekday],
        "recent_dates": [d.isoformat() for d in recent[-12:]],
        "advice": ("更新节奏稳定，保持当前频率即可。" if consistency >= 70 and per_week >= 1
                   else "更新间隔波动较大，固定 1-2 个发布日有助于算法建立预期。"),
    }


def _forecast(rows: list[dict], followers: int, days: int) -> dict:
    views = [float(r.get("views") or 0) for r in rows]
    if not views:
        return {"dates": [], "views": [], "lower": [], "upper": [], "followers": [],
                "r2": 0, "trend": "flat", "summary": "数据不足，暂时无法预测。"}
    recent_rows = rows[-28:]
    recent = [float(r.get("views") or 0) for r in recent_rows]
    slope, intercept, r2 = _linreg(recent)
    weekday = [0.0] * 7
    counts = [0] * 7
    for row, value in zip(recent_rows, recent):
        d = _parse_day(row.get("day", ""))
        idx = d.weekday() if d else 0
        weekday[idx] += value
        counts[idx] += 1
    overall = _mean(recent)
    factors = [w / c / overall if c and overall else 1 for w, c in zip(weekday, counts)]
    dates, forecast, lower, upper = [], [], [], []
    followers_series = []
    f = followers
    net_avg = _mean([float(r.get("followers_gained") or 0) - float(r.get("followers_lost") or 0) for r in rows[-14:]])
    for i in range(14):
        day = date.today() + timedelta(days=i + 1)
        base = max(0.0, intercept + slope * (len(recent) + i))
        pred = base * factors[day.weekday()]
        if overall > 0:
            pred = 0.65 * pred + 0.35 * overall
        dates.append(day.strftime("%m/%d"))
        forecast.append(int(pred))
        lower.append(int(pred * 0.78))
        upper.append(int(pred * 1.23))
        f += net_avg
        followers_series.append(int(f))
    trend = "up" if slope > overall * 0.005 else ("down" if slope < -overall * 0.005 else "flat")
    return {
        "dates": dates, "views": forecast, "lower": lower, "upper": upper,
        "followers": followers_series, "r2": round(r2, 3), "trend": trend,
        "summary": f"未来 14 天预计播放 {_fmt_num(sum(forecast))}，粉丝约 {_fmt_num(followers_series[-1])}（趋势：{'上升' if trend == 'up' else '下降' if trend == 'down' else '平稳'}）。",
    }


def _anomalies(rows: list[dict], videos: list[dict]) -> list[dict]:
    values = [float(r.get("views") or 0) for r in rows]
    if len(values) < 7:
        return []
    mean = _mean(values)
    sd = statistics.pstdev(values) if len(values) > 1 else 0
    if not sd:
        return []
    out = []
    for r, value in zip(rows, values):
        z = (value - mean) / sd
        if z >= 2.0:
            out.append({"date": r["day"], "views": int(value), "z": round(z, 2),
                        "type": "spike", "label": "流量峰值"})
    return sorted(out, key=lambda x: x["z"], reverse=True)[:5]


def _title_patterns(videos: list[dict]) -> list[dict]:
    if not videos:
        return []
    overall = _mean([v["first7"] for v in videos]) or 1
    labels = {
        "number": "带数字", "question": "疑问句", "bracket": "括号/分隔符", "emoji": "带 Emoji",
        "howto": "教程/指南", "challenge": "挑战/实测", "negative": "反常识/避坑",
    }
    rows = []
    for flag, label in labels.items():
        group = [v for v in videos if _feature_flags(v["title"], "bilibili")[flag]]
        if len(group) < 2:
            continue
        avg = _mean([v["first7"] for v in group])
        rows.append({
            "flag": flag, "label": label, "count": len(group),
            "avg_views": int(avg), "lift": round((avg / overall - 1) * 100, 1),
            "engagement": round(_mean([v["engagement_rate"] for v in group]), 2),
        })
    rows.sort(key=lambda r: r["lift"], reverse=True)
    return rows


def _tag_performance(videos: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for video in videos:
        for tag in video.get("tags", [])[:6]:
            groups.setdefault(str(tag), []).append(video)
    overall = _mean([v["first7"] for v in videos]) or 1
    rows = []
    for tag, group in groups.items():
        if len(group) < 2:
            continue
        avg = _mean([v["first7"] for v in group])
        rows.append({
            "tag": tag, "count": len(group), "avg_views": int(avg),
            "lift": round((avg / overall - 1) * 100, 1),
            "engagement": round(_mean([v["engagement_rate"] for v in group]), 2),
        })
    rows.sort(key=lambda r: r["avg_views"], reverse=True)
    return rows[:18]


def _health(account, kpis, engagement_rate, conversion, cadence, duration_rows,
            benchmark, platform) -> dict:
    growth_delta = next((k["delta"] for k in kpis if k["key"] == "net_followers"), 0)
    views_delta = next((k["delta"] for k in kpis if k["key"] == "views"), 0)
    growth = _clamp(52 + (views_delta or 0) * 0.22 + (growth_delta or 0) * 0.12)
    engagement = _clamp(45 + (engagement_rate / benchmark["engagement"]) * 40)
    conversion_score = _clamp(40 + (conversion / benchmark["conversion"]) * 42)
    cadence_score = _clamp(cadence.get("consistency", 0))
    rets = [d["retention3"] for d in duration_rows if d.get("retention3")]
    retention = _clamp(45 + (_mean(rets) / (benchmark["retention3"] * 100)) * 40) if rets else 52
    overall = round(growth * 0.24 + engagement * 0.2 + conversion_score * 0.2 +
                    cadence_score * 0.16 + retention * 0.2)
    grade = "S" if overall >= 88 else "A" if overall >= 78 else "B" if overall >= 66 else "C" if overall >= 52 else "D"
    return {
        "score": overall, "grade": grade,
        "subscores": [
            {"label": "增长动能", "value": round(growth), "weight": 24},
            {"label": "互动质量", "value": round(engagement), "weight": 20},
            {"label": "转粉效率", "value": round(conversion_score), "weight": 20},
            {"label": "更新稳定", "value": round(cadence_score), "weight": 16},
            {"label": "内容留存", "value": round(retention), "weight": 20},
        ],
        "verdict": ("账号处于强势上升期，建议趁势扩大选题矩阵。" if overall >= 80 else
                    "账号基本盘健康，优先补足短板指标。" if overall >= 65 else
                    "存在明显增长瓶颈，建议先聚焦留存与更新节奏。"),
    }


def _funnel(views: int, engagements: int, followers: int, impressions: int) -> list[dict]:
    rows = []
    if impressions:
        rows.append({"label": "曝光", "value": impressions, "rate": 100.0})
        rows.append({"label": "播放", "value": views, "rate": round(_safe_div(views, impressions) * 100, 2)})
    else:
        rows.append({"label": "播放", "value": views, "rate": 100.0})
    rows.append({"label": "互动", "value": engagements, "rate": round(_safe_div(engagements, views) * 100, 2)})
    rows.append({"label": "转粉", "value": max(0, followers), "rate": round(_safe_div(max(0, followers), views) * 100, 2)})
    return rows


def _source_view(row: dict) -> dict:
    return {"source": row["source"], "views": int(row["views"]),
            "watch_minutes": round(float(row.get("watch_minutes") or 0), 1)}


def _demographics(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["dimension"], []).append(
            {"name": row["bucket"], "value": float(row["value"])}
        )
    return grouped


# --------------------------------------------------------------------------- insights
def generate_insights(account, kpis, best_slots, duration_rows, tags, cadence, sources,
                      anomalies, top_videos, platform, benchmark, days) -> list[dict]:
    insights: list[dict] = []
    kpi = {k["key"]: k for k in kpis}
    net = kpi.get("net_followers", {})
    views_kpi = kpi.get("views", {})
    if net.get("value", 0) < 0:
        insights.append({
            "severity": "critical", "category": "增长", "title": "粉丝出现净流失",
            "body": f"本周期净增 {net['value']:+,}，取关量高于新增关注。先检查近期是否偏离账号主线或更新中断。",
            "metric": f"{net['value']:+,}", "action": "回看掉粉起点前后 3 条内容，恢复熟悉选题并减少跨区",
        })
    elif views_kpi.get("delta", 0) > 25:
        insights.append({
            "severity": "good", "category": "增长", "title": "播放进入加速区间",
            "body": f"周期播放较上期增长 {views_kpi['delta']:.1f}%，流量窗口正在打开。",
            "metric": f"{views_kpi['delta']:+.1f}%", "action": "保持更新频率，优先复用本期高播放选题的结构",
        })

    if best_slots:
        slot = best_slots[0]
        insights.append({
            "severity": "opportunity", "category": "发布策略", "title": f"黄金时段：{slot['label']}",
            "body": f"该时段样本 {slot['count']} 条，首 7 日播放较账号均值高 {slot['lift']:+.0f}%（置信度 {slot['confidence']}）。",
            "metric": slot["label"], "action": f"把重点稿件排到 {slot['label']}，提前 30 分钟发布预告",
        })

    ret_rows = [d for d in duration_rows if d.get("retention3")]
    if ret_rows:
        worst = min(ret_rows, key=lambda d: d["retention3"])
        best = max(ret_rows, key=lambda d: d["retention3"])
        if worst.get("bounce3") and worst["bounce3"] > 40:
            insights.append({
                "severity": "warning", "category": "留存", "title": f"{worst['label']} 前三秒流失偏高",
                "body": f"该时长段 3 秒跳出率约 {worst['bounce3']:.0f}%，高于健康线。开头可能缺少视觉钩子或信息承诺。",
                "metric": f"{worst['bounce3']:.0f}%", "action": "把结论/冲突画面前置到 0-3 秒，删掉寒暄和片头",
            })
        if best.get("retention3", 0) > benchmark["retention3"] * 100:
            insights.append({
                "severity": "good", "category": "留存", "title": f"{best['label']} 留存表现最佳",
                "body": f"3 秒留存约 {best['retention3']:.0f}%，是账号当前最健康的内容长度。",
                "metric": f"{best['retention3']:.0f}%", "action": f"未来两周优先测试 {best['label']} 的选题",
            })

    if tags:
        top_tag = tags[0]
        share = top_tag["count"] / max(1, sum(t["count"] for t in tags))
        if share > 0.38:
            insights.append({
                "severity": "warning", "category": "内容结构", "title": f"选题过度集中在「{top_tag['tag']}」",
                "body": f"该标签占近期样本 {share*100:.0f}%，虽然首 7 日播放较高，但账号抗风险能力下降。",
                "metric": f"{share*100:.0f}%", "action": "保留 60% 主线，拿出 20% 预算测试相邻选题",
            })
        insights.append({
            "severity": "opportunity", "category": "选题", "title": f"高潜标签「{top_tag['tag']}」",
            "body": f"该标签内容首 7 日播放均值 {_fmt_num(top_tag['avg_views'])}，相对大盘 {top_tag['lift']:+.0f}%。",
            "metric": top_tag["tag"], "action": "围绕该标签做 3 期系列化内容，统一封面视觉",
        })

    if cadence.get("avg_gap", 0) > 9:
        insights.append({
            "severity": "warning", "category": "更新", "title": "更新间隔偏长",
            "body": f"近期平均 {cadence['avg_gap']:.1f} 天发布一条，稳定性得分 {cadence['consistency']:.0f}/100。",
            "metric": f"{cadence['avg_gap']:.1f} 天", "action": "固定每周 2 个发布日，提前备好 2 条库存",
        })
    elif cadence.get("consistency", 0) >= 75:
        insights.append({
            "severity": "good", "category": "更新", "title": "更新节奏稳定",
            "body": f"平均 {cadence['avg_gap']:.1f} 天一条，节奏稳定性 {cadence['consistency']:.0f}/100。",
            "metric": f"{cadence['per_week']:.1f} 条/周", "action": "保持节奏，避免突然高频导致质量波动",
        })

    if sources:
        total = sum(s["views"] for s in sources) or 1
        top = max(sources, key=lambda s: s["views"])
        share = top["views"] / total * 100
        if share > 55:
            insights.append({
                "severity": "warning", "category": "流量", "title": f"流量过度依赖「{top['source']}」",
                "body": f"该来源占 {share:.0f}%，一旦推荐波动，播放会出现明显回撤。",
                "metric": f"{share:.0f}%", "action": "加强搜索关键词布局与站外分发，降低单一来源占比",
            })

    if top_videos:
        top = top_videos[0]
        if top.get("conversion", 0) > benchmark["conversion"] * 1.4:
            insights.append({
                "severity": "good", "category": "转化", "title": "出现高转粉样本",
                "body": f"《{top['title']}》转粉率 {top['conversion']:.2f}%，显著高于账号均值。",
                "metric": f"{top['conversion']:.2f}%", "action": "拆解其开场承诺、评论区运营与结尾引导，做成模板",
            })

    if anomalies:
        a = anomalies[0]
        insights.append({
            "severity": "opportunity", "category": "异常", "title": f"{a['date']} 出现流量峰值",
            "body": f"当日播放 {_fmt_num(a['views'])}，偏离均值 {a['z']:.1f} 个标准差，可能由单条爆款或站外传播触发。",
            "metric": f"Z={a['z']:.1f}", "action": "定位当日增长稿件，48 小时内发布同主题续集承接流量",
        })

    sev_order = {"critical": 0, "warning": 1, "opportunity": 2, "good": 3, "info": 4}
    insights.sort(key=lambda i: sev_order.get(i["severity"], 4))
    return insights[:10]


def ensure_insights(store: Store, account: dict, days: int = 30) -> list[dict]:
    dashboard = build_dashboard(store, account, days)
    store.replace_insights(int(account["id"]), dashboard["insights"])
    return dashboard["insights"]


# --------------------------------------------------------------------------- detail
def video_detail(store: Store, video_id: int) -> dict[str, Any] | None:
    video = store.get_video(video_id)
    if not video:
        return None
    account = store.get_account(int(video["account_id"]))
    snaps = store.video_snapshots(video_id)
    points = store.retention(video_id)
    comments = store.comments(video_id)
    stats = video["stats"]
    views = max(1, int(stats.get("views", 0) or 0))
    eng = sum(int(stats.get(k, 0) or 0) for k in ("likes", "coins", "favorites", "comments", "shares", "danmaku"))
    published = _parse_day(video.get("published_at", ""))
    age_days = (date.today() - published).days if published else 0
    all_videos = store.videos(int(video["account_id"]))
    metrics = []
    for v in all_videos:
        s = v.get("stats") or {}
        vv = max(1, int(s.get("views", 0) or 0))
        ee = sum(int(s.get(k, 0) or 0) for k in ("likes", "coins", "favorites", "comments", "shares", "danmaku"))
        metrics.append({
            "views": int(s.get("views", 0) or 0), "engagement": ee / vv * 100,
            "conversion": _safe_div(int(s.get("followers_gained", 0) or 0), vv) * 100,
        })
    views_sorted = sorted(m["views"] for m in metrics)
    eng_sorted = sorted(m["engagement"] for m in metrics)
    conv_sorted = sorted(m["conversion"] for m in metrics)
    ret3 = _retention3(store, video_id)

    def percentile(sorted_values: list[float], value: float) -> float:
        if not sorted_values:
            return 0.0
        below = sum(1 for x in sorted_values if x <= value)
        return round(below / len(sorted_values) * 100, 0)

    suggestion = []
    if ret3 is not None and ret3 < 0.62:
        suggestion.append({"tag": "开场", "text": "前 3 秒留存偏低：删除片头/寒暄，先给冲突画面或最终结果。"})
    if ret3 is not None and ret3 >= 0.72:
        suggestion.append({"tag": "优势", "text": "开场钩子有效，可将这一开场结构固化为模板。"})
    if age_days > 30 and int(stats.get("views", 0)) < 5000:
        suggestion.append({"tag": "冷启动", "text": "发布 30 天后播放仍偏低，建议换封面/标题，并在相关旧稿评论区做二次分发。"})
    if eng / views * 100 > 8:
        suggestion.append({"tag": "互动", "text": "互动率高于账号均值，可在评论区置顶一个可讨论的问题，延长流量生命周期。"})
    if int(stats.get("favorites", 0) or 0) / views > 0.04:
        suggestion.append({"tag": "收藏", "text": "收藏率突出，适合做系列化教程或资料合集，提升长尾搜索。"})
    if not suggestion:
        suggestion.append({"tag": "稳健", "text": "各项指标处于正常区间，优先复用本期选题结构与封面风格。"})

    first7 = _video_first7(video, snaps, date.today())
    return {
        "video": {
            "id": video["id"], "vid": video["vid"], "title": video["title"],
            "cover": video.get("cover", ""), "url": video.get("url", ""),
            "published_at": video.get("published_at", ""), "duration": video.get("duration", 0),
            "category": video.get("category", ""), "tags": video.get("tags", []),
            "description": video.get("description", ""), "platform": account["platform"] if account else "",
            "account_name": account["name"] if account else "",
        },
        "stats": {**stats, "engagement_rate": round(eng / views * 100, 2),
                  "conversion": round(_safe_div(int(stats.get("followers_gained", 0) or 0), views) * 100, 2),
                  "first7": int(first7)},
        "snapshots": snaps,
        "retention": points,
        "retention3": round(ret3 * 100, 1) if ret3 is not None else None,
        "bounce3": round((1 - ret3) * 100, 1) if ret3 is not None else None,
        "retention_source": points[0]["source"] if points else "",
        "comments": comments,
        "sentiment": {
            "positive": sum(1 for c in comments if c["sentiment"] > 0.1),
            "neutral": sum(1 for c in comments if -0.1 <= c["sentiment"] <= 0.1),
            "negative": sum(1 for c in comments if c["sentiment"] < -0.1),
        },
        "percentiles": {
            "views": percentile(views_sorted, int(stats.get("views", 0) or 0)),
            "engagement": percentile(eng_sorted, eng / views * 100),
            "conversion": percentile(conv_sorted, _safe_div(int(stats.get("followers_gained", 0) or 0), views) * 100),
            "retention": percentile([0.5, 0.6, 0.7], ret3 or 0) if ret3 else 0,
        },
        "suggestions": suggestion,
        "age_days": age_days,
    }


# --------------------------------------------------------------------------- pages
def video_table(store: Store, account: dict, days: int = 90) -> dict:
    start, end = _range(days)
    videos = store.videos(int(account["id"]))
    all_snaps = store.all_video_snapshots(int(account["id"]))
    rows = [_video_period_metrics(v, all_snaps.get(int(v["id"]), []), start, end, today=end)
            for v in videos]
    for row in rows:
        row["retention3"] = _retention3(store, int(row["id"]))
    rows.sort(key=lambda r: r["published_date"] or "", reverse=True)
    return {
        "videos": rows,
        "categories": sorted({r["category"] for r in rows if r["category"]}),
        "tags": sorted({tag for r in rows for tag in r["tags"]})[:50],
    }


def growth_page(store: Store, account: dict, days: int = 90) -> dict:
    dash = build_dashboard(store, account, days)
    series = dash["series"]
    followers = [s["followers"] for s in series]
    net = [s["net_followers"] for s in series]
    current_followers = followers[-1] if followers else int(account.get("followers") or 0)
    step = 10_000 if current_followers < 200_000 else 50_000 if current_followers < 1_000_000 else 100_000
    next_target = (current_followers // step + 1) * step
    milestones = []
    for i in range(4):
        target = next_target + i * step
        milestones.append({
            "target": target, "date": "", "reached": False,
            "progress": round(current_followers / target * 100, 1),
            "remaining": max(0, target - current_followers),
        })
    weekday = [0] * 7
    for s in series:
        weekday[datetime.fromisoformat(s["date"]).weekday()] += s["net_followers"]
    return {
        "series": series,
        "milestones": milestones,
        "weekday_growth": [{"label": WEEKDAYS[i], "value": weekday[i]} for i in range(7)],
        "forecast": dash["forecast"],
        "kpis": dash["kpis"],
        "health": dash["health"],
        "top_videos": sorted(dash["top_videos"], key=lambda v: v["period_followers"], reverse=True)[:8],
        "summary": dash["summary"],
        "platform_note": dash["platform_note"],
    }


def traffic_page(store: Store, account: dict, days: int = 30) -> dict:
    dash = build_dashboard(store, account, days)
    sources = dash["sources"]
    total = sum(s["views"] for s in sources) or 1
    for s in sources:
        s["share"] = round(s["views"] / total * 100, 1)
    demographics = dash["demographics"]
    concentration = round(sum((s["views"] / total) ** 2 for s in sources) * 10000, 0) if sources else 0
    return {
        "sources": sources, "demographics": demographics,
        "concentration": concentration,
        "diversity": "集中" if concentration > 2800 else ("适中" if concentration > 1800 else "分散"),
        "insights": [i for i in dash["insights"] if i["category"] in ("流量", "增长")],
        "kpis": dash["kpis"],
        "platform_note": dash["platform_note"],
    }


def retention_page(store: Store, account: dict, days: int = 90) -> dict:
    videos = store.videos(int(account["id"]))
    rows = []
    curves = []
    for video in videos:
        points = store.retention(int(video["id"]))
        if not points:
            continue
        r3 = _retention3(store, int(video["id"]))
        stats = video.get("stats") or {}
        views = max(1, int(stats.get("views", 0) or 0))
        rows.append({
            "id": video["id"], "title": video["title"], "duration": video.get("duration", 0),
            "retention3": round((r3 or 0) * 100, 1),
            "bounce3": round((1 - (r3 or 0)) * 100, 1),
            "views": int(stats.get("views", 0) or 0),
            "conversion": round(_safe_div(int(stats.get("followers_gained", 0) or 0), views) * 100, 2),
            "engagement": round(_safe_div(sum(int(stats.get(k, 0) or 0) for k in
                                              ("likes", "coins", "favorites", "comments", "shares", "danmaku")), views) * 100, 2),
            "published_at": video.get("published_at", ""),
        })
        if len(curves) < 10:
            curves.append({"id": video["id"], "title": video["title"], "points": points})
    rows.sort(key=lambda r: r["retention3"], reverse=True)
    avg_curve = []
    if curves:
        for i in range(31):
            vals = []
            for c in curves:
                if i < len(c["points"]):
                    vals.append(float(c["points"][i]["audience_ratio"]))
            avg_curve.append(round(_mean(vals) * 100, 2))
    avg3 = _mean([r["retention3"] for r in rows]) if rows else 0
    return {
        "videos": rows, "curves": curves, "avg_curve": avg_curve,
        "avg_retention3": round(avg3, 1), "avg_bounce3": round(100 - avg3, 1),
        "source": "model" if account["platform"] == "bilibili" else "platform",
        "note": ("B 站未公开逐秒留存接口，此页根据播放、互动、时长与完播代理变量建立估算模型，"
                 "用于相对比较，不等同于创作中心后台绝对值。" if account["platform"] == "bilibili"
                 else "YouTube Analytics 提供的真实受众留存曲线，按视频时长比例采样。"),
        "buckets": _retention_buckets(rows),
    }


def _retention_buckets(rows: list[dict]) -> list[dict]:
    buckets = [
        ("高留存 (≥80%)", 80, 101), ("健康 (72-80%)", 72, 80),
        ("待优化 (66-72%)", 66, 72), ("高风险 (<66%)", 0, 66),
    ]
    out = []
    for label, low, high in buckets:
        group = [r for r in rows if low <= r["retention3"] < high]
        out.append({"label": label, "count": len(group),
                    "avg_conversion": round(_mean([r["conversion"] for r in group]), 2) if group else 0,
                    "avg_views": int(_mean([r["views"] for r in group])) if group else 0})
    return out


def lab_page(store: Store, account: dict, days: int = 90) -> dict:
    dash = build_dashboard(store, account, days)
    return {
        "title_patterns": dash["title_patterns"],
        "tags": dash["tags"],
        "best_slots": dash["best_slots"][:4],
        "top_videos": dash["top_videos"][:5],
        "duration": dash["duration"],
        "keywords": _keyword_cloud(dash["top_videos"] + store.videos(int(account["id"]))[:80]),
        "benchmarks": BENCHMARKS.get(account["platform"], BENCHMARKS["bilibili"]),
    }


def _keyword_cloud(videos: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    stops = {"一个", "这个", "什么", "怎么", "为什么", "我们", "他们", "可以", "没有", "the", "and",
             "for", "with", "that", "this", "your", "you", "its", "from", "how", "why", "what"}
    for video in videos:
        title = video["title"]
        for token in re.findall(r"[\u4e00-\u9fa5]{2,4}|[A-Za-z]{3,}", title):
            token = token.lower()
            if token in stops:
                continue
            counts[token] = counts.get(token, 0) + 1
    rows = [{"name": k, "value": v} for k, v in counts.items() if v >= 2]
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows[:36]


def analyze_title(store: Store, account: dict, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        return {"score": 0, "error": "请输入标题"}
    platform = account["platform"]
    videos = store.videos(int(account["id"]))
    dash = build_dashboard(store, account, 90)
    patterns = {p["flag"]: p for p in dash["title_patterns"]}
    flags = _feature_flags(title, platform)
    overall = _mean([v["first7"] for v in dash["top_videos"]]) or 1
    score = 52
    reasons = []
    for flag, active in flags.items():
        if not active:
            continue
        pattern = patterns.get(flag)
        if pattern:
            score += max(-6, min(9, pattern["lift"] * 0.10))
            reasons.append(f"{pattern['label']}：历史 {pattern['count']} 条样本，首 7 日播放 {pattern['lift']:+.0f}%")
        else:
            score += 2
    length = len(title)
    if 12 <= length <= 28:
        score += 7
        reasons.append("长度处于高点击区间（12-28 字）")
    elif length > 34:
        score -= 6
        reasons.append("标题偏长，移动端可能被截断")
    elif length < 8:
        score -= 4
        reasons.append("信息量偏少，缺少具体承诺")
    if re.search(r"\d", title):
        score += 3
    if re.search(r"[\U0001F300-\U0001FAFF]", title):
        score += 1
    suggestions = []
    if not flags["number"]:
        suggestions.append("加入具体数字（如「3 个方法」「48 小时」「100 元」）提升可信度。")
    if not flags["challenge"] and not flags["howto"]:
        suggestions.append("补充结果或方法承诺，让用户一眼知道能获得什么。")
    if flags["bracket"]:
        suggestions.append("括号信息靠后时，试试把核心冲突放到最前面。")
    if len(title) > 30:
        suggestions.append("尝试压缩到 26 字以内，把关键词前置。")
    benchmark = BENCHMARKS.get(platform, BENCHMARKS["bilibili"])
    predicted = int(overall * max(0.4, min(2.5, score / 62)))
    return {
        "title": title, "score": int(_clamp(score, 0, 100)),
        "grade": "S" if score >= 86 else "A" if score >= 76 else "B" if score >= 64 else "C",
        "predicted_views": predicted, "predicted_label": _fmt_num(predicted),
        "reasons": reasons[:6], "suggestions": suggestions[:5],
        "benchmark": benchmark,
        "features": flags,
    }
