"""分析引擎：把 Dataset 转换为各个分析模块的结果（数据 + 结论 + 建议）。

每个模块返回 dict：{"ok": bool, "insights": [str], ...数据}。
数据不足时 ok=False 并在 insights 说明原因，界面据此显示提示而不是空图。
"""
import math
from collections import Counter
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import textutil
from .storage import Dataset

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
HOUR_BLOCKS = [(0, 3), (3, 6), (6, 9), (9, 12), (12, 15), (15, 18), (18, 21), (21, 24)]
DUR_EDGES = [0, 60, 180, 300, 600, 1200, 1800, float("inf")]
DUR_LABELS = ["<1分钟", "1-3分钟", "3-5分钟", "5-10分钟", "10-20分钟", "20-30分钟", ">30分钟"]
MATURE_DAYS = 7
INTERACTION_COLS = ["likes", "coins", "favorites", "comments", "shares", "danmaku"]
RATE_NAMES = {"likes": "点赞率", "coins": "投币率", "favorites": "收藏率", "comments": "评论率",
              "shares": "分享率", "danmaku": "弹幕率"}


# ---------------------------------------------------------------- 格式化工具
def fnum(x, digits=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    x = float(x)
    if abs(x) >= 1e8:
        return f"{x / 1e8:.{digits}f}亿"
    if abs(x) >= 1e4:
        return f"{x / 1e4:.{digits}f}万"
    return f"{x:,.0f}" if abs(x) >= 100 or x == int(x) else f"{x:.{digits}f}"


def fpct(x, digits=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x * 100:.{digits}f}%"


def fdur(sec):
    if sec is None or (isinstance(sec, float) and math.isnan(sec)):
        return "—"
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def _has(df, col):
    return col in df.columns and df[col].notna().sum() > 0


def _shrink(values: pd.Series, k=3.0):
    """小样本收缩：样本越少越接近 1，避免 1 个视频决定结论。"""
    n = values.count() if hasattr(values, "count") else len(values)
    med = values.median()
    return (n * med + k * 1.0) / (n + k) if n else 1.0


# ---------------------------------------------------------------- 预处理
def prepare(ds: Dataset) -> pd.DataFrame:
    df = ds.videos.copy()
    if df.empty:
        return df
    df = df[df["publish_time"].notna()].copy()
    now = datetime.now()
    df["age_days"] = ((now - df["publish_time"]).dt.total_seconds() / 86400).clip(lower=0.25)
    df["mature"] = df["age_days"] >= MATURE_DAYS
    df["weekday"] = df["publish_time"].dt.weekday
    df["hour"] = df["publish_time"].dt.hour
    df["hour_block"] = df["hour"] // 3
    df["dur_min"] = df["duration"] / 60
    df["dur_bucket"] = pd.cut(df["duration"].fillna(0), DUR_EDGES, labels=DUR_LABELS, right=False)
    df["views"] = df["views"].fillna(0)
    avail = [c for c in INTERACTION_COLS if _has(df, c)]
    df["interactions"] = df[avail].fillna(0).sum(axis=1) if avail else np.nan
    v = df["views"].replace(0, np.nan)
    df["engagement_rate"] = df["interactions"] / v
    for c in avail:
        df[f"{c}_rate"] = df[c] / v
    if {"likes", "coins", "favorites"} <= set(avail):
        df["triple_rate"] = (df["likes"] + df["coins"] + df["favorites"]) / v
    df["subs_per_1k"] = df["subs_gained"] / v * 1000
    df["net_subs"] = df["subs_gained"] - df["subs_lost"].fillna(0)
    df["views_per_day"] = df["views"] / df["age_days"]
    df["title_len"] = df["title"].astype(str).str.len()

    # 表现指数：与发布时间相邻的成熟稿件中位数相比，抵消账号成长与播放累积时间的影响
    df = df.sort_values("publish_time").reset_index(drop=True)
    mature = df[df["mature"]]
    base = mature["views"].rolling(15, center=True, min_periods=3).median()
    df["baseline"] = np.nan
    df.loc[mature.index, "baseline"] = base
    df["baseline"] = df["baseline"].ffill().bfill()
    if df["baseline"].isna().all():
        df["baseline"] = df["views"].median()
    df["perf_index"] = np.where(df["mature"], df["views"] / df["baseline"].replace(0, np.nan), np.nan)
    return df.sort_values("publish_time", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- 时间序列
def follower_series(ds: Dataset) -> pd.Series:
    s = ds.account_snaps.dropna(subset=["followers"])
    if len(s) >= 2:
        ser = s.set_index("ts")["followers"].resample("D").last().dropna()
        if len(ser) >= 2:
            return ser
    d = ds.daily
    if not d.empty and "subs_gained" in d.columns and len(s):
        net = (d["subs_gained"].fillna(0) - d.get("subs_lost", pd.Series(0, index=d.index)).fillna(0))
        net.index = d["date"]
        latest = s["followers"].iloc[-1]
        back = net[::-1].cumsum()[::-1].shift(-1).fillna(0)
        return (latest - back).astype(float)
    return pd.Series(dtype=float)


def daily_views_series(ds: Dataset) -> pd.Series:
    d = ds.daily
    if not d.empty and "views" in d.columns and d["views"].notna().sum() >= 3:
        return d.set_index("date")["views"].dropna()
    vs = ds.video_snaps.dropna(subset=["views"])
    if vs.empty:
        return pd.Series(dtype=float)
    vs = vs.assign(day=vs["ts"].dt.floor("D"))
    latest = vs.sort_values("ts").groupby(["day", "video_id"])["views"].last().unstack().ffill()
    total = latest.sum(axis=1)
    diff = total.diff().dropna()
    gaps = pd.Series(total.index, index=total.index).diff().dt.days.dropna()
    return (diff / gaps.reindex(diff.index)).clip(lower=0)


# ---------------------------------------------------------------- 各模块
def overview(ds, df):
    out = {"ok": not df.empty, "insights": [], "kpis": []}
    if df.empty:
        out["insights"].append("还没有稿件数据。请登录账号后点击“刷新数据”，或先加载演示数据体验。")
        return out
    fol = follower_series(ds)
    followers = fol.iloc[-1] if len(fol) else (ds.account_snaps["followers"].dropna().iloc[-1]
                                               if ds.account_snaps["followers"].notna().any() else np.nan)

    def change(days):
        if len(fol) < 2:
            return np.nan
        past = fol[fol.index <= fol.index[-1] - pd.Timedelta(days=days)]
        return fol.iloc[-1] - (past.iloc[-1] if len(past) else fol.iloc[0])

    now = datetime.now()
    recent = df[df["publish_time"] >= now - timedelta(days=90)]
    k = out["kpis"]
    k.append(("粉丝数", fnum(followers), f"近7天 {fnum(change(7))} / 近30天 {fnum(change(30))}"))
    k.append(("总播放", fnum(df["views"].sum()), f"共 {len(df)} 个稿件"))
    k.append(("平均播放", fnum(df["views"].mean()), f"中位数 {fnum(df['views'].median())}"))
    k.append(("互动率", fpct(df["engagement_rate"].median()), "互动总数 / 播放（中位数）"))
    if _has(df, "avg_view_pct"):
        k.append(("平均完播率", fpct(df["avg_view_pct"].mean()), f"平均观看 {fdur(df['avg_view_duration'].mean())}"))
    if _has(df, "subs_per_1k"):
        k.append(("千次播放涨粉", f"{df['subs_per_1k'].median():.2f}", f"累计涨粉 {fnum(df['subs_gained'].sum())}"))
    if _has(df, "bounce_3s"):
        k.append(("3秒跳出率", fpct(df["bounce_3s"].mean()), "越低越好"))
    k.append(("近90天更新", f"{len(recent)} 个", f"约 {len(recent) / 12.9:.1f} 个/周"))
    last = df["publish_time"].max()
    k.append(("最近投稿", last.strftime("%m-%d %H:%M"), f"{(now - last).days} 天前"))

    m = df[df["mature"]]
    cur = m[m["publish_time"] >= now - timedelta(days=37)]
    prev = m[(m["publish_time"] < now - timedelta(days=37)) & (m["publish_time"] >= now - timedelta(days=67))]
    if len(cur) >= 2 and len(prev) >= 2:
        ratio = cur["views"].median() / max(prev["views"].median(), 1) - 1
        word = "上升" if ratio > 0 else "下降"
        out["insights"].append(f"近30天发布的稿件中位播放较前30天{word} {abs(ratio) * 100:.0f}%"
                               f"（{fnum(cur['views'].median())} vs {fnum(prev['views'].median())}）。")
    c30 = change(30)
    if not np.isnan(c30) and followers and followers > 0:
        out["insights"].append(f"近30天粉丝净增长 {fnum(c30)}，增速 {c30 / max(followers - c30, 1) * 100:.2f}%。")
    if (now - last).days > 14:
        out["insights"].append(f"已经 {(now - last).days} 天没有更新，长期断更会降低推荐权重和粉丝黏性。")
    top = df.nlargest(1, "views").iloc[0]
    out["insights"].append(f"播放最高的稿件是《{top['title']}》，播放 {fnum(top['views'])}。")
    return out


def growth(ds, df):
    out = {"ok": False, "insights": []}
    fol = follower_series(ds)
    views = daily_views_series(ds)
    out["followers"], out["daily_views"] = fol, views
    if not ds.daily.empty and "subs_gained" in ds.daily.columns:
        d = ds.daily.set_index("date")
        out["subs_gained"] = d["subs_gained"]
        out["subs_lost"] = d.get("subs_lost")
    if len(fol) >= 3:
        out["ok"] = True
        recent = fol.iloc[-30:]
        x = (recent.index - recent.index[0]).days.values.astype(float)
        slope, _ = np.polyfit(x, recent.values, 1)
        future_idx = pd.date_range(recent.index[-1] + pd.Timedelta(days=1), periods=30, freq="D")
        out["forecast"] = pd.Series(recent.iloc[-1] + slope * np.arange(1, 31), index=future_idx)
        cur = fol.iloc[-1]
        out["insights"].append(f"按近 {len(recent)} 天趋势，粉丝日均净增约 {slope:.1f}，"
                               f"预计 30 天后达到 {fnum(out['forecast'].iloc[-1])}。")
        milestones = [1e3, 5e3, 1e4, 3e4, 5e4, 1e5, 2e5, 5e5, 1e6, 2e6, 5e6, 1e7]
        nxt = next((m for m in milestones if m > cur), None)
        if nxt and slope > 0:
            days = (nxt - cur) / slope
            out["insights"].append(f"距离下一个里程碑 {fnum(nxt)} 粉还差 {fnum(nxt - cur)}，"
                                   f"按当前速度约需 {days:.0f} 天（{(datetime.now() + timedelta(days=days)):%Y-%m-%d}）。")
        elif slope <= 0:
            out["insights"].append("近期粉丝净增长为负或停滞，建议优先排查掉粉原因（内容方向变化、断更、争议内容）。")
    if len(views) >= 7:
        out["ok"] = True
        last7, prev7 = views.iloc[-7:].sum(), views.iloc[-14:-7].sum()
        if prev7 > 0:
            out["insights"].append(f"近7天总播放 {fnum(last7)}，环比 {'+' if last7 >= prev7 else ''}{(last7 / prev7 - 1) * 100:.0f}%。")
        wd = views.groupby(views.index.dayofweek).mean()
        if len(wd) == 7:
            out["insights"].append(f"账号整体播放在{WEEKDAYS[int(wd.idxmax())]}最高、{WEEKDAYS[int(wd.idxmin())]}最低，"
                                   "可把重点内容安排在高峰日之前 1 天发布以吃满流量。")
    if not out["ok"]:
        out["insights"].append("趋势数据不足：每次刷新都会保存一次快照，开启“自动监控”后数据会自动积累。")
    return out


def timing(ds, df):
    out = {"ok": False, "insights": []}
    m = df[df["mature"] & df["perf_index"].notna()]
    if len(m) < 6:
        out["insights"].append("成熟稿件（发布满7天）少于 6 个，暂不足以分析最佳投稿时间。")
        return out
    out["ok"] = True
    grid = m.pivot_table(index="weekday", columns="hour_block", values="perf_index", aggfunc="median")
    cnt = m.pivot_table(index="weekday", columns="hour_block", values="perf_index", aggfunc="count")
    out["heat"] = grid.reindex(index=range(7), columns=range(8))
    out["heat_count"] = cnt.reindex(index=range(7), columns=range(8)).fillna(0)
    out["by_hour"] = m.groupby("hour")["perf_index"].agg(["median", "count"]).reindex(range(24))
    out["by_weekday"] = m.groupby("weekday")["perf_index"].agg(["median", "count"]).reindex(range(7))

    cells = []
    min_n = 3 if len(m) >= 40 else 2
    for (wd, hb), g in m.groupby(["weekday", "hour_block"]):
        if len(g) >= min_n:
            cells.append((_shrink(g["perf_index"], k=4), wd, hb, len(g), g["perf_index"].median()))
    cells.sort(reverse=True)
    out["best_slots"] = []
    for score, wd, hb, n, med in cells[:3]:
        a, b = HOUR_BLOCKS[hb]
        label = f"{WEEKDAYS[wd]} {a:02d}:00-{b:02d}:00"
        out["best_slots"].append((label, med, n))
    if out["best_slots"]:
        txt = "；".join(f"{l}（表现 {v:.2f}x，样本 {n}）" for l, v, n in out["best_slots"])
        out["insights"].append(f"最佳投稿时段 Top3：{txt}。")
    hours = m.groupby("hour")["perf_index"].agg(["median", "count"])
    hours = hours[hours["count"] >= min_n]
    if len(hours):
        h = int(hours.apply(lambda r: (r["count"] * r["median"] + 4) / (r["count"] + 4), axis=1).idxmax())
        out["insights"].append(f"按小时看，{h}:00 前后发布的稿件表现最好（中位表现 {hours.loc[h, 'median']:.2f}x，样本 {int(hours.loc[h, 'count'])}）。"
                               f"建议比高峰提前 30-60 分钟发布，给审核与首轮推荐留出时间。")
        out["best_hour"] = h
    wk = m.groupby(m["weekday"] >= 5)["perf_index"].median()
    if len(wk) == 2:
        diff = wk[True] / wk[False] - 1
        out["insights"].append(f"周末发布比工作日{'高' if diff > 0 else '低'} {abs(diff) * 100:.0f}%。")
    worst = cells[-1:] if len(cells) > 3 else []
    for score, wd, hb, n, med in worst:
        a, b = HOUR_BLOCKS[hb]
        out["insights"].append(f"表现最弱的时段是 {WEEKDAYS[wd]} {a:02d}:00-{b:02d}:00（{med:.2f}x），尽量避开。")
    used = m["hour_block"].value_counts(normalize=True)
    if len(used) and used.iloc[0] > 0.6:
        out["insights"].append("你的投稿时间非常集中，其他时段样本太少，可以有计划地测试 2-3 个新时段。")
    return out


def duration(ds, df):
    out = {"ok": False, "insights": []}
    m = df[df["mature"] & df["duration"].notna()]
    if len(m) < 5:
        out["insights"].append("成熟稿件不足，暂无法分析时长。")
        return out
    out["ok"] = True
    agg = {"views": ["count", "median"], "perf_index": "median", "engagement_rate": "median"}
    for c in ("avg_view_pct", "bounce_3s", "subs_per_1k", "avg_view_duration", "ctr"):
        if _has(m, c):
            agg[c] = "mean"
    t = m.groupby("dur_bucket", observed=True).agg(agg)
    t.columns = ["数量" if c == ("views", "count") else c[0] for c in t.columns]
    t = t.rename(columns={"views": "播放中位数", "perf_index": "表现指数", "engagement_rate": "互动率",
                          "avg_view_pct": "完播率", "bounce_3s": "3秒跳出率", "subs_per_1k": "千播涨粉",
                          "avg_view_duration": "平均观看时长", "ctr": "点击率"})
    out["table"] = t
    out["scatter"] = m[["duration", "views", "avg_view_pct", "subs_per_1k", "bounce_3s", "title"]]
    valid = t[t["数量"] >= (3 if len(m) >= 30 else 2)]
    if len(valid):
        shrunk = (valid["数量"] * valid["表现指数"] + 4) / (valid["数量"] + 4)
        best = shrunk.idxmax()
        out["insights"].append(f"播放表现最好的时长区间是「{best}」（表现 {valid.loc[best, '表现指数']:.2f}x，"
                               f"{int(valid.loc[best, '数量'])} 个样本）。")
        out["best_bucket"] = best
        if "千播涨粉" in valid.columns and valid["千播涨粉"].notna().any():
            bc = valid["千播涨粉"].idxmax()
            out["insights"].append(f"转粉效率最高的是「{bc}」视频，每千次播放涨粉 {valid.loc[bc, '千播涨粉']:.2f}，"
                                   f"是最低区间的 {valid.loc[bc, '千播涨粉'] / max(valid['千播涨粉'].min(), 1e-6):.1f} 倍。")
        if "完播率" in valid.columns and valid["完播率"].notna().any():
            corr = m[["duration", "avg_view_pct"]].dropna().corr().iloc[0, 1]
            out["insights"].append(f"时长与完播率相关系数 {corr:.2f}："
                                   + ("视频越长完播率越低，属正常规律；长视频需加强章节结构与节奏。" if corr < -0.3
                                      else "完播率受时长影响不大，内容本身的吸引力更关键。"))
        if "3秒跳出率" in valid.columns and valid["3秒跳出率"].notna().any():
            bb = valid["3秒跳出率"].idxmax()
            out["insights"].append(f"「{bb}」视频的 3 秒跳出率最高（{fpct(valid.loc[bb, '3秒跳出率'])}），"
                                   "这类视频的开头需要更快进入主题。")
    share = m["dur_bucket"].value_counts(normalize=True)
    if len(share):
        out["insights"].append(f"你最常做的时长是「{share.idxmax()}」（占 {share.max() * 100:.0f}%）。")
    return out


def engagement(ds, df):
    out = {"ok": False, "insights": []}
    m = df[df["views"] > 0]
    rates = {RATE_NAMES[c]: m[f"{c}_rate"].median() for c in INTERACTION_COLS if f"{c}_rate" in m.columns}
    if not rates:
        out["insights"].append("没有互动数据。")
        return out
    out["ok"] = True
    out["rates"] = rates
    out["per_video"] = m[["title", "views", "engagement_rate"] + [f"{c}_rate" for c in INTERACTION_COLS
                                                                  if f"{c}_rate" in m.columns]]
    # 互动随时间
    t = m.sort_values("publish_time").set_index("publish_time")
    out["trend"] = t["engagement_rate"].rolling(5, min_periods=2).median()
    if "triple_rate" in m.columns:
        out["insights"].append(f"三连率（(赞+币+藏)/播放）中位数 {fpct(m['triple_rate'].median(), 2)}。")
    if "coins_rate" in m.columns and "likes_rate" in m.columns:
        cl = (m["coins"] / m["likes"].replace(0, np.nan)).median()
        out["insights"].append(f"币赞比 {cl:.2f}：" + ("观众认可度高，内容具有“值得投币”的稀缺性。" if cl > 0.3
                                                       else "投币偏少，可在结尾用具体理由引导投币（如：做这期花了XX小时）。"))
    if "favorites_rate" in m.columns and "likes_rate" in m.columns:
        fl = (m["favorites"] / m["likes"].replace(0, np.nan)).median()
        out["insights"].append(f"藏赞比 {fl:.2f}：" + ("收藏意愿强，说明内容有“以后还要用”的工具价值，适合做系列化。" if fl > 0.5
                                                       else "收藏偏低，可增加清单、模板、步骤总结等可复用信息。"))
    if "comments_rate" in m.columns:
        out["insights"].append(f"评论率中位数 {fpct(m['comments_rate'].median(), 2)}；在视频中抛出具体问题、"
                               "置顶引导评论能显著提升讨论度，评论区活跃也会提升推荐权重。")
    if "shares_rate" in m.columns:
        top_share = m.nlargest(1, "shares_rate").iloc[0]
        out["insights"].append(f"分享率最高的是《{top_share['title']}》（{fpct(top_share['shares_rate'], 2)}），"
                               "高分享内容往往有“社交货币”属性，值得复刻选题。")
    corr = m[["engagement_rate", "perf_index"]].dropna()
    if len(corr) >= 8:
        c = corr.corr().iloc[0, 1]
        out["insights"].append(f"互动率与播放表现相关系数 {c:.2f}，"
                               + ("互动越高的视频越容易被推荐放大。" if c > 0.2 else "两者关联较弱，播放更多取决于选题与封面标题。"))
    if len(out["trend"].dropna()) >= 6:
        tr = out["trend"].dropna()
        delta = tr.iloc[-3:].mean() / max(tr.iloc[:3].mean(), 1e-9) - 1
        out["insights"].append(f"互动率长期趋势：{'上升' if delta > 0 else '下降'} {abs(delta) * 100:.0f}%（最近 vs 最早）。")
    return out


def _curve_stats(curve):
    arr = np.array(curve, dtype=float)
    x, y = arr[:, 0], arr[:, 1]
    if len(y) < 5:
        return None
    ys = pd.Series(y).rolling(3, center=True, min_periods=1).mean().values
    slope = np.diff(ys)
    body = slope[int(len(slope) * 0.1):int(len(slope) * 0.9)]
    drop_i = int(np.argmin(body)) + int(len(slope) * 0.1) if len(body) else 0
    peaks = [i for i in range(2, len(ys) - 2) if ys[i] > ys[i - 2] * 1.02 and ys[i] > ys[i + 2] * 1.02]
    return {
        "start": float(ys[0]),
        "at10": float(np.interp(0.1, x, ys)),
        "at50": float(np.interp(0.5, x, ys)),
        "end": float(ys[-1]),
        "steepest_at": float(x[drop_i]),
        "steepest_drop": float(-slope[drop_i]) if len(slope) else 0,
        "rewatch_peaks": [float(x[i]) for i in peaks][:3],
        "x": x, "y": ys,
    }


def retention(ds, df):
    out = {"ok": False, "insights": [], "curves": {}, "suggestions": []}
    titles = dict(zip(df["video_id"], df["title"]))
    durs = dict(zip(df["video_id"], df["duration"]))
    for vid, curve in (ds.retention or {}).items():
        st = _curve_stats(curve)
        if st and vid in titles:
            st["title"], st["duration"] = titles[vid], durs.get(vid)
            out["curves"][vid] = st
    has_pct = _has(df, "avg_view_pct")
    if not out["curves"] and not has_pct and not _has(df, "bounce_3s"):
        out["insights"].append("暂无留存/完播数据。YouTube 登录后自动获取；B站可通过“导入后台数据”导入创作中心表格。")
        return out
    out["ok"] = True
    if has_pct:
        m = df.dropna(subset=["avg_view_pct", "duration"])
        m = m[m["duration"] > 0]
        if len(m) >= 5:
            coef = np.polyfit(np.log(m["duration"]), m["avg_view_pct"], 1)
            expected = np.polyval(coef, np.log(m["duration"]))
            m = m.assign(expected_pct=expected, retention_gap=m["avg_view_pct"] - expected)
            out["fit"] = coef
            out["by_video"] = m
            weak = m.nsmallest(3, "retention_gap")
            strong = m.nlargest(3, "retention_gap")
            out["insights"].append("同等时长下完播率最好的稿件：" +
                                   "、".join(f"《{t}》" for t in strong["title"]) + "，可分析其节奏与结构作为模板。")
            out["insights"].append("同等时长下完播率最差的稿件：" +
                                   "、".join(f"《{t}》({fpct(p)})" for t, p in zip(weak["title"], weak["avg_view_pct"])) +
                                   "，建议回看这些视频的流失点。")
            c = m[["avg_view_pct", "perf_index"]].dropna()
            if len(c) >= 8:
                cc = c.corr().iloc[0, 1]
                out["insights"].append(f"完播率与播放表现相关系数 {cc:.2f}：" +
                                       ("完播率高的视频明显更容易被放量。" if cc >= 0.2 else
                                        "在你的账号中两者关联不明显，播放更多受选题和点击率影响；但完播率仍是平台推荐的重要信号。"))
    if _has(df, "bounce_3s"):
        b = df.dropna(subset=["bounce_3s"])
        out["bounce"] = b
        out["insights"].append(f"平均 3 秒跳出率 {fpct(b['bounce_3s'].mean())}，最高的是《{b.nlargest(1, 'bounce_3s').iloc[0]['title']}》"
                               f"（{fpct(b['bounce_3s'].max())}）。")
        hi = b[b["bounce_3s"] > b["bounce_3s"].quantile(0.75)]
        lo = b[b["bounce_3s"] < b["bounce_3s"].quantile(0.25)]
        if len(hi) and len(lo):
            out["insights"].append(f"跳出率最低的 1/4 稿件中位播放是最高 1/4 的 "
                                   f"{lo['views'].median() / max(hi['views'].median(), 1):.1f} 倍，开头 3 秒决定了推荐池的放量。")
    if out["curves"]:
        sts = list(out["curves"].values())
        avg_start = np.mean([s["start"] for s in sts])
        avg10 = np.mean([s["at10"] for s in sts])
        avg50 = np.mean([s["at50"] for s in sts])
        out["insights"].append(f"留存曲线平均值：开头 {fpct(avg_start)} → 10% 处 {fpct(avg10)} → 50% 处 {fpct(avg50)}。")
        sug = out["suggestions"]
        if avg_start - avg10 > 0.2:
            sug.append("前 10% 进度流失超过 20 个百分点：开场太慢。建议前 5 秒直接抛出结论/冲突/成果展示，删掉片头和自我介绍。")
        steep = Counter(round(s["steepest_at"], 1) for s in sts).most_common(1)[0][0]
        sug.append(f"多数视频的最陡流失点集中在 {steep * 100:.0f}% 进度附近：检查该位置是否有长铺垫、广告口播或节奏断档，"
                   "可用“下面是最关键的一步”等预告句跨过流失点。")
        ends = np.mean([s["at50"] - s["end"] for s in sts])
        if ends > 0.15:
            sug.append("后半段持续流失较多：考虑精简结尾、把总结前置，或在中段加入“彩蛋/后面还有”预告。")
        peaks = [p for s in sts for p in s["rewatch_peaks"]]
        if peaks:
            sug.append(f"在 {np.median(peaks) * 100:.0f}% 进度附近常出现回看峰值：这里的内容最受关注，可剪成短视频/切片二次分发。")
    if has_pct:
        avg = df["avg_view_pct"].mean()
        out["suggestions"].append(f"整体平均完播率 {fpct(avg)}。" +
                                  ("表现良好，继续保持信息密度。" if avg > 0.45 else
                                   "偏低：建议加章节标记、每 30-60 秒设置一个新信息点或视觉变化，并把视频长度控制在内容需要的最短长度。"))
    return out


def content(ds, df):
    out = {"ok": False, "insights": []}
    m = df[df["mature"] & df["perf_index"].notna()]
    if len(m) < 6:
        out["insights"].append("成熟稿件不足，暂无法分析内容方向。")
        return out
    out["ok"] = True
    overall = m["perf_index"].median()
    agg = dict(数量=("views", "count"), 播放中位数=("views", "median"), 表现指数=("perf_index", "median"),
               互动率=("engagement_rate", "median"))
    if _has(m, "subs_per_1k"):
        agg["千播涨粉"] = ("subs_per_1k", "mean")
    cat = m[m["category"].astype(str) != ""].groupby("category").agg(**agg).sort_values("表现指数", ascending=False)
    out["category"] = cat
    if len(cat) >= 2:
        best = cat[cat["数量"] >= 2].head(1)
        if len(best):
            out["insights"].append(f"表现最好的分区/类别是「{best.index[0]}」（{best['表现指数'].iloc[0]:.2f}x）。")

    # 标签
    rows = []
    for _, r in m.iterrows():
        for tag in {t.strip() for t in str(r["tags"] or "").split(",") if t.strip()}:
            rows.append((tag, r["perf_index"], r["views"]))
    if rows:
        tg = pd.DataFrame(rows, columns=["tag", "perf", "views"]).groupby("tag").agg(
            数量=("perf", "count"), 表现指数=("perf", "median"), 播放中位数=("views", "median"))
        tg = tg[tg["数量"] >= 3].sort_values("表现指数", ascending=False)
        out["tags"] = tg
        if len(tg) >= 2:
            out["insights"].append(f"高表现标签：{'、'.join(tg.head(3).index)}；低表现标签：{'、'.join(tg.tail(2).index)}。")

    # 标题关键词提升度
    rows = []
    for _, r in m.iterrows():
        for w in set(textutil.tokenize(r["title"])):
            rows.append((w, r["perf_index"]))
    if rows:
        kw = pd.DataFrame(rows, columns=["词", "perf"]).groupby("词")["perf"].agg(["count", "median"])
        kw = kw[kw["count"] >= 3]
        kw["提升度"] = kw["median"] / overall - 1
        kw = kw.sort_values("提升度", ascending=False)
        out["keywords"] = kw
        good = kw[kw["提升度"] > 0.15].head(5)
        if len(good):
            out["insights"].append("标题中带来正向提升的关键词：" +
                                   "、".join(f"“{w}”(+{v * 100:.0f}%)" for w, v in good["提升度"].items()) + "。")

    # 标题特征
    feats = pd.DataFrame([textutil.title_features(t) for t in m["title"]], index=m.index)
    feat_rows = []
    for f in feats.columns:
        yes, no = m.loc[feats[f], "perf_index"], m.loc[~feats[f], "perf_index"]
        if len(yes) >= 3 and len(no) >= 3:
            feat_rows.append((f, len(yes), yes.median() / no.median() - 1))
    out["title_features"] = pd.DataFrame(feat_rows, columns=["特征", "样本", "提升"]).set_index("特征") \
        .sort_values("提升", ascending=False) if feat_rows else pd.DataFrame()
    if feat_rows:
        best = max(feat_rows, key=lambda r: r[2])
        worst = min(feat_rows, key=lambda r: r[2])
        if best[2] > 0.1:
            out["insights"].append(f"标题{best[0]}的稿件表现高出 {best[2] * 100:.0f}%。")
        if worst[2] < -0.1:
            out["insights"].append(f"标题{worst[0]}的稿件表现反而低 {abs(worst[2]) * 100:.0f}%。")

    lens = pd.cut(m["title_len"], [0, 12, 18, 24, 30, 200], labels=["≤12字", "13-18字", "19-24字", "25-30字", ">30字"])
    tl = m.groupby(lens, observed=True)["perf_index"].agg(["count", "median"])
    out["title_len"] = tl
    tl2 = tl[tl["count"] >= 3]
    if len(tl2):
        out["insights"].append(f"标题长度在「{tl2['median'].idxmax()}」时表现最好。")
    return out


def outliers(ds, df):
    out = {"ok": False, "insights": []}
    m = df[df["mature"] & (df["perf_index"] > 0)].copy()
    if len(m) < 8:
        out["insights"].append("稿件太少，暂不做爆款诊断。")
        return out
    out["ok"] = True
    lp = np.log(m["perf_index"])
    m["z"] = (lp - lp.mean()) / (lp.std() or 1)
    hits, flops = m[m["z"] > 1.3].sort_values("z", ascending=False), m[m["z"] < -1.2].sort_values("z")
    out["hits"], out["flops"], out["all"] = hits, flops, m
    out["insights"].append(f"识别出 {len(hits)} 个爆款（表现显著高于同期）和 {len(flops)} 个低于预期的稿件。")
    if len(hits) >= 2:
        def share(frame, cond):
            return cond(frame).mean() if len(frame) else 0
        checks = [
            ("晚间18-23点发布", lambda f: f["hour"].between(18, 22)),
            ("周末发布", lambda f: f["weekday"] >= 5),
            ("时长5-20分钟", lambda f: f["duration"].between(300, 1200)),
            ("标题含数字", lambda f: f["title"].str.contains(r"\d")),
            ("标题含问句", lambda f: f["title"].str.contains(r"[?？]|为什么|如何|怎么")),
        ]
        factors = []
        for name, cond in checks:
            a, b = share(hits, cond), share(m, cond)
            if a - b > 0.15:
                factors.append(f"{name}（爆款中 {a * 100:.0f}% vs 整体 {b * 100:.0f}%）")
        if factors:
            out["insights"].append("爆款的共同特征：" + "；".join(factors) + "。")
        cats = hits["category"].value_counts()
        if len(cats) and cats.iloc[0] >= 2:
            out["insights"].append(f"爆款集中在「{cats.index[0]}」类别，可以围绕它做系列化选题。")
    if len(hits):
        h = hits.iloc[0]
        out["insights"].append(f"最大爆款《{h['title']}》是同期中位水平的 {h['perf_index']:.1f} 倍，"
                               "建议复盘其选题切入点、封面与前 30 秒，并尽快制作续集/相关选题承接流量。")
    hit_rate = (m["perf_index"] >= 2).mean()
    out["hit_rate"] = hit_rate
    out["insights"].append(f"“2倍爆款率”（播放 ≥ 同期中位 2 倍）为 {fpct(hit_rate)}。")
    return out


def cadence(ds, df):
    out = {"ok": False, "insights": []}
    if len(df) < 4:
        out["insights"].append("稿件太少，无法分析更新节奏。")
        return out
    out["ok"] = True
    s = df.sort_values("publish_time")
    gaps = s["publish_time"].diff().dt.total_seconds() / 86400
    s = s.assign(gap_before=gaps)
    out["weekly"] = s.set_index("publish_time").resample("W")["video_id"].count().iloc[-26:]
    recent = gaps.iloc[-20:].dropna()
    cv = recent.std() / recent.mean() if recent.mean() else np.nan
    out["median_gap"], out["cv"] = recent.median(), cv
    out["insights"].append(f"近期平均每 {recent.median():.1f} 天更新一次，节奏稳定度 "
                           f"{max(0, 1 - cv) * 100:.0f}/100（间隔越规律越高）。")
    m = s[s["mature"] & s["gap_before"].notna()]
    if len(m) >= 8:
        b = pd.cut(m["gap_before"], [0, 3, 7, 14, 10000], labels=["≤3天", "3-7天", "7-14天", ">14天"])
        g = m.groupby(b, observed=True)["perf_index"].agg(["count", "median"])
        out["gap_perf"] = g
        g2 = g[g["count"] >= 2]
        if len(g2) >= 2:
            out["insights"].append(f"间隔「{g2['median'].idxmax()}」后发布的稿件表现最好，"
                                   f"「{g2['median'].idxmin()}」最差。")
    longest = gaps.max()
    if longest > 30:
        out["insights"].append(f"历史最长断更 {longest:.0f} 天。断更后首个视频往往需要重新积累推荐。")
    if recent.median() > 10:
        out["insights"].append("更新频率偏低，建议至少保持每周 1 更；可用短视频/切片填补长视频之间的空档。")
    return out


def lifecycle(ds, df):
    out = {"ok": False, "insights": []}
    vs = ds.video_snaps.dropna(subset=["views"])
    if vs.empty:
        return out
    pub = dict(zip(df["video_id"], df["publish_time"]))
    vs = vs[vs["video_id"].isin(pub)].copy()
    vs["age"] = (vs["ts"] - vs["video_id"].map(pub)).dt.total_seconds() / 86400
    curves = []
    for vid, g in vs.groupby("video_id"):
        g = g.sort_values("age")
        if len(g) < 3 or g["age"].iloc[0] > 2 or g["age"].iloc[-1] < 14:
            continue
        v14 = np.interp(14, g["age"], g["views"])
        if v14 <= 0:
            continue
        days = np.arange(1, 15)
        curves.append(np.interp(days, g["age"], g["views"]) / v14)
    if len(curves) >= 2:
        out["ok"] = True
        avg = np.mean(curves, axis=0)
        out["curve"] = pd.Series(avg, index=np.arange(1, 15))
        out["insights"].append(f"基于 {len(curves)} 个稿件的历史快照：首日获得 14 天播放的 {avg[0] * 100:.0f}%，"
                               f"3 天 {avg[2] * 100:.0f}%，7 天 {avg[6] * 100:.0f}%。")
        if avg[2] > 0.7:
            out["insights"].append("流量高度集中在发布后 3 天内，首发时段与首日互动（置顶评论、动态、社群推送）非常关键。")
        else:
            out["insights"].append("播放增长较为平缓、长尾明显，说明搜索/推荐带来持续流量，适合多做可被搜索的选题。")
    # 常青内容：发布 60 天以上仍在持续涨播放
    last = vs.sort_values("ts").groupby("video_id").tail(1).set_index("video_id")
    week_ago = vs[vs["ts"] <= vs["ts"].max() - pd.Timedelta(days=6)].sort_values("ts").groupby("video_id").tail(1).set_index("video_id")
    common = last.index.intersection(week_ago.index)
    if len(common):
        gain = (last.loc[common, "views"] - week_ago.loc[common, "views"]) / \
               ((last.loc[common, "ts"] - week_ago.loc[common, "ts"]).dt.total_seconds() / 86400).clip(lower=1)
        old = [v for v in common if last.loc[v, "age"] > 60]
        ev = gain.loc[old].sort_values(ascending=False) if old else pd.Series(dtype=float)
        ev = ev[ev > 0]
        if len(ev):
            out["ok"] = True
            titles = dict(zip(df["video_id"], df["title"]))
            out["evergreen"] = [(titles[v], g) for v, g in ev.head(8).items()]
            out["insights"].append("长尾常青稿件（发布超60天仍持续增长）：" +
                                   "、".join(f"《{t}》(日增{fnum(g)})" for t, g in out["evergreen"][:3]) +
                                   "。可以为它们更新简介/置顶评论，引导到新视频。")
    if not out["ok"]:
        out["insights"].append("生命周期分析需要多次快照：开启自动监控，数天后即可看到每个视频的播放增长曲线。")
    return out


def conversion(ds, df):
    out = {"ok": False, "insights": [], "estimated": False}
    m = df.copy()
    if not _has(m, "subs_gained"):
        fol = follower_series(ds)
        if len(fol) >= 10:
            base = fol.diff().median()
            est = []
            for _, r in m.iterrows():
                d0 = r["publish_time"].normalize()
                before = fol[fol.index < d0]
                after = fol[(fol.index >= d0 + pd.Timedelta(days=3))]
                if len(before) and len(after):
                    est.append(max(after.iloc[0] - before.iloc[-1] - 4 * base, 0))
                else:
                    est.append(np.nan)
            m["subs_gained"] = est
            m["subs_per_1k"] = m["subs_gained"] / m["views"].replace(0, np.nan) * 1000
            out["estimated"] = True
    m = m.dropna(subset=["subs_per_1k"])
    if len(m) < 4:
        out["insights"].append("暂无转粉数据。YouTube 登录后自动获取；B站可导入创作中心的“涨粉”数据，或开启自动监控用粉丝快照估算。")
        return out
    out["ok"] = True
    out["data"] = m
    if out["estimated"]:
        out["insights"].append("（以下转粉数据由粉丝快照估算：发布后 3 天粉丝增量扣除日常自然增长。）")
    out["insights"].append(f"每千次播放平均涨粉 {m['subs_per_1k'].mean():.2f}，中位数 {m['subs_per_1k'].median():.2f}。")
    top = m.nlargest(3, "subs_per_1k")
    out["insights"].append("转粉效率最高的稿件：" + "、".join(f"《{t}》({v:.1f}/千播)" for t, v in zip(top["title"], top["subs_per_1k"])) + "。")
    c = m[["subs_per_1k", "engagement_rate"]].dropna()
    if len(c) >= 8:
        out["insights"].append(f"转粉率与互动率相关系数 {c.corr().iloc[0, 1]:.2f}。")
    viral = m[m["perf_index"] >= 2]
    if len(viral) >= 2:
        r = viral["subs_per_1k"].median() / max(m["subs_per_1k"].median(), 1e-9)
        out["insights"].append(f"爆款视频的千播涨粉是整体的 {r:.2f} 倍"
                               + ("——“泛流量”爆款不一定带来粉丝，需在视频中强化人设与系列预告。" if r < 0.9 else "。"))
    if _has(m, "subs_lost"):
        churn = m["subs_lost"].sum() / max(m["subs_gained"].sum(), 1)
        out["insights"].append(f"掉粉/涨粉比 {fpct(churn)}" + ("，偏高，注意内容方向是否偏离粉丝预期。" if churn > 0.2 else "，健康。"))
    return out


def audience(ds, df):
    b = ds.breakdowns or {}
    out = {"ok": bool(b), "insights": [], "breakdowns": b}
    if not b:
        out["insights"].append("暂无流量来源与受众画像数据（YouTube 登录后自动获取；B站接口暂不开放此类数据）。")
        return out

    def top(name):
        d = b.get(name) or {}
        if not d:
            return None
        total = sum(d.values()) or 1
        k = max(d, key=d.get)
        return k, d[k] / total

    t = top("traffic")
    if t:
        out["insights"].append(f"最大流量来源是「{t[0]}」，占 {t[1] * 100:.0f}%。" +
                               ("推荐流量为主，封面点击率和完播率是关键。" if any(x in t[0] for x in ("推荐", "首页", "浏览"))
                                else "搜索流量为主，标题和简介里的关键词非常重要。" if "搜索" in t[0] else ""))
    d = top("device")
    if d:
        out["insights"].append(f"「{d[0]}」观看占 {d[1] * 100:.0f}%" +
                               ("：封面文字要大、字幕要清晰，竖屏用户占比高时可尝试竖版内容。" if d[0] == "手机" else "。"))
    a = top("age")
    if a:
        out["insights"].append(f"核心观众年龄段：{a[0]}（{a[1] * 100:.0f}%）。")
    g = b.get("gender")
    if g:
        tot = sum(g.values()) or 1
        out["insights"].append("性别分布：" + "，".join(f"{k} {v / tot * 100:.0f}%" for k, v in g.items()) + "。")
    s = b.get("subscribed")
    if s:
        tot = sum(s.values()) or 1
        k = next((x for x in s if "已" in x), None)
        if k:
            out["insights"].append(f"{s[k] / tot * 100:.0f}% 的播放来自已关注用户，"
                                   + ("新观众占比高，增长潜力大，需加强关注引导。" if s[k] / tot < 0.4 else "粉丝黏性高，可多做粉丝向互动内容。"))
    return out


def comments(ds, df):
    out = {"ok": False, "insights": []}
    allc = [(vid, c) for vid, lst in (ds.comments or {}).items() for c in lst if c]
    if not allc:
        out["insights"].append("暂无评论数据（在设置中开启“抓取评论”后刷新）。")
        return out
    out["ok"] = True
    texts = [c for _, c in allc]
    scores = [textutil.sentiment(c) for c in texts]
    pos = sum(s > 0.2 for s in scores) / len(scores)
    neg = sum(s < -0.2 for s in scores) / len(scores)
    out["sentiment"] = {"正面": pos, "中性": 1 - pos - neg, "负面": neg}
    out["keywords"] = textutil.keywords(texts, 20)
    reqs = [c for c in texts if textutil.is_request(c)]
    reqs.sort(key=lambda c: -textutil.request_strength(c))
    out["requests"] = list(dict.fromkeys(reqs))[:15]
    out["negatives"] = list(dict.fromkeys(c for c, s in zip(texts, scores) if s < -0.2))[:10]
    titles = dict(zip(df["video_id"], df["title"]))
    per = pd.DataFrame(allc, columns=["video_id", "text"]).assign(score=scores)
    out["per_video"] = per.groupby("video_id")["score"].mean().rename(index=titles)
    out["insights"].append(f"分析了 {len(texts)} 条热门评论：正面 {pos * 100:.0f}%、负面 {neg * 100:.0f}%。")
    if out["keywords"]:
        out["insights"].append("评论高频词：" + "、".join(w for w, _ in out["keywords"][:10]) + "。")
    if reqs:
        out["insights"].append(f"{len(reqs) / len(texts) * 100:.0f}% 的评论包含提问或选题需求——这是最直接的选题来源，见“观众诉求”列表。")
    if neg > 0.15 and out["negatives"]:
        out["insights"].append("负面反馈占比较高，主要集中在：" + "；".join(out["negatives"][:3]) + "。")
    return out


def _score(x, pts):
    """分段线性映射到 0-100。pts=[(x, score), ...] 升序。"""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    xs, ys = zip(*pts)
    return float(np.interp(x, xs, ys))


def health(ds, df, res):
    out = {"ok": not df.empty, "insights": [], "scores": {}}
    if df.empty:
        return out
    yt = ds.platform == "youtube"
    fol = res["growth"].get("followers")
    g = None
    if fol is not None and len(fol) >= 7:
        past = fol[fol.index <= fol.index[-1] - pd.Timedelta(days=30)]
        start = past.iloc[-1] if len(past) else fol.iloc[0]
        g = (fol.iloc[-1] - start) / max(start, 1)
    sc = out["scores"]
    sc["增长力"] = _score(g, [(-0.05, 10), (0, 35), (0.02, 60), (0.05, 80), (0.12, 100)])
    sc["互动力"] = _score(df["engagement_rate"].median(),
                          [(0, 0), (0.02, 35), (0.04, 60), (0.08, 85), (0.15, 100)] if yt else
                          [(0, 0), (0.04, 35), (0.08, 60), (0.14, 85), (0.25, 100)])
    cad = res["cadence"]
    if cad.get("ok"):
        freq = _score(7 / max(cad["median_gap"], 0.5), [(0, 0), (0.5, 40), (1, 65), (2, 85), (4, 100)])
        stab = max(0, 1 - (cad["cv"] if not np.isnan(cad["cv"]) else 1)) * 100
        sc["稳定性"] = 0.6 * freq + 0.4 * stab
    sc["留存力"] = _score(df["avg_view_pct"].mean() if _has(df, "avg_view_pct") else None,
                          [(0.1, 10), (0.25, 40), (0.4, 65), (0.55, 85), (0.7, 100)])
    conv = res["conversion"]
    sc["转粉力"] = _score(conv["data"]["subs_per_1k"].median() if conv.get("ok") else None,
                          [(0, 0), (1, 35), (3, 60), (6, 85), (12, 100)])
    out_ = res["outliers"]
    sc["爆款力"] = _score(out_.get("hit_rate"), [(0, 10), (0.05, 45), (0.12, 75), (0.25, 100)])
    valid = {k: v for k, v in sc.items() if v is not None}
    out["scores"] = valid
    weights = {"增长力": 1.3, "互动力": 1.0, "稳定性": 0.8, "留存力": 1.1, "转粉力": 1.1, "爆款力": 0.7}
    total = sum(valid[k] * weights[k] for k in valid) / sum(weights[k] for k in valid) if valid else 0
    out["total"] = total
    grade = "S" if total >= 85 else "A" if total >= 72 else "B" if total >= 58 else "C" if total >= 45 else "D"
    out["grade"] = grade
    out["insights"].append(f"账号健康度 {total:.0f} 分（{grade} 级）。")
    if valid:
        weakest = min(valid, key=valid.get)
        strongest = max(valid, key=valid.get)
        out["insights"].append(f"优势项：{strongest}（{valid[strongest]:.0f}）；短板：{weakest}（{valid[weakest]:.0f}），优先改进短板收益最大。")
    return out


def competitors(ds, df, comps):
    out = {"ok": False, "insights": [], "rows": []}
    if not comps:
        out["insights"].append("还没有添加竞品账号。点击“竞品管理”添加同领域账号即可进行对标。")
        return out

    def row(d):
        p = prepare(d)
        if p.empty:
            return None
        fol = follower_series(d)
        recent = p[p["publish_time"] >= datetime.now() - timedelta(days=90)]
        return {"账号": d.name, "平台": d.platform_name,
                "粉丝": fol.iloc[-1] if len(fol) else (d.account_snaps["followers"].dropna().iloc[-1]
                                                     if d.account_snaps["followers"].notna().any() else np.nan),
                "稿件数": len(p), "播放中位数": p["views"].median(), "互动率": p["engagement_rate"].median(),
                "周更数": len(recent) / 12.9, "平均时长": p["duration"].median(),
                "播粉比": p["views"].median() / max(fol.iloc[-1] if len(fol) else 1, 1),
                "主要类别": p["category"].mode().iloc[0] if p["category"].notna().any() else "—",
                "热门时段": f"{int(p.nlargest(max(len(p) // 4, 1), 'views')['hour'].median())}点"}
    me = row(ds)
    rows = [r for r in [me] + [row(c) for c in comps] if r]
    if len(rows) < 2:
        return out
    out["ok"] = True
    out["rows"] = rows
    others = rows[1:]
    med = lambda k: np.nanmedian([r[k] for r in others])  # noqa: E731
    for k, label, fmt in [("播放中位数", "稿件播放中位数", fnum), ("互动率", "互动率", fpct),
                          ("周更数", "更新频率", lambda v: f"{v:.1f}/周"), ("播粉比", "播粉比（播放/粉丝）", lambda v: f"{v:.2f}")]:
        mine, theirs = me[k], med(k)
        if theirs and not np.isnan(theirs):
            diff = mine / theirs - 1 if theirs else 0
            out["insights"].append(f"{label}：你 {fmt(mine)}，竞品中位 {fmt(theirs)}（{'领先' if diff >= 0 else '落后'} {abs(diff) * 100:.0f}%）。")
    hours = [r["热门时段"] for r in others]
    out["insights"].append(f"竞品爆款常见发布时段：{'、'.join(hours)}，可作为测试新时段的参考。")
    return out


# ---------------------------------------------------------------- 发布模拟器
def predict(df: pd.DataFrame, weekday: int, hour: int, duration_sec: int, category: str | None = None):
    """基于历史表现的乘法模型，返回 (预计中位播放, 低, 高, 解释列表)。"""
    m = df[df["mature"] & df["perf_index"].notna()]
    if len(m) < 6:
        return None
    recent = m.nlargest(min(15, len(m)), "publish_time")
    base = recent["views"].median()
    factors = []

    def f(mask, label, k=4.0):
        sub = m.loc[mask, "perf_index"]
        val = _shrink(sub, k) / max(m["perf_index"].median(), 1e-9)
        factors.append((label, val, len(sub)))
        return val

    hb = hour // 3
    mult = f((m["weekday"] == weekday) & (m["hour_block"] == hb),
             f"{WEEKDAYS[weekday]} {HOUR_BLOCKS[hb][0]}-{HOUR_BLOCKS[hb][1]}点", k=6.0)
    mult *= f(m["hour"].between(hour - 1, hour + 1), f"{hour}点前后") ** 0.5
    bucket = pd.cut([duration_sec], DUR_EDGES, labels=DUR_LABELS, right=False)[0]
    mult *= f(m["dur_bucket"] == bucket, f"时长 {bucket}")
    if category:
        mult *= f(m["category"] == category, f"类别 {category}")
    spread = np.log(m["perf_index"]).std()
    est = base * mult
    lo, hi = est * math.exp(-0.674 * spread), est * math.exp(0.674 * spread)
    return est, lo, hi, factors, base


# ---------------------------------------------------------------- 建议汇总
def recommendations(ds, df, res):
    recs = []

    def add(priority, area, text):
        recs.append({"优先级": priority, "方向": area, "建议": text})

    t = res["timing"]
    if t.get("best_slots"):
        add("高", "发布时间", f"把主力稿件固定在「{t['best_slots'][0][0]}」发布，形成观众预期；每月拿 1-2 期测试新时段。")
    d = res["duration"]
    if d.get("best_bucket"):
        add("高", "视频时长", f"优先制作「{d['best_bucket']}」的视频；超出该区间的内容考虑拆分成上下集或系列。")
    r = res["retention"]
    for s in r.get("suggestions", [])[:3]:
        add("高", "留存优化", s)
    h = res["health"]
    if h.get("scores"):
        weakest = min(h["scores"], key=h["scores"].get)
        tips = {"增长力": "粉丝增长慢：在视频中段与结尾明确给出关注理由（系列预告、福利、专属栏目）。",
                "互动力": "互动偏低：每期设计一个可回答的问题，置顶评论引导讨论，并积极回复前 50 条评论。",
                "稳定性": "更新不规律：制定固定排期（如每周三/六），提前储备 2-3 期稿件应对突发情况。",
                "留存力": "完播率偏低：压缩开场、加快节奏、使用章节，并删除与主题无关的段落。",
                "转粉力": "转粉效率低：强化人设和账号定位，让观众知道“关注你能持续获得什么”。",
                "爆款力": "缺少爆款：参考热门榜与评论区诉求选题，打磨封面标题，并对已有爆款做续集。"}
        add("高", "短板补强", tips[weakest])
    o = res["outliers"]
    if o.get("ok") and len(o["hits"]):
        add("中", "爆款复用", f"为爆款《{o['hits'].iloc[0]['title']}》制作续集/同系列选题，并在其简介与置顶评论中导流到新视频。")
    c = res["content"]
    if c.get("ok") and isinstance(c.get("keywords"), pd.DataFrame) and len(c["keywords"]):
        good = c["keywords"][c["keywords"]["提升度"] > 0.15].head(3)
        if len(good):
            add("中", "选题与标题", f"在标题中更多使用高表现关键词：{'、'.join(good.index)}。")
    cm = res["comments"]
    if cm.get("requests"):
        add("中", "观众诉求", f"评论区高频诉求示例：「{cm['requests'][0]}」——把这类问题整理成下一期选题。")
    cad = res["cadence"]
    if cad.get("ok") and cad["median_gap"] > 7:
        add("中", "更新频率", "目前更新间隔超过一周，建议提升到每周至少 1 更，可穿插低成本的短视频。")
    conv = res["conversion"]
    if conv.get("ok"):
        add("低", "涨粉", "在转粉效率高的视频类型上加大投入，并在结尾加入系列合集入口。")
    a = res["audience"]
    if a.get("ok"):
        add("低", "受众", "根据受众画像调整表达方式与封面风格；移动端占比高时注意字幕字号与封面信息量。")
    add("低", "数据习惯", "开启自动监控并保持每天至少一次刷新，长期快照能让生命周期与转粉分析更准确。")
    return recs


# ---------------------------------------------------------------- 总入口
MODULES = ["overview", "growth", "timing", "duration", "engagement", "retention", "content",
           "outliers", "cadence", "lifecycle", "conversion", "audience", "comments"]


def analyze(ds: Dataset, comps=None) -> dict:
    df = prepare(ds)
    res = {"df": df, "dataset": ds}
    for name in MODULES:
        try:
            res[name] = globals()[name](ds, df) if not df.empty or name in ("overview", "growth", "audience", "comments") \
                else {"ok": False, "insights": ["暂无稿件数据。"]}
        except Exception as e:  # noqa: BLE001 - 单个模块失败不影响其他模块
            res[name] = {"ok": False, "insights": [f"分析出错：{e}"]}
    try:
        res["health"] = health(ds, df, res)
    except Exception as e:  # noqa: BLE001
        res["health"] = {"ok": False, "insights": [f"分析出错：{e}"], "scores": {}}
    try:
        res["competitors"] = competitors(ds, df, comps or [])
    except Exception as e:  # noqa: BLE001
        res["competitors"] = {"ok": False, "insights": [f"分析出错：{e}"], "rows": []}
    res["recommendations"] = recommendations(ds, df, res) if not df.empty else []
    return res
