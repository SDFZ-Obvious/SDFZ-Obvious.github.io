/* MediaPulse front-end — dependency-free SPA with ECharts. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
  const md = (text) => esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");

  const PAGE_META = {
    overview: { title: "数据总览", eyebrow: "WORKSPACE / OVERVIEW", range: true,
      desc: "把播放、粉丝、互动和内容表现放进同一张作战地图。" },
    content: { title: "内容分析", eyebrow: "WORKSPACE / CONTENT", range: true,
      desc: "找到真正带动增长的稿件，拆解标题、时长与选题结构。" },
    growth: { title: "粉丝增长", eyebrow: "WORKSPACE / GROWTH", range: true,
      desc: "看见每一次涨粉与掉粉，预测下一阶段的增长曲线。" },
    traffic: { title: "流量洞察", eyebrow: "WORKSPACE / TRAFFIC", range: true,
      desc: "识别流量来源、受众结构与平台分发依赖。" },
    timing: { title: "发布策略", eyebrow: "STRATEGY / TIMING", range: true,
      desc: "用历史表现反推黄金发布窗口与稳定更新节奏。" },
    retention: { title: "留存诊断", eyebrow: "STRATEGY / RETENTION", range: true,
      desc: "从 3 秒开场到中段节奏，定位观众离开的位置。" },
    lab: { title: "选题实验室", eyebrow: "STRATEGY / LAB", range: true,
      desc: "把账号数据变成可执行的标题、标签与选题假设。" },
    reports: { title: "报表中心", eyebrow: "DELIVERABLES / REPORTS", range: false,
      desc: "生成可归档、可分享、可打印的运营分析报告。" },
    settings: { title: "账号与设置", eyebrow: "SYSTEM / SETTINGS", range: false,
      desc: "连接账号、同步策略与本机数据管理。" },
  };

  const state = {
    token: "",
    app: {},
    accounts: [],
    accountId: null,
    days: 30,
    page: "overview",
    data: null,
    cache: {},
    charts: [],
    loading: false,
    jobId: null,
    jobTimer: null,
    qrTimer: null,
    ytTimer: null,
    lastRetention: null,
  };

  // ------------------------------------------------------------------ api
  async function api(path, options = {}) {
    const opts = { ...options, headers: { "X-MP-Token": state.token, ...(options.headers || {}) } };
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, opts);
    let payload = null;
    try { payload = await res.json(); } catch (_) { payload = {}; }
    if (!res.ok) {
      const error = new Error(payload.message || `请求失败 (${res.status})`);
      error.status = res.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  // ------------------------------------------------------------------ format
  function fmt(value, digits = 1) {
    const n = Number(value || 0);
    const abs = Math.abs(n);
    if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
    if (abs >= 1e4) return `${(n / 1e4).toFixed(digits)}万`;
    if (abs >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toLocaleString("zh-CN", { maximumFractionDigits: abs < 10 ? 2 : 0 });
  }
  function signed(value, digits = 0) {
    const n = Number(value || 0);
    return `${n > 0 ? "+" : ""}${n.toLocaleString("zh-CN", { maximumFractionDigits: digits })}`;
  }
  function duration(sec) {
    sec = Number(sec || 0);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  }
  function shortDate(value) {
    if (!value) return "—";
    const d = String(value).slice(0, 10).split("-");
    return d.length === 3 ? `${d[1]}/${d[2]}` : String(value).slice(0, 10);
  }
  function datetime(value) {
    if (!value) return "—";
    return String(value).replace("T", " ").slice(0, 16);
  }
  function pct(value, digits = 1) { return `${Number(value || 0).toFixed(digits)}%`; }
  function platformName(account) {
    if (!account) return "";
    return account.platform === "youtube" ? "YouTube" : "哔哩哔哩";
  }
  function platformIcon(account) {
    if (!account) return "";
    return `<span class="platform-icon ${account.platform}">${account.platform === "youtube" ? "YT" : "B"}</span>`;
  }
  function avatar(account, cls = "avatar") {
    const name = account?.name || "M";
    const inner = account?.avatar
      ? `<img src="${esc(account.avatar)}" alt="" onerror="this.style.display='none'">`
      : esc(name.slice(0, 1).toUpperCase());
    return `<div class="${cls}" data-platform="${esc(account?.platform || "")}">${inner}</div>`;
  }

  // ------------------------------------------------------------------ chart helpers
  function disposeCharts() {
    state.charts.forEach((chart) => { try { chart.dispose(); } catch (_) {} });
    state.charts = [];
  }
  function makeChart(id, option) {
    const el = document.getElementById(id);
    if (!el) return null;
    try {
      const chart = echarts.init(el, null, { renderer: "canvas" });
      chart.setOption(option);
      state.charts.push(chart);
      return chart;
    } catch (error) {
      console.error(`chart ${id} failed`, error.message, error.stack);
      return null;
    }
  }
  const AXIS = {
    axisLine: { lineStyle: { color: "#2a3043" } },
    axisTick: { show: false },
    axisLabel: { color: "#7d879e", fontSize: 9 },
    splitLine: { lineStyle: { color: "rgba(255,255,255,.045)" } },
  };
  const TOOLTIP = {
    backgroundColor: "#171c2b",
    borderColor: "rgba(255,255,255,.14)",
    borderWidth: 1,
    padding: [9, 11],
    textStyle: { color: "#e5e9f2", fontSize: 11 },
    extraCssText: "box-shadow:0 14px 40px rgba(0,0,0,.45);border-radius:9px;",
  };
  const PALETTE = ["#7c5cff", "#fb7299", "#22d3ee", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#60a5fa"];

  function sparkline(values, color = "#7c5cff", width = 62, height = 22) {
    if (!values || values.length < 2) values = [0, 0];
    const nums = values.map((v) => Number(v || 0));
    const min = Math.min(...nums), max = Math.max(...nums);
    const span = max - min || 1;
    const pts = nums.map((v, i) => [
      (i / (nums.length - 1)) * 100,
      height - ((v - min) / span) * (height - 3) - 1.5,
    ]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const area = `${line} L100,${height} L0,${height} Z`;
    const id = `sg-${Math.random().toString(36).slice(2, 8)}`;
    return `<svg class="kpi-spark" width="${width}" height="${height}" viewBox="0 0 100 ${height}" preserveAspectRatio="none">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      <path d="${area}" fill="url(#${id})"/><path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
  }

  function healthRing(score) {
    score = Math.max(0, Math.min(100, Number(score || 0)));
    const r = 44, c = 2 * Math.PI * r;
    const color = score >= 80 ? "#34d399" : score >= 65 ? "#7c5cff" : score >= 50 ? "#fbbf24" : "#f87171";
    const id = `hr-${Math.random().toString(36).slice(2, 7)}`;
    return `<div class="health-ring">
      <svg width="108" height="108" viewBox="0 0 108 108">
        <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="${color}"/></linearGradient></defs>
        <circle cx="54" cy="54" r="${r}" fill="none" stroke="rgba(255,255,255,.055)" stroke-width="7"/>
        <circle cx="54" cy="54" r="${r}" fill="none" stroke="url(#${id})" stroke-width="7" stroke-linecap="round"
          stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - score / 100)}"/>
      </svg>
      <div class="score">${Math.round(score)}<small>/100</small></div>
    </div>`;
  }

  function kpiIcon(key) {
    const icons = {
      followers: '<path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>',
      views: '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
      engagement_rate: '<path d="M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 00-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 000-7.8z"/>',
      conversion: '<path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM19 8v6M22 11h-6"/>',
      net_followers: '<path d="M12 20V10M18 20V4M6 20v-4"/>',
      watch_hours: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[key] || icons.views}</svg>`;
  }

  function kpiCards(kpis) {
    return `<div class="kpi-grid">${kpis.map((k) => {
      const d = Number(k.delta || 0);
      const dir = d > 0 ? "delta-up" : d < 0 ? "delta-down" : "delta-flat";
      const arrow = d > 0 ? "↑" : d < 0 ? "↓" : "·";
      const display = typeof k.value === "number" && Math.abs(k.value) < 10 && k.unit === "%"
        ? k.value.toFixed(2) : fmt(k.value);
      return `<div class="kpi" title="${esc(k.hint || "")}">
        <div class="kpi-top"><span class="kpi-label">${esc(k.label)}</span><span class="kpi-icon">${kpiIcon(k.key)}</span></div>
        <div class="kpi-value">${display}<span>${esc(k.unit || "")}</span></div>
        <div class="kpi-foot ${dir}">${arrow} ${d ? Math.abs(d).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) : "0"}${esc(k.delta_unit || "")}<span class="vs">较上期</span></div>
        ${sparkline(k.spark, d < 0 ? "#f87171" : "#7c5cff")}
      </div>`;
    }).join("")}</div>`;
  }

  function insightList(insights, limit = 6) {
    if (!insights?.length) return `<div class="tiny muted">暂无诊断，等待更多数据。</div>`;
    const icons = { critical: "!", warning: "!", opportunity: "↗", good: "✓", info: "i" };
    return `<div class="insights">${insights.slice(0, limit).map((i) => `
      <div class="insight ${esc(i.severity)}">
        <div class="insight-icon">${icons[i.severity] || "i"}</div>
        <div>
          <div class="insight-title">${esc(i.title)}</div>
          <div class="insight-body">${esc(i.body)}</div>
          <div class="insight-action"><b>行动</b> · ${esc(i.action)}</div>
        </div>
      </div>`).join("")}</div>`;
  }

  function topVideos(videos, valueKey = "period_views") {
    if (!videos?.length) return `<div class="tiny muted">暂无稿件</div>`;
    return `<div class="top-list">${videos.slice(0, 7).map((v, i) => `
      <div class="top-row clickable" data-video-id="${v.id}">
        <div class="rank r${i + 1}">${String(i + 1).padStart(2, "0")}</div>
        <div class="top-thumb">${v.cover ? `<img src="${esc(v.cover)}" onerror="this.style.display='none'">` : "▶"}</div>
        <div class="top-info"><div class="top-title">${esc(v.title)}</div><div class="top-meta">${shortDate(v.published_date || v.published_at)} · ${duration(v.duration)}</div></div>
        <div class="top-value">${fmt(v[valueKey] ?? v.period_views)}<span>${valueKey === "period_followers" ? "转粉" : "周期播放"}</span></div>
      </div>`).join("")}</div>`;
  }

  function pageHead(title, desc, meta = "") {
    return `<div class="page-head"><div><h2>${esc(title)}</h2><p>${esc(desc)}</p></div>${meta ? `<div class="head-meta">${meta}</div>` : ""}</div>`;
  }

  function demoBanner() {
    const account = activeAccount();
    if (!account?.is_demo) return "";
    return `<div class="demo-banner"><span>●</span><span>当前为 <b>演示数据</b>，所有图表与诊断均可体验。登录真实账号后，同步的个人数据会自动替换。</span><button class="btn small" id="demo-add">连接真实账号</button></div>`;
  }

  function emptyState() {
    return `<div class="empty">
      <div class="empty-icon"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M3 17l5-5 4 3 8-9" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 6h4v4" stroke-linecap="round"/></svg></div>
      <h3>还没有连接账号</h3>
      <p>MediaPulse 只读取你自己的 B 站或 YouTube 账号数据，所有分析都在本机完成。扫码或授权后即可自动同步播放、互动、粉丝与留存。</p>
      <div class="flex"><button class="btn primary" id="empty-connect">连接我的账号</button><button class="btn" id="empty-demo">载入演示数据</button></div>
    </div>`;
  }

  // ------------------------------------------------------------------ navigation
  function activeAccount() {
    return state.accounts.find((a) => Number(a.id) === Number(state.accountId)) || null;
  }

  function updateChrome() {
    const meta = PAGE_META[state.page] || PAGE_META.overview;
    $("#page-title").textContent = meta.title;
    $("#page-eyebrow").textContent = meta.eyebrow;
    $("#range-seg").classList.toggle("hidden", !meta.range);
    $$("#nav .nav-item").forEach((el) => el.classList.toggle("active", el.dataset.page === state.page));
    $$("#range-seg button").forEach((el) => el.classList.toggle("active", Number(el.dataset.days) === state.days));
    const account = activeAccount();
    if (account) {
      $("#active-name").textContent = account.name;
      $("#active-meta").innerHTML = `${platformIcon(account)} ${platformName(account)} · ${fmt(account.followers)} 粉丝`;
      $("#active-avatar").outerHTML = avatar(account, "avatar").replace('class="avatar"', 'class="avatar" id="active-avatar"');
      $("#top-avatar").outerHTML = avatar(account, "avatar").replace('class="avatar"', 'class="avatar" id="top-avatar" style="width:30px;height:30px;border-radius:9px;font-size:11px"');
    }
    const syncBtn = $("#sync-btn");
    syncBtn.disabled = !!account?.is_demo || state.loading || !!state.jobId;
    syncBtn.title = account?.is_demo ? "演示账号不连接网络" : "同步最新数据";
  }

  function renderAccountMenu() {
    const menu = $("#account-menu");
    menu.innerHTML = state.accounts.map((a) => `
      <div class="account-item" data-account="${a.id}">
        ${avatar(a, "avatar").replace('class="avatar"', 'class="avatar" style="width:24px;height:24px;border-radius:7px;font-size:10px"')}
        <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.name)}</span>
        <span class="platform-dot" style="background:${a.platform === "youtube" ? "#ff4d4d" : "#fb7299"}"></span>
      </div>`).join("") + `<div class="account-add" id="menu-add">＋ 连接新账号</div>`;
    $$("#account-menu .account-item").forEach((el) => el.addEventListener("click", () => {
      setAccount(Number(el.dataset.account));
      menu.classList.add("hidden");
    }));
    $("#menu-add")?.addEventListener("click", () => { menu.classList.add("hidden"); openConnectModal(); });
  }

  function setAccount(id) {
    if (Number(id) === Number(state.accountId)) return;
    state.accountId = Number(id);
    localStorage.setItem("mp_account", String(id));
    state.cache = {};
    updateChrome();
    renderAccountMenu();
    navigate(state.page, true);
  }

  async function refreshBootstrap() {
    const boot = await api("/api/bootstrap");
    state.app = boot.app;
    state.accounts = boot.accounts || [];
    if (!state.accounts.some((a) => Number(a.id) === Number(state.accountId))) {
      const stored = Number(localStorage.getItem("mp_account"));
      state.accountId = state.accounts.some((a) => Number(a.id) === stored)
        ? stored : (state.accounts[0]?.id ?? null);
    }
    if (boot.settings?.last_range) {
      const d = Number(boot.settings.last_range);
      if ([7, 30, 90, 180].includes(d) && !localStorage.getItem("mp_days")) state.days = d;
    }
    $("#version-label").textContent = `v${boot.app.version}`;
    updateChrome();
    renderAccountMenu();
    return boot;
  }

  function navigate(page, force = false) {
    if (!PAGE_META[page]) page = "overview";
    if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
    state.page = page;
    updateChrome();
    loadPage(force);
    $("#sidebar").classList.remove("open");
  }

  // ------------------------------------------------------------------ load / skeleton
  function skeleton() {
    return `<div class="sk-page">
      <div class="skeleton" style="height:20px;width:180px"></div>
      <div class="sk-row">${Array(6).fill('<div class="skeleton sk-card"></div>').join("")}</div>
      <div class="skeleton sk-hero"></div>
      <div class="skeleton sk-chart"></div>
    </div>`;
  }

  async function loadPage(force = false) {
    const account = activeAccount();
    if (!account) {
      disposeCharts();
      $("#view").innerHTML = emptyState();
      bindEmpty();
      return;
    }
    const key = `${state.page}:${account.id}:${state.days}`;
    if (!force && state.cache[key]) {
      state.data = state.cache[key];
      renderPage(state.data);
      return;
    }
    state.loading = true;
    updateChrome();
    $("#view").innerHTML = skeleton();
    try {
      let data;
      if (state.page === "overview") {
        data = await api(`/api/dashboard?account_id=${account.id}&days=${state.days}`);
      } else if (state.page === "content") {
        const [dash, table] = await Promise.all([
          api(`/api/dashboard?account_id=${account.id}&days=${state.days}`),
          api(`/api/videos?account_id=${account.id}&days=${Math.max(90, state.days)}`),
        ]);
        data = { dash, table };
      } else if (state.page === "growth") {
        data = await api(`/api/growth?account_id=${account.id}&days=${Math.max(30, state.days)}`);
      } else if (state.page === "traffic") {
        data = await api(`/api/traffic?account_id=${account.id}&days=${state.days}`);
      } else if (state.page === "timing") {
        data = await api(`/api/dashboard?account_id=${account.id}&days=${state.days}`);
      } else if (state.page === "retention") {
        data = await api(`/api/retention?account_id=${account.id}&days=${Math.max(90, state.days)}`);
      } else if (state.page === "lab") {
        data = await api(`/api/lab?account_id=${account.id}&days=${Math.max(90, state.days)}`);
      } else if (state.page === "reports") {
        data = await api("/api/reports");
      } else if (state.page === "settings") {
        data = { boot: await api("/api/bootstrap") };
        state.accounts = data.boot.accounts || state.accounts;
      }
      state.data = data;
      state.cache[key] = data;
      renderPage(data);
    } catch (error) {
      console.error(error.message, error.stack);
      $("#view").innerHTML = `<div class="empty"><div class="empty-icon">!</div><h3>加载失败</h3>
        <p>${esc(error.message || "未知错误")}</p><button class="btn" onclick="location.reload()">重新加载</button></div>`;
    } finally {
      state.loading = false;
      updateChrome();
    }
  }

  function renderPage(data) {
    disposeCharts();
    const renderers = {
      overview: renderOverview, content: renderContent, growth: renderGrowth,
      traffic: renderTraffic, timing: renderTiming, retention: renderRetention,
      lab: renderLab, reports: renderReports, settings: renderSettings,
    };
    (renderers[state.page] || renderOverview)(data);
    bindVideoRows();
    window.scrollTo({ top: 0 });
  }

  // ------------------------------------------------------------------ overview
  function renderOverview(d) {
    const account = activeAccount();
    const health = d.health;
    const chips = (d.insights || []).slice(0, 3).map((i) => {
      const cls = i.severity === "good" ? "good" : i.severity === "critical" ? "bad" : i.severity === "warning" ? "warn" : "brand";
      return `<span class="chip ${cls}">${esc(i.title)}</span>`;
    }).join("");
    $("#view").innerHTML = `${demoBanner()}
      <div class="hero">
        <div class="hero-main">
          <div class="hero-kicker">WEEKLY PULSE · ${esc(d.period.label)}</div>
          <h3>${greeting()}，${esc(account.name)} 的运营脉搏</h3>
          <div class="hero-summary">${md(d.summary)}</div>
          <div class="hero-chips">${chips}</div>
        </div>
        <div class="card health-card">
          <div class="health-top"><div><div class="card-title">账号健康度</div><div class="card-sub">增长 · 互动 · 转化 · 留存</div></div><span class="chip brand">${esc(health.grade)} 级</span></div>
          ${healthRing(health.score)}
          <div class="health-grade">综合评分 <b>${health.score}</b> / 100</div>
          <div class="health-subs">${health.subscores.map((s) => `<div class="health-sub"><span>${esc(s.label)}</span><b>${s.value}</b></div>`).join("")}</div>
          <div class="health-verdict">${esc(health.verdict)}</div>
        </div>
      </div>
      ${kpiCards(d.kpis)}
      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">播放与粉丝走势</div><div class="card-sub">柱形为新增播放，折线为粉丝总量</div></div><span class="pill-note">${esc(d.period.label)}</span></div>
          <div class="chart lg" id="overview-trend"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">增长引擎</div><div class="card-sub">本周期贡献播放最多的稿件</div></div><span class="pill-note">TOP 7</span></div>
          ${topVideos(d.top_videos)}
        </div>
      </div>
      <div class="grid-2b mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">黄金发布时间</div><div class="card-sub">颜色越亮，首 7 日播放越高</div></div><a class="tiny muted" href="#timing">完整策略 →</a></div>
          <div class="chart sm" id="overview-heat"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">内容时长诊断</div><div class="card-sub">首 7 日播放与转粉效率</div></div><a class="tiny muted" href="#retention">留存详情 →</a></div>
          ${durationList(d.duration)}
        </div>
      </div>
      <div class="grid-2 mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">本周关键洞察</div><div class="card-sub">由你的数据自动生成，按优先级排序</div></div><span class="pill-note">${d.insights.length} 条</span></div>
          ${insightList(d.insights, 5)}
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">转化漏斗</div><div class="card-sub">从曝光到关注的效率损耗</div></div><span class="pill-note">${esc(d.period.label)}</span></div>
          ${funnel(d.funnel)}
          <div class="divider"></div>
          <div class="flex between"><span class="tiny muted">内容更新</span><span class="tiny">${d.totals.uploads} 条 · 周均 ${d.cadence.per_week}</span></div>
          <div class="flex between" style="margin-top:5px"><span class="tiny muted">平均单稿播放</span><span class="tiny">${fmt(d.totals.avg_views_per_upload)}</span></div>
        </div>
      </div>
      <div class="section-head"><h3>本周期内容表现</h3><a class="more" href="#content">查看全部 →</a></div>
      <div class="card"><div class="table-wrap"><table class="data-table"><thead><tr><th>稿件</th><th>发布</th><th>周期播放</th><th>互动率</th><th>转粉率</th><th>3秒留存</th><th>趋势</th></tr></thead>
        <tbody>${d.top_videos.slice(0, 7).map((v) => videoRow(v)).join("")}</tbody></table></div></div>
      <div class="warn-note mt14">${esc(d.platform_note)}</div>`;

    makeChart("overview-trend", trendOption(d.series));
    makeChart("overview-heat", heatOption(d.heatmap, true));
    if (d.top_videos.length) bindVideoRows();
  }

  function greeting() {
    const h = new Date().getHours();
    if (h < 6) return "夜深了";
    if (h < 11) return "早上好";
    if (h < 14) return "中午好";
    if (h < 18) return "下午好";
    return "晚上好";
  }

  function trendOption(series) {
    const fvals = series.map((s) => Number(s.followers || 0)).filter((v) => v > 0);
    const fmin = fvals.length ? Math.max(0, Math.min(...fvals) * 0.97) : 0;
    const fmax = fvals.length ? Math.max(...fvals) * 1.01 : 100;
    return {
      tooltip: { ...TOOLTIP, trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: ["新增播放", "粉丝总量"], top: 0, right: 4, textStyle: { color: "#9aa3b8", fontSize: 9 }, itemWidth: 10, itemHeight: 6 },
      grid: { left: 46, right: 50, top: 34, bottom: 28 },
      xAxis: { type: "category", data: series.map((s) => s.label), ...AXIS, splitLine: { show: false } },
      yAxis: [
        { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
        { type: "value", min: fmin, max: fmax, ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
      ],
      series: [
        { name: "新增播放", type: "bar", data: series.map((s) => s.views), barMaxWidth: 13,
          itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(124,92,255,.9)" }, { offset: 1, color: "rgba(124,92,255,.22)" }]), borderRadius: [3, 3, 0, 0] } },
        { name: "粉丝总量", type: "line", yAxisIndex: 1, data: series.map((s) => s.followers), smooth: true, symbol: "none",
          lineStyle: { width: 2.2, color: "#fb7299" }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(251,114,153,.16)" }, { offset: 1, color: "rgba(251,114,153,0)" }]) } },
      ],
    };
  }

  function heatOption(matrix, compact = false) {
    const data = matrix.filter((c) => c.count).map((c) => [c.hour, c.weekday, c.value]);
    const max = Math.max(1, ...data.map((d) => d[2]));
    return {
      tooltip: { ...TOOLTIP, position: "top", formatter: (p) => `${["周一", "周二", "周三", "周四", "周五", "周六", "周日"][p.value[1]]} ${p.value[0]}:00<br/>首7日播放 <b>${fmt(p.value[2])}</b>` },
      grid: { left: compact ? 34 : 44, right: 8, top: 6, bottom: compact ? 4 : 26 },
      xAxis: { type: "category", data: Array.from({ length: 24 }, (_, i) => `${i}`), ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, interval: compact ? 5 : 2 } },
      yAxis: { type: "category", data: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"], ...AXIS, splitLine: { show: false } },
      visualMap: compact ? { show: false, min: 0, max, inRange: { color: ["#1a1f2e", "#3d3380", "#7c5cff", "#fb7299"] } }
        : { min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 9, itemHeight: 70, textStyle: { color: "#7d879e", fontSize: 8 }, inRange: { color: ["#1a1f2e", "#3d3380", "#7c5cff", "#fb7299"] } },
      series: [{ type: "heatmap", data, itemStyle: { borderColor: "#0b0d14", borderWidth: 2, borderRadius: 3 },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(124,92,255,.5)" } } }],
    };
  }

  function funnel(rows) {
    if (!rows?.length) return `<div class="tiny muted">暂无漏斗数据</div>`;
    const max = Math.max(...rows.map((r) => r.value)) || 1;
    return `<div class="funnel">${rows.map((r) => `
      <div class="funnel-row"><div class="funnel-label">${esc(r.label)}</div>
        <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(2, r.value / max * 100)}%"></div></div>
        <div class="funnel-value">${fmt(r.value)}</div><div class="funnel-rate">${r.rate}%</div>
      </div>`).join("")}</div>`;
  }

  function durationList(rows) {
    const max = Math.max(1, ...rows.map((r) => r.avg_views));
    return `<div class="dur-list">${rows.map((r) => `
      <div class="dur-row" title="${r.count} 条样本 · 转粉率 ${r.conversion}%${r.retention3 ? ` · 3秒留存 ${r.retention3}%` : ""}">
        <div><div class="dur-label">${esc(r.label)}</div><div class="dur-sub">${r.count} 条 · 转粉 ${r.conversion}%</div></div>
        <div class="dur-track"><div class="dur-fill" style="width:${Math.max(2, r.avg_views / max * 100)}%"></div></div>
        <div class="dur-value">${fmt(r.avg_views)}<div class="dur-sub" style="text-align:right">首7日</div></div>
      </div>`).join("")}</div>`;
  }

  function videoRow(v) {
    const retention = v.retention3 == null ? "—" : `${(Number(v.retention3) * 100).toFixed(1)}%`;
    return `<tr class="clickable" data-video-id="${v.id}">
      <td><div class="video-cell"><div class="video-thumb">${v.cover ? `<img src="${esc(v.cover)}" onerror="this.style.display='none'">` : "▶"}</div>
        <div style="min-width:0"><div class="video-name">${esc(v.title)}</div><div class="video-meta">${esc((v.tags || []).slice(0, 3).join(" · "))}</div></div></div></td>
      <td class="num">${shortDate(v.published_date || v.published_at)}</td>
      <td class="num">${fmt(v.period_views)}</td>
      <td class="num">${pct(v.engagement_rate, 2)}</td>
      <td class="num">${pct(v.conversion, 2)}</td>
      <td class="num">${retention}</td>
      <td><div class="spark-cell">${sparkline(v.spark, "#22d3ee", 64, 19)}</div></td>
    </tr>`;
  }

  function median(values) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  // ------------------------------------------------------------------ content
  function renderContent({ dash, table }) {
    const videos = table.videos || [];
    const med = median(videos.map((v) => v.first7));
    const highConv = videos.filter((v) => v.conversion >= 0.15).length;
    const patternMax = Math.max(1, ...(dash.title_patterns || []).map((p) => Math.abs(p.lift)));
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("内容分析", PAGE_META.content.desc, `共 ${videos.length} 条稿件<br>周期 ${state.days} 天 · 表格近 90 天`)}
      <div class="grid-3 mb14">
        <div class="card"><div class="card-title">稿件总数</div><div class="kpi-value" style="margin-top:12px">${videos.length}<span>条</span></div><div class="card-sub">中位首 7 日播放 ${fmt(med)}</div></div>
        <div class="card"><div class="card-title">高转粉稿件</div><div class="kpi-value" style="margin-top:12px">${highConv}<span>条</span></div><div class="card-sub">转粉率 ≥ 0.15% · 优先复用结构</div></div>
        <div class="card"><div class="card-title">平均互动率</div><div class="kpi-value" style="margin-top:12px">${pct(median(videos.map((v) => v.engagement_rate)), 2)}</div><div class="card-sub">中位数口径，避免爆款拉偏</div></div>
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">时长 × 首 7 日播放</div><div class="card-sub">气泡越大互动越高，点击查看稿件详情</div></div><span class="pill-note">${videos.length} 条</span></div>
          <div class="chart lg" id="content-scatter"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">标题结构增益</div><div class="card-sub">相对账号中位首 7 日播放的提升</div></div><span class="pill-note">A/B 参考</span></div>
          ${(dash.title_patterns || []).length ? `<div class="dur-list">${dash.title_patterns.slice(0, 7).map((p) => `
            <div class="dur-row" title="${p.count} 条样本">
              <div><div class="dur-label">${esc(p.label)}</div><div class="dur-sub">${p.count} 条</div></div>
              <div class="dur-track"><div class="dur-fill" style="width:${Math.max(3, Math.abs(p.lift) / patternMax * 100)}%;${p.lift < 0 ? "background:linear-gradient(90deg,rgba(248,113,113,.75),rgba(251,191,36,.5))" : ""}"></div></div>
              <div class="dur-value ${p.lift >= 0 ? "pos" : "neg"}">${p.lift > 0 ? "+" : ""}${p.lift.toFixed(0)}%</div>
            </div>`).join("")}</div>` : `<div class="tiny muted">样本不足，继续积累内容后自动分析。</div>`}
          <div class="divider"></div>
          <div class="tiny muted">高潜标签</div>
          <div class="tag-cloud" style="margin-top:8px">${(dash.tags || []).slice(0, 8).map((t) => `<span class="cloud-tag ${t.lift > 30 ? "hot" : ""}" title="${t.count} 条 · ${t.lift > 0 ? "+" : ""}${t.lift}%">${esc(t.tag)} <span style="opacity:.55;font-size:8px">${t.count}</span></span>`).join("") || '<span class="tiny muted">暂无标签</span>'}</div>
        </div>
      </div>
      <div class="card mt14">
        <div class="card-head"><div><div class="card-title">稿件明细</div><div class="card-sub">点击任意行打开单稿诊断</div></div><span class="count-chip" id="content-count"></span></div>
        <div class="toolbar">
          <input class="input search" id="content-search" placeholder="搜索标题 / 标签 / 分类">
          <select class="select" id="content-cat"><option value="">全部分类</option>${(table.categories || []).map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}</select>
          <select class="select" id="content-sort">
            <option value="published">按发布时间</option><option value="period_views">按周期播放</option>
            <option value="first7">按首 7 日播放</option><option value="engagement_rate">按互动率</option>
            <option value="conversion">按转粉率</option>
          </select>
          <div class="spacer"></div><span class="tiny muted">周期列为近 90 天新增</span>
        </div>
        <div class="table-wrap"><table class="data-table"><thead><tr><th>稿件</th><th>发布</th><th>周期播放</th><th>互动率</th><th>转粉率</th><th>3秒留存</th><th>趋势</th></tr></thead><tbody id="content-tbody"></tbody></table></div>
      </div>`;

    makeChart("content-scatter", scatterOption(videos));
    state.charts[state.charts.length - 1]?.on("click", (p) => {
      const id = p.data?.[4];
      if (id) openVideo(Number(id));
    });

    const draw = () => {
      const q = ($("#content-search").value || "").toLowerCase().trim();
      const cat = $("#content-cat").value;
      const sort = $("#content-sort").value;
      let rows = videos.filter((v) => {
        const hay = `${v.title} ${(v.tags || []).join(" ")} ${v.category}`.toLowerCase();
        return (!q || hay.includes(q)) && (!cat || v.category === cat);
      });
      if (sort === "published") rows.sort((a, b) => String(b.published_at).localeCompare(String(a.published_at)));
      else rows.sort((a, b) => Number(b[sort] || 0) - Number(a[sort] || 0));
      $("#content-tbody").innerHTML = rows.map(videoRow).join("") || `<tr><td colspan="7"><div class="tiny muted" style="padding:24px;text-align:center">没有匹配的稿件</div></td></tr>`;
      $("#content-count").textContent = `${rows.length} / ${videos.length} 条`;
      bindVideoRows();
    };
    $("#content-search").addEventListener("input", draw);
    $("#content-cat").addEventListener("change", draw);
    $("#content-sort").addEventListener("change", draw);
    draw();
  }

  function scatterOption(videos) {
    const points = videos.filter((v) => v.duration > 0).map((v) => [
      +(v.duration / 60).toFixed(1), v.first7, v.engagement_rate,
      v.title, v.id, v.conversion,
    ]);
    return {
      tooltip: { ...TOOLTIP, formatter: (p) => {
        const v = p.data;
        return `<div style="max-width:250px;white-space:normal;line-height:1.6"><b>${esc(v[3])}</b><br>时长 ${v[0]} 分钟 · 首7日播放 ${fmt(v[1])}<br>互动率 ${pct(v[2], 2)} · 转粉率 ${pct(v[5], 2)}</div>`;
      } },
      grid: { left: 52, right: 18, top: 18, bottom: 40 },
      xAxis: { type: "value", name: "时长 / 分钟", nameTextStyle: { color: "#6b7489", fontSize: 9 }, ...AXIS },
      yAxis: { type: "value", name: "首 7 日播放", nameTextStyle: { color: "#6b7489", fontSize: 9 }, ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
      series: [{
        type: "scatter", data: points,
        symbolSize: (v) => Math.max(7, Math.min(30, 7 + Math.sqrt(v[2] || 0) * 5)),
        itemStyle: {
          color: (p) => (p.data[5] >= 0.15 ? "rgba(251,114,153,.82)" : "rgba(124,92,255,.72)"),
          borderColor: "rgba(255,255,255,.18)", borderWidth: 1,
          shadowBlur: 8, shadowColor: "rgba(124,92,255,.25)",
        },
        emphasis: { itemStyle: { borderColor: "#fff", borderWidth: 1.5 } },
      }],
    };
  }

  // ------------------------------------------------------------------ growth
  function renderGrowth(d) {
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("粉丝增长", PAGE_META.growth.desc, `样本周期 ${d.series.length} 天<br>预测置信度 R² ${d.forecast.r2}`)}
      ${kpiCards(d.kpis)}
      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">粉丝累计与净增</div><div class="card-sub">柱形为每日净增，折线为粉丝总量</div></div><span class="pill-note">${d.series.length} 天</span></div>
          <div class="chart lg" id="growth-main"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">未来 14 天预测</div><div class="card-sub">基于近期趋势与星期效应，阴影为区间</div></div><span class="chip brand">${d.forecast.trend === "up" ? "上升" : d.forecast.trend === "down" ? "下行" : "平稳"}</span></div>
          <div class="chart lg" id="growth-forecast"></div>
          <div class="tiny muted" style="margin-top:2px">${esc(d.forecast.summary)}</div>
        </div>
      </div>
      <div class="grid-3 mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">粉丝里程碑</div><div class="card-sub">下一阶段目标进度</div></div></div>
          ${milestones(d.milestones)}
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">星期增长偏好</div><div class="card-sub">哪一天最容易涨粉</div></div></div>
          <div class="chart sm" id="growth-weekday"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">健康度拆解</div><div class="card-sub">短板优先于长板</div></div></div>
          ${healthSubs(d.health)}
        </div>
      </div>
      <div class="section-head"><h3>最会转粉的内容</h3><span class="tiny muted">按周期内转粉数排序</span></div>
      <div class="card"><div class="table-wrap"><table class="data-table"><thead><tr><th>稿件</th><th>发布</th><th>周期转粉</th><th>转粉率</th><th>周期播放</th><th>互动率</th></tr></thead>
        <tbody>${d.top_videos.map((v) => `<tr class="clickable" data-video-id="${v.id}"><td><div class="video-cell"><div class="video-thumb">${v.cover ? `<img src="${esc(v.cover)}" onerror="this.style.display='none'">` : "▶"}</div><div><div class="video-name">${esc(v.title)}</div><div class="video-meta">${shortDate(v.published_date)} · ${duration(v.duration)}</div></div></div></td><td class="num">${shortDate(v.published_date)}</td><td class="num pos">+${fmt(v.period_followers)}</td><td class="num">${pct(v.conversion, 2)}</td><td class="num">${fmt(v.period_views)}</td><td class="num">${pct(v.engagement_rate, 2)}</td></tr>`).join("") || `<tr><td colspan="6" class="tiny muted">暂无数据</td></tr>`}</tbody></table></div></div>
      <div class="warn-note mt14">${esc(d.platform_note || "")}</div>`;

    const growthFollowers = d.series.map((s) => Number(s.followers || 0)).filter((v) => v > 0);
    const growthMin = growthFollowers.length ? Math.max(0, Math.min(...growthFollowers) * 0.97) : 0;
    const growthMax = growthFollowers.length ? Math.max(...growthFollowers) * 1.01 : 100;
    makeChart("growth-main", {
      tooltip: { ...TOOLTIP, trigger: "axis" },
      legend: { data: ["净增粉丝", "粉丝总量"], top: 0, right: 4, textStyle: { color: "#9aa3b8", fontSize: 9 }, itemWidth: 10, itemHeight: 6 },
      grid: { left: 46, right: 50, top: 34, bottom: 28 },
      xAxis: { type: "category", data: d.series.map((s) => s.label), ...AXIS, splitLine: { show: false } },
      yAxis: [
        { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
        { type: "value", min: growthMin, max: growthMax, ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
      ],
      series: [
        { name: "净增粉丝", type: "bar", data: d.series.map((s) => s.net_followers), barMaxWidth: 12,
          itemStyle: { color: (p) => p.value >= 0 ? "rgba(52,211,153,.7)" : "rgba(248,113,113,.65)", borderRadius: [3, 3, 0, 0] } },
        { name: "粉丝总量", type: "line", yAxisIndex: 1, data: d.series.map((s) => s.followers), smooth: true, symbol: "none", lineStyle: { width: 2.2, color: "#7c5cff" } },
      ],
    });
    makeChart("growth-forecast", {
      tooltip: { ...TOOLTIP, trigger: "axis" },
      grid: { left: 44, right: 16, top: 16, bottom: 28 },
      xAxis: { type: "category", data: d.forecast.dates, ...AXIS, splitLine: { show: false } },
      yAxis: { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
      series: [
        { name: "下界", type: "line", data: d.forecast.lower, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 } },
        { name: "区间", type: "line", data: d.forecast.views.map((v, i) => Math.max(0, d.forecast.upper[i] - d.forecast.lower[i])), stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(124,92,255,.12)" } },
        { name: "预测播放", type: "line", data: d.forecast.views, smooth: true, symbol: "none", lineStyle: { color: "#22d3ee", width: 2.2, type: "dashed" } },
      ],
    });
    makeChart("growth-weekday", {
      tooltip: { ...TOOLTIP, trigger: "axis" },
      grid: { left: 40, right: 10, top: 12, bottom: 24 },
      xAxis: { type: "category", data: d.weekday_growth.map((x) => x.label), ...AXIS, splitLine: { show: false } },
      yAxis: { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
      series: [{ type: "bar", data: d.weekday_growth.map((x) => x.value), barMaxWidth: 22,
        itemStyle: { color: (p) => p.value >= 0 ? "rgba(124,92,255,.72)" : "rgba(248,113,113,.65)", borderRadius: [3, 3, 0, 0] } }],
    });
  }

  function milestones(rows) {
    return `<div style="display:flex;flex-direction:column;gap:10px">${rows.map((m) => `
      <div>
        <div class="flex between" style="font-size:9.5px;margin-bottom:3px">
          <span class="muted">${fmt(m.target)} 粉丝</span>
          <span class="tiny">${m.progress}% · 还差 ${fmt(m.remaining)}</span>
        </div>
        <div class="dur-track"><div class="dur-fill" style="width:${Math.min(100, m.progress)}%;background:linear-gradient(90deg,rgba(124,92,255,.8),rgba(251,114,153,.55))"></div></div>
      </div>`).join("")}</div>`;
  }

  function healthSubs(health) {
    return `<div style="display:flex;flex-direction:column;gap:9px;margin-top:2px">${health.subscores.map((s) => `
      <div><div class="flex between" style="font-size:9px;margin-bottom:3px"><span class="muted">${esc(s.label)}</span><span>${s.value}</span></div>
      <div class="dur-track"><div class="dur-fill" style="width:${s.value}%;background:linear-gradient(90deg,rgba(124,92,255,.8),rgba(34,211,238,.55))"></div></div></div>`).join("")}
      <div class="tiny muted" style="margin-top:3px">${esc(health.verdict)}</div></div>`;
  }

  // ------------------------------------------------------------------ traffic
  function renderTraffic(d) {
    const sources = d.sources || [];
    const total = sources.reduce((s, x) => s + x.views, 0) || 1;
    const age = d.demographics?.age || [];
    const gender = d.demographics?.gender || [];
    const device = d.demographics?.device || d.demographics?.device_detail || [];
    const region = d.demographics?.province || d.demographics?.country || [];
    const terms = d.demographics?.search_term || [];
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("流量洞察", PAGE_META.traffic.desc, `集中度 ${d.concentration}<br>结构 ${d.diversity}`)}
      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">流量来源</div><div class="card-sub">平台最近可用来源占比，按当前周期播放缩放</div></div><span class="pill-note">${sources.length} 个来源</span></div>
          <div class="chart lg" id="traffic-source"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">来源贡献排名</div><div class="card-sub">播放量 · 占比</div></div><span class="chip ${d.concentration > 2800 ? "warn" : "good"}">${esc(d.diversity)}</span></div>
          ${sources.length ? `<div class="dur-list">${sources.map((s) => `
            <div class="dur-row"><div><div class="dur-label">${esc(s.source)}</div><div class="dur-sub">${s.share}%</div></div>
              <div class="dur-track"><div class="dur-fill" style="width:${Math.max(2, s.share)}%"></div></div>
              <div class="dur-value">${fmt(s.views)}</div></div>`).join("")}</div>` : `<div class="tiny muted">同步后显示</div>`}
          <div class="divider"></div>
          <div class="flex between"><span class="tiny muted">来源集中度 (HHI)</span><span class="tiny">${d.concentration} / 10000</span></div>
          <div class="tiny muted" style="margin-top:4px">${d.concentration > 2800 ? "过度依赖单一来源，推荐位波动会直接冲击播放。" : "来源结构相对健康，继续培育搜索与站外流量。"}</div>
        </div>
      </div>
      <div class="grid-3 mt14">
        <div class="card"><div class="card-head"><div><div class="card-title">年龄结构</div><div class="card-sub">观看占比</div></div></div><div class="chart sm" id="traffic-age"></div></div>
        <div class="card"><div class="card-head"><div><div class="card-title">性别分布</div><div class="card-sub">观看占比</div></div></div><div class="chart sm" id="traffic-gender"></div></div>
        <div class="card"><div class="card-head"><div><div class="card-title">设备来源</div><div class="card-sub">播放终端占比</div></div></div><div class="chart sm" id="traffic-device"></div></div>
      </div>
      <div class="grid-2 mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">${d.demographics?.country ? "国家 / 地区" : "省份分布"}</div><div class="card-sub">按播放或受众规模排序</div></div></div>
          <div class="chart sm" id="traffic-region"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">搜索词与受众意图</div><div class="card-sub">YouTube 搜索来源；B 站以推荐流量为主</div></div><span class="pill-note">${terms.length} 个</span></div>
          ${terms.length ? `<div style="display:flex;flex-direction:column;gap:5px">${terms.slice(0, 12).map((t, i) => `<div class="flex between" style="font-size:9.5px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04)"><span><span class="muted">${i + 1}.</span> ${esc(t.name)}</span><span class="tiny muted">${fmt(t.value)}</span></div>`).join("")}</div>` : `<div class="tiny muted">暂无搜索词数据。B 站不公开搜索词；YouTube 账号同步后可用。</div>`}
        </div>
      </div>
      <div class="grid-2 mt14">
        <div class="card"><div class="card-head"><div><div class="card-title">流量诊断</div><div class="card-sub">从来源结构看风险与机会</div></div></div>${insightList(d.insights, 4)}</div>
        <div class="card"><div class="card-head"><div><div class="card-title">受众策略建议</div><div class="card-sub">基于当前画像的行动假设</div></div></div>
          <div class="suggest"><b>选题</b><span>优先覆盖 ${esc((age[0]?.name || "核心"))} 岁人群的强需求场景，用他们熟悉的案例开场。</span></div>
          <div class="suggest"><b>渠道</b><span>${d.concentration > 2800 ? "把 20% 精力投入搜索关键词与站外分发，降低推荐流依赖。" : "维持推荐流优势，同时用系列播放列表提升连续观看。"}</span></div>
          <div class="suggest"><b>形式</b><span>${device[0] ? `针对 ${esc(device[0].name)} 端优化首屏信息密度与字幕可读性。` : "根据主要设备端优化字幕和封面信息。"}</span></div>
          <div class="suggest"><b>验证</b><span>下一次更新后对比来源占比与粉丝质量，确认策略是否有效。</span></div>
        </div>
      </div>
      <div class="warn-note mt14">${esc(d.platform_note || "")}</div>`;

    if (sources.length) {
      makeChart("traffic-source", {
        tooltip: { ...TOOLTIP, trigger: "item", formatter: "{b}<br/>{c} 播放（{d}%）" },
        legend: { bottom: 0, left: "center", textStyle: { color: "#9aa3b8", fontSize: 9 }, itemWidth: 8, itemHeight: 8, icon: "circle" },
        series: [{
          type: "pie", radius: ["42%", "67%"], center: ["50%", "44%"], data: sources.map((s) => ({ name: s.source, value: s.views })),
          color: PALETTE, itemStyle: { borderColor: "#141826", borderWidth: 3, borderRadius: 4 },
          label: { color: "#b9c1d1", fontSize: 9, formatter: "{b}\n{d}%" }, labelLine: { length: 8, length2: 6, lineStyle: { color: "#394156" } },
        }],
        graphic: [{ type: "text", left: "center", top: "40%", style: { text: fmt(total), fill: "#eef0f8", fontSize: 17, fontWeight: 700, textAlign: "center" } },
          { type: "text", left: "center", top: "47%", style: { text: "总播放", fill: "#6b7489", fontSize: 8, textAlign: "center" } }],
      });
    }
    makeChart("traffic-age", donutOption(age, "年龄"));
    makeChart("traffic-gender", donutOption(gender, "性别"));
    makeChart("traffic-device", barOption(device, "设备"));
    makeChart("traffic-region", barOption(region, "地区", true));
  }

  function donutOption(items, name) {
    if (!items?.length) return { title: { text: "暂无数据", left: "center", top: "middle", textStyle: { color: "#5e687d", fontSize: 10 } } };
    return {
      tooltip: { ...TOOLTIP, trigger: "item", formatter: "{b}<br/>{d}%" },
      legend: { bottom: 0, textStyle: { color: "#9aa3b8", fontSize: 8 }, itemWidth: 7, itemHeight: 7, icon: "circle" },
      series: [{ type: "pie", radius: ["45%", "68%"], center: ["50%", "43%"], data: items.map((x) => ({ name: x.name, value: x.value })),
        color: PALETTE, label: { show: false }, itemStyle: { borderColor: "#141826", borderWidth: 2 } }],
    };
  }

  function barOption(items, label, horizontal = false) {
    if (!items?.length) return { title: { text: "暂无数据", left: "center", top: "middle", textStyle: { color: "#5e687d", fontSize: 10 } } };
    const data = items.slice(0, 10);
    if (horizontal) {
      return {
        tooltip: { ...TOOLTIP, trigger: "axis" },
        grid: { left: 58, right: 18, top: 6, bottom: 12 },
        xAxis: { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
        yAxis: { type: "category", data: data.map((x) => x.name).reverse(), ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, width: 52, overflow: "truncate" } },
        series: [{ type: "bar", data: data.map((x) => x.value).reverse(), barMaxWidth: 11, itemStyle: { color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [{ offset: 0, color: "rgba(124,92,255,.8)" }, { offset: 1, color: "rgba(34,211,238,.4)" }]), borderRadius: [0, 3, 3, 0] } }],
      };
    }
    return {
      tooltip: { ...TOOLTIP, trigger: "axis" },
      grid: { left: 38, right: 10, top: 12, bottom: 24 },
      xAxis: { type: "category", data: data.map((x) => x.name), ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, interval: 0, rotate: data.length > 5 ? 20 : 0 } },
      yAxis: { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (v) => fmt(v) } },
      series: [{ type: "bar", data: data.map((x) => x.value), barMaxWidth: 18, itemStyle: { color: "rgba(34,211,238,.55)", borderRadius: [3, 3, 0, 0] } }],
    };
  }

  // ------------------------------------------------------------------ timing
  function renderTiming(d) {
    const slots = d.best_slots || [];
    const cadence = d.cadence;
    const weekday = cadence.weekday_counts || [0, 0, 0, 0, 0, 0, 0];
    const maxWeek = Math.max(1, ...weekday);
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("发布策略", PAGE_META.timing.desc, `最佳时段 ${esc(slots[0]?.label || "样本不足")}<br>更新稳定性 ${cadence.consistency}/100`)}
      <div class="slot-grid mb14">
        ${slots.slice(0, 4).map((s, i) => `<div class="slot ${i === 0 ? "best" : ""}">
          <div class="slot-time">${esc(s.label)} ${i === 0 ? '<span class="chip brand" style="font-size:7px;margin-left:3px">推荐</span>' : ""}</div>
          <div class="slot-lift">${s.lift > 0 ? "+" : ""}${s.lift.toFixed(0)}%</div>
          <div class="slot-meta"><span>${s.count} 条样本</span><span class="conf ${s.confidence === "高" ? "high" : ""}">${s.confidence}置信</span></div>
        </div>`).join("") || '<div class="tiny muted">样本不足，先积累 10 条以上稿件。</div>'}
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">发布热力地图</div><div class="card-sub">横轴小时 · 纵轴星期 · 颜色为首 7 日播放</div></div><span class="pill-note">全历史样本</span></div>
          <div class="chart lg" id="timing-heat"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">更新节奏</div><div class="card-sub">稳定性比爆发更重要</div></div><span class="chip ${cadence.consistency >= 70 ? "good" : "warn"}">${cadence.consistency}/100</span></div>
          <div class="grid-3" style="gap:7px">
            <div class="stat-mini"><div class="label">周期更新</div><div class="value">${cadence.uploads}<span> 条</span></div></div>
            <div class="stat-mini"><div class="label">周均频率</div><div class="value">${cadence.per_week}<span> 条</span></div></div>
            <div class="stat-mini"><div class="label">平均间隔</div><div class="value">${cadence.avg_gap}<span> 天</span></div></div>
          </div>
          <div class="divider"></div>
          <div class="tiny muted">近 ${Math.min(12, cadence.recent_dates.length)} 次发布时间</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px">${cadence.recent_dates.slice(-12).map((x) => `<span class="chip" style="font-size:8px">${shortDate(x)}</span>`).join("")}</div>
          <div class="divider"></div>
          <div class="tiny" style="line-height:1.8">${esc(cadence.advice)}</div>
        </div>
      </div>
      <div class="grid-2b mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">星期发布分布</div><div class="card-sub">当前内容节奏</div></div></div>
          <div class="chart sm" id="timing-weekday"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">下两周排期建议</div><div class="card-sub">把重点稿件放到高杠杆时段</div></div></div>
          ${schedulePlan(slots, cadence)}
        </div>
      </div>
      <div class="section-head"><h3>不同时长的效率</h3><span class="tiny muted">首 7 日播放 · 转粉率 · 3 秒留存</span></div>
      <div class="card"><div class="table-wrap"><table class="data-table"><thead><tr><th>时长段</th><th>样本</th><th>首 7 日播放</th><th>互动率</th><th>转粉率</th><th>3 秒留存</th><th>3 秒跳出</th></tr></thead>
        <tbody>${(d.duration || []).map((r) => `<tr><td>${esc(r.label)}</td><td class="num">${r.count}</td><td class="num">${fmt(r.avg_views)}</td><td class="num">${pct(r.engagement, 2)}</td><td class="num">${pct(r.conversion, 2)}</td><td class="num">${r.retention3 == null ? "—" : pct(r.retention3)}</td><td class="num ${r.bounce3 > 40 ? "neg" : ""}">${r.bounce3 == null ? "—" : pct(r.bounce3)}</td></tr>`).join("")}</tbody></table></div>
        <div class="tiny muted" style="margin-top:9px">结论：优先把资源投入“高播放 + 高转粉”的时长段；若某段播放高但转粉低，多是泛流量，需强化账号定位与结尾引导。</div>
      </div>
      <div class="warn-note mt14">${esc(d.platform_note || "")}</div>`;

    makeChart("timing-heat", heatOption(d.heatmap, false));
    makeChart("timing-weekday", {
      tooltip: { ...TOOLTIP, trigger: "axis" },
      grid: { left: 34, right: 8, top: 12, bottom: 24 },
      xAxis: { type: "category", data: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"], ...AXIS, splitLine: { show: false } },
      yAxis: { type: "value", ...AXIS, minInterval: 1 },
      series: [{ type: "bar", data: weekday, barMaxWidth: 24, itemStyle: { color: "rgba(251,114,153,.55)", borderRadius: [3, 3, 0, 0] } }],
    });
  }

  function schedulePlan(slots, cadence) {
    const picks = slots.slice(0, 3);
    const cadenceText = cadence.per_week >= 2 ? "每周 2-3 更" : cadence.per_week >= 1 ? "每周 1-2 更" : "每周至少 1 更";
    return `<div class="best-card"><div class="best-head"><span>节奏</span><b>${cadenceText}</b></div><div class="best-sub">${esc(cadence.advice)}</div></div>
      ${picks.map((s, i) => `<div class="best-card"><div class="best-head"><span>第 ${i + 1} 优先时段</span><b>${esc(s.label)}</b></div><div class="best-sub">首 7 日播放 ${fmt(s.avg_first7)} · 较均值 ${s.lift > 0 ? "+" : ""}${s.lift.toFixed(0)}% · ${s.confidence}置信</div></div>`).join("")}
      <div class="best-card"><div class="best-head"><span>发布后 30 分钟</span><b>黄金互动窗</b></div><div class="best-sub">置顶一个问题、回复前 10 条评论，给算法一个继续分发的理由。</div></div>`;
  }

  // ------------------------------------------------------------------ retention
  function renderRetention(d) {
    state.lastRetention = d;
    const videos = d.videos || [];
    const curves = d.curves || [];
    const best = videos[0];
    const worst = videos[videos.length - 1];
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("留存诊断", PAGE_META.retention.desc, `${d.source === "model" ? "模型估算" : "平台真实数据"}<br>样本 ${videos.length} 条`)}
      <div class="grid-3 mb14">
        <div class="card"><div class="card-title">平均 3 秒留存</div><div class="kpi-value" style="margin-top:11px;color:${d.avg_retention3 >= 65 ? "var(--green)" : "var(--amber)"}">${d.avg_retention3}<span>%</span></div><div class="card-sub">健康线约 62-70%</div></div>
        <div class="card"><div class="card-title">平均 3 秒跳出</div><div class="kpi-value" style="margin-top:11px;color:${d.avg_bounce3 > 40 ? "var(--red)" : "var(--green)"}">${d.avg_bounce3}<span>%</span></div><div class="card-sub">越低越好，优先优化开场</div></div>
        <div class="card"><div class="card-title">最佳留存稿件</div><div class="kpi-value" style="margin-top:11px">${best ? best.retention3 : 0}<span>%</span></div><div class="card-sub" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(best?.title || "暂无数据")}</div></div>
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">受众留存曲线</div><div class="card-sub">横轴为视频进度，纵轴为仍在观看的比例</div></div>
            <select class="select" id="ret-select">${curves.map((c) => `<option value="${c.id}">${esc(c.title.slice(0, 34))}</option>`).join("")}</select>
          </div>
          <div class="chart lg" id="ret-curve"></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">留存 × 转粉</div><div class="card-sub">高留存是否真的带来关注</div></div><span class="pill-note">每点一条稿件</span></div>
          <div class="chart lg" id="ret-scatter"></div>
        </div>
      </div>
      <div class="grid-3 mt14">
        ${(d.buckets || []).map((b) => `<div class="card"><div class="card-title">${esc(b.label)}</div><div class="kpi-value" style="margin-top:9px">${b.count}<span>条</span></div><div class="card-sub">平均转粉 ${b.avg_conversion}% · 平均播放 ${fmt(b.avg_views)}</div></div>`).join("")}
      </div>
      <div class="grid-2 mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">留存诊断清单</div><div class="card-sub">按 3 秒留存排序</div></div></div>
          <div class="table-wrap"><table class="data-table"><thead><tr><th>稿件</th><th>时长</th><th>3秒留存</th><th>跳出</th><th>转粉</th></tr></thead>
            <tbody>${videos.slice(0, 12).map((v) => `<tr class="clickable" data-video-id="${v.id}"><td><div class="video-name" style="max-width:220px">${esc(v.title)}</div><div class="video-meta">${shortDate(v.published_at)}</div></td><td class="num">${duration(v.duration)}</td><td class="num ${v.retention3 >= 65 ? "pos" : "neg"}">${v.retention3}%</td><td class="num">${v.bounce3}%</td><td class="num">${v.conversion}%</td></tr>`).join("") || `<tr><td colspan="5" class="tiny muted">暂无留存数据</td></tr>`}</tbody></table></div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">怎么读这张图</div><div class="card-sub">从曲线形状定位问题</div></div></div>
          <div class="suggest"><b>0-3秒</b><span>断崖式下跌 = 开场承诺不清、片头太长或封面与内容不符。把结果、冲突或反常识结论前置。</span></div>
          <div class="suggest"><b>3-15秒</b><span>持续下滑 = 节奏拖沓或信息密度不足。每 5-8 秒给一个新信息点。</span></div>
          <div class="suggest"><b>中段</b><span>平台期 = 内容进入正题；若平台期过低，说明中段结构与预期不符。</span></div>
          <div class="suggest"><b>结尾</b><span>尾部抬升通常来自反转或彩蛋；可把这一结构产品化。</span></div>
          <div class="warn-note" style="margin-top:9px">${esc(d.note)}</div>
        </div>
      </div>`;

    const drawCurve = (id) => {
      const curve = curves.find((c) => Number(c.id) === Number(id)) || curves[0];
      if (!curve) return;
      const points = curve.points;
      if (state.retChart) { try { state.retChart.dispose(); } catch (_) {} state.retChart = null; }
      state.retChart = makeChart("ret-curve", {
        tooltip: { ...TOOLTIP, trigger: "axis", valueFormatter: (v) => `${v}%` },
        legend: { data: ["当前视频", "账号平均"], top: 0, right: 4, textStyle: { color: "#9aa3b8", fontSize: 9 }, itemWidth: 10, itemHeight: 6 },
        grid: { left: 44, right: 14, top: 34, bottom: 26 },
        xAxis: { type: "category", data: points.map((p) => `${Math.round(Number(p.point) * 100)}%`), ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, interval: 4 } },
        yAxis: { type: "value", min: 0, max: 100, ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: "{value}%" } },
        series: [
          { name: "当前视频", type: "line", data: points.map((p) => +(Number(p.audience_ratio) * 100).toFixed(2)), smooth: true, symbol: "none", lineStyle: { width: 2.8, color: "#fb7299" }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(251,114,153,.22)" }, { offset: 1, color: "rgba(251,114,153,0)" }]) } },
          { name: "账号平均", type: "line", data: (d.avg_curve || []), smooth: true, symbol: "none", lineStyle: { width: 1.6, color: "#22d3ee", type: "dashed" } },
        ],
      });
    };
    if (curves.length) {
      drawCurve(curves[0].id);
      $("#ret-select")?.addEventListener("change", (event) => drawCurve(event.target.value));
    }
    makeChart("ret-scatter", {
      tooltip: { ...TOOLTIP, formatter: (p) => `<div style="max-width:220px;white-space:normal"><b>${esc(p.data[2])}</b><br>留存 ${p.data[0]}% · 转粉 ${p.data[1]}%</div>` },
      grid: { left: 44, right: 16, top: 16, bottom: 32 },
      xAxis: { type: "value", name: "3秒留存 %", nameTextStyle: { color: "#6b7489", fontSize: 9 }, ...AXIS, min: 30, max: 95 },
      yAxis: { type: "value", name: "转粉率 %", nameTextStyle: { color: "#6b7489", fontSize: 9 }, ...AXIS },
      series: [{ type: "scatter", data: videos.map((v) => [v.retention3, v.conversion, v.title, v.id]),
        symbolSize: 9, itemStyle: { color: "rgba(124,92,255,.75)", borderColor: "rgba(255,255,255,.2)", borderWidth: 1 } }],
    });
  }

  // ------------------------------------------------------------------ lab
  function renderLab(d) {
    const tags = d.tags || [];
    const keywords = d.keywords || [];
    const maxKeyword = Math.max(1, ...keywords.map((k) => k.value));
    const slots = d.best_slots || [];
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("选题实验室", PAGE_META.lab.desc, `历史样本 ${d.top_videos?.length ? "已就绪" : "积累中"}<br>标题模型 v1`)}
      <div class="lab-grid">
        <div class="card">
          <div class="card-head"><div><div class="card-title">标题体检</div><div class="card-sub">用账号历史表现评估标题结构，而不是通用玄学</div></div><span class="chip brand">LOCAL MODEL</span></div>
          <textarea class="textarea title-input" id="lab-title" placeholder="输入一个候选标题，例如：我用 300 行代码，复刻了小时候的电子宠物">我用 300 行代码，复刻了小时候的电子宠物</textarea>
          <div class="analyze-row"><button class="btn primary" id="lab-analyze"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" stroke-linecap="round"/></svg> 分析标题</button><span class="tiny muted">Ctrl / ⌘ + Enter</span></div>
          <div id="lab-result" class="tiny muted" style="margin-top:16px;padding-top:14px;border-top:1px solid var(--line)">输入候选标题，查看预测播放、结构优势与改写建议。</div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">高潜标签</div><div class="card-sub">按历史首 7 日播放排序</div></div><span class="pill-note">${tags.length} 个</span></div>
          <div class="tag-cloud">${tags.slice(0, 16).map((t, i) => `<span class="cloud-tag ${i < 5 ? "hot" : ""}" style="font-size:${Math.max(9, Math.min(13, 9 + Math.sqrt(t.count)))}px" title="${t.count} 条 · 首7日 ${fmt(t.avg_views)}">${esc(t.tag)}<span style="opacity:.5;font-size:7px;margin-left:4px">${t.lift > 0 ? "+" : ""}${t.lift}%</span></span>`).join("") || '<span class="tiny muted">暂无标签</span>'}</div>
          <div class="divider"></div>
          <div class="tiny muted">关键词频率（来自标题）</div>
          <div class="tag-cloud" style="margin-top:8px">${keywords.slice(0, 26).map((k) => `<span class="cloud-tag" style="opacity:${0.45 + k.value / maxKeyword * 0.55};font-size:${8.5 + k.value / maxKeyword * 4}px">${esc(k.name)}</span>`).join("") || '<span class="tiny muted">暂无关键词</span>'}</div>
        </div>
      </div>
      <div class="grid-2 mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">高杠杆发布窗口</div><div class="card-sub">提交前先决定发布时间</div></div></div>
          ${slots.length ? slots.map((s, i) => `<div class="best-card"><div class="best-head"><span>#${i + 1} ${esc(s.label)}</span><b>${s.lift > 0 ? "+" : ""}${s.lift.toFixed(0)}%</b></div><div class="best-sub">${s.count} 条样本 · ${s.confidence}置信 · 首7日 ${fmt(s.avg_first7)}</div></div>`).join("") : '<div class="tiny muted">暂无足够样本</div>'}
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">爆款基因</div><div class="card-sub">从历史高播放稿件提取可复用结构</div></div></div>
          ${(d.top_videos || []).slice(0, 5).map((v, i) => `<div class="top-row clickable" data-video-id="${v.id}"><div class="rank r${i + 1}">${String(i + 1).padStart(2, "0")}</div><div class="top-info"><div class="top-title">${esc(v.title)}</div><div class="top-meta">${fmt(v.period_views)} 周期播放 · 互动 ${pct(v.engagement_rate, 2)}</div></div><span class="tag pink">${esc((v.tags || [])[0] || "内容")}</span></div>`).join("") || '<div class="tiny muted">暂无数据</div>'}
        </div>
      </div>
      <div class="card mt14">
        <div class="card-head"><div><div class="card-title">结构实验建议</div><div class="card-sub">下一轮内容可以验证的三个假设</div></div></div>
        <div class="grid-3">
          <div class="best-card"><div class="best-head"><span>H1 · 数字承诺</span><b>+ 播放</b></div><div class="best-sub">用具体数字替代形容词，测试同一选题的两种标题，间隔 7 天发布。</div></div>
          <div class="best-card"><div class="best-head"><span>H2 · 反常识开场</span><b>+ 留存</b></div><div class="best-sub">前 3 秒先给与常识相反的结论，再用正文解释，观察 3 秒留存变化。</div></div>
          <div class="best-card"><div class="best-head"><span>H3 · 系列化标签</span><b>+ 转粉</b></div><div class="best-sub">连续 3 期使用同一标签与封面版式，测试系列识别对转粉的影响。</div></div>
        </div>
      </div>`;

    const analyze = async () => {
      const title = $("#lab-title").value.trim();
      if (!title) { toast("请输入标题", "info"); return; }
      const button = $("#lab-analyze");
      button.disabled = true;
      try {
        const r = await api("/api/title/analyze", { method: "POST", body: { account_id: state.accountId, title } });
        $("#lab-result").innerHTML = `
          <div class="score-box">
            <div class="score-circle" style="--v:${r.score}"><span>${r.score}</span></div>
            <div class="score-info"><h4>${r.grade} 级标题 · 预测首 7 日播放 ${esc(r.predicted_label)}</h4><p>基于账号历史样本的点击结构模型，预测仅代表相对概率，不保证实际播放。</p></div>
          </div>
          <div class="reason-list">${(r.reasons || []).map((x) => `<div class="reason">${esc(x)}</div>`).join("")}</div>
          <div class="divider"></div>
          <div class="tiny muted" style="margin-bottom:6px">改写建议</div>
          ${(r.suggestions || []).map((x) => `<div class="suggest"><b>建议</b><span>${esc(x)}</span></div>`).join("") || '<div class="tiny muted">结构已经比较完整，可以直接进入制作。</div>'}`;
      } catch (error) {
        $("#lab-result").innerHTML = `<div class="alert err">${esc(error.message)}</div>`;
      } finally { button.disabled = false; }
    };
    $("#lab-analyze").addEventListener("click", analyze);
    $("#lab-title").addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") analyze();
    });
  }

  // ------------------------------------------------------------------ reports
  function renderReports(d) {
    const files = d.files || [];
    $("#view").innerHTML = `${demoBanner()}
      ${pageHead("报表中心", PAGE_META.reports.desc, `本机归档<br>${files.length} 份历史文件`)}
      <div class="report-grid">
        ${[
          { days: 7, title: "周报 · 快速复盘", desc: "适合每周固定复盘：本周流量、涨粉、内容表现与下周动作。" },
          { days: 30, title: "月报 · 运营全检", desc: "完整分析月：留存、时长、流量结构与账号健康度。" },
          { days: 90, title: "季报 · 战略回顾", desc: "看趋势与结构变化，适合季度选题规划与账号定位复盘。" },
        ].map((r) => `<div class="report-card">
          <div class="report-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 2h9l4 4v16H6V2z"/><path d="M15 2v4h4M9 11h7M9 15h7M9 19h4" stroke-linecap="round"/></svg></div>
          <h4>${r.title}</h4><p>${r.desc}</p>
          <button class="btn primary small" data-report-days="${r.days}">生成 ${r.days} 天报告</button>
        </div>`).join("")}
      </div>
      <div class="grid-2 mt14">
        <div class="card">
          <div class="card-head"><div><div class="card-title">快捷数据导出</div><div class="card-sub">适合二次分析或交给团队</div></div></div>
          <div class="report-files">
            <div class="file-row" id="export-csv"><div class="file-type">CSV</div><div class="file-name">全部稿件明细 · UTF-8 BOM</div><span class="btn small ghost">下载</span></div>
            <div class="file-row" id="export-xlsx"><div class="file-type xlsx">XLS</div><div class="file-name">完整 Excel 工作簿 · 含图表</div><span class="btn small ghost">生成</span></div>
            <div class="file-row" id="export-html"><div class="file-type">HTML</div><div class="file-name">交互式 HTML 报告 · 可打印</div><span class="btn small ghost">生成</span></div>
          </div>
          <div class="tiny muted" style="margin-top:10px">报告默认保存在本机数据目录，可离线打开；PDF 由 Edge 无头模式自动渲染。</div>
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">最近生成的报告</div><div class="card-sub">文件不会上传到任何服务器</div></div><span class="pill-note">${files.length} 份</span></div>
          ${files.length ? `<div class="report-files">${files.slice(0, 7).map((f) => `<a class="file-row" href="${esc(f.url)}" target="_blank"><div class="file-type ${f.ext === "xlsx" ? "xlsx" : f.ext === "pdf" ? "pdf" : ""}">${f.ext.toUpperCase()}</div><div class="file-name">${esc(f.name)}</div><span class="file-size">${f.size_label}</span></a>`).join("")}</div>` : `<div class="tiny muted" style="padding:16px 0">还没有生成报告。选择上方周期开始。</div>`}
        </div>
      </div>
      <div class="warn-note mt14">报告中的 B 站 3 秒跳出率为互动模型估算，已在报告页脚标注；YouTube 留存为平台真实数据。请勿把估算值当作平台后台绝对值。</div>`;

    $$("[data-report-days]").forEach((el) => el.addEventListener("click", () => generateReport(Number(el.dataset.reportDays))));
    $("#export-csv")?.addEventListener("click", () => downloadFile(`/api/export/videos.csv?account_id=${state.accountId}&days=90`, "MediaPulse_videos.csv"));
    $("#export-xlsx")?.addEventListener("click", () => generateReport(30, "xlsx"));
    $("#export-html")?.addEventListener("click", () => generateReport(30, "html"));
  }

  async function generateReport(days, kind = "full") {
    const account = activeAccount();
    if (!account) { toast("请先连接账号", "error"); return; }
    showModal(`<div class="modal-head"><div><h3>正在生成 ${days} 天运营报告</h3><p>聚合数据、渲染图表、生成 Excel 与 PDF，通常需要 10-30 秒。</p></div></div>
      <div style="display:flex;align-items:center;gap:14px;padding:16px 0"><div class="boot-logo" style="width:46px;height:46px;border-radius:13px;margin:0"><svg viewBox="0 0 24 24" fill="none" style="width:24px;height:24px"><path d="M2 13h4l2.2-6 3.1 11L14 10l2 3h6" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div style="flex:1"><div class="skeleton" style="height:8px;width:100%"></div><div class="tiny muted" style="margin-top:8px" id="report-status">正在准备报告数据…</div></div></div>`);
    try {
      const result = await api(`/api/report?account_id=${account.id}&days=${days}&pdf=${kind === "full" ? "1" : "0"}`);
      const links = [];
      if (result.html) links.push({ type: "HTML", label: "交互式报告", url: result.html_url, desc: "在新标签页打开，可直接打印" });
      if (result.pdf) links.push({ type: "PDF", label: "PDF 归档", url: result.pdf_url, desc: "适合分享与存档" });
      if (result.xlsx) links.push({ type: "XLS", label: "Excel 工作簿", url: result.xlsx_url, desc: "含每日数据、视频明细与诊断" });
      showModal(`<div class="modal-head"><div><h3>报告已生成</h3><p>${esc(account.name)} · ${days} 天 · ${datetime(new Date().toISOString())}</p></div><button class="modal-close" data-close="1">×</button></div>
        <div class="alert info">${esc(result.summary || "报告已保存在本机数据目录。")}</div>
        ${result.ai_summary ? `<div class="ai-summary" style="font-size:11px;line-height:1.8;color:#c7cede;background:rgba(34,211,238,.05);border:1px solid rgba(34,211,238,.2);border-left:3px solid var(--cyan);border-radius:10px;padding:12px 14px;margin-bottom:12px;white-space:pre-wrap">${esc(result.ai_summary)}</div>` : ""}
        ${result.ai_error ? `<div class="alert warn">${esc(result.ai_error)}</div>` : ""}
        <div class="report-files">${links.map((l) => `<a class="file-row" href="${esc(l.url)}" target="_blank"><div class="file-type ${l.type === "XLS" ? "xlsx" : l.type === "PDF" ? "pdf" : ""}">${l.type}</div><div class="file-name">${esc(l.label)}<div class="tiny muted" style="font-weight:400;margin-top:2px">${esc(l.desc)}</div></div><span class="btn small ghost">打开</span></a>`).join("")}</div>
        ${result.pdf_error ? `<div class="alert warn" style="margin-top:12px">PDF 自动渲染未完成：${esc(result.pdf_error)}。可以打开 HTML 报告后使用浏览器打印为 PDF。</div>` : ""}
        <div class="flex" style="justify-content:flex-end;margin-top:16px"><button class="btn" data-close="1">关闭</button></div>`);
      bindModalClose();
    } catch (error) {
      showModal(`<div class="modal-head"><div><h3>报告生成失败</h3><p>${esc(error.message)}</p></div><button class="modal-close" data-close="1">×</button></div>
        <div class="alert err">可以先尝试“仅生成 HTML”或稍后重试。若 PDF 渲染失败，通常是 Edge 正在更新。</div>
        <div class="flex" style="justify-content:flex-end"><button class="btn" data-close="1">关闭</button></div>`);
      bindModalClose();
    }
  }

  async function downloadFile(url, filename) {
    try {
      const res = await fetch(url, { headers: { "X-MP-Token": state.token } });
      if (!res.ok) throw new Error("下载失败");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 3000);
    } catch (error) { toast(error.message, "error"); }
  }

  // ------------------------------------------------------------------ settings
  function renderSettings({ boot }) {
    const settings = boot.settings || {};
    const accounts = boot.accounts || [];
    $("#view").innerHTML = `${pageHead("账号与设置", PAGE_META.settings.desc, `数据目录<br>${esc(boot.data_dir || "本机")}`)}
      <div class="settings-grid">
        <div>
          <div class="card">
            <div class="card-head"><div><div class="card-title">已连接账号</div><div class="card-sub">支持同时管理多个 B 站 / YouTube 账号</div></div><button class="btn primary small" id="settings-add">＋ 连接账号</button></div>
            ${accounts.map((a) => `<div class="connected-account">${avatar(a, "avatar").replace('class="avatar"', 'class="avatar" style="width:32px;height:32px;border-radius:9px"')}
              <div class="connected-info"><div class="connected-name">${platformIcon(a)} ${esc(a.name)} ${a.is_demo ? '<span class="tag pink">演示</span>' : ""} ${a.status === "auth_expired" ? '<span class="tag" style="background:rgba(248,113,113,.12);color:#f3a1a1">登录失效</span>' : ""}</div>
              <div class="connected-sub">${platformName(a)} · ${fmt(a.followers)} 粉丝 · ${a.last_sync ? `同步于 ${datetime(a.last_sync)}` : "尚未同步"}</div></div>
              <button class="btn small ghost" data-disconnect="${a.id}">断开</button></div>`).join("") || `<div class="tiny muted" style="padding:18px 0">还没有连接账号。</div>`}
          </div>
          <div class="card mt14">
            <div class="card-head"><div><div class="card-title">同步与提醒</div><div class="card-sub">本程序不常驻后台服务，自动同步仅在运行时检查</div></div></div>
            <div class="field"><label>自动同步间隔</label><select class="select" id="set-auto"><option value="0">关闭（手动同步）</option><option value="30">每 30 分钟</option><option value="60">每 1 小时</option><option value="180">每 3 小时</option><option value="720">每 12 小时</option></select><div class="field-hint">登录后首次同步会拉取近 90 天数据；之后增量更新。</div></div>
            <div class="field"><label>默认分析周期</label><select class="select" id="set-range"><option value="7">近 7 天</option><option value="30">近 30 天</option><option value="90">近 90 天</option><option value="180">近 180 天</option></select></div>
            <button class="btn primary small" id="settings-save">保存设置</button>
          </div>
          <div class="card mt14">
            <div class="card-head"><div><div class="card-title">可选 AI 摘要</div><div class="card-sub">不填写也能使用全部规则诊断</div></div><span class="pill-note">DeepSeek</span></div>
            <div class="field"><label>API Key</label><input class="input" id="set-key" type="password" placeholder="${settings.has_deepseek_key ? "已保存（留空则不修改）" : "sk-...（可选）"}"><div class="field-hint">密钥仅保存在本机 SQLite。启用后生成报告时，会把聚合指标（不含评论原文与粉丝明细）发送给 DeepSeek 生成一段运营结论。</div></div>
            <div class="switch-row"><div class="switch-label">启用 AI 摘要<span>将汇总指标发送给你配置的模型服务</span></div><div class="switch" id="set-llm"></div></div>
          </div>
        </div>
        <div>
          <div class="card">
            <div class="card-head"><div><div class="card-title">连接新平台</div><div class="card-sub">扫码或 OAuth，不需要输入密码</div></div></div>
            <div class="platform-cards">
              <div class="platform-card" id="settings-bili"><div class="p-icon bili">B</div><h4>哔哩哔哩</h4><p>扫码登录，读取公开视频数据与创作中心数据。</p></div>
              <div class="platform-card" id="settings-yt"><div class="p-icon yt">▶</div><h4>YouTube</h4><p>Google OAuth，读取 Data API 与 Analytics。</p></div>
            </div>
            <div class="alert info" style="margin-top:12px">登录凭据只存在本机加密前的 SQLite 中。建议在个人电脑使用，不要共享数据目录。</div>
          </div>
          <div class="card mt14">
            <div class="card-head"><div><div class="card-title">数据与隐私</div><div class="card-sub">Local-first 设计</div></div><span class="local-chip"><span class="local-dot"></span> LOCAL</span></div>
            <div class="legal">
              <p><b>数据位置</b><br>${esc(boot.data_dir || "本机数据目录")}</p>
              <p><b>采集范围</b><br>B 站：公开视频信息、播放/互动、创作中心统计、流量来源、受众画像。YouTube：频道、视频、Analytics 留存、流量来源、受众画像、评论。</p>
              <p><b>不上传</b><br>MediaPulse 不运营云端账号系统，不会把你的数据发送到第三方。只有在你配置 AI Key 并主动启用时，汇总指标才会发送给对应模型服务。</p>
              <p><b>合规</b><br>请仅分析你拥有或获授权的账号，遵守平台服务条款，控制同步频率。</p>
            </div>
          </div>
          <div class="card mt14">
            <div class="card-head"><div><div class="card-title">维护</div><div class="card-sub">演示数据与程序退出</div></div></div>
            <div class="flex" style="flex-wrap:wrap"><button class="btn small" id="settings-reset">重置演示数据</button><button class="btn small" id="settings-quit">退出程序</button></div>
            <div class="tiny muted" style="margin-top:10px">版本 ${esc(boot.app.version)} · 构建 ${esc(boot.app.build)} · 数据引擎 SQLite</div>
          </div>
        </div>
      </div>`;

    $("#set-auto").value = settings.auto_sync_minutes || "0";
    $("#set-range").value = settings.last_range || "30";
    $("#set-llm").classList.toggle("on", settings.llm_enabled === "1");
    $("#set-llm").addEventListener("click", () => $("#set-llm").classList.toggle("on"));
    $("#settings-save").addEventListener("click", async () => {
      const payload = {
        auto_sync_minutes: $("#set-auto").value,
        last_range: $("#set-range").value,
        llm_enabled: $("#set-llm").classList.contains("on") ? "1" : "0",
      };
      const key = $("#set-key").value.trim();
      if (key) payload.deepseek_api_key = key;
      try { await api("/api/settings", { method: "POST", body: payload }); toast("设置已保存", "success"); }
      catch (error) { toast(error.message, "error"); }
    });
    $("#settings-add").addEventListener("click", openConnectModal);
    $("#settings-bili").addEventListener("click", () => startBiliLogin());
    $("#settings-yt").addEventListener("click", () => startYouTubeLogin());
    $$("[data-disconnect]").forEach((el) => el.addEventListener("click", async () => {
      const id = Number(el.dataset.disconnect);
      const account = accounts.find((a) => Number(a.id) === id);
      if (!confirm(`确定断开「${account?.name || "该账号"}」？本机保存的该账号历史数据也会删除。`)) return;
      try {
        await api(`/api/accounts/${id}`, { method: "DELETE" });
        toast("账号已断开", "success");
        await refreshBootstrap();
        state.cache = {};
        navigate("settings", true);
      } catch (error) { toast(error.message, "error"); }
    }));
    $("#settings-reset").addEventListener("click", async () => {
      if (!confirm("重置演示数据会删除并重建演示账号，不影响真实账号。继续？")) return;
      try { await api("/api/demo/reset", { method: "POST", body: {} }); toast("演示数据已重置", "success"); await refreshBootstrap(); state.cache = {}; navigate("overview", true); }
      catch (error) { toast(error.message, "error"); }
    });
    $("#settings-quit").addEventListener("click", async () => {
      if (!confirm("退出 MediaPulse？本地服务将停止。")) return;
      try { await api("/api/shutdown", { method: "POST", body: {} }); } catch (_) {}
      document.body.innerHTML = `<div class="empty" style="height:100vh"><div class="empty-icon">✓</div><h3>MediaPulse 已退出</h3><p>现在可以关闭这个窗口。</p></div>`;
    });
  }

  // ------------------------------------------------------------------ modal / toast
  function showModal(html, wide = false) {
    const root = $("#modal-root");
    root.innerHTML = `<div class="modal-mask"><div class="modal ${wide ? "wide" : ""}">${html}</div></div>`;
    const mask = $(".modal-mask", root);
    mask.addEventListener("click", (event) => { if (event.target === mask) closeModal(); });
    bindModalClose();
  }

  function bindModalClose() {
    $$("[data-close]", $("#modal-root")).forEach((el) => el.onclick = closeModal);
  }

  function closeModal() {
    $("#modal-root").innerHTML = "";
    if (state.qrTimer) { clearInterval(state.qrTimer); state.qrTimer = null; }
    if (state.ytTimer) { clearInterval(state.ytTimer); state.ytTimer = null; }
  }

  function toast(message, type = "info", title = "") {
    const root = $("#toast-root");
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<div style="flex:1"><div class="toast-title">${esc(title || (type === "error" ? "操作失败" : type === "success" ? "完成" : "提示"))}</div><div class="toast-msg">${esc(message)}</div></div>`;
    root.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(6px)"; el.style.transition = ".25s"; setTimeout(() => el.remove(), 300); }, type === "error" ? 6000 : 3800);
  }

  // ------------------------------------------------------------------ connect accounts
  function openConnectModal() {
    showModal(`<div class="modal-head"><div><h3>连接账号</h3><p>扫码或 OAuth 授权，MediaPulse 不会接触你的密码。</p></div><button class="modal-close" data-close="1">×</button></div>
      <div class="platform-cards">
        <div class="platform-card" id="connect-bili"><div class="p-icon bili">B</div><h4>哔哩哔哩</h4><p>使用 B 站 App 扫码登录。同步公开视频、创作中心数据、流量来源与受众画像。</p><div class="tiny" style="color:var(--brand-2);margin-top:9px">扫码登录 →</div></div>
        <div class="platform-card" id="connect-yt"><div class="p-icon yt">▶</div><h4>YouTube</h4><p>通过 Google OAuth 授权。同步 Data API + Analytics，包括真实留存曲线。</p><div class="tiny" style="color:var(--brand-2);margin-top:9px">开始授权 →</div></div>
      </div>
      <div class="alert info" style="margin-top:14px">B 站扫码登录后会自动同步一次；YouTube 需要你提前在 Google Cloud 创建 OAuth 桌面客户端，详细步骤会在下一步给出。</div>`);
    $("#connect-bili").addEventListener("click", startBiliLogin);
    $("#connect-yt").addEventListener("click", startYouTubeLogin);
  }

  async function startBiliLogin() {
    showModal(`<div class="modal-head"><div><h3>B 站扫码登录</h3><p>打开哔哩哔哩 App，扫描二维码并确认。</p></div><button class="modal-close" data-close="1">×</button></div>
      <div class="qr-box"><div class="qr-wrap" id="qr-wrap"><div class="skeleton" style="width:150px;height:150px"></div></div>
      <div class="qr-status" id="qr-status">正在生成二维码…</div><div class="qr-tip">登录信息仅保存在本机，用于读取你自己的账号数据</div></div>
      <div class="flex" style="justify-content:center;margin-top:8px"><button class="btn small ghost" id="qr-refresh">刷新二维码</button></div>`);
    $("#qr-refresh").addEventListener("click", startBiliLogin);
    try {
      const qr = await api("/api/auth/bilibili/qr", { method: "POST", body: {} });
      const wrap = $("#qr-wrap");
      wrap.innerHTML = "";
      if (window.QRCode) {
        new QRCode(wrap, { text: qr.url, width: 170, height: 170, colorDark: "#0a0a0a", colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.M });
      } else {
        wrap.innerHTML = `<div style="font-size:8px;word-break:break-all;color:#111">${esc(qr.url)}</div>`;
      }
      $("#qr-status").innerHTML = `等待扫码 <b id="qr-count">${qr.expires_in || 180}</b> 秒`;
      let left = Number(qr.expires_in || 180);
      if (state.qrTimer) clearInterval(state.qrTimer);
      state.qrTimer = setInterval(async () => {
        left -= 2;
        const counter = $("#qr-count");
        if (counter) counter.textContent = Math.max(0, left);
        if (left <= 0) { clearInterval(state.qrTimer); state.qrTimer = null; $("#qr-status").innerHTML = `<span class="neg">二维码已过期，请刷新</span>`; return; }
        try {
          const result = await api("/api/auth/bilibili/poll", { method: "POST", body: { key: qr.key } });
          if (result.status === "scanned") $("#qr-status").innerHTML = `<span style="color:var(--green)">已扫码，请在手机上确认登录</span>`;
          else if (result.status === "expired") { clearInterval(state.qrTimer); state.qrTimer = null; $("#qr-status").innerHTML = `<span class="neg">二维码已过期，请刷新</span>`; }
          else if (result.status === "error") { clearInterval(state.qrTimer); state.qrTimer = null; $("#qr-status").innerHTML = `<span class="neg">${esc(result.message || "登录失败")}</span>`; }
          else if (result.status === "success") {
            clearInterval(state.qrTimer); state.qrTimer = null;
            closeModal();
            toast("B 站登录成功，正在同步数据", "success", "账号已连接");
            await refreshBootstrap();
            state.accountId = result.account.id;
            localStorage.setItem("mp_account", String(result.account.id));
            state.cache = {};
            updateChrome(); renderAccountMenu(); navigate("overview", true);
            if (result.job_id) trackJob(result.job_id);
          }
        } catch (error) {
          clearInterval(state.qrTimer); state.qrTimer = null;
          const status = $("#qr-status"); if (status) status.innerHTML = `<span class="neg">${esc(error.message)}</span>`;
        }
      }, 2000);
    } catch (error) {
      $("#qr-wrap").innerHTML = `<div class="alert err" style="font-size:9px">${esc(error.message)}</div>`;
      $("#qr-status").textContent = "二维码生成失败";
    }
  }

  function startYouTubeLogin() {
    const redirect = `${location.origin}/oauth2callback`;
    showModal(`<div class="modal-head"><div><h3>连接 YouTube</h3><p>需要 Google Cloud OAuth 桌面客户端，按下面 4 步操作。</p></div><button class="modal-close" data-close="1">×</button></div>
      <div class="steps">
        <div class="step">打开 Google Cloud Console，创建（或选择）项目，启用 <b>YouTube Data API v3</b> 与 <b>YouTube Analytics API</b>。</div>
        <div class="step">配置 OAuth 同意屏幕：选择 External，把你自己加入 Test users。应用无需发布。</div>
        <div class="step">创建凭据 → OAuth 客户端 ID → 应用类型选择 <b>桌面应用</b>，下载 JSON。</div>
        <div class="step">把 JSON 内容粘贴到下方，点击开始授权。Google 会打开新窗口。</div>
      </div>
      <div class="alert info">回调地址已自动使用本机端口；如果 Google 要求填写重定向 URI，请填写：</div>
      <div class="redirect-box">${esc(redirect)}</div>
      <div class="field"><label>OAuth 客户端 JSON</label><textarea class="textarea" id="yt-client" style="min-height:104px;font-family:ui-monospace,Consolas,monospace;font-size:9px" placeholder='{"installed":{"client_id":"...","client_secret":"...","redirect_uris":["http://localhost"]}}'></textarea></div>
      <div id="yt-alert"></div>
      <div class="flex between"><span class="tiny muted">授权只请求只读权限</span><button class="btn primary" id="yt-start">开始 Google 授权</button></div>`);
    $("#yt-start").addEventListener("click", async () => {
      const raw = $("#yt-client").value.trim();
      if (!raw) { $("#yt-alert").innerHTML = `<div class="alert err">请先粘贴 OAuth 客户端 JSON。</div>`; return; }
      const popup = window.open("about:blank", "_blank", "width=620,height=760");
      try {
        const r = await api("/api/auth/youtube/start", { method: "POST", body: { client_json: raw } });
        if (popup) popup.location.href = r.auth_url; else window.open(r.auth_url, "_blank");
        $("#yt-alert").innerHTML = `<div class="alert info">已打开 Google 授权页。完成授权后此窗口会自动更新。</div>`;
        if (state.ytTimer) clearInterval(state.ytTimer);
        let tries = 0;
        state.ytTimer = setInterval(async () => {
          tries += 1;
          if (tries > 180) { clearInterval(state.ytTimer); state.ytTimer = null; return; }
          try {
            const s = await api("/api/auth/youtube/status");
            if (s.status === "success") {
              clearInterval(state.ytTimer); state.ytTimer = null;
              closeModal();
              toast("YouTube 授权成功，正在同步数据", "success", "账号已连接");
              await refreshBootstrap();
              if (s.account_id) { state.accountId = s.account_id; localStorage.setItem("mp_account", String(s.account_id)); }
              state.cache = {};
              updateChrome(); renderAccountMenu(); navigate("overview", true);
              if (s.job_id) trackJob(s.job_id);
            } else if (s.status === "error") {
              clearInterval(state.ytTimer); state.ytTimer = null;
              $("#yt-alert").innerHTML = `<div class="alert err">${esc(s.message || "授权失败")}</div>`;
            }
          } catch (_) {}
        }, 1500);
      } catch (error) {
        if (popup) popup.close();
        $("#yt-alert").innerHTML = `<div class="alert err">${esc(error.message)}</div>`;
      }
    });
  }

  // ------------------------------------------------------------------ jobs
  async function trackJob(jobId) {
    if (!jobId) return;
    state.jobId = jobId;
    if (state.jobTimer) clearInterval(state.jobTimer);
    const pill = $("#job-pill"), text = $("#job-text"), bar = $("#job-bar");
    pill.classList.remove("hidden");
    const tick = async () => {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        text.textContent = job.message || "同步中";
        bar.style.width = `${job.progress || 0}%`;
        if (job.status === "success") {
          clearInterval(state.jobTimer); state.jobTimer = null; state.jobId = null;
          pill.classList.add("hidden");
          toast("数据同步完成，图表与诊断已更新", "success", "同步完成");
          await refreshBootstrap();
          state.cache = {};
          loadPage(true);
        } else if (job.status === "error") {
          clearInterval(state.jobTimer); state.jobTimer = null; state.jobId = null;
          pill.classList.add("hidden");
          toast(job.message || "同步失败", "error", "同步失败");
          updateChrome();
        }
      } catch (error) {
        clearInterval(state.jobTimer); state.jobTimer = null; state.jobId = null;
        pill.classList.add("hidden");
        toast(error.message, "error");
      }
    };
    tick();
    state.jobTimer = setInterval(tick, 1200);
  }

  // ------------------------------------------------------------------ video drawer
  function bindVideoRows() {
    $$("[data-video-id]").forEach((el) => {
      if (el.dataset.bound === "1") return;
      el.dataset.bound = "1";
      el.addEventListener("click", (event) => {
        if (event.target.closest("a,button,select,input")) return;
        openVideo(Number(el.dataset.videoId));
      });
    });
  }

  async function openVideo(id) {
    const mask = document.createElement("div");
    mask.className = "drawer-mask";
    mask.id = "drawer-mask";
    const drawer = document.createElement("div");
    drawer.className = "drawer";
    drawer.id = "drawer";
    drawer.innerHTML = `<div class="drawer-body"><div class="skeleton" style="height:28px;width:70%;margin-bottom:12px"></div><div class="skeleton" style="height:14px;width:45%;margin-bottom:20px"></div><div class="skeleton" style="height:180px"></div></div>`;
    document.body.append(mask, drawer);
    requestAnimationFrame(() => { mask.classList.add("show"); drawer.classList.add("show"); });
    mask.addEventListener("click", closeDrawer);
    try {
      const d = await api(`/api/video/${id}`);
      renderVideoDrawer(d);
    } catch (error) {
      drawer.innerHTML = `<div class="drawer-body"><div class="alert err">${esc(error.message)}</div></div>`;
    }
  }

  function closeDrawer() {
    $("#drawer-mask")?.classList.remove("show");
    $("#drawer")?.classList.remove("show");
    setTimeout(() => { $("#drawer-mask")?.remove(); $("#drawer")?.remove(); }, 280);
    state.drawerCharts?.forEach((c) => { try { c.dispose(); } catch (_) {} });
    state.drawerCharts = [];
  }

  function renderVideoDrawer(d) {
    const v = d.video, s = d.stats;
    const sentimentTotal = Math.max(1, d.sentiment.positive + d.sentiment.neutral + d.sentiment.negative);
    const drawer = $("#drawer");
    drawer.innerHTML = `<div class="drawer-head">
      <button class="drawer-close" id="drawer-close">×</button>
      <div class="drawer-title">${esc(v.title)}</div>
      <div class="drawer-meta"><span class="chip">${esc(v.platform === "youtube" ? "YouTube" : "哔哩哔哩")}</span><span>${datetime(v.published_at)}</span><span>${duration(v.duration)}</span><span>${esc(v.category || "未分类")}</span></div>
    </div>
    <div class="drawer-body">
      <div class="stat-strip">
        <div class="stat-mini"><div class="label">总播放</div><div class="value">${fmt(s.views)}</div></div>
        <div class="stat-mini"><div class="label">互动率</div><div class="value">${pct(s.engagement_rate, 2)}</div></div>
        <div class="stat-mini"><div class="label">转粉率</div><div class="value">${pct(s.conversion, 2)}</div></div>
        <div class="stat-mini"><div class="label">3 秒留存</div><div class="value">${d.retention3 == null ? "—" : `${d.retention3}<span>%</span>`}</div></div>
      </div>
      <div class="grid-2b">
        <div><div class="card-title" style="margin-bottom:6px">播放趋势</div><div class="chart sm" id="drawer-views"></div></div>
        <div><div class="card-title" style="margin-bottom:6px">能力雷达</div><div class="chart sm" id="drawer-radar"></div></div>
      </div>
      ${d.retention.length ? `<div class="card mt14" style="padding:12px"><div class="card-title" style="margin-bottom:4px">留存曲线 <span class="tag ${d.retention_source === "model" ? "pink" : "cyan"}">${d.retention_source === "model" ? "模型估算" : "平台真实"}</span></div><div class="chart sm" id="drawer-retention"></div></div>` : ""}
      <div class="section-head" style="margin-top:18px"><h3>优化建议</h3></div>
      ${d.suggestions.map((x) => `<div class="suggest"><b>${esc(x.tag)}</b><span>${esc(x.text)}</span></div>`).join("")}
      <div class="section-head" style="margin-top:18px"><h3>互动结构</h3><span class="tiny muted">评论情绪 ${d.sentiment.positive}/${d.sentiment.neutral}/${d.sentiment.negative}</span></div>
      <div class="dur-list">
        <div class="dur-row"><div class="dur-label">点赞</div><div class="dur-track"><div class="dur-fill" style="width:${Math.min(100, s.likes / Math.max(1, s.views) * 1000)}%"></div></div><div class="dur-value">${fmt(s.likes)}</div></div>
        <div class="dur-row"><div class="dur-label">投币</div><div class="dur-track"><div class="dur-fill" style="width:${Math.min(100, s.coins / Math.max(1, s.views) * 3000)}%"></div></div><div class="dur-value">${fmt(s.coins)}</div></div>
        <div class="dur-row"><div class="dur-label">收藏</div><div class="dur-track"><div class="dur-fill" style="width:${Math.min(100, s.favorites / Math.max(1, s.views) * 2500)}%"></div></div><div class="dur-value">${fmt(s.favorites)}</div></div>
        <div class="dur-row"><div class="dur-label">评论</div><div class="dur-track"><div class="dur-fill" style="width:${Math.min(100, s.comments / Math.max(1, s.views) * 8000)}%"></div></div><div class="dur-value">${fmt(s.comments)}</div></div>
        <div class="dur-row"><div class="dur-label">分享</div><div class="dur-track"><div class="dur-fill" style="width:${Math.min(100, s.shares / Math.max(1, s.views) * 12000)}%"></div></div><div class="dur-value">${fmt(s.shares)}</div></div>
      </div>
      <div class="section-head" style="margin-top:18px"><h3>观众评论</h3><span class="tiny muted">${d.comments.length} 条高赞</span></div>
      ${d.comments.length ? d.comments.slice(0, 8).map((c) => `<div class="comment"><div class="comment-head"><span class="comment-author">${esc(c.author)}</span><span>${shortDate(c.created_at)}</span><span class="comment-likes">♥ ${c.likes}</span></div><div class="comment-text">${esc(c.content)}</div></div>`).join("") : `<div class="tiny muted">暂无评论数据。YouTube 需频道开启评论；B 站仅抓取近期高赞评论。</div>`}
      <div class="flex" style="margin-top:18px"><a class="btn" href="${esc(v.url)}" target="_blank">打开原视频 ↗</a></div>
    </div>`;
    $("#drawer-close").addEventListener("click", closeDrawer);
    state.drawerCharts = [];
    const initDrawer = (id, option) => {
      const el = document.getElementById(id); if (!el) return;
      const chart = echarts.init(el); chart.setOption(option); state.drawerCharts.push(chart);
    };
    const snaps = d.snapshots || [];
    initDrawer("drawer-views", {
      tooltip: { ...TOOLTIP, trigger: "axis" },
      grid: { left: 38, right: 10, top: 10, bottom: 24 },
      xAxis: { type: "category", data: snaps.map((x) => shortDate(x.day)), ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, interval: Math.max(0, Math.floor(snaps.length / 6)) } },
      yAxis: { type: "value", ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: (x) => fmt(x) } },
      series: [{ type: "line", data: snaps.map((x) => x.views), smooth: true, symbol: "none", lineStyle: { color: "#22d3ee", width: 2 }, areaStyle: { color: "rgba(34,211,238,.08)" } }],
    });
    const p = d.percentiles;
    initDrawer("drawer-radar", {
      radar: {
        indicator: [{ name: "播放", max: 100 }, { name: "互动", max: 100 }, { name: "转粉", max: 100 }, { name: "传播", max: 100 }, { name: "留存", max: 100 }],
        radius: "58%", splitNumber: 3, axisName: { color: "#8d96aa", fontSize: 8 },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } }, splitArea: { areaStyle: { color: ["rgba(124,92,255,.02)", "rgba(124,92,255,.05)"] } }, axisLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
      },
      series: [{ type: "radar", data: [{ value: [p.views, p.engagement, p.conversion, Math.round((s.shares / Math.max(1, s.views)) * 10000), p.retention], name: "本稿" }], symbolSize: 4, lineStyle: { color: "#7c5cff", width: 2 }, areaStyle: { color: "rgba(124,92,255,.2)" }, itemStyle: { color: "#c4b5fd" } }],
    });
    if (d.retention.length) {
      initDrawer("drawer-retention", {
        tooltip: { ...TOOLTIP, trigger: "axis", valueFormatter: (x) => `${x}%` },
        grid: { left: 40, right: 10, top: 10, bottom: 24 },
        xAxis: { type: "category", data: d.retention.map((x) => `${Math.round(x.point * 100)}%`), ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, interval: 5 } },
        yAxis: { type: "value", min: 0, max: 100, ...AXIS, axisLabel: { ...AXIS.axisLabel, formatter: "{value}%" } },
        series: [{ type: "line", data: d.retention.map((x) => +(x.audience_ratio * 100).toFixed(1)), smooth: true, symbol: "none", lineStyle: { color: "#fb7299", width: 2.4 }, areaStyle: { color: "rgba(251,114,153,.1)" } }],
      });
    }
  }

  // ------------------------------------------------------------------ binding / init
  function bindEmpty() {
    $("#empty-connect")?.addEventListener("click", openConnectModal);
    $("#empty-demo")?.addEventListener("click", async () => {
      try { await api("/api/accounts/demo", { method: "POST", body: {} }); await refreshBootstrap(); state.cache = {}; navigate("overview", true); }
      catch (error) { toast(error.message, "error"); }
    });
  }

  function bindGlobal() {
    $$("#nav .nav-item").forEach((el) => el.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(el.dataset.page);
    }));
    $$("#range-seg button").forEach((el) => el.addEventListener("click", () => {
      state.days = Number(el.dataset.days);
      localStorage.setItem("mp_days", String(state.days));
      updateChrome();
      state.cache = {};
      loadPage(true);
    }));
    $("#sync-btn").addEventListener("click", async () => {
      const account = activeAccount();
      if (!account) return openConnectModal();
      if (account.is_demo) { toast("演示账号不连接网络。请先登录真实账号。", "info"); return; }
      try {
        const r = await api("/api/sync", { method: "POST", body: { account_id: account.id } });
        trackJob(r.job_id);
      } catch (error) { toast(error.message, "error"); }
    });
    $("#report-btn").addEventListener("click", () => generateReport(state.days));
    $("#account-switch").addEventListener("click", (event) => {
      if (event.target.closest("#account-menu")) return;
      $("#account-menu").classList.toggle("hidden");
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest("#account-switch")) $("#account-menu").classList.add("hidden");
    });
    $("#mobile-menu").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
    window.addEventListener("hashchange", () => {
      const page = location.hash.replace("#", "") || "overview";
      if (page !== state.page) navigate(page);
    });
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { state.charts.forEach((c) => { try { c.resize(); } catch (_) {} }); state.drawerCharts?.forEach((c) => { try { c.resize(); } catch (_) {} }); }, 120);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { closeModal(); closeDrawer(); $("#account-menu").classList.add("hidden"); }
    });
    document.addEventListener("click", (event) => {
      const demo = event.target.closest("#demo-add");
      if (demo) openConnectModal();
    });
  }

  async function init() {
    const params = new URLSearchParams(location.search);
    state.token = params.get("token") || sessionStorage.getItem("mp_token") || "";
    if (state.token) {
      sessionStorage.setItem("mp_token", state.token);
      params.delete("token");
      const clean = `${location.pathname}${params.toString() ? `?${params}` : ""}${location.hash}`;
      history.replaceState(null, "", clean);
    }
    if (!state.token) {
      $("#boot").innerHTML = `<div class="boot-inner"><div class="empty-icon">!</div><h1>访问令牌缺失</h1><p>请从 MediaPulse 程序启动，或重新打开桌面快捷方式。</p></div>`;
      return;
    }
    const savedDays = Number(localStorage.getItem("mp_days"));
    if ([7, 30, 90, 180].includes(savedDays)) state.days = savedDays;
    $("#app").classList.remove("hidden");
    bindGlobal();
    try {
      await refreshBootstrap();
      const page = location.hash.replace("#", "") || "overview";
      state.page = PAGE_META[page] ? page : "overview";
      updateChrome();
      renderAccountMenu();
      if (!state.accounts.length) {
        $("#view").innerHTML = emptyState();
        bindEmpty();
      } else {
        await loadPage(true);
      }
    } catch (error) {
      console.error(error);
      $("#view").innerHTML = `<div class="empty"><div class="empty-icon">!</div><h3>无法连接本地服务</h3><p>${esc(error.message)}</p><p class="tiny">请关闭窗口后重新启动 MediaPulse.exe。</p></div>`;
    } finally {
      const boot = $("#boot");
      if (boot) {
        boot.classList.add("done");
        boot.style.pointerEvents = "none";
        setTimeout(() => boot.remove(), 450);
      }
      setTimeout(() => {
        state.charts.forEach((chart) => { try { chart.resize(); } catch (_) {} });
      }, 80);
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
