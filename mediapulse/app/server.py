"""Local HTTP server + JSON API for the MediaPulse desktop app."""
from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import traceback
import urllib.parse
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import analytics, reports
from .bilibili import AuthExpired, BilibiliClient
from .config import APP_CN, APP_NAME, BUILD_DATE, EXPORT_DIR, REPORT_DIR, VERSION, WEB_DIR, PLATFORM_LABELS
from .store import Store, today_str
from .youtube import YouTubeClient, build_auth_url, exchange_code, parse_client_config

log = logging.getLogger("mediapulse.server")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


class AppState:
    def __init__(self, store: Store):
        self.store = store
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self.started = time.time()
        self.bili_sessions: dict[str, dict[str, Any]] = {}
        self.youtube_pending: dict[str, dict[str, Any]] = {}
        self.youtube_status: dict[str, Any] = {"status": "idle", "message": ""}
        self.sync_locks: dict[int, threading.Lock] = {}
        self.active_jobs: set[int] = set()
        self.server: ThreadingHTTPServer | None = None
        self.edge_process = None
        self.shutting_down = False

    def lock_for(self, account_id: int) -> threading.Lock:
        return self.sync_locks.setdefault(account_id, threading.Lock())

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class Handler(BaseHTTPRequestHandler):
    server_version = f"MediaPulse/{VERSION}"
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> AppState:
        return self.server.state  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, content_type: str,
              extra_headers: dict[str, str] | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, payload: Any, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def error(self, message: str, status: int = 400, code: str = "bad_request"):
        self.json({"error": code, "message": message}, status)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"JSON 格式错误: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def authorized(self, query: dict[str, list[str]]) -> bool:
        token = self.headers.get("X-MP-Token", "")
        if not token:
            token = (query.get("token") or [""])[0]
        return secrets.compare_digest(token, self.state.token)

    def account(self, account_id: int | str | None) -> dict[str, Any] | None:
        if account_id in (None, "", "0"):
            accounts = self.state.store.list_accounts()
            return self.state.store.get_account(accounts[0]["id"]) if accounts else None
        try:
            return self.state.store.get_account(int(account_id))
        except Exception:
            return None

    # ------------------------------------------------------------------ routing
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/oauth2callback":
            self.youtube_callback(query)
            return
        if path.startswith("/api/"):
            if not self.authorized(query):
                self.error("访问令牌无效，请重新启动 MediaPulse", 403, "forbidden")
                return
            try:
                self.api_get(path, query)
            except AuthExpired as exc:
                self.error(str(exc), 401, "auth_expired")
            except Exception as exc:
                log.error("GET %s failed: %s\n%s", path, exc, traceback.format_exc())
                self.error(str(exc) or "服务器内部错误", 500, "server_error")
            return
        self.serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not path.startswith("/api/"):
            self.error("Not found", 404, "not_found")
            return
        if not self.authorized(query):
            self.error("访问令牌无效，请重新启动 MediaPulse", 403, "forbidden")
            return
        try:
            body = self.read_json()
            self.api_post(path, body)
        except AuthExpired as exc:
            self.error(str(exc), 401, "auth_expired")
        except ValueError as exc:
            self.error(str(exc), 400, "bad_request")
        except Exception as exc:
            log.error("POST %s failed: %s\n%s", path, exc, traceback.format_exc())
            self.error(str(exc) or "服务器内部错误", 500, "server_error")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not self.authorized(query):
            self.error("访问令牌无效", 403, "forbidden")
            return
        try:
            match = re.match(r"^/api/accounts/(\d+)$", path)
            if match:
                account = self.account(int(match.group(1)))
                if not account:
                    self.error("账号不存在", 404)
                    return
                self.state.store.delete_account(int(account["id"]))
                self.json({"ok": True})
                return
            self.error("Not found", 404)
        except Exception as exc:
            log.exception("DELETE failed")
            self.error(str(exc), 500)

    # ------------------------------------------------------------------ static
    def serve_static(self, path: str):
        if path in ("/", "/index.html"):
            target = WEB_DIR / "index.html"
        elif path.startswith("/reports/"):
            target = REPORT_DIR / path[len("/reports/"):]
        elif path.startswith("/exports/"):
            target = EXPORT_DIR / path[len("/exports/"):]
        else:
            rel = path.lstrip("/")
            target = WEB_DIR / rel
        try:
            target = target.resolve()
            allowed_roots = [WEB_DIR.resolve(), REPORT_DIR.resolve(), EXPORT_DIR.resolve()]
            if not any(str(target).startswith(str(root)) for root in allowed_roots):
                self.error("Forbidden", 403)
                return
            if not target.is_file():
                self.error("Not found", 404)
                return
            data = target.read_bytes()
            ctype = MIME.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            headers = {}
            if target.suffix.lower() in (".xlsx", ".pdf", ".csv"):
                headers["Content-Disposition"] = f'attachment; filename="{urllib.parse.quote(target.name)}"'
            if "/vendor/" in path:
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            self._send(200, data, ctype, headers)
        except Exception as exc:
            log.error("static failed: %s", exc)
            try:
                self.error("File error", 500)
            except Exception:
                pass

    # ------------------------------------------------------------------ GET API
    def api_get(self, path: str, query: dict[str, list[str]]):
        store = self.state.store

        def q(name: str, default: str = "") -> str:
            return (query.get(name) or [default])[0]

        if path == "/api/ping":
            self.json({"ok": True, "app": APP_NAME, "version": VERSION})
            return
        if path == "/api/bootstrap":
            accounts = store.list_accounts()
            settings = store.settings()
            self.json({
                "app": {"name": APP_NAME, "cn": APP_CN, "version": VERSION, "build": BUILD_DATE},
                "accounts": accounts,
                "settings": {
                    "auto_sync_minutes": settings.get("auto_sync_minutes", "0"),
                    "theme": settings.get("theme", "dark"),
                    "last_range": settings.get("last_range", "30"),
                    "llm_enabled": settings.get("llm_enabled", "0"),
                    "has_deepseek_key": bool(settings.get("deepseek_api_key")),
                    "deepseek_model": settings.get("deepseek_model", "deepseek-chat"),
                },
                "jobs": store.recent_jobs(6),
                "server_time": datetime.now().isoformat(timespec="seconds"),
                "data_dir": str(REPORT_DIR.parent),
            })
            return
        if path == "/api/reports":
            files = []
            for folder, prefix in ((REPORT_DIR, "/reports"), (EXPORT_DIR, "/exports")):
                for item in folder.glob("*"):
                    if item.is_file() and item.suffix.lower() in (".html", ".pdf", ".xlsx"):
                        stat = item.stat()
                        size = stat.st_size
                        size_label = f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024 else f"{max(1, size // 1024)} KB"
                        files.append({
                            "name": item.name, "ext": item.suffix.lower().lstrip("."),
                            "url": f"{prefix}/{urllib.parse.quote(item.name)}",
                            "size": size, "size_label": size_label,
                            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        })
            files.sort(key=lambda f: f["mtime"], reverse=True)
            self.json({"files": files[:40]})
            return
        if path == "/api/dashboard":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号，请先登录或载入演示数据", 404, "no_account")
                return
            days = int(q("days", "30") or 30)
            self.json(analytics.build_dashboard(store, account, days))
            return
        if path == "/api/videos":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            self.json(analytics.video_table(store, account, int(q("days", "90") or 90)))
            return
        if path.startswith("/api/video/"):
            try:
                video_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self.error("视频 ID 无效", 400)
                return
            detail = analytics.video_detail(store, video_id)
            if not detail:
                self.error("视频不存在", 404)
                return
            self.json(detail)
            return
        if path == "/api/growth":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            self.json(analytics.growth_page(store, account, int(q("days", "90") or 90)))
            return
        if path == "/api/traffic":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            self.json(analytics.traffic_page(store, account, int(q("days", "30") or 30)))
            return
        if path == "/api/retention":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            self.json(analytics.retention_page(store, account, int(q("days", "90") or 90)))
            return
        if path == "/api/lab":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            self.json(analytics.lab_page(store, account, int(q("days", "90") or 90)))
            return
        if path == "/api/insights":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            days = int(q("days", "30") or 30)
            dash = analytics.build_dashboard(store, account, days)
            store.replace_insights(int(account["id"]), dash["insights"])
            self.json({"insights": dash["insights"]})
            return
        if path == "/api/jobs":
            self.json({"jobs": store.recent_jobs(10)})
            return
        if path.startswith("/api/jobs/"):
            try:
                job_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self.error("任务 ID 无效", 400)
                return
            job = store.get_job(job_id)
            if not job:
                self.error("任务不存在", 404)
                return
            self.json(job)
            return
        if path == "/api/auth/youtube/status":
            self.json(self.state.youtube_status)
            return
        if path == "/api/report":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            days = int(q("days", "30") or 30)
            make_pdf = q("pdf", "1") != "0"
            result = reports.build_report(store, account, days, make_pdf=make_pdf)
            result["html_url"] = f"/reports/{Path(result['html']).name}"
            result["xlsx_url"] = f"/exports/{Path(result['xlsx']).name}" if result.get("xlsx") else ""
            result["pdf_url"] = f"/reports/{Path(result['pdf']).name}" if result.get("pdf") else ""
            self.json(result)
            return
        if path == "/api/export/videos.csv":
            account = self.account(q("account_id"))
            if not account:
                self.error("没有可用的账号", 404)
                return
            table = analytics.video_table(store, account, int(q("days", "90") or 90))
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["标题", "BVID/ID", "发布", "时长(秒)", "总播放", "周期播放", "点赞", "投币",
                             "收藏", "评论", "分享", "互动率%", "转粉率%", "首7日播放", "链接"])
            for v in table["videos"]:
                writer.writerow([v["title"], v["vid"], v.get("published_at", ""), v["duration"],
                                 v["total_views"], v["period_views"], v["likes"], v["coins"],
                                 v["favorites"], v["comments"], v["shares"], v["engagement_rate"],
                                 v["conversion"], v["first7"], v["url"]])
            body = "\ufeff" + buf.getvalue()
            filename = f"MediaPulse_videos_{datetime.now():%Y%m%d_%H%M%S}.csv"
            self._send(200, body.encode("utf-8"), "text/csv; charset=utf-8",
                       {"Content-Disposition": f'attachment; filename="{filename}"'})
            return
        self.error("Not found", 404, "not_found")

    # ------------------------------------------------------------------ POST API
    def api_post(self, path: str, body: dict[str, Any]):
        store = self.state.store
        if path == "/api/settings":
            allowed = {"auto_sync_minutes", "theme", "deepseek_api_key", "deepseek_model",
                       "llm_enabled", "last_range"}
            values = {k: v for k, v in body.items() if k in allowed}
            if "auto_sync_minutes" in values:
                try:
                    values["auto_sync_minutes"] = str(max(0, min(1440, int(values["auto_sync_minutes"])))
                                                      )
                except Exception:
                    values["auto_sync_minutes"] = "0"
            store.set_settings(values)
            self.json({"ok": True})
            return
        if path == "/api/sync":
            account = self.account(body.get("account_id"))
            if not account:
                self.error("账号不存在", 404)
                return
            if account.get("is_demo"):
                self.error("演示账号不连接网络。请登录真实的 B 站或 YouTube 账号后同步。", 400, "demo_account")
                return
            job_id = self.start_sync(int(account["id"]))
            self.json({"job_id": job_id})
            return
        if path == "/api/accounts/demo":
            from .demo import seed_demo
            seed_demo(store)
            accounts = store.list_accounts()
            self.json({"ok": True, "accounts": accounts})
            return
        if path == "/api/demo/reset":
            from .demo import seed_demo
            for account in store.list_accounts():
                if account.get("is_demo"):
                    store.delete_account(int(account["id"]))
            ids = seed_demo(store, force=True)
            self.json({"ok": True, "ids": ids})
            return
        if path == "/api/title/analyze":
            account = self.account(body.get("account_id"))
            if not account:
                self.error("账号不存在", 404)
                return
            self.json(analytics.analyze_title(store, account, str(body.get("title", ""))))
            return
        if path == "/api/shutdown":
            self.json({"ok": True})
            self.state.shutting_down = True
            threading.Thread(target=self._shutdown_later, daemon=True).start()
            return
        if path == "/api/auth/bilibili/qr":
            client = BilibiliClient()
            qr = client.qr_generate()
            self.state.bili_sessions[qr["key"]] = {"client": client, "created": time.time()}
            # prune old sessions
            for key, sess in list(self.state.bili_sessions.items()):
                if time.time() - sess["created"] > 300:
                    self.state.bili_sessions.pop(key, None)
            self.json(qr)
            return
        if path == "/api/auth/bilibili/poll":
            key = str(body.get("key", ""))
            session = self.state.bili_sessions.get(key)
            if not session:
                self.json({"status": "expired", "message": "二维码已过期，请刷新"})
                return
            client: BilibiliClient = session["client"]
            result = client.qr_poll(key)
            if result.get("status") == "success":
                profile = client.nav()
                relation = client.relation_stat(profile["mid"])
                account_id = store.create_account(
                    platform="bilibili", uid=profile["mid"], name=profile["name"],
                    avatar=profile["avatar"], cookie=result.get("cookies", ""),
                    meta={"signature": profile.get("sign", ""), "level": profile.get("level"),
                          "mid": profile["mid"]},
                    followers=relation["followers"],
                )
                self.state.bili_sessions.pop(key, None)
                job_id = self.start_sync(int(account_id))
                account = store.get_account(account_id)
                self.json({"status": "success", "account": account, "job_id": job_id})
                return
            if result.get("status") in ("expired", "error"):
                self.state.bili_sessions.pop(key, None)
            self.json(result)
            return
        if path == "/api/auth/youtube/start":
            try:
                client_cfg = parse_client_config(body.get("client_json", ""))
            except ValueError as exc:
                self.error(str(exc), 400, "client_config")
                return
            state = secrets.token_urlsafe(18)
            redirect_uri = f"{self.state.url()}/oauth2callback"
            self.state.youtube_pending[state] = {
                "client": client_cfg, "redirect_uri": redirect_uri, "created": time.time(),
            }
            self.state.youtube_status = {"status": "pending", "message": "等待 Google 授权"}
            self.json({"auth_url": build_auth_url(client_cfg, redirect_uri, state),
                       "redirect_uri": redirect_uri})
            return
        self.error("Not found", 404, "not_found")

    def start_sync(self, account_id: int) -> int:
        return start_sync_job(self.state, account_id)

    # ------------------------------------------------------------------ oauth callback
    def youtube_callback(self, query: dict[str, list[str]]):
        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        error = (query.get("error") or [""])[0]
        pending = self.state.youtube_pending.pop(state, None)
        if error or not code or not pending:
            self.state.youtube_status = {"status": "error",
                                         "message": error or "授权回调无效或 state 已过期"}
            self.render_oauth_result(False, error or "授权失败或已过期，请回到 MediaPulse 重新发起登录。")
            return
        try:
            token = exchange_code(pending["client"], code, pending["redirect_uri"])
            client = YouTubeClient(token)
            channel = client.channel()
            snippet = channel.get("snippet") or {}
            thumbs = snippet.get("thumbnails") or {}
            avatar = (thumbs.get("medium") or {}).get("url", "")
            stats = channel.get("statistics") or {}
            account_id = self.state.store.create_account(
                platform="youtube", uid=channel.get("id", ""),
                name=snippet.get("title", "YouTube Channel"), avatar=avatar,
                token=token, meta={"signature": snippet.get("description", "")[:300],
                                   "custom_url": snippet.get("customUrl", "")},
                followers=int(stats.get("subscriberCount", 0) or 0),
                total_views=int(stats.get("viewCount", 0) or 0),
            )
            job_id = self.start_sync(int(account_id))
            self.state.youtube_status = {"status": "success", "message": "授权成功，正在同步数据",
                                         "account_id": account_id, "job_id": job_id}
            self.render_oauth_result(True, "YouTube 授权成功，数据同步已在后台开始。可以关闭此页面回到 MediaPulse。")
        except Exception as exc:
            log.error("youtube callback failed: %s\n%s", exc, traceback.format_exc())
            self.state.youtube_status = {"status": "error", "message": str(exc)}
            self.render_oauth_result(False, f"授权失败：{exc}")

    def render_oauth_result(self, ok: bool, message: str):
        color = "#34d399" if ok else "#f87171"
        icon = "✓" if ok else "!"
        text = (message or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        page = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>MediaPulse 授权</title>
<style>body{{margin:0;background:#0b0d14;color:#eef0f8;font-family:"Microsoft YaHei",Arial,sans-serif;display:grid;place-items:center;height:100vh}}
.card{{max-width:520px;padding:40px;border:1px solid rgba(255,255,255,.1);border-radius:20px;background:#141826;text-align:center;box-shadow:0 30px 80px rgba(0,0,0,.4)}}
.icon{{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;margin:0 auto 20px;background:{color}22;color:{color};font-size:28px;font-weight:700}}
h1{{font-size:22px;margin:0 0 10px}}p{{color:#9aa3b8;font-size:14px;line-height:1.8;margin:0}}a{{display:inline-block;margin-top:24px;color:#c4b5fd;text-decoration:none;font-size:13px}}</style></head>
<body><div class="card"><div class="icon">{icon}</div><h1>MediaPulse · YouTube 授权</h1><p>{text}</p>
<a href="/?token={self.state.token}">返回 MediaPulse</a></div>
<script>setTimeout(()=>{{if({str(ok).lower()}) window.close();}},3500)</script></body></html>"""
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _shutdown_later(self):
        time.sleep(0.6)
        if self.state.server:
            self.state.server.shutdown()


def start_sync_job(state: AppState, account_id: int) -> int:
    job_id = state.store.create_job("sync", account_id, "任务已创建")
    thread = threading.Thread(target=run_sync_job, args=(state, job_id, account_id), daemon=True)
    thread.start()
    return job_id


def run_sync_job(state: AppState, job_id: int, account_id: int):
    store = state.store
    lock = state.lock_for(account_id)
    if not lock.acquire(blocking=False):
        store.update_job(job_id, status="error", message="该账号正在同步中，请稍候", progress=0)
        return
    state.active_jobs.add(job_id)
    try:
        store.update_job(job_id, status="running", progress=2, message="准备同步")
        account = store.get_account(account_id, with_secrets=True)
        if not account:
            raise RuntimeError("账号不存在")
        last_progress = {"value": 2}

        def progress(pct: int, message: str):
            pct = max(2, min(97, int(pct)))
            if pct - last_progress["value"] >= 1 or message != "同步中":
                last_progress["value"] = pct
                store.update_job(job_id, progress=pct, message=message)

        if account["platform"] == "bilibili":
            summary = BilibiliClient(account.get("cookie", "")).sync(store, account_id, progress)
        else:
            summary = YouTubeClient().sync(store, account_id, progress)
        store.update_job(job_id, progress=98, message="生成运营洞察")
        account = store.get_account(account_id)
        if account:
            analytics.ensure_insights(store, account, 30)
        store.update_job(job_id, status="success", progress=100,
                         message="同步完成", result=json.dumps(summary, ensure_ascii=False))
    except AuthExpired as exc:
        store.update_job(job_id, status="error", message=str(exc), progress=100)
        store.update_account(account_id, status="auth_expired")
    except Exception as exc:
        log.error("sync job %s failed: %s\n%s", job_id, exc, traceback.format_exc())
        store.update_job(job_id, status="error", progress=100, message=str(exc)[:500])
    finally:
        state.active_jobs.discard(job_id)
        lock.release()


def start_auto_sync_thread(state: AppState):
    def loop():
        while not state.shutting_down:
            try:
                minutes = int(state.store.get_setting("auto_sync_minutes", "0") or 0)
                if minutes > 0:
                    now = datetime.now()
                    for account in state.store.list_accounts():
                        if account.get("is_demo") or account.get("status") == "auth_expired":
                            continue
                        lock = state.lock_for(int(account["id"]))
                        if lock.locked():
                            continue
                        last = account.get("last_sync") or ""
                        try:
                            last_dt = datetime.fromisoformat(last)
                        except Exception:
                            last_dt = datetime.min
                        if (now - last_dt).total_seconds() >= minutes * 60:
                            start_sync_job(state, int(account["id"]))
            except Exception as exc:
                log.warning("auto sync loop: %s", exc)
            for _ in range(60):
                if state.shutting_down:
                    return
                time.sleep(1)
    threading.Thread(target=loop, name="mediapulse-auto-sync", daemon=True).start()


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, state: AppState):
        self.state = state
        super().__init__(addr, Handler)
        state.server = self


def create_server(store: Store, host: str = "127.0.0.1", port: int = 0) -> tuple[AppServer, AppState]:
    state = AppState(store)
    server = AppServer((host, port), state)
    state.port = server.server_address[1]
    return server, state
