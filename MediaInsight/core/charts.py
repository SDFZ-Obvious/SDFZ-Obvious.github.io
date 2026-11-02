"""图表：每个分析模块对应一个 matplotlib Figure（可嵌入界面，也可导出到报告）。

配色遵循固定顺序的分类色板、单色相顺序色阶、蓝-红发散色，不使用双 Y 轴。
"""
import io

import matplotlib
matplotlib.use("Agg")  # noqa: E402 - 界面层会切换到 TkAgg 画布
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, PercentFormatter

from .analytics import HOUR_BLOCKS, WEEKDAYS, fnum

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, NEUTRAL = "#e1e0d9", "#c3c2b7", "#b9b8b0"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
POS_COLOR, NEG_COLOR = "#2a78d6", "#e34948"
SEQ = LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP)

matplotlib.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC",
                        "Arial Unicode MS", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "font.size": 9,
    "axes.titlesize": 10.5,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "axes.labelcolor": INK2,
    "axes.edgecolor": AXIS,
    "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "lines.linewidth": 2,
})

def _big(x, _=None):
    for div, unit in ((1e8, "亿"), (1e4, "万")):
        if abs(x) >= div:
            return f"{x / div:.2f}".rstrip("0").rstrip(".") + unit
    return f"{x:,.0f}"


big_fmt = FuncFormatter(_big)


def _fig(rows, cols, h=6.6, w=11):
    fig = Figure(figsize=(w, h), dpi=100)
    axes = fig.subplots(rows, cols, squeeze=False)
    for ax in axes.flat:
        _style(ax)
    return fig, axes


def _style(ax, grid_axis="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.grid(axis=grid_axis)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def _empty(ax, msg="暂无数据"):
    ax.clear()
    ax.set_axis_off()
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=MUTED, fontsize=10, wrap=True,
            transform=ax.transAxes)


def _finish(fig):
    # 使用布局引擎而不是一次性 tight_layout，界面缩放窗口时会自动重新排版
    fig.set_layout_engine("tight", pad=1.4, h_pad=2.2, w_pad=2.0)
    return fig


def _barh(ax, labels, values, color=SERIES[0], fmt=lambda v: f"{v:.2f}", title=None):
    labels, values = list(labels), list(values)
    y = np.arange(len(labels))
    ax.barh(y, values, color=color, height=0.62, edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    _style(ax, "x")
    vmax = max([abs(v) for v in values if not pd.isna(v)] + [1e-9])
    for yi, v in zip(y, values):
        if not pd.isna(v):
            ax.text(v + vmax * 0.01 * (1 if v >= 0 else -1), yi, fmt(v), va="center",
                    ha="left" if v >= 0 else "right", color=INK2, fontsize=8)
    ax.set_xlim(min(0, min(values) * 1.25) if values else 0, vmax * 1.2)
    if title:
        ax.set_title(title, loc="left")


def _short(t, n=14):
    t = str(t)
    return t if len(t) <= n else t[:n] + "…"


# ------------------------------------------------------------------- 页面
def fig_overview(res):
    fig, ax = _fig(2, 2)
    df = res["df"]
    a = ax[0, 0]
    if not df.empty:
        d = df.sort_values("publish_time")
        a.bar(d["publish_time"], d["views"], width=2.2, color=SERIES[0], alpha=0.85)
        a.plot(d["publish_time"], d["baseline"], color=INK2, linewidth=1.5, label="同期中位水平")
        a.yaxis.set_major_formatter(big_fmt)
        a.legend(loc="upper left")
        a.set_title("每个稿件的播放量（按发布时间）", loc="left")
        fig.autofmt_xdate(rotation=0, ha="center")
    else:
        _empty(a)
    a = ax[0, 1]
    fol = res["growth"].get("followers")
    if fol is not None and len(fol) >= 2:
        a.plot(fol.index, fol.values, color=SERIES[0])
        a.yaxis.set_major_formatter(big_fmt)
        a.set_title("粉丝数变化", loc="left")
        a.annotate(fnum(fol.iloc[-1]), (fol.index[-1], fol.iloc[-1]), xytext=(4, 0),
                   textcoords="offset points", color=INK, fontsize=9, va="center")
    else:
        _empty(a, "粉丝趋势需要至少 2 次刷新快照")
    a = ax[1, 0]
    h = res["health"]
    if h.get("scores"):
        items = list(h["scores"].items())
        _barh(a, [k for k, _ in items], [v for _, v in items], fmt=lambda v: f"{v:.0f}",
              title=f"账号健康度 {h['total']:.0f} 分（{h['grade']} 级）")
        a.set_xlim(0, 115)
    else:
        _empty(a)
    a = ax[1, 1]
    e = res["engagement"]
    if e.get("ok"):
        rates = e["rates"]
        _barh(a, list(rates), list(rates.values()), color=SERIES[2], fmt=lambda v: f"{v * 100:.2f}%",
              title="互动指标（每次播放，中位数）")
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=1))
    else:
        _empty(a)
    return _finish(fig)


def fig_growth(res):
    g = res["growth"]
    fig, ax = _fig(3, 1, h=8.2)
    a = ax[0, 0]
    fol = g.get("followers")
    if fol is not None and len(fol) >= 2:
        a.plot(fol.index, fol.values, color=SERIES[0], label="粉丝数")
        fc = g.get("forecast")
        if fc is not None:
            a.plot(fc.index, fc.values, color=SERIES[0], linestyle=(0, (4, 3)), linewidth=1.5, label="30天预测")
        a.yaxis.set_major_formatter(big_fmt)
        a.legend(loc="upper left")
        a.set_title("粉丝增长与预测", loc="left")
    else:
        _empty(a, "粉丝趋势需要多次快照")
    a = ax[1, 0]
    v = g.get("daily_views")
    if v is not None and len(v) >= 2:
        a.bar(v.index, v.values, color=BLUE_RAMP[1], width=0.8, label="每日播放")
        a.plot(v.index, v.rolling(7, min_periods=1).mean(), color=SERIES[0], label="7日均线")
        a.yaxis.set_major_formatter(big_fmt)
        a.legend(loc="upper left")
        a.set_title("每日新增播放", loc="left")
    else:
        _empty(a, "每日播放需要创作中心/Analytics 数据或多次快照")
    a = ax[2, 0]
    sg = g.get("subs_gained")
    if sg is not None and sg.notna().sum() >= 2:
        a.bar(sg.index, sg.values, color=POS_COLOR, width=0.8, label="新增关注")
        sl = g.get("subs_lost")
        if sl is not None and sl.notna().any():
            a.bar(sl.index, -sl.values, color=NEG_COLOR, width=0.8, label="取消关注")
        a.axhline(0, color=AXIS, linewidth=1)
        a.legend(loc="upper left")
        a.set_title("每日涨粉 / 掉粉", loc="left")
    else:
        _empty(a, "暂无每日涨掉粉数据")
    return _finish(fig)


def fig_timing(res):
    t = res["timing"]
    fig = Figure(figsize=(11, 6.6), dpi=100)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1])
    a = fig.add_subplot(gs[0, :])
    if not t.get("ok"):
        _empty(a, t["insights"][0] if t["insights"] else "数据不足")
        return _finish(fig)
    heat, cnt = t["heat"], t["heat_count"]
    vals = heat.values.astype(float)
    vmax = np.nanmax(vals) if np.isfinite(vals).any() else 1
    im = a.imshow(np.ma.masked_invalid(vals), cmap=SEQ, aspect="auto", vmin=0, vmax=min(vmax, 3))
    a.set_facecolor("#f0efec")
    a.set_xticks(range(8), [f"{s:02d}-{e:02d}点" for s, e in HOUR_BLOCKS])
    a.set_yticks(range(7), WEEKDAYS)
    for i in range(7):
        for j in range(8):
            if not np.isnan(vals[i, j]):
                dark = vals[i, j] > min(vmax, 3) * 0.55
                a.text(j, i, f"{vals[i, j]:.2f}x\n({int(cnt.values[i, j])})", ha="center", va="center",
                       fontsize=7.5, color="#ffffff" if dark else INK)
    for s in a.spines.values():
        s.set_visible(False)
    a.tick_params(length=0)
    a.set_title("发布时段表现热力图（表现指数 = 播放 ÷ 同期中位；括号内为样本数；灰色为未发布过）", loc="left")
    fig.colorbar(im, ax=a, fraction=0.025, pad=0.01).outline.set_visible(False)

    a = fig.add_subplot(gs[1, 0])
    _style(a)
    bh = t["by_hour"]
    a.bar(bh.index, bh["median"].fillna(0), color=[SERIES[0] if c >= 2 else BLUE_RAMP[1] for c in bh["count"].fillna(0)],
          width=0.7)
    a.axhline(1, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
    a.set_xticks(range(0, 24, 2))
    a.set_title("按发布小时（浅色 = 样本少于 2）", loc="left")
    a = fig.add_subplot(gs[1, 1])
    _style(a)
    bw = t["by_weekday"]
    a.bar(range(7), bw["median"].fillna(0), color=SERIES[0], width=0.6)
    a.axhline(1, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
    a.set_xticks(range(7), WEEKDAYS)
    a.set_title("按星期", loc="left")
    return _finish(fig)


def fig_duration(res):
    d = res["duration"]
    fig, ax = _fig(2, 2)
    if not d.get("ok"):
        for a in ax.flat:
            _empty(a)
        return _finish(fig)
    t = d["table"]
    labels = [str(i) for i in t.index]
    x = np.arange(len(labels))

    def bars(a, col, title, color, fmt):
        if col not in t.columns or t[col].isna().all():
            _empty(a, f"暂无{col}数据")
            return
        a.bar(x, t[col].fillna(0), color=color, width=0.62, edgecolor=SURFACE, linewidth=2)
        for xi, v, n in zip(x, t[col], t["数量"]):
            if not pd.isna(v):
                a.text(xi, v, fmt(v), ha="center", va="bottom", fontsize=7.5, color=INK2)
        a.set_xticks(x, labels, fontsize=8)
        a.set_title(title, loc="left")

    bars(ax[0, 0], "播放中位数", "各时长区间的播放中位数", SERIES[0], lambda v: fnum(v, 1))
    ax[0, 0].yaxis.set_major_formatter(big_fmt)
    bars(ax[0, 1], "千播涨粉", "各时长区间的转粉率（每千次播放涨粉）", SERIES[2], lambda v: f"{v:.1f}")
    bars(ax[1, 0], "3秒跳出率", "各时长区间的 3 秒跳出率（越低越好）", SERIES[1], lambda v: f"{v * 100:.0f}%")
    if "3秒跳出率" in t.columns:
        ax[1, 0].yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    a = ax[1, 1]
    sc = d["scatter"].dropna(subset=["avg_view_pct"])
    if len(sc):
        a.scatter(sc["duration"] / 60, sc["avg_view_pct"], s=26, color=SERIES[0], alpha=0.75,
                  edgecolor=SURFACE, linewidth=1)
        a.set_xscale("log")
        a.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        a.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        a.set_xlabel("时长（分钟，对数刻度）")
        a.set_title("时长 vs 完播率", loc="left")
        _style(a, "both")
    else:
        _empty(a, "暂无完播率数据")
    return _finish(fig)


def fig_engagement(res):
    e = res["engagement"]
    fig, ax = _fig(2, 2)
    if not e.get("ok"):
        for a in ax.flat:
            _empty(a)
        return _finish(fig)
    rates = e["rates"]
    _barh(ax[0, 0], list(rates), list(rates.values()), fmt=lambda v: f"{v * 100:.2f}%", title="各项互动率（中位数）")
    ax[0, 0].xaxis.set_major_formatter(PercentFormatter(1, decimals=1))
    a = ax[0, 1]
    tr = e["trend"].dropna()
    if len(tr) >= 2:
        a.plot(tr.index, tr.values, color=SERIES[0])
        a.yaxis.set_major_formatter(PercentFormatter(1, decimals=1))
        a.set_title("互动率趋势（5 稿滚动中位数）", loc="left")
        fig.autofmt_xdate(rotation=0, ha="center")
    else:
        _empty(a)
    a = ax[1, 0]
    pv = e["per_video"].dropna(subset=["engagement_rate"])
    pv = pv[pv["views"] > 0]
    a.scatter(pv["views"], pv["engagement_rate"], s=24, color=SERIES[0], alpha=0.7, edgecolor=SURFACE, linewidth=1)
    a.set_xscale("log")
    a.xaxis.set_major_formatter(big_fmt)
    a.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    a.set_xlabel("播放量（对数）")
    a.set_title("播放量 vs 互动率", loc="left")
    _style(a, "both")
    top = pv.nlargest(8, "engagement_rate")
    _barh(ax[1, 1], [_short(t) for t in top["title"]], top["engagement_rate"].tolist(), color=SERIES[2],
          fmt=lambda v: f"{v * 100:.1f}%", title="互动率最高的稿件")
    ax[1, 1].xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    return _finish(fig)


def fig_retention(res):
    r = res["retention"]
    fig, ax = _fig(2, 2)
    a = ax[0, 0]
    curves = r.get("curves") or {}
    if curves:
        items = sorted(curves.values(), key=lambda s: -s["start"])[:5]
        allx = np.linspace(0.01, 1, 100)
        avg = np.mean([np.interp(allx, s["x"], s["y"]) for s in curves.values()], axis=0)
        for i, s in enumerate(items):
            a.plot(s["x"], s["y"], color=SERIES[i], linewidth=1.4, alpha=0.9, label=_short(s["title"], 12))
        a.plot(allx, avg, color=INK, linewidth=2.4, label="平均留存")
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        a.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        a.set_xlabel("视频进度")
        a.legend(loc="upper right", fontsize=7)
        a.set_title("观众留存曲线", loc="left")
    else:
        _empty(a, "暂无留存曲线（YouTube 登录后自动获取）")
    a = ax[0, 1]
    bv = r.get("by_video")
    if bv is not None and len(bv):
        colors = np.where(bv["retention_gap"] >= 0, POS_COLOR, NEG_COLOR)
        a.scatter(bv["duration"] / 60, bv["avg_view_pct"], c=colors, s=24, alpha=0.8, edgecolor=SURFACE, linewidth=1)
        xs = np.linspace(bv["duration"].min(), bv["duration"].max(), 100)
        a.plot(xs / 60, np.polyval(r["fit"], np.log(xs)), color=INK2, linewidth=1.5, label="同时长期望完播率")
        a.set_xscale("log")
        a.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        a.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        a.set_xlabel("时长（分钟）· 蓝 = 高于期望，红 = 低于期望")
        a.legend(loc="upper right")
        a.set_title("完播率诊断", loc="left")
        _style(a, "both")
    else:
        _empty(a, "暂无完播率数据（B站可导入创作中心表格）")
    a = ax[1, 0]
    b = r.get("bounce")
    if b is not None and len(b):
        a.hist(b["bounce_3s"], bins=15, color=SERIES[1], edgecolor=SURFACE, linewidth=2)
        a.axvline(b["bounce_3s"].mean(), color=INK, linewidth=1.5, linestyle=(0, (3, 3)))
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        a.set_title("3 秒跳出率分布（虚线 = 平均）", loc="left")
    else:
        _empty(a, "暂无 3 秒跳出率数据")
    a = ax[1, 1]
    if b is not None and len(b) >= 3:
        worst = b.nlargest(8, "bounce_3s")
        _barh(a, [_short(t) for t in worst["title"]], worst["bounce_3s"].tolist(), color=SERIES[1],
              fmt=lambda v: f"{v * 100:.0f}%", title="跳出率最高的稿件（优先优化开头）")
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    else:
        _empty(a)
    return _finish(fig)


def fig_content(res):
    c = res["content"]
    fig, ax = _fig(2, 2)
    if not c.get("ok"):
        for a in ax.flat:
            _empty(a)
        return _finish(fig)
    cat = c["category"].head(8)
    _barh(ax[0, 0], cat.index, cat["表现指数"].tolist(), fmt=lambda v: f"{v:.2f}x", title="分区/类别表现指数")
    kw = c.get("keywords")
    a = ax[0, 1]
    if isinstance(kw, pd.DataFrame) and len(kw):
        sel = pd.concat([kw.head(7), kw.tail(5)]).drop_duplicates()
        vals = sel["提升度"].tolist()
        a.barh(range(len(sel)), vals, color=[POS_COLOR if v >= 0 else NEG_COLOR for v in vals], height=0.62)
        a.set_yticks(range(len(sel)), sel.index)
        a.invert_yaxis()
        a.axvline(0, color=AXIS, linewidth=1)
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        _style(a, "x")
        a.set_title("标题关键词对播放的提升度", loc="left")
    else:
        _empty(a, "关键词样本不足（每个词至少出现 3 次）")
    tf = c.get("title_features")
    a = ax[1, 0]
    if isinstance(tf, pd.DataFrame) and len(tf):
        vals = tf["提升"].tolist()
        a.barh(range(len(tf)), vals, color=[POS_COLOR if v >= 0 else NEG_COLOR for v in vals], height=0.62)
        a.set_yticks(range(len(tf)), tf.index)
        a.invert_yaxis()
        a.axvline(0, color=AXIS, linewidth=1)
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        _style(a, "x")
        a.set_title("标题特征的影响（有 vs 无）", loc="left")
    else:
        _empty(a)
    tl = c.get("title_len")
    a = ax[1, 1]
    if tl is not None and len(tl):
        a.bar([str(i) for i in tl.index], tl["median"], color=SERIES[0], width=0.6)
        a.axhline(1, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
        a.set_title("标题长度 vs 表现指数", loc="left")
    else:
        _empty(a)
    return _finish(fig)


def fig_outliers(res):
    o = res["outliers"]
    fig, ax = _fig(1, 1, h=5.4)
    a = ax[0, 0]
    if not o.get("ok"):
        _empty(a, "数据不足")
        return _finish(fig)
    m = o["all"]
    normal = m[(m["z"] <= 1.3) & (m["z"] >= -1.2)]
    a.scatter(normal["publish_time"], normal["perf_index"], s=22, color=NEUTRAL, label="正常")
    a.scatter(o["hits"]["publish_time"], o["hits"]["perf_index"], s=46, color=POS_COLOR,
              edgecolor=SURFACE, linewidth=1.5, label="爆款")
    a.scatter(o["flops"]["publish_time"], o["flops"]["perf_index"], s=46, color=NEG_COLOR,
              edgecolor=SURFACE, linewidth=1.5, label="低于预期")
    for _, r in o["hits"].head(4).iterrows():
        a.annotate(_short(r["title"], 12), (r["publish_time"], r["perf_index"]), xytext=(5, 4),
                   textcoords="offset points", fontsize=7.5, color=INK2)
    a.set_yscale("log")
    a.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}x"))
    a.axhline(1, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
    a.legend(loc="upper left")
    a.set_title("爆款诊断：每个稿件相对同期中位水平的倍数（对数刻度）", loc="left")
    return _finish(fig)


def fig_cadence(res):
    c = res["cadence"]
    fig, ax = _fig(1, 2, h=4.6)
    if not c.get("ok"):
        for a in ax.flat:
            _empty(a)
        return _finish(fig)
    w = c["weekly"]
    a = ax[0, 0]
    a.bar(w.index, w.values, width=5, color=SERIES[0])
    a.set_title("近 26 周每周投稿数", loc="left")
    fig.autofmt_xdate(rotation=0, ha="center")
    a = ax[0, 1]
    g = c.get("gap_perf")
    if g is not None and len(g):
        a.bar([str(i) for i in g.index], g["median"], color=SERIES[2], width=0.6)
        for i, (v, n) in enumerate(zip(g["median"], g["count"])):
            a.text(i, v, f"{v:.2f}x\n(n={n})", ha="center", va="bottom", fontsize=7.5, color=INK2)
        a.axhline(1, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
        a.set_title("距上次更新的间隔 vs 表现", loc="left")
    else:
        _empty(a)
    return _finish(fig)


def fig_lifecycle(res):
    lc = res["lifecycle"]
    fig, ax = _fig(1, 2, h=4.6)
    a = ax[0, 0]
    cur = lc.get("curve")
    if cur is not None:
        a.plot(cur.index, cur.values, color=SERIES[0], marker="o", markersize=5)
        a.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        a.set_xlabel("发布后天数")
        a.set_title("播放累积曲线（占 14 天播放的比例）", loc="left")
    else:
        _empty(a, "需要多次快照（开启自动监控）")
    a = ax[0, 1]
    ev = lc.get("evergreen")
    if ev:
        _barh(a, [_short(t) for t, _ in ev], [g for _, g in ev], color=SERIES[2],
              fmt=lambda v: fnum(v), title="长尾常青稿件（日均新增播放）")
    else:
        _empty(a, "暂无常青稿件数据")
    return _finish(fig)


def fig_conversion(res):
    c = res["conversion"]
    fig, ax = _fig(1, 2, h=4.8)
    if not c.get("ok"):
        for a in ax.flat:
            _empty(a, "暂无转粉数据")
        return _finish(fig)
    m = c["data"]
    a = ax[0, 0]
    sc = m.dropna(subset=["engagement_rate"])
    a.scatter(sc["engagement_rate"], sc["subs_per_1k"], s=24, color=SERIES[0], alpha=0.75, edgecolor=SURFACE, linewidth=1)
    a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    a.set_xlabel("互动率")
    a.set_ylabel("千播涨粉")
    a.set_title("互动率 vs 转粉率" + ("（估算）" if c["estimated"] else ""), loc="left")
    _style(a, "both")
    top = m.nlargest(10, "subs_per_1k")
    _barh(ax[0, 1], [_short(t) for t in top["title"]], top["subs_per_1k"].tolist(), color=SERIES[2],
          fmt=lambda v: f"{v:.1f}", title="转粉效率 Top10（每千次播放涨粉）")
    return _finish(fig)


AUDIENCE_TITLES = {"traffic": "流量来源", "device": "观看设备", "age": "年龄分布", "gender": "性别分布",
                   "country": "地区分布", "subscribed": "粉丝 / 非粉丝播放", "playback": "播放位置"}


def fig_audience(res):
    b = res["audience"].get("breakdowns") or {}
    keys = [k for k in AUDIENCE_TITLES if b.get(k)]
    if not keys:
        fig, ax = _fig(1, 1, h=4)
        _empty(ax[0, 0], "暂无受众数据（YouTube 登录后自动获取）")
        return _finish(fig)
    cols = 3 if len(keys) > 4 else 2
    rows = int(np.ceil(len(keys) / cols))
    fig, ax = _fig(rows, cols, h=3.3 * rows)
    for a, k in zip(ax.flat, keys):
        d = b[k]
        total = sum(d.values()) or 1
        items = sorted(d.items(), key=lambda x: -x[1])[:8]
        _barh(a, [i[0] for i in items], [i[1] / total for i in items], color=SERIES[0],
              fmt=lambda v: f"{v * 100:.0f}%", title=AUDIENCE_TITLES[k])
        a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    for a in list(ax.flat)[len(keys):]:
        a.set_axis_off()
    return _finish(fig)


def fig_comments(res):
    c = res["comments"]
    fig, ax = _fig(1, 2, h=4.8)
    if not c.get("ok"):
        for a in ax.flat:
            _empty(a, "暂无评论数据")
        return _finish(fig)
    a = ax[0, 0]
    s = c["sentiment"]
    left = 0
    colors = {"正面": POS_COLOR, "中性": NEUTRAL, "负面": NEG_COLOR}
    for k, v in s.items():
        a.barh([0], [v], left=left, color=colors[k], height=0.5, edgecolor=SURFACE, linewidth=2)
        if v > 0.06:
            a.text(left + v / 2, 0, f"{k}\n{v * 100:.0f}%", ha="center", va="center",
                   color="#ffffff" if k != "中性" else INK, fontsize=9)
        left += v
    a.set_xlim(0, 1)
    a.set_yticks([])
    a.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    a.set_title("评论情感分布", loc="left")
    kw = c["keywords"][:15]
    if kw:
        _barh(ax[0, 1], [w for w, _ in kw], [n for _, n in kw], color=SERIES[0], fmt=lambda v: f"{v:.0f}",
              title="评论高频词")
    else:
        _empty(ax[0, 1])
    return _finish(fig)


def fig_competitors(res):
    c = res["competitors"]
    if not c.get("ok"):
        fig, ax = _fig(1, 1, h=4)
        _empty(ax[0, 0], "添加竞品账号后显示对比")
        return _finish(fig)
    rows = c["rows"][:8]
    names = [_short(r["账号"], 10) for r in rows]
    colors = SERIES[:len(rows)]
    fig, ax = _fig(2, 2)
    metrics = [("粉丝", big_fmt, lambda v: fnum(v)), ("播放中位数", big_fmt, lambda v: fnum(v)),
               ("互动率", PercentFormatter(1, decimals=0), lambda v: f"{v * 100:.1f}%"),
               ("周更数", None, lambda v: f"{v:.1f}")]
    for a, (k, formatter, fmt) in zip(ax.flat, metrics):
        vals = [r[k] if not pd.isna(r[k]) else 0 for r in rows]
        a.bar(range(len(rows)), vals, color=colors, width=0.6, edgecolor=SURFACE, linewidth=2)
        for i, v in enumerate(vals):
            a.text(i, v, fmt(v), ha="center", va="bottom", fontsize=7.5, color=INK2)
        a.set_xticks(range(len(rows)), names, fontsize=8)
        if formatter:
            a.yaxis.set_major_formatter(formatter)
        a.set_title(k + ("（第一个为你的账号）" if k == "粉丝" else ""), loc="left")
    return _finish(fig)


PAGES = [
    ("overview", "总览", fig_overview),
    ("growth", "增长趋势", fig_growth),
    ("timing", "发布时间", fig_timing),
    ("duration", "时长分析", fig_duration),
    ("engagement", "互动分析", fig_engagement),
    ("retention", "留存与跳出", fig_retention),
    ("content", "内容与标题", fig_content),
    ("outliers", "爆款诊断", fig_outliers),
    ("conversion", "粉丝转化", fig_conversion),
    ("cadence", "更新节奏", fig_cadence),
    ("lifecycle", "生命周期", fig_lifecycle),
    ("audience", "流量与受众", fig_audience),
    ("comments", "评论洞察", fig_comments),
    ("competitors", "竞品对比", fig_competitors),
]


def to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    return buf.getvalue()
