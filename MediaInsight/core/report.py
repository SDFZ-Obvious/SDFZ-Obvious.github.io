"""运营报告：文字版（界面显示）、HTML（含图表，可直接发给团队）、Excel（明细数据）。"""
import base64
import html
from datetime import datetime

import pandas as pd

from . import APP_NAME, charts
from .analytics import fdur, fnum, fpct

SECTION_ORDER = [(key, title) for key, title, _ in charts.PAGES]


def text_report(res) -> str:
    ds = res["dataset"]
    lines = [f"# {ds.name} · {ds.platform_name} 运营分析报告",
             f"生成时间：{datetime.now():%Y-%m-%d %H:%M}    稿件数：{len(res['df'])}"
             + ("    （演示数据）" if ds.is_demo else ""), ""]
    h = res.get("health", {})
    if h.get("scores"):
        lines.append(f"## 账号健康度：{h['total']:.0f} 分（{h['grade']} 级）")
        lines.append("    " + "  ".join(f"{k} {v:.0f}" for k, v in h["scores"].items()))
        lines.append("")
    ov = res.get("overview", {})
    if ov.get("kpis"):
        lines.append("## 核心指标")
        for name, val, sub in ov["kpis"]:
            lines.append(f"  · {name}：{val}（{sub}）")
        lines.append("")
    if res.get("recommendations"):
        lines.append("## 行动清单（按优先级）")
        for i, r in enumerate(res["recommendations"], 1):
            lines.append(f"  {i}. [{r['优先级']}] {r['方向']}：{r['建议']}")
        lines.append("")
    for key, title in SECTION_ORDER:
        sec = res.get(key) or {}
        ins = sec.get("insights") or []
        if not ins:
            continue
        lines.append(f"## {title}")
        lines += [f"  · {s}" for s in ins]
        if key == "retention" and sec.get("suggestions"):
            lines.append("  稿件内容留存建议：")
            lines += [f"    - {s}" for s in sec["suggestions"]]
        if key == "comments" and sec.get("requests"):
            lines.append("  观众诉求（可直接作为选题）：")
            lines += [f"    - {s}" for s in sec["requests"][:10]]
        lines.append("")
    if ds.notes:
        lines.append("## 数据说明")
        lines += [f"  · {n}" for n in ds.notes]
    return "\n".join(lines)


CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f9f9f7;color:#0b0b0b;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding:28px}
h1{font-size:24px;margin:0 0 4px} h2{font-size:18px;margin:32px 0 10px;border-left:4px solid #2a78d6;padding-left:10px}
.sub{color:#52514e;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin-top:18px}
.tile{background:#fcfcfb;border:1px solid rgba(11,11,11,.10);border-radius:10px;padding:12px 14px}
.tile .k{color:#52514e;font-size:12px}.tile .v{font-size:22px;font-weight:600;margin:4px 0}.tile .s{color:#898781;font-size:11px}
.card{background:#fcfcfb;border:1px solid rgba(11,11,11,.10);border-radius:10px;padding:16px 18px;margin-bottom:14px}
ul{margin:6px 0 0 18px;padding:0} li{margin:4px 0;line-height:1.55}
img{max-width:100%;border-radius:6px;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:12px} th,td{border-bottom:1px solid #e1e0d9;padding:6px 8px;text-align:left}
th{color:#52514e;font-weight:600;background:#f0efec} td.n{text-align:right;font-variant-numeric:tabular-nums}
.p-高{color:#d03b3b;font-weight:600}.p-中{color:#b07a00;font-weight:600}.p-低{color:#52514e}
.foot{color:#898781;font-size:12px;margin-top:40px}
"""


def html_report(res, path, progress=lambda p, m: None):
    ds = res["dataset"]
    e = html.escape
    parts = [f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{e(ds.name)} 运营分析报告</title>"
             f"<style>{CSS}</style></head><body><div class='wrap'>",
             f"<h1>{e(ds.name)} · {e(ds.platform_name)} 运营分析报告</h1>",
             f"<div class='sub'>生成时间 {datetime.now():%Y-%m-%d %H:%M} · 稿件 {len(res['df'])} 个"
             + (" · 演示数据" if ds.is_demo else "") + "</div>"]
    kpis = res.get("overview", {}).get("kpis") or []
    h = res.get("health", {})
    tiles = ([("健康度", f"{h['total']:.0f} 分", f"{h['grade']} 级")] if h.get("scores") else []) + list(kpis)
    parts.append("<div class='tiles'>" + "".join(
        f"<div class='tile'><div class='k'>{e(k)}</div><div class='v'>{e(str(v))}</div><div class='s'>{e(s)}</div></div>"
        for k, v, s in tiles) + "</div>")
    if res.get("recommendations"):
        parts.append("<h2>行动清单</h2><div class='card'><table><tr><th>优先级</th><th>方向</th><th>建议</th></tr>")
        for r in res["recommendations"]:
            parts.append(f"<tr><td class='p-{r['优先级']}'>{r['优先级']}</td><td>{e(r['方向'])}</td><td>{e(r['建议'])}</td></tr>")
        parts.append("</table></div>")
    for i, (key, title, builder) in enumerate(charts.PAGES):
        progress(i / len(charts.PAGES), f"生成图表：{title}")
        sec = res.get(key) or {}
        parts.append(f"<h2>{e(title)}</h2><div class='card'>")
        ins = list(sec.get("insights") or [])
        if key == "retention":
            ins += [f"建议：{s}" for s in sec.get("suggestions", [])]
        if ins:
            parts.append("<ul>" + "".join(f"<li>{e(s)}</li>" for s in ins) + "</ul>")
        if key == "comments" and sec.get("requests"):
            parts.append("<p><b>观众诉求：</b></p><ul>" + "".join(f"<li>{e(s)}</li>" for s in sec["requests"][:10]) + "</ul>")
        try:
            png = charts.to_png(builder(res))
            parts.append(f"<img alt='{e(title)}' src='data:image/png;base64,{base64.b64encode(png).decode()}'>")
        except Exception as ex:  # noqa: BLE001
            parts.append(f"<p class='sub'>图表生成失败：{e(str(ex))}</p>")
        parts.append("</div>")
    df = res["df"]
    if not df.empty:
        parts.append("<h2>稿件明细（按播放排序，前 50）</h2><div class='card'><table><tr><th>标题</th><th>发布时间</th>"
                     "<th>时长</th><th>播放</th><th>互动率</th><th>完播率</th><th>3秒跳出</th><th>千播涨粉</th><th>表现指数</th></tr>")
        for _, r in df.nlargest(50, "views").iterrows():
            parts.append(
                f"<tr><td><a href='{e(str(r['url']))}'>{e(str(r['title']))}</a></td><td>{r['publish_time']:%Y-%m-%d %H:%M}</td>"
                f"<td class='n'>{fdur(r['duration'])}</td><td class='n'>{fnum(r['views'])}</td>"
                f"<td class='n'>{fpct(r['engagement_rate'])}</td><td class='n'>{fpct(r['avg_view_pct'])}</td>"
                f"<td class='n'>{fpct(r['bounce_3s'])}</td>"
                f"<td class='n'>{'—' if pd.isna(r['subs_per_1k']) else f'{r['subs_per_1k']:.2f}'}</td>"
                f"<td class='n'>{'—' if pd.isna(r['perf_index']) else f'{r['perf_index']:.2f}x'}</td></tr>")
        parts.append("</table></div>")
    if ds.notes:
        parts.append("<h2>数据说明</h2><div class='card'><ul>" + "".join(f"<li>{e(n)}</li>" for n in ds.notes) + "</ul></div>")
    parts.append(f"<div class='foot'>由 {APP_NAME} 生成 · 表现指数 = 稿件播放 ÷ 相邻发布稿件的中位播放，用于抵消账号成长和发布时长差异。</div>")
    parts.append("</div></body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    progress(1, "完成")


VIDEO_EXPORT = {
    "title": "标题", "url": "链接", "publish_time": "发布时间", "duration": "时长(秒)", "category": "分类",
    "tags": "标签", "views": "播放", "likes": "点赞", "coins": "投币", "favorites": "收藏", "comments": "评论",
    "shares": "分享", "danmaku": "弹幕", "engagement_rate": "互动率", "triple_rate": "三连率",
    "avg_view_pct": "完播率", "avg_view_duration": "平均观看(秒)", "bounce_3s": "3秒跳出率",
    "subs_gained": "涨粉", "subs_per_1k": "千播涨粉", "impressions": "曝光", "ctr": "点击率",
    "perf_index": "表现指数", "views_per_day": "日均播放",
}


def excel_report(res, path):
    df = res["df"]
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        cols = [c for c in VIDEO_EXPORT if c in df.columns]
        df[cols].rename(columns=VIDEO_EXPORT).to_excel(w, sheet_name="稿件明细", index=False)
        if res.get("recommendations"):
            pd.DataFrame(res["recommendations"]).to_excel(w, sheet_name="行动清单", index=False)
        d = res.get("duration", {}).get("table")
        if d is not None:
            d.to_excel(w, sheet_name="时长分析")
        c = res.get("content", {})
        for k, name in (("category", "分类表现"), ("tags", "标签表现"), ("keywords", "标题关键词")):
            if isinstance(c.get(k), pd.DataFrame) and len(c[k]):
                c[k].to_excel(w, sheet_name=name)
        t = res.get("timing", {})
        if t.get("ok"):
            heat = t["heat"].copy()
            heat.index = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            heat.columns = [f"{c * 3:02d}-{c * 3 + 3:02d}点" for c in heat.columns]
            heat.to_excel(w, sheet_name="发布时段热力")
        ds = res["dataset"]
        if not ds.daily.empty:
            ds.daily.to_excel(w, sheet_name="每日数据", index=False)
        cp = res.get("competitors", {})
        if cp.get("rows"):
            pd.DataFrame(cp["rows"]).to_excel(w, sheet_name="竞品对比", index=False)
        for ws in w.book.worksheets:
            for col in ws.columns:
                width = max(len(str(cell.value or "")) for cell in col[:60])
                ws.column_dimensions[col[0].column_letter].width = min(max(width * 1.6, 8), 60)
