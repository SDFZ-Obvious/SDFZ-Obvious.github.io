"""主窗口：账号切换、数据刷新、图表分析页、发布模拟器、视频明细、运营报告。"""
import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")  # noqa: E402
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from core import APP_NAME, APP_VERSION, analytics, charts, demo, importer, report, textutil
from core.analytics import HOUR_BLOCKS, WEEKDAYS, fdur, fnum, fpct
from core.bilibili import BilibiliClient
from core.config import app_dir, load_settings, resource_path, save_settings
from core.storage import PLATFORM_NAMES, Storage
from core.youtube import YouTubeClient

from .dialogs import (BiliLoginDialog, CompetitorDialog, SettingsDialog,
                      YouTubeLoginDialog)

TABLE_COLS = [
    ("title", "标题", 300, None), ("publish_time", "发布时间", 120, lambda v: f"{v:%Y-%m-%d %H:%M}"),
    ("duration", "时长", 60, fdur), ("views", "播放", 75, fnum), ("likes", "点赞", 65, fnum),
    ("coins", "投币", 60, fnum), ("favorites", "收藏", 60, fnum), ("comments", "评论", 60, fnum),
    ("shares", "分享", 60, fnum), ("danmaku", "弹幕", 60, fnum), ("engagement_rate", "互动率", 65, fpct),
    ("avg_view_pct", "完播率", 65, fpct), ("bounce_3s", "3秒跳出", 65, fpct), ("subs_gained", "涨粉", 60, fnum),
    ("subs_per_1k", "千播涨粉", 70, lambda v: "—" if pd.isna(v) else f"{v:.2f}"),
    ("perf_index", "表现指数", 70, lambda v: "—" if pd.isna(v) else f"{v:.2f}x"),
]


class App(tk.Tk):
    BG, CARD, INK, MUTED, ACCENT = "#f9f9f7", "#fcfcfb", "#0b0b0b", "#52514e", "#2a78d6"
    FONT = ("Microsoft YaHei UI", 10)

    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = int(sw * 0.9), int(sh * 0.86)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 3, 0)}")
        self.minsize(min(1100, sw - 40), min(700, sh - 80))
        self.configure(bg=self.BG)
        ico = resource_path("assets/icon.ico")
        if ico.exists():
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                pass
        self._style()
        self.settings = load_settings()
        self.storage = Storage()
        self.bili = BilibiliClient(log=self.log)
        self.yt = YouTubeClient(log=self.log)
        self._q = queue.Queue()
        self._busy = 0
        self._auto_job = None
        self.res = None
        self.current_key = None
        self._rendered = {}
        self._account_keys = []
        self._build()
        self.after(60, self._drain)
        self.after(200, self._startup)

    # ------------------------------------------------------------ 样式与布局
    def _style(self):
        s = ttk.Style(self)
        if "vista" in s.theme_names():
            s.theme_use("vista")
        s.configure(".", font=self.FONT)
        s.configure("TFrame", background=self.BG)
        s.configure("Card.TFrame", background=self.CARD)
        s.configure("TLabel", background=self.BG, foreground=self.INK)
        s.configure("Card.TLabel", background=self.CARD)
        s.configure("H1.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        s.configure("H2.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        s.configure("Muted.TLabel", foreground=self.MUTED)
        s.configure("KpiK.TLabel", background=self.CARD, foreground=self.MUTED, font=("Microsoft YaHei UI", 8))
        s.configure("KpiV.TLabel", background=self.CARD, font=("Microsoft YaHei UI", 13, "bold"))
        s.configure("KpiS.TLabel", background=self.CARD, foreground="#898781", font=("Microsoft YaHei UI", 8))
        s.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))
        s.configure("Small.TButton", font=("Microsoft YaHei UI", 9), padding=(6, 1))
        s.configure("TNotebook", background=self.BG)
        s.configure("TNotebook.Tab", padding=(8, 3), font=("Microsoft YaHei UI", 9))
        s.configure("Treeview", rowheight=24)

    def _build(self):
        top = ttk.Frame(self, padding=(12, 8, 12, 2))
        top.pack(fill="x")
        ttk.Label(top, text="MediaInsight", style="H1.TLabel").pack(side="left")
        ttk.Label(top, text="  账号：").pack(side="left", padx=(16, 0))
        self.account_var = tk.StringVar()
        self.account_cb = ttk.Combobox(top, textvariable=self.account_var, state="readonly", width=34)
        self.account_cb.pack(side="left")
        self.account_cb.bind("<<ComboboxSelected>>", lambda e: self.select_account(
            self._account_keys[self.account_cb.current()]))
        ttk.Button(top, text="刷新数据", command=self.refresh_current, style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(top, text="删除账号", command=self.delete_account, style="Small.TButton").pack(side="right")
        row2 = ttk.Frame(self, padding=(12, 2, 12, 2))
        row2.pack(fill="x")
        btns = [("B站扫码登录", self.login_bili), ("YouTube登录", self.login_youtube), ("加载演示数据", self.load_demo),
                ("导入后台数据", self.import_data), ("竞品管理", lambda: CompetitorDialog(self)),
                ("导出报告", self.export_report), ("设置 / 自动监控", lambda: SettingsDialog(self))]
        for text, cmd in btns:
            ttk.Button(row2, text=text, command=cmd, style="Small.TButton").pack(side="left", padx=(0, 6))

        self.kpi_frame = ttk.Frame(self, padding=(12, 4))
        self.kpi_frame.pack(fill="x")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(4, 4))
        self.pages = {}
        for key, title, builder in charts.PAGES:
            frame = ttk.Frame(self.nb)
            pw = ttk.PanedWindow(frame, orient="horizontal")
            pw.pack(fill="both", expand=True)
            chart_holder = ttk.Frame(pw, style="Card.TFrame")
            text = tk.Text(pw, width=34, wrap="word", relief="flat", bg=self.CARD, fg=self.INK,
                           font=self.FONT, padx=12, pady=8, spacing1=2, spacing3=4)
            text.tag_configure("h", font=("Microsoft YaHei UI", 10, "bold"), foreground=self.ACCENT)
            pw.add(chart_holder, weight=3)
            pw.add(text, weight=1)
            self.nb.add(frame, text=title)
            self.pages[key] = {"frame": frame, "holder": chart_holder, "text": text, "builder": builder,
                               "title": title}
        self._build_simulator()
        self._build_table()
        self._build_report()
        self._build_log()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._render_current())

        bar = ttk.Frame(self, padding=(12, 2, 12, 8))
        bar.pack(fill="x", side="bottom")
        self.status = ttk.Label(bar, text="就绪", style="Muted.TLabel")
        self.status.pack(side="left")
        self.auto_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.auto_label.pack(side="right", padx=8)
        self.progress = ttk.Progressbar(bar, length=260, mode="determinate", maximum=1.0)
        self.progress.pack(side="right")

    def _build_simulator(self):
        f = ttk.Frame(self.nb, padding=16)
        self.nb.add(f, text="发布模拟器")
        ttk.Label(f, text="发布模拟器：根据你的历史数据，预测一条新视频在不同发布条件下的播放表现",
                  style="H2.TLabel").grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))
        self.sim_wd = ttk.Combobox(f, values=WEEKDAYS, state="readonly", width=8)
        self.sim_wd.current(5)
        self.sim_hour = ttk.Spinbox(f, from_=0, to=23, width=6)
        self.sim_hour.set(20)
        self.sim_dur = ttk.Spinbox(f, from_=0.25, to=180, increment=0.5, width=8)
        self.sim_dur.set(8)
        self.sim_cat = ttk.Combobox(f, values=["（不限）"], state="readonly", width=16)
        self.sim_cat.current(0)
        self.sim_title = ttk.Entry(f, width=60)
        for i, (label, w) in enumerate([("星期", self.sim_wd), ("小时", self.sim_hour),
                                        ("时长(分钟)", self.sim_dur), ("类别", self.sim_cat)]):
            ttk.Label(f, text=label).grid(row=1, column=i * 2, sticky="e", padx=(8, 4))
            w.grid(row=1, column=i * 2 + 1, sticky="w")
        ttk.Label(f, text="标题（可选）").grid(row=2, column=0, sticky="e", padx=(8, 4), pady=8)
        self.sim_title.grid(row=2, column=1, columnspan=6, sticky="we", pady=8)
        ttk.Button(f, text="预测", style="Accent.TButton", command=self.simulate).grid(row=2, column=7, padx=8)
        self.sim_out = tk.Text(f, wrap="word", relief="flat", bg=self.CARD, font=self.FONT, padx=14, pady=10,
                               spacing1=2, spacing3=4)
        self.sim_out.tag_configure("big", font=("Microsoft YaHei UI", 18, "bold"), foreground=self.ACCENT)
        self.sim_out.tag_configure("h", font=("Microsoft YaHei UI", 10, "bold"))
        self.sim_out.grid(row=3, column=0, columnspan=9, sticky="nsew", pady=8)
        f.rowconfigure(3, weight=1)
        f.columnconfigure(8, weight=1)

    def _build_table(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="视频明细")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="搜索标题：").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._fill_table())
        ttk.Entry(row, textvariable=self.search_var, width=30).pack(side="left")
        ttk.Label(row, text="  点击表头排序，双击打开视频", style="Muted.TLabel").pack(side="left")
        self.tree = ttk.Treeview(f, columns=[c[0] for c in TABLE_COLS], show="headings")
        for key, title, w, _ in TABLE_COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self._sort_table(k))
            self.tree.column(key, width=w, anchor="w" if key == "title" else "e", stretch=key == "title")
        ys = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._open_video)
        self._sort = ("views", True)

    def _build_report(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="运营报告")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(0, 6))
        ttk.Button(row, text="导出 HTML 报告（含图表）", command=lambda: self.export_report("html")).pack(side="left")
        ttk.Button(row, text="导出 Excel 明细", command=lambda: self.export_report("xlsx")).pack(side="left", padx=6)
        ttk.Button(row, text="复制文字报告", command=self._copy_report).pack(side="left")
        self.report_text = tk.Text(f, wrap="word", relief="flat", bg=self.CARD, font=self.FONT, padx=14, pady=10,
                                   spacing1=2, spacing3=3)
        self.report_text.tag_configure("h1", font=("Microsoft YaHei UI", 15, "bold"))
        self.report_text.tag_configure("h2", font=("Microsoft YaHei UI", 11, "bold"), foreground=self.ACCENT)
        ys = ttk.Scrollbar(f, orient="vertical", command=self.report_text.yview)
        self.report_text.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.report_text.pack(fill="both", expand=True)

    def _build_log(self):
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="日志")
        self.log_text = tk.Text(f, wrap="word", relief="flat", bg=self.CARD, font=("Consolas", 9), padx=10, pady=8)
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 线程工具
    def post(self, fn):
        self._q.put(fn)

    def _drain(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self.after(60, self._drain)

    def log(self, msg):
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        try:
            with open(app_dir() / "log.txt", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        self.post(lambda: (self.log_text.insert("end", line + "\n"), self.log_text.see("end")))

    def set_status(self, text, p=None):
        self.status.config(text=text)
        if p is not None:
            self.progress["value"] = p

    def run_task(self, job, title, done=None, error=None, silent=False):
        """在后台线程执行 job(progress)，完成后在主线程回调 done(result)。"""
        self._busy += 1
        self.set_status(f"{title}…", 0)
        self.log(f"开始：{title}")

        def progress(p, msg):
            self.post(lambda: self.set_status(f"{title}：{msg}", p))

        def worker():
            try:
                result = job(progress)
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc()
                self.log(tb)

                def fail(e=e):
                    self._busy -= 1
                    self.set_status(f"{title}失败：{e}", 0)
                    if error:
                        error(e)
                    elif not silent:
                        messagebox.showerror("出错了", f"{title}失败：\n{e}")
                self.post(fail)
                return

            def ok():
                self._busy -= 1
                self.set_status(f"{title}完成", 1.0)
                self.log(f"完成：{title}")
                if done:
                    done(result)
            self.post(ok)
        threading.Thread(target=worker, daemon=True).start()

    def save_settings(self):
        save_settings(self.settings)

    # ------------------------------------------------------------ 账号
    def _startup(self):
        self.yt.api_key = self.settings.get("youtube_api_key", "")
        threading.Thread(target=self.yt.load_saved, daemon=True).start()
        self.reload_accounts(self.settings.get("last_account"))
        if not self._account_keys:
            self._welcome()
        self.schedule_auto_refresh()

    def _welcome(self):
        t = self.pages["overview"]["text"]
        t.delete("1.0", "end")
        t.insert("end", "欢迎使用 MediaInsight！\n", "h")
        t.insert("end", "· 点击「B站登录」扫码登录，或「YouTube登录」授权 Google 账号，程序会自动抓取全部稿件数据并生成分析。\n"
                        "· 没有账号也可以点击「演示数据」，用模拟数据体验全部功能。\n"
                        "· 在「设置」中开启自动监控后，程序会定时刷新并积累历史快照，用于增长趋势与生命周期分析。\n")

    def reload_accounts(self, select=None):
        accs = self.storage.list_accounts(competitors=False)
        self._account_keys = [a["key"] for a in accs]
        self.account_cb["values"] = [f"{a['name']}（{PLATFORM_NAMES.get(a['platform'], a['platform'])}"
                                     f"{'·演示' if a['is_demo'] else ''}）" for a in accs]
        if accs:
            key = select if select in self._account_keys else self._account_keys[0]
            self.select_account(key)

    def select_account(self, key):
        self.current_key = key
        if key in self._account_keys:
            self.account_cb.current(self._account_keys.index(key))
        self.settings["last_account"] = key
        self.save_settings()
        self.reanalyze()

    def reanalyze(self):
        key = self.current_key
        if not key:
            return

        def job(progress):
            progress(0.2, "读取数据")
            ds = self.storage.load(key)
            comps = [self.storage.load(a["key"]) for a in self.storage.list_accounts(competitors=True)]
            progress(0.5, "分析中")
            return analytics.analyze(ds, [c for c in comps if c])
        self.run_task(job, "分析数据", done=self._show_results)

    def delete_account(self):
        if not self.current_key:
            return
        if messagebox.askyesno("确认", "删除该账号在本机保存的全部数据？（不会影响平台上的账号）"):
            self.storage.delete_account(self.current_key)
            self.current_key = None
            self.reload_accounts()

    # ------------------------------------------------------------ 登录与刷新
    def _fetch_kwargs(self):
        s = self.settings
        return dict(max_videos=int(s["max_videos"]), fetch_comments=bool(s["fetch_comments"]),
                    comment_videos=int(s["comment_videos"]))

    def login_bili(self):
        BiliLoginDialog(self, on_success=lambda: self.fetch_bili(own=True))

    def fetch_bili(self, mid=None, own=True, competitor=False, done=None, silent=False):
        def job(progress):
            r = self.bili.fetch(mid=mid, own=own, progress=progress, **self._fetch_kwargs())
            return self.storage.save(r, is_competitor=competitor), r.notes
        self.run_task(job, "抓取B站数据", done=lambda res: self._after_fetch(res, competitor, done), silent=silent)

    def login_youtube(self):
        YouTubeLoginDialog(self, on_oauth=self._yt_oauth, on_public=lambda ch: self.fetch_youtube(ch, own=True))

    def _yt_oauth(self, path):
        def job(progress):
            progress(0.1, "已打开浏览器，请在 Google 页面完成授权…")
            self.yt.login(path)
        self.run_task(job, "YouTube 授权", done=lambda _: self.fetch_youtube(None, own=True))

    def fetch_youtube(self, channel=None, own=True, competitor=False, done=None, silent=False):
        def job(progress):
            self.yt.api_key = self.settings.get("youtube_api_key", "")
            if not self.yt.creds:
                self.yt.load_saved()
            cid = self.yt.resolve_channel(channel) if channel else None
            r = self.yt.fetch(channel_id=cid, own=own and not competitor and channel is None,
                              retention_videos=int(self.settings["retention_videos"]), progress=progress,
                              **self._fetch_kwargs())
            return self.storage.save(r, is_competitor=competitor), r.notes
        self.run_task(job, "抓取YouTube数据", done=lambda res: self._after_fetch(res, competitor, done), silent=silent)

    def _after_fetch(self, res, competitor, done=None):
        key, notes = res
        for n in notes:
            self.log("提示：" + n)
        if competitor:
            if done:
                done()
            else:
                self.reanalyze()
        else:
            self.reload_accounts(key)
            if done:
                done()

    def fetch_competitor(self, platform, ident, done=None):
        if platform == "bilibili":
            if not ident.isdigit():
                messagebox.showwarning("提示", "B站请填写数字 UID（个人空间链接中的数字）。")
                return
            self.fetch_bili(mid=ident, own=False, competitor=True, done=done)
        else:
            self.fetch_youtube(channel=ident, own=False, competitor=True, done=done)

    def refresh_competitors(self, done=None, silent=False):
        for a in self.storage.list_accounts(competitors=True):
            if a["is_demo"]:
                continue
            if a["platform"] == "bilibili":
                self.fetch_bili(mid=a["account_id"], own=False, competitor=True, done=done, silent=silent)
            else:
                self.fetch_youtube(channel=a["account_id"], own=False, competitor=True, done=done, silent=silent)

    def refresh_current(self, silent=False):
        key = self.current_key
        if not key:
            if not silent:
                messagebox.showinfo("提示", "请先登录账号或加载演示数据。")
            return
        ds_platform, acc_id = key.split(":", 1)
        accs = {a["key"]: a for a in self.storage.list_accounts()}
        if accs.get(key, {}).get("is_demo"):
            if not silent:
                messagebox.showinfo("提示", "演示账号的数据是模拟生成的，无需刷新。登录真实账号后即可抓取实时数据。")
            return
        if ds_platform == "bilibili":
            def check(progress):
                progress(0.1, "检查登录状态")
                user = self.bili.logged_in_user()
                return user and user["mid"] == acc_id
            self.run_task(check, "检查B站登录",
                          done=lambda own: self.fetch_bili(mid=None if own else acc_id, own=bool(own), silent=silent),
                          silent=silent)
        else:
            own = self.yt.creds is not None or self.yt.load_saved()
            self.fetch_youtube(channel=None if own else acc_id, own=True, silent=silent)

    def load_demo(self):
        def job(progress):
            progress(0.2, "生成B站演示数据")
            k = demo.generate(self.storage, "bilibili")
            progress(0.6, "生成YouTube演示数据")
            demo.generate(self.storage, "youtube")
            return k
        self.run_task(job, "生成演示数据", done=self.reload_accounts)

    def schedule_auto_refresh(self):
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None
        minutes = int(self.settings.get("auto_refresh_minutes") or 0)
        if minutes > 0:
            self._auto_job = self.after(minutes * 60_000, self._auto_tick)
            self.auto_label.config(text=f"● 自动监控：每 {minutes} 分钟")
        else:
            self.auto_label.config(text="自动监控：关闭")

    def _auto_tick(self):
        self.log("自动监控：开始刷新")
        if self._busy == 0:
            self.refresh_current(silent=True)
            self.refresh_competitors(silent=True)
        self.schedule_auto_refresh()

    # ------------------------------------------------------------ 导入与导出
    def import_data(self):
        if not self.res or self.res["df"].empty:
            messagebox.showinfo("提示", "请先选择一个已有稿件数据的账号。")
            return
        path = filedialog.askopenfilename(title="选择创作中心 / YouTube Studio 导出的表格",
                                          filetypes=[("表格", "*.xlsx *.xls *.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            updates, mapping = importer.build_updates(importer.read_table(path), self.res["df"])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导入失败", str(e))
            return
        n = self.storage.update_videos(self.current_key, updates)
        cols = "、".join(f"{c}→{f}" for c, f in mapping.items())
        messagebox.showinfo("导入完成", f"识别到的列：{cols}\n成功匹配并更新 {n} 个稿件。")
        self.reanalyze()

    def export_report(self, kind=None):
        if not self.res:
            messagebox.showinfo("提示", "还没有可导出的分析结果。")
            return
        kind = kind or "html"
        ds = self.res["dataset"]
        name = f"{ds.name}_{datetime.now():%Y%m%d_%H%M}".replace("/", "_").replace("\\", "_")
        ext = {"html": ".html", "xlsx": ".xlsx"}[kind]
        path = filedialog.asksaveasfilename(initialdir=str(app_dir() / "reports"), initialfile=name + ext,
                                            defaultextension=ext,
                                            filetypes=[("HTML 报告", "*.html")] if kind == "html" else [("Excel", "*.xlsx")])
        if not path:
            return
        res = self.res

        def job(progress):
            if kind == "html":
                report.html_report(res, path, progress)
            else:
                report.excel_report(res, path)
            return path

        def done(p):
            if messagebox.askyesno("导出完成", f"报告已保存到：\n{p}\n\n现在打开吗？"):
                os.startfile(p) if sys.platform == "win32" else webbrowser.open(p)
        self.run_task(job, "导出报告", done=done)

    def _copy_report(self):
        self.clipboard_clear()
        self.clipboard_append(self.report_text.get("1.0", "end"))
        self.set_status("报告已复制到剪贴板")

    # ------------------------------------------------------------ 结果展示
    def _show_results(self, res):
        self.res = res
        self._rendered.clear()
        self._fill_kpis()
        for key, page in self.pages.items():
            t = page["text"]
            t.delete("1.0", "end")
            sec = res.get(key) or {}
            t.insert("end", "分析结论\n", "h")
            for s in sec.get("insights") or ["暂无"]:
                t.insert("end", f"· {s}\n")
            if key == "retention" and sec.get("suggestions"):
                t.insert("end", "\n稿件内容留存建议\n", "h")
                for s in sec["suggestions"]:
                    t.insert("end", f"· {s}\n")
            if key == "comments" and sec.get("requests"):
                t.insert("end", "\n观众诉求（可直接作为选题）\n", "h")
                for s in sec["requests"][:10]:
                    t.insert("end", f"· {s}\n")
            if key == "overview" and res.get("recommendations"):
                t.insert("end", "\n行动清单\n", "h")
                for r in res["recommendations"][:6]:
                    t.insert("end", f"· [{r['优先级']}] {r['方向']}：{r['建议']}\n")
            if key == "outliers" and sec.get("ok"):
                t.insert("end", "\n爆款列表\n", "h")
                for _, r in sec["hits"].head(8).iterrows():
                    t.insert("end", f"· 《{r['title']}》 {fnum(r['views'])} 播放，{r['perf_index']:.1f}x\n")
            if key == "competitors" and sec.get("rows"):
                t.insert("end", "\n对标明细\n", "h")
                for r in sec["rows"]:
                    t.insert("end", f"· {r['账号']}（{r['平台']}）粉丝 {fnum(r['粉丝'])}，播放中位 {fnum(r['播放中位数'])}，"
                                    f"互动率 {fpct(r['互动率'])}，{r['周更数']:.1f} 更/周，主要类别 {r['主要类别']}\n")
        cats = sorted({str(c) for c in res["df"].get("category", pd.Series(dtype=str)).dropna() if str(c)})
        self.sim_cat["values"] = ["（不限）"] + cats
        self.sim_cat.current(0)
        self._fill_table()
        self._fill_report()
        self._render_current()
        if res["dataset"].notes:
            self.set_status("分析完成（部分数据缺失，详见“日志”或报告末尾的数据说明）", 1.0)

    def _fill_kpis(self):
        for w in self.kpi_frame.winfo_children():
            w.destroy()
        h = self.res.get("health", {})
        tiles = ([("健康度", f"{h['total']:.0f}分 · {h['grade']}", "综合评分")] if h.get("scores") else [])
        tiles += list(self.res.get("overview", {}).get("kpis") or [])
        for i, (k, v, s) in enumerate(tiles[:9]):
            card = ttk.Frame(self.kpi_frame, style="Card.TFrame", padding=(10, 4))
            card.grid(row=0, column=i, sticky="nsew", padx=3)
            self.kpi_frame.columnconfigure(i, weight=1)
            ttk.Label(card, text=k, style="KpiK.TLabel").pack(anchor="w")
            ttk.Label(card, text=v, style="KpiV.TLabel").pack(anchor="w")
            ttk.Label(card, text=s, style="KpiS.TLabel").pack(anchor="w")

    def _render_current(self):
        if not self.res:
            return
        idx = self.nb.index("current")
        keys = list(self.pages)
        if idx >= len(keys):
            return
        key = keys[idx]
        if key in self._rendered:
            return
        page = self.pages[key]
        for w in page["holder"].winfo_children():
            w.destroy()
        try:
            fig = page["builder"](self.res)
        except Exception as e:  # noqa: BLE001
            self.log(traceback.format_exc())
            ttk.Label(page["holder"], text=f"图表生成失败：{e}", style="Muted.TLabel").pack(pady=20)
            return
        canvas = FigureCanvasTkAgg(fig, master=page["holder"])
        tb = NavigationToolbar2Tk(canvas, page["holder"], pack_toolbar=False)
        tb.update()
        tb.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw_idle()
        self._rendered[key] = canvas

    def _fill_table(self):
        if not self.res:
            return
        df = self.res["df"]
        q = self.search_var.get().strip().lower()
        if q:
            df = df[df["title"].astype(str).str.lower().str.contains(q, regex=False)]
        col, desc = self._sort
        if col in df.columns:
            df = df.sort_values(col, ascending=not desc, na_position="last")
        self.tree.delete(*self.tree.get_children())
        for _, r in df.iterrows():
            vals = []
            for key, _, _, fmt in TABLE_COLS:
                v = r.get(key)
                if v is None or (not isinstance(v, str) and pd.isna(v)):
                    vals.append("—")
                else:
                    vals.append(fmt(v) if fmt else v)
            self.tree.insert("", "end", iid=str(r["video_id"]), values=vals)

    def _sort_table(self, col):
        cur, desc = self._sort
        self._sort = (col, not desc if cur == col else True)
        self._fill_table()

    def _open_video(self, _):
        sel = self.tree.selection()
        if sel and self.res:
            df = self.res["df"]
            url = df.loc[df["video_id"] == sel[0], "url"]
            if len(url):
                webbrowser.open(url.iloc[0])

    def _fill_report(self):
        t = self.report_text
        t.delete("1.0", "end")
        for line in report.text_report(self.res).splitlines():
            if line.startswith("# "):
                t.insert("end", line[2:] + "\n", "h1")
            elif line.startswith("## "):
                t.insert("end", "\n" + line[3:] + "\n", "h2")
            else:
                t.insert("end", line + "\n")

    # ------------------------------------------------------------ 发布模拟器
    def simulate(self):
        out = self.sim_out
        out.delete("1.0", "end")
        if not self.res or self.res["df"].empty:
            out.insert("end", "请先加载账号数据。")
            return
        df = self.res["df"]
        try:
            wd = self.sim_wd.current()
            hour = int(self.sim_hour.get())
            dur = int(float(self.sim_dur.get()) * 60)
        except ValueError:
            out.insert("end", "请输入有效的小时与时长。")
            return
        cat = self.sim_cat.get()
        cat = None if cat.startswith("（") else cat
        p = analytics.predict(df, wd, hour, dur, cat)
        if not p:
            out.insert("end", "成熟稿件少于 6 个，暂无法预测。")
            return
        est, lo, hi, factors, base = p
        out.insert("end", "预计 14 天播放（中位估计）\n", "h")
        out.insert("end", f"{fnum(est)}\n", "big")
        out.insert("end", f"常见区间：{fnum(lo)} ~ {fnum(hi)}（50% 概率区间）    基准：近期稿件中位播放 {fnum(base)}\n\n")
        out.insert("end", "影响因素\n", "h")
        for label, val, n in factors:
            out.insert("end", f"· {label}：×{val:.2f}（历史样本 {n} 个{'，样本少，已向平均值收缩' if n < 3 else ''}）\n")
        # 在同等条件下寻找更好的发布时段
        best = []
        for d in range(7):
            for hb, (a, _) in enumerate(HOUR_BLOCKS):
                r = analytics.predict(df, d, a + 1, dur, cat)
                if r:
                    best.append((r[0], d, hb))
        best.sort(reverse=True)
        out.insert("end", "\n同等内容下更推荐的发布时段\n", "h")
        for e, d, hb in best[:3]:
            a, b = HOUR_BLOCKS[hb]
            out.insert("end", f"· {WEEKDAYS[d]} {a:02d}:00-{b:02d}:00 → 预计 {fnum(e)}（{(e / est - 1) * 100:+.0f}%）\n")
        title = self.sim_title.get().strip()
        if title:
            out.insert("end", "\n标题检查\n", "h")
            feats = textutil.title_features(title)
            tf = self.res.get("content", {}).get("title_features")
            for f, has in feats.items():
                if has and isinstance(tf, pd.DataFrame) and f in tf.index:
                    out.insert("end", f"· {f}：在你的账号中历史提升 {tf.loc[f, '提升'] * 100:+.0f}%\n")
            kw = self.res.get("content", {}).get("keywords")
            if isinstance(kw, pd.DataFrame):
                hits = [w for w in set(textutil.tokenize(title)) if w in kw.index]
                for w in hits:
                    out.insert("end", f"· 关键词“{w}”：历史提升 {kw.loc[w, '提升度'] * 100:+.0f}%\n")
            out.insert("end", f"· 标题长度 {len(title)} 字" + ("，偏长，移动端可能显示不全。\n" if len(title) > 30 else "。\n"))


def _enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def run():
    _enable_dpi_awareness()
    app = App()
    app.mainloop()
