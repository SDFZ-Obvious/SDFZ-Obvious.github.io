"""登录、竞品、设置、导入等对话框。"""
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

from core import bilibili, demo

PAD = {"padx": 10, "pady": 6}


class _Dialog(tk.Toplevel):
    def __init__(self, app, title, size="520x420"):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.geometry(size)
        self.transient(app)
        self.resizable(True, True)
        self.configure(bg=app.BG)
        self.closed = False
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        self.closed = True
        self.destroy()


# ------------------------------------------------------------------ B站扫码登录
class BiliLoginDialog(_Dialog):
    def __init__(self, app, on_success):
        super().__init__(app, "登录哔哩哔哩", "420x560")
        self.on_success = on_success
        ttk.Label(self, text="请使用哔哩哔哩手机客户端扫码登录", style="H2.TLabel").pack(**PAD)
        self.img_label = ttk.Label(self)
        self.img_label.pack(pady=4)
        self.status = ttk.Label(self, text="正在获取二维码…", style="Muted.TLabel")
        self.status.pack(**PAD)
        row = ttk.Frame(self)
        row.pack(pady=4)
        ttk.Button(row, text="刷新二维码", command=self.start).pack(side="left", padx=4)
        ttk.Button(row, text="粘贴 Cookie 登录", command=self.paste_cookie).pack(side="left", padx=4)
        ttk.Label(self, text="登录凭据仅保存在本机 %APPDATA%\\MediaInsight 目录，\n不会上传到任何第三方服务器。",
                  style="Muted.TLabel", justify="center").pack(side="bottom", pady=10)
        self._gen = 0
        self.start()

    def start(self):
        self._gen += 1
        gen = self._gen
        self.status.config(text="正在获取二维码…")
        threading.Thread(target=self._worker, args=(gen,), daemon=True).start()

    def _worker(self, gen):
        client = self.app.bili
        try:
            url, key = client.qr_generate()
        except Exception as e:  # noqa: BLE001
            self.app.post(lambda: self.status.config(text=f"获取二维码失败：{e}"))
            return
        self.app.post(lambda: self._show_qr(url))
        while not self.closed and gen == self._gen:
            try:
                code, _ = client.qr_poll(key)
            except Exception as e:  # noqa: BLE001
                self.app.post(lambda e=e: self._set_status(f"网络错误：{e}"))
                time.sleep(3)
                continue
            if code == bilibili.QR_WAITING:
                self.app.post(lambda: self._set_status("等待扫码…"))
            elif code == bilibili.QR_SCANNED:
                self.app.post(lambda: self._set_status("已扫码，请在手机上确认登录"))
            elif code == bilibili.QR_EXPIRED:
                self.app.post(lambda: self._set_status("二维码已过期，请点击“刷新二维码”"))
                return
            elif code == bilibili.QR_OK:
                self.app.post(self._done)
                return
            time.sleep(2)

    def _set_status(self, text):
        if not self.closed:
            self.status.config(text=text)

    def _show_qr(self, url):
        if self.closed:
            return
        import qrcode
        from PIL import ImageTk
        img = qrcode.make(url, box_size=7, border=2).convert("RGB")
        self._photo = ImageTk.PhotoImage(img)
        self.img_label.config(image=self._photo)
        self.status.config(text="等待扫码…")

    def paste_cookie(self):
        raw = simpledialog.askstring("粘贴 Cookie", "在浏览器登录 bilibili.com 后，从开发者工具复制 Cookie（需包含 SESSDATA）：",
                                     parent=self)
        if raw and "SESSDATA" in raw:
            self.app.bili.set_cookie_string(raw)
            self._done()
        elif raw:
            messagebox.showwarning("提示", "Cookie 中没有找到 SESSDATA。", parent=self)

    def _done(self):
        if self.closed:
            return
        self.close()
        self.on_success()


# ------------------------------------------------------------------ YouTube 登录
YT_HELP = """YouTube 深度数据（留存曲线、转粉、流量来源、受众画像）需要使用 Google 官方 OAuth 授权：

1. 打开 Google Cloud 控制台，新建项目；
2. 在“API 和服务 → 库”中启用 YouTube Data API v3 和 YouTube Analytics API；
3. 配置 OAuth 同意屏幕（用户类型选“外部”，把自己的 Google 账号添加为测试用户）；
4. 在“凭据”中创建 OAuth 客户端 ID，应用类型选“桌面应用”，下载 JSON 文件；
5. 点击下方按钮选择该 JSON 文件，浏览器会打开 Google 登录页完成授权。

只想查看公开数据（或追踪竞品）？可以只填写 API Key。"""


class YouTubeLoginDialog(_Dialog):
    def __init__(self, app, on_oauth, on_public):
        super().__init__(app, "登录 YouTube", "600x560")
        self.on_oauth, self.on_public = on_oauth, on_public
        ttk.Label(self, text="方式一：Google 账号授权（推荐，数据最全）", style="H2.TLabel").pack(anchor="w", **PAD)
        txt = tk.Text(self, height=11, wrap="word", relief="flat", bg=app.CARD, font=app.FONT, padx=8, pady=6)
        txt.insert("1.0", YT_HELP)
        txt.config(state="disabled")
        txt.pack(fill="x", padx=10)
        row = ttk.Frame(self)
        row.pack(fill="x", **PAD)
        ttk.Button(row, text="打开 Google Cloud 控制台",
                   command=lambda: webbrowser.open("https://console.cloud.google.com/apis/credentials")).pack(side="left")
        ttk.Button(row, text="选择 client_secret.json 并登录", style="Accent.TButton",
                   command=self.oauth).pack(side="left", padx=8)
        ttk.Separator(self).pack(fill="x", pady=8)
        ttk.Label(self, text="方式二：API Key 公开数据模式", style="H2.TLabel").pack(anchor="w", **PAD)
        f = ttk.Frame(self)
        f.pack(fill="x", padx=10)
        ttk.Label(f, text="API Key：").grid(row=0, column=0, sticky="w", pady=3)
        self.key = ttk.Entry(f, width=50)
        self.key.insert(0, app.settings.get("youtube_api_key", ""))
        self.key.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(f, text="频道（ID / @handle / 链接）：").grid(row=1, column=0, sticky="w", pady=3)
        self.channel = ttk.Entry(f, width=50)
        self.channel.grid(row=1, column=1, sticky="we", pady=3)
        f.columnconfigure(1, weight=1)
        ttk.Button(self, text="获取公开数据", command=self.public).pack(anchor="e", **PAD)

    def oauth(self):
        path = filedialog.askopenfilename(parent=self, title="选择 OAuth 客户端 JSON",
                                          filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        self.app.settings["youtube_client_secret"] = path
        self.app.save_settings()
        self.close()
        self.on_oauth(path)

    def public(self):
        key, ch = self.key.get().strip(), self.channel.get().strip()
        if not key or not ch:
            messagebox.showwarning("提示", "请填写 API Key 和频道。", parent=self)
            return
        self.app.settings["youtube_api_key"] = key
        self.app.save_settings()
        self.close()
        self.on_public(ch)


# ------------------------------------------------------------------ 竞品管理
class CompetitorDialog(_Dialog):
    def __init__(self, app):
        super().__init__(app, "竞品管理", "640x460")
        ttk.Label(self, text="添加同领域账号，系统会抓取其公开数据用于对标分析。", style="Muted.TLabel").pack(anchor="w", **PAD)
        f = ttk.Frame(self)
        f.pack(fill="x", padx=10)
        self.platform = tk.StringVar(value="bilibili")
        ttk.Radiobutton(f, text="B站（UID）", variable=self.platform, value="bilibili").pack(side="left")
        ttk.Radiobutton(f, text="YouTube（频道ID/@handle）", variable=self.platform, value="youtube").pack(side="left", padx=8)
        self.ident = ttk.Entry(f, width=26)
        self.ident.pack(side="left", padx=4)
        ttk.Button(f, text="添加", style="Accent.TButton", command=self.add).pack(side="left", padx=4)
        cols = ("name", "platform", "updated")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        for c, t, w in zip(cols, ("账号", "平台", "最近更新"), (260, 100, 160)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True, padx=10, pady=6)
        row = ttk.Frame(self)
        row.pack(fill="x", **PAD)
        ttk.Button(row, text="添加演示竞品", command=self.add_demo).pack(side="left")
        ttk.Button(row, text="删除选中", command=self.remove).pack(side="left", padx=6)
        ttk.Button(row, text="刷新全部竞品数据", command=self.refresh_all).pack(side="right")
        self.reload()

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        for a in self.app.storage.list_accounts(competitors=True):
            self.tree.insert("", "end", iid=a["key"], values=(a["name"], a["platform"], a["updated_at"]))

    def add(self):
        ident = self.ident.get().strip()
        if not ident:
            return
        self.app.fetch_competitor(self.platform.get(), ident, done=self._after_change)

    def add_demo(self):
        def job(progress):
            progress(0.3, "生成演示竞品…")
            demo.generate(self.app.storage, "bilibili", competitor=True)
            demo.generate(self.app.storage, "youtube", competitor=True)
        self.app.run_task(job, "生成演示竞品", done=lambda _: self._after_change())

    def remove(self):
        for key in self.tree.selection():
            self.app.storage.delete_account(key)
        self._after_change()

    def refresh_all(self):
        self.app.refresh_competitors(done=self._after_change)

    def _after_change(self, *_):
        if not self.closed:
            self.reload()
        self.app.reanalyze()


# ------------------------------------------------------------------ 设置
class SettingsDialog(_Dialog):
    FIELDS = [
        ("auto_refresh_minutes", "自动监控间隔（分钟，0=关闭）", int),
        ("max_videos", "每次抓取的最大稿件数", int),
        ("comment_videos", "抓取评论的热门视频数", int),
        ("retention_videos", "YouTube 抓取留存曲线的视频数", int),
        ("youtube_api_key", "YouTube API Key（可选）", str),
    ]

    def __init__(self, app):
        super().__init__(app, "设置", "540x330")
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True, padx=14, pady=10)
        self.vars = {}
        for i, (k, label, _) in enumerate(self.FIELDS):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=5)
            v = tk.StringVar(value=str(app.settings.get(k, "")))
            ttk.Entry(f, textvariable=v, width=32).grid(row=i, column=1, sticky="we", pady=5)
            self.vars[k] = v
        self.comments = tk.BooleanVar(value=app.settings.get("fetch_comments", True))
        ttk.Checkbutton(f, text="抓取热门视频评论（用于评论洞察）", variable=self.comments).grid(
            row=len(self.FIELDS), column=0, columnspan=2, sticky="w", pady=5)
        f.columnconfigure(1, weight=1)
        ttk.Button(self, text="保存", style="Accent.TButton", command=self.save).pack(anchor="e", padx=14, pady=8)

    def save(self):
        try:
            for k, _, typ in self.FIELDS:
                self.app.settings[k] = typ(self.vars[k].get().strip() or (0 if typ is int else ""))
        except ValueError:
            messagebox.showerror("错误", "数字字段请输入整数。", parent=self)
            return
        self.app.settings["fetch_comments"] = self.comments.get()
        self.app.save_settings()
        self.app.schedule_auto_refresh()
        self.close()
