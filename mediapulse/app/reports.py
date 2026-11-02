"""Standalone report generation (HTML / PDF via Edge / XLSX)."""
from __future__ import annotations

import html
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import analytics
from .config import EXPORT_DIR, REPORT_DIR, WEB_DIR, PLATFORM_LABELS
from .llm import deepseek_summary
from .store import Store

log = logging.getLogger("mediapulse.reports")

BRAND = "#7c5cff"
PINK = "#fb7299"
CYAN = "#22d3ee"


def _safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fa5]+", "_", text)[:40].strip("_") or "account"


def _fmt(value: float) -> str:
    value = float(value or 0)
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.1f}万"
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:,.0f}"


def _kpi_cards(kpis: list[dict]) -> str:
    out = []
    for k in kpis:
        delta = float(k.get("delta") or 0)
        cls = "up" if delta > 0 else ("down" if delta < 0 else "flat")
        sign = "+" if delta > 0 else ""
        unit = k.get("delta_unit", "")
        val = k.get("value")
        if isinstance(val, float):
            val = f"{val:,.1f}" if val < 1000 else _fmt(val)
        else:
            val = _fmt(val)
        out.append(f"""
        <div class="kpi">
          <div class="kpi-label">{html.escape(k['label'])}</div>
          <div class="kpi-value">{val}<span>{html.escape(k.get('unit',''))}</span></div>
          <div class="kpi-delta {cls}">{sign}{delta:g}{unit} <span>较上期</span></div>
          <div class="kpi-hint">{html.escape(k.get('hint',''))}</div>
        </div>""")
    return "".join(out)


def _insight_cards(insights: list[dict]) -> str:
    icons = {"critical": "!", "warning": "!", "opportunity": "↗", "good": "✓", "info": "i"}
    out = []
    for item in insights:
        sev = item.get("severity", "info")
        out.append(f"""
        <div class="insight {sev}">
          <div class="insight-icon">{icons.get(sev, 'i')}</div>
          <div>
            <div class="insight-title">{html.escape(item.get('title',''))}</div>
            <div class="insight-body">{html.escape(item.get('body',''))}</div>
            <div class="insight-action">建议：{html.escape(item.get('action',''))}</div>
          </div>
        </div>""")
    return "".join(out)


def _video_rows(videos: list[dict], limit: int = 20) -> str:
    rows = []
    for v in videos[:limit]:
        rows.append(f"""
        <tr>
          <td class="title-cell">{html.escape(v['title'][:46])}</td>
          <td>{v.get('published_date','')[:10]}</td>
          <td>{v.get('duration',0)//60}:{v.get('duration',0)%60:02d}</td>
          <td>{_fmt(v.get('period_views',0))}</td>
          <td>{_fmt(v.get('total_views',0))}</td>
          <td>{v.get('engagement_rate',0):.2f}%</td>
          <td>{v.get('conversion',0):.2f}%</td>
          <td>{f"{v['retention3']*100:.1f}%" if v.get('retention3') is not None else '—'}</td>
        </tr>""")
    return "".join(rows)


def _duration_rows(rows: list[dict]) -> str:
    out = []
    for r in rows:
        out.append(f"""
        <tr><td>{html.escape(r['label'])}</td><td>{r['count']}</td><td>{_fmt(r['avg_views'])}</td>
        <td>{r['engagement']:.2f}%</td><td>{r['conversion']:.2f}%</td>
        <td>{f"{r['retention3']:.1f}%" if r.get('retention3') is not None else '—'}</td></tr>""")
    return "".join(out)


def build_html(store: Store, account: dict, days: int = 30) -> tuple[str, dict]:
    dash = analytics.build_dashboard(store, account, days)
    table = analytics.video_table(store, account, 90)
    retention = analytics.retention_page(store, account, 90)
    platform = PLATFORM_LABELS.get(account["platform"], account["platform"])
    generated = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    health = dash["health"]
    best_slot = dash["best_slots"][0]["label"] if dash["best_slots"] else "样本不足"
    # Choose the most viewed video with a retention curve.
    curve = None
    if retention["curves"]:
        viewed = {v["id"]: v["views"] for v in retention["videos"]}
        curve = max(retention["curves"], key=lambda c: viewed.get(c["id"], 0))
    retention_series = []
    if curve:
        retention_series.append({
            "name": "当前视频", "type": "line", "smooth": True, "symbol": "none",
            "data": [round(float(p["audience_ratio"]) * 100, 2) for p in curve["points"]],
            "lineStyle": {"width": 3, "color": PINK},
            "areaStyle": {"color": "rgba(251,114,153,.12)"},
        })
    if retention["avg_curve"]:
        retention_series.append({
            "name": "账号平均", "type": "line", "smooth": True, "symbol": "none",
            "data": retention["avg_curve"], "lineStyle": {"width": 2, "color": CYAN, "type": "dashed"},
        })

    heat = [[c["hour"], c["weekday"], c["value"]] for c in dash["heatmap"] if c["count"]]
    max_heat = max([h[2] for h in heat], default=1)
    chart_data = {
        "dates": [s["label"] for s in dash["series"]],
        "views": [s["views"] for s in dash["series"]],
        "followers": [s["followers"] for s in dash["series"]],
        "sources": [{"name": s["source"], "value": s["views"]} for s in dash["sources"]],
        "duration": dash["duration"],
        "heat": heat,
        "maxHeat": max_heat,
        "curveX": [round(float(p["point"]) * 100, 0) for p in (curve["points"] if curve else [])],
        "retentionSeries": retention_series,
        "top": [{"name": v["title"][:28], "value": v["period_views"]} for v in dash["top_videos"][:8]][::-1],
    }
    echarts_js = (WEB_DIR / "vendor" / "echarts.min.js").read_text(encoding="utf-8")
    styles = """
    :root{--bg:#0b0d14;--panel:#141826;--line:rgba(255,255,255,.08);--text:#eef0f8;--muted:#9aa3b8;--brand:#7c5cff;--pink:#fb7299;--cyan:#22d3ee;--green:#34d399;--amber:#fbbf24;--red:#f87171}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 700px at 10% -10%,rgba(124,92,255,.18),transparent 60%),radial-gradient(900px 500px at 100% 0%,rgba(34,211,238,.08),transparent 55%),var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC","Noto Sans SC",Arial,sans-serif;line-height:1.65}
    .page{max-width:1180px;margin:0 auto;padding:46px 42px 70px}
    .cover{display:flex;justify-content:space-between;gap:30px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:32px;margin-bottom:30px}
    .brand{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:13px;letter-spacing:.14em}
    .mark{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--brand),var(--pink));display:grid;place-items:center;font-weight:800;color:white}
    h1{font-size:34px;line-height:1.2;margin:18px 0 8px;letter-spacing:-.5px}
    .sub{color:var(--muted);font-size:14px}.cover-right{text-align:right;min-width:200px}
    .score{font-size:58px;font-weight:800;background:linear-gradient(135deg,#fff,#a78bfa);-webkit-background-clip:text;background-clip:text;color:transparent;line-height:1}
    .score-label{font-size:12px;color:var(--muted);letter-spacing:.16em;text-transform:uppercase}
    .summary{font-size:15px;color:#cdd3e3;background:linear-gradient(90deg,rgba(124,92,255,.12),rgba(34,211,238,.04));border:1px solid rgba(124,92,255,.22);border-radius:16px;padding:18px 22px;margin:0 0 26px}
    .ai-summary{font-size:13px;color:#c7cede;background:rgba(34,211,238,.045);border:1px solid rgba(34,211,238,.18);border-left:3px solid var(--cyan);border-radius:14px;padding:16px 20px;margin:-10px 0 24px;line-height:1.9;white-space:pre-wrap}
    .ai-summary .ai-label{font-size:9px;letter-spacing:.16em;color:#7fd4e2;margin-bottom:6px}
    .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:26px}
    .kpi{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:15px 14px}
    .kpi-label{font-size:12px;color:var(--muted)}.kpi-value{font-size:23px;font-weight:700;margin:4px 0 2px;letter-spacing:-.4px}
    .kpi-value span{font-size:12px;color:var(--muted);font-weight:500;margin-left:2px}
    .kpi-delta{font-size:11px;color:var(--muted)}.kpi-delta.up{color:var(--green)}.kpi-delta.down{color:var(--red)}
    .kpi-delta span{color:#6b7280;margin-left:2px}.kpi-hint{font-size:10px;color:#606a80;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .grid2{display:grid;grid-template-columns:1.45fr 1fr;gap:16px}.grid2b{display:grid;grid-template-columns:1fr 1fr;gap:16px}
    .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:19px 20px;margin-bottom:16px;break-inside:avoid}
    .card h2{font-size:15px;margin:0 0 4px;font-weight:600}.card .hint{font-size:11px;color:var(--muted);margin-bottom:12px}
    .chart{width:100%;height:270px}.chart.tall{height:330px}
    .section-title{font-size:19px;margin:34px 0 14px;display:flex;align-items:center;gap:10px}.section-title:before{content:"";width:4px;height:18px;border-radius:2px;background:linear-gradient(var(--brand),var(--pink))}
    .insights{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .insight{display:flex;gap:12px;background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--brand);border-radius:12px;padding:14px 15px}
    .insight.warning{border-left-color:var(--amber)}.insight.critical{border-left-color:var(--red)}.insight.good{border-left-color:var(--green)}.insight.opportunity{border-left-color:var(--cyan)}
    .insight-icon{width:22px;height:22px;border-radius:50%;background:rgba(124,92,255,.18);display:grid;place-items:center;font-size:12px;color:#c4b5fd;flex:none;margin-top:2px}
    .insight-title{font-weight:600;font-size:13px}.insight-body{font-size:12px;color:#b7bfd1;margin:3px 0}.insight-action{font-size:11px;color:#8f9ab2}
    table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;color:var(--muted);font-weight:500;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
    td{padding:9px 8px;border-bottom:1px solid rgba(255,255,255,.045);color:#d7dce8}tr:last-child td{border-bottom:0}
    .title-cell{max-width:330px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:10px;background:rgba(124,92,255,.14);color:#c4b5fd}
    .method{font-size:11px;color:#7d879e;border-top:1px solid var(--line);margin-top:34px;padding-top:16px}
    .footer{display:flex;justify-content:space-between;color:#606a80;font-size:10px;margin-top:18px}
    .print-btn{position:fixed;right:24px;bottom:24px;border:0;background:linear-gradient(135deg,var(--brand),#a855f7);color:#fff;border-radius:12px;padding:12px 18px;font-size:13px;cursor:pointer;box-shadow:0 10px 30px rgba(124,92,255,.35)}
    @media(max-width:900px){.kpis{grid-template-columns:repeat(3,1fr)}.grid2,.grid2b{grid-template-columns:1fr}.insights{grid-template-columns:1fr}.page{padding:26px 18px}.cover{flex-direction:column}.cover-right{text-align:left}}
    @media print{body{background:#0b0d14 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}.page{max-width:none;padding:22px}.print-btn{display:none}.card{box-shadow:none}@page{size:A4;margin:10mm}.section-title{break-after:avoid}}
    """
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(account['name'])} · 账号运营分析报告</title>
<style>{styles}</style></head>
<body><div class="page">
  <div class="cover">
    <div>
      <div class="brand"><div class="mark">M</div> MEDIAPULSE · 脉策</div>
      <h1>{html.escape(account['name'])}</h1>
      <div class="sub">{platform} · {html.escape(str(account.get('uid','')))} · 分析周期 {dash['period']['label']}（{days} 天）</div>
    </div>
    <div class="cover-right">
      <div class="score-label">账号健康度</div>
      <div class="score">{health['score']}<small style="font-size:16px;color:#9aa3b8"> / 100</small></div>
      <div class="sub">评级 {health['grade']} · 生成于 {generated}</div>
    </div>
  </div>
  <div class="summary">{dash['summary'].replace('**','')}</div>
  <!--AI_SUMMARY-->
  <div class="kpis">{_kpi_cards(dash['kpis'])}</div>

  <div class="grid2">
    <div class="card"><h2>播放与粉丝走势</h2><div class="hint">柱状为新增播放，折线为粉丝总量</div><div id="trend" class="chart tall"></div></div>
    <div class="card"><h2>流量来源</h2><div class="hint">最近可用周期</div><div id="sources" class="chart tall"></div></div>
  </div>

  <div class="grid2b">
    <div class="card"><h2>最佳发布时间热力</h2><div class="hint">颜色越亮，首 7 日播放越高</div><div id="heat" class="chart"></div></div>
    <div class="card"><h2>时长 × 表现</h2><div class="hint">不同内容长度的首 7 日播放与转粉</div><div id="duration" class="chart"></div></div>
  </div>

  <div class="card">
    <h2>受众留存曲线</h2>
    <div class="hint">{html.escape(retention['note'])} · 平均 3 秒留存 {retention['avg_retention3']}%，跳出 {retention['avg_bounce3']}%</div>
    <div id="retention" class="chart"></div>
  </div>

  <div class="section-title">核心诊断与行动建议</div>
  <div class="insights">{_insight_cards(dash['insights'])}</div>

  <div class="section-title">内容表现明细</div>
  <div class="card">
    <table><thead><tr><th>标题</th><th>发布</th><th>时长</th><th>周期播放</th><th>总播放</th><th>互动率</th><th>转粉率</th><th>3秒留存</th></tr></thead>
    <tbody>{_video_rows(table['videos'])}</tbody></table>
  </div>

  <div class="grid2b">
    <div class="card"><h2>时长段诊断</h2>
      <table><thead><tr><th>时长段</th><th>样本</th><th>首7日播放</th><th>互动率</th><th>转粉率</th><th>3秒留存</th></tr></thead>
      <tbody>{_duration_rows(dash['duration'])}</tbody></table>
    </div>
    <div class="card"><h2>增长引擎</h2><div id="top" class="chart"></div></div>
  </div>

  <div class="card">
    <h2>运营结论</h2>
    <div style="font-size:13px;color:#c3cad9;line-height:1.9">
      <p><b>健康度拆解：</b>{' / '.join(f"{s['label']} {s['value']}" for s in health['subscores'])}。{html.escape(health['verdict'])}</p>
      <p><b>最佳时段：</b>{html.escape(best_slot)}。建议把重点稿件前置到该时段，并在发布后 30 分钟内完成首轮评论互动。</p>
      <p><b>内容策略：</b>{html.escape((dash['tags'][0]['tag'] if dash['tags'] else '样本不足'))} 是当前最强标签；建议保持主线稳定，同时用 20% 的更新量测试相邻选题。</p>
      <p><b>下一步：</b>先优化 3 秒开场与标题承诺，把高播放稿件的结构复用 3 次；连续两周复盘留存与转粉的变化。</p>
    </div>
  </div>

  <div class="method">{html.escape(dash['platform_note'])}<br>
  数据口径：播放为周期内新增；互动率 =（点赞+投币+收藏+评论+分享+弹幕）/ 播放；转粉率 = 净增粉丝 / 播放。
  本报告由 MediaPulse 本地生成，原始数据保存在本机。</div>
  <div class="footer"><span>MEDIAPULSE · 自媒体数据驾驶舱</span><span>{generated}</span></div>
</div>
<button class="print-btn" onclick="window.print()">打印 / 导出 PDF</button>
<script>{echarts_js}</script>
<script>
const D = {json.dumps(chart_data, ensure_ascii=False)};
const palette = ['#7c5cff','#fb7299','#22d3ee','#34d399','#fbbf24','#f87171','#a78bfa'];
function init(id, option){{const el=document.getElementById(id); if(!el)return; const c=echarts.init(el,null,{{renderer:'canvas'}}); c.setOption(option); window.addEventListener('resize',()=>c.resize());}}
init('trend', {{
  tooltip:{{trigger:'axis'}}, legend:{{textStyle:{{color:'#9aa3b8'}},top:0}},
  grid:{{left:46,right:52,top:36,bottom:28}},
  xAxis:{{type:'category',data:D.dates,axisLine:{{lineStyle:{{color:'#2a3043'}}}},axisLabel:{{color:'#7d879e',fontSize:10}}}},
  yAxis:[{{type:'value',axisLabel:{{color:'#7d879e',fontSize:10}},splitLine:{{lineStyle:{{color:'rgba(255,255,255,.05)'}}}}}},
         {{type:'value',axisLabel:{{color:'#7d879e',fontSize:10}},splitLine:{{show:false}}}}],
  series:[{{name:'播放',type:'bar',data:D.views,itemStyle:{{color:'rgba(124,92,255,.55)',borderRadius:[4,4,0,0]}},barMaxWidth:14}},
          {{name:'粉丝总量',type:'line',yAxisIndex:1,data:D.followers,smooth:true,symbol:'none',lineStyle:{{color:'#fb7299',width:2.5}}}}]
}});
init('sources', {{
  tooltip:{{trigger:'item',formatter:'{{b}}<br/>{{c}} ({{d}}%)'}},
  legend:{{bottom:0,textStyle:{{color:'#9aa3b8',fontSize:10}},itemWidth:8,itemHeight:8}},
  series:[{{type:'pie',radius:['42%','68%'],center:['50%','45%'],data:D.sources,
    label:{{color:'#c3cad9',fontSize:10,formatter:'{{b}}\\n{{d}}%'}},itemStyle:{{borderColor:'#141826',borderWidth:3}},
    color:palette}}]
}});
init('heat', {{
  tooltip:{{position:'top',formatter:p=>`${{['周一','周二','周三','周四','周五','周六','周日'][p.value[1]]}} ${{p.value[0]}}:00<br/>首7日播放 ${{p.value[2]}}`}},
  grid:{{left:48,right:18,top:12,bottom:36}},
  xAxis:{{type:'category',data:Array.from({{length:24}}, (_,i)=>i+':00'),splitArea:{{show:true}},axisLabel:{{color:'#7d879e',fontSize:9,interval:3}}}},
  yAxis:{{type:'category',data:['周一','周二','周三','周四','周五','周六','周日'],axisLabel:{{color:'#7d879e',fontSize:10}}}},
  visualMap:{{min:0,max:D.maxHeat,calculable:false,orient:'horizontal',left:'center',bottom:0,inRange:{{color:['#1a1f2e','#4c3b9e','#7c5cff','#fb7299']}},textStyle:{{color:'#7d879e',fontSize:9}}}},
  series:[{{type:'heatmap',data:D.heat,itemStyle:{{borderColor:'#0b0d14',borderWidth:2,borderRadius:3}}}}]
}});
init('duration', {{
  tooltip:{{trigger:'axis'}}, legend:{{textStyle:{{color:'#9aa3b8'}},top:0}},
  grid:{{left:48,right:16,top:36,bottom:46}},
  xAxis:{{type:'category',data:D.duration.map(x=>x.label),axisLabel:{{color:'#7d879e',fontSize:9,rotate:22}}}},
  yAxis:{{type:'value',axisLabel:{{color:'#7d879e',fontSize:10}},splitLine:{{lineStyle:{{color:'rgba(255,255,255,.05)'}}}}}},
  series:[{{name:'首7日播放',type:'bar',data:D.duration.map(x=>x.avg_views),itemStyle:{{color:'rgba(34,211,238,.6)',borderRadius:[4,4,0,0]}},barMaxWidth:28}},
          {{name:'转粉率%',type:'line',data:D.duration.map(x=>x.conversion),smooth:true,symbolSize:5,lineStyle:{{color:'#fb7299',width:2}}}}]
}});
init('retention', {{
  tooltip:{{trigger:'axis',valueFormatter:v=>v+'%'}}, legend:{{textStyle:{{color:'#9aa3b8'}},top:0}},
  grid:{{left:46,right:18,top:36,bottom:32}},
  xAxis:{{type:'category',data:D.curveX.map(x=>x+'%'),axisLabel:{{color:'#7d879e',fontSize:10}}}},
  yAxis:{{type:'value',min:0,max:100,axisLabel:{{color:'#7d879e',fontSize:10,formatter:'{{value}}%'}},splitLine:{{lineStyle:{{color:'rgba(255,255,255,.05)'}}}}}},
  series:D.retentionSeries
}});
init('top', {{
  tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}}}},
  grid:{{left:4,right:24,top:8,bottom:8,containLabel:true}},
  xAxis:{{type:'value',axisLabel:{{color:'#7d879e',fontSize:9}},splitLine:{{lineStyle:{{color:'rgba(255,255,255,.05)'}}}}}},
  yAxis:{{type:'category',data:D.top.map(x=>x.name),axisLabel:{{color:'#9aa3b8',fontSize:9,width:130,overflow:'truncate'}}}},
  series:[{{type:'bar',data:D.top.map(x=>x.value),itemStyle:{{color:'rgba(124,92,255,.7)',borderRadius:[0,4,4,0]}},barMaxWidth:14}}]
}});
</script>
</body></html>"""
    summary = {
        "account": account, "dashboard": dash, "table": table,
        "retention": retention, "generated": generated,
    }
    return doc, summary


def build_xlsx(store: Store, account: dict, days: int = 30, path: Path | None = None) -> Path | None:
    try:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, LineChart, Reference
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except Exception as exc:
        log.warning("openpyxl unavailable: %s", exc)
        return None
    dash = analytics.build_dashboard(store, account, days)
    table = analytics.video_table(store, account, 90)
    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="171A26")
    accent = PatternFill("solid", fgColor="7C5CFF")
    head_font = Font(color="FFFFFF", bold=True, size=10)
    title_font = Font(color="FFFFFF", bold=True, size=18)
    sub_font = Font(color="9AA3B8", size=9)
    thin = Side(style="thin", color="2A3043")
    border = Border(bottom=thin)

    def style_header(ws, row=1, cols=8):
        for col in range(1, cols + 1):
            cell = ws.cell(row=row, column=col)
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(vertical="center")
            cell.border = border
        ws.row_dimensions[row].height = 22

    ws = wb.active
    ws.title = "运营概览"
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:H2")
    ws["A1"] = f"{account['name']} · 账号运营分析"
    ws["A1"].font = title_font
    ws["A1"].fill = PatternFill("solid", fgColor="0B0D14")
    ws["A1"].alignment = Alignment(vertical="center")
    ws["A3"] = f"平台：{PLATFORM_LABELS.get(account['platform'], account['platform'])}"
    ws["C3"] = f"分析周期：{dash['period']['label']}"
    ws["E3"] = f"健康度：{dash['health']['score']} / 100（{dash['health']['grade']}）"
    for cell in ("A3", "C3", "E3"):
        ws[cell].font = sub_font
    ws["A5"] = "核心指标"
    ws["A5"].font = Font(bold=True, size=12, color="C4B5FD")
    headers = ["指标", "当前值", "较上期", "说明"]
    for i, h in enumerate(headers, 1):
        ws.cell(row=6, column=i, value=h)
    style_header(ws, 6, 4)
    for idx, k in enumerate(dash["kpis"], 7):
        ws.cell(row=idx, column=1, value=k["label"])
        ws.cell(row=idx, column=2, value=k["value"])
        ws.cell(row=idx, column=3, value=f"{k['delta']:+g}{k.get('delta_unit','')}")
        ws.cell(row=idx, column=4, value=k.get("hint", ""))
        for col in range(1, 5):
            ws.cell(row=idx, column=col).border = border
            ws.cell(row=idx, column=col).font = Font(size=10, color="D7DCE8")
    ws.cell(row=15, column=1, value="健康度拆解").font = Font(bold=True, size=11, color="C4B5FD")
    for i, sub in enumerate(dash["health"]["subscores"]):
        ws.cell(row=16 + i, column=1, value=sub["label"])
        ws.cell(row=16 + i, column=2, value=sub["value"])
        ws.cell(row=16 + i, column=3, value=f"权重 {sub['weight']}%")
    ws.cell(row=23, column=1, value="运营摘要")
    ws.cell(row=23, column=1).font = Font(bold=True, size=11, color="C4B5FD")
    ws.merge_cells("A24:H27")
    ws["A24"] = dash["summary"].replace("**", "")
    ws["A24"].alignment = Alignment(wrap_text=True, vertical="top")
    for col, width in enumerate([18, 16, 20, 46, 14, 14, 14, 14], 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    ws2 = wb.create_sheet("每日数据")
    ws2.sheet_view.showGridLines = False
    cols = ["日期", "播放", "净增粉丝", "新增关注", "取关", "互动", "观看时长(小时)"]
    ws2.append(cols)
    style_header(ws2, 1, len(cols))
    for row in dash["series"]:
        ws2.append([row["date"], row["views"], row["net_followers"], row["gained"], row["lost"],
                    row["engagements"], round(row["watch_minutes"] / 60, 2)])
    for col, width in enumerate([13, 14, 12, 12, 10, 12, 16], 1):
        ws2.column_dimensions[get_column_letter(col)].width = width
    if len(dash["series"]) > 2:
        chart = LineChart()
        chart.title = "播放趋势"
        chart.height = 7
        chart.width = 22
        data = Reference(ws2, min_col=2, min_row=1, max_row=len(dash["series"]) + 1)
        cats = Reference(ws2, min_col=1, min_row=2, max_row=len(dash["series"]) + 1)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.style = 13
        ws2.add_chart(chart, "I2")

    ws3 = wb.create_sheet("视频明细")
    ws3.sheet_view.showGridLines = False
    cols = ["标题", "发布", "时长(秒)", "总播放", "周期播放", "点赞", "投币", "收藏", "评论", "分享",
            "互动率%", "转粉率%", "3秒留存%", "首7日播放", "链接"]
    ws3.append(cols)
    style_header(ws3, 1, len(cols))
    for v in table["videos"]:
        ws3.append([
            v["title"], (v.get("published_at") or "")[:19], v["duration"], v["total_views"],
            v["period_views"], v["likes"], v["coins"], v["favorites"], v["comments"], v["shares"],
            v["engagement_rate"], v["conversion"],
            round(v["retention3"] * 100, 1) if v.get("retention3") is not None else "",
            v["first7"], v["url"],
        ])
    for col, width in enumerate([46, 19, 10, 12, 12, 9, 9, 9, 9, 9, 10, 10, 11, 12, 48], 1):
        ws3.column_dimensions[get_column_letter(col)].width = width
    for row in ws3.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(size=9, color="D7DCE8")
            cell.border = border
    ws3.freeze_panes = "A2"
    ws3.auto_filter.ref = f"A1:O{len(table['videos']) + 1}"

    ws4 = wb.create_sheet("发布时段")
    ws4.sheet_view.showGridLines = False
    cols = ["时段", "样本数", "首7日播放", "较均值", "互动率%", "置信度"]
    ws4.append(cols)
    style_header(ws4, 1, len(cols))
    for slot in dash["best_slots"]:
        ws4.append([slot["label"], slot["count"], slot["avg_first7"], f"{slot['lift']:+.0f}%",
                    slot["engagement"], slot["confidence"]])
    for col, width in enumerate([16, 9, 15, 10, 12, 10], 1):
        ws4.column_dimensions[get_column_letter(col)].width = width

    ws5 = wb.create_sheet("流量与受众")
    ws5.sheet_view.showGridLines = False
    ws5.append(["流量来源", "播放", "占比"])
    style_header(ws5, 1, 3)
    total = sum(s["views"] for s in dash["sources"]) or 1
    for s in dash["sources"]:
        ws5.append([s["source"], s["views"], round(s["views"] / total * 100, 1)])
    start_row = len(dash["sources"]) + 4
    ws5.cell(row=start_row, column=1, value="受众画像").font = Font(bold=True, color="C4B5FD")
    row = start_row + 1
    for dim, items in dash["demographics"].items():
        ws5.cell(row=row, column=1, value=dim)
        for i, item in enumerate(items[:12], 2):
            ws5.cell(row=row, column=i, value=item["name"])
            ws5.cell(row=row + 1, column=i, value=item["value"])
        row += 3
    ws5.column_dimensions["A"].width = 18
    for i in range(2, 14):
        ws5.column_dimensions[get_column_letter(i)].width = 13

    ws6 = wb.create_sheet("诊断建议")
    ws6.sheet_view.showGridLines = False
    ws6.append(["级别", "类别", "标题", "诊断", "建议动作"])
    style_header(ws6, 1, 5)
    sev_cn = {"critical": "严重", "warning": "警告", "opportunity": "机会", "good": "优势", "info": "提示"}
    for item in dash["insights"]:
        ws6.append([sev_cn.get(item["severity"], item["severity"]), item["category"],
                    item["title"], item["body"], item["action"]])
    for col, width in enumerate([8, 12, 30, 60, 50], 1):
        ws6.column_dimensions[get_column_letter(col)].width = width
    for row in ws6.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.font = Font(size=9, color="D7DCE8")

    path = path or EXPORT_DIR / f"MediaPulse_{_safe_name(account['name'])}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    wb.save(path)
    return path


def build_pdf(html_path: Path, out_path: Path) -> tuple[bool, str]:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    ]
    exe = next((p for p in candidates if p.is_file()), None)
    if not exe:
        return False, "未找到 Edge/Chrome，无法自动生成 PDF；请打开 HTML 报告后打印为 PDF。"
    try:
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [str(exe), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             "--virtual-time-budget=6000", f"--print-to-pdf={out_path}", html_path.as_uri()],
            capture_output=True, timeout=90, creationflags=flags,
        )
        if out_path.exists() and out_path.stat().st_size > 5000:
            return True, ""
        return False, (result.stderr.decode("utf-8", errors="replace")[-400:] or "PDF 渲染失败")
    except Exception as exc:
        return False, str(exc)


def build_report(store: Store, account: dict, days: int = 30, make_pdf: bool = True,
                 use_ai: bool = True) -> dict[str, Any]:
    doc, summary = build_html(store, account, days)
    ai_text, ai_error = "", ""
    if use_ai:
        ai_text, ai_error = deepseek_summary(
            store, account, summary["dashboard"], summary["table"]
        )
    if ai_text:
        block = ('<div class="ai-summary"><div class="ai-label">AI 运营结论 · DEEPSEEK</div>'
                 + html.escape(ai_text) + "</div>")
    else:
        block = ""
    doc = doc.replace("<!--AI_SUMMARY-->", block)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"MediaPulse_{_safe_name(account['name'])}_{days}d_{stamp}"
    html_path = REPORT_DIR / f"{base}.html"
    html_path.write_text(doc, encoding="utf-8")
    xlsx_path = build_xlsx(store, account, days, EXPORT_DIR / f"{base}.xlsx")
    pdf_path = REPORT_DIR / f"{base}.pdf"
    pdf_ok, pdf_error = (False, "未启用 PDF 导出")
    if make_pdf:
        pdf_ok, pdf_error = build_pdf(html_path, pdf_path)
    return {
        "html": str(html_path), "xlsx": str(xlsx_path) if xlsx_path else "",
        "pdf": str(pdf_path) if pdf_ok else "", "pdf_error": pdf_error,
        "name": base,
        "summary": summary["dashboard"]["summary"],
        "ai_summary": ai_text,
        "ai_error": ai_error,
    }
