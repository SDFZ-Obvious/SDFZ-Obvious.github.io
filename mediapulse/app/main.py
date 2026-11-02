"""MediaPulse entry point: local server + native app window (Edge/Chrome app mode)."""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from .config import APP_NAME, DATA_DIR, LOG_PATH, VERSION
from .demo import seed_demo
from .server import create_server, start_auto_sync_thread
from .store import Store

log = logging.getLogger("mediapulse")


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr and sys.stderr.isatty():
        root.addHandler(logging.StreamHandler())


def find_browser() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def launch_window(url: str):
    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return None
    profile = DATA_DIR / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1560,980",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeSidebarV2,msEdgeCollections",
        "--disable-sync",
        "--disable-background-mode",
    ]
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(args, creationflags=flags)
        return proc
    except Exception as exc:
        log.warning("app window failed: %s", exc)
        webbrowser.open(url)
        return None


def instance_path() -> Path:
    return DATA_DIR / "instance.json"


def existing_instance() -> dict | None:
    try:
        data = json.loads(instance_path().read_text(encoding="utf-8"))
        url = data.get("url", "")
        token = data.get("token", "")
        if not url or not token:
            return None
        with urllib.request.urlopen(f"{url}/api/ping?token={token}", timeout=1.2) as resp:
            if resp.status == 200:
                return data
    except Exception:
        return None
    return None


def run(no_browser: bool = False, port: int = 0, host: str = "127.0.0.1"):
    setup_logging()
    log.info("MediaPulse %s starting; data=%s", VERSION, DATA_DIR)
    if not no_browser:
        existing = existing_instance()
        if existing:
            log.info("existing instance found at %s", existing["url"])
            launch_window(f"{existing['url']}/?token={existing['token']}")
            return 0

    store = Store()
    accounts = store.list_accounts()
    if not accounts:
        log.info("seeding demo dataset")
        seed_demo(store)
    server, state = create_server(store, host, port)
    url = state.url()
    full_url = f"{url}/?token={state.token}"
    try:
        instance_path().write_text(json.dumps({
            "url": url, "token": state.token, "pid": os.getpid(), "started": time.time(),
        }), encoding="utf-8")
    except Exception:
        pass

    thread = threading.Thread(target=server.serve_forever, name="mediapulse-http", daemon=True)
    thread.start()
    start_auto_sync_thread(state)
    log.info("server listening at %s", url)

    proc = None
    if not no_browser:
        proc = launch_window(full_url)
        if proc is not None:
            state.edge_process = proc

    try:
        if proc is not None:
            # If the app window crashes immediately, keep the server alive and use a browser tab.
            started = time.time()
            proc.wait()
            if time.time() - started > 2.5:
                state.shutting_down = True
            else:
                log.warning("app window exited immediately; falling back to browser")
                webbrowser.open(full_url)
                while not state.shutting_down:
                    time.sleep(0.7)
        else:
            while not state.shutting_down:
                time.sleep(0.7)
    except KeyboardInterrupt:
        state.shutting_down = True
    finally:
        log.info("shutting down")
        server.shutdown()
        server.server_close()
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            data = json.loads(instance_path().read_text(encoding="utf-8"))
            if data.get("pid") == os.getpid():
                instance_path().unlink(missing_ok=True)
        except Exception:
            pass
    return 0


def main():
    parser = argparse.ArgumentParser(description="MediaPulse")
    parser.add_argument("--no-browser", action="store_true", help="只启动本地服务")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.no_browser, args.port, args.host))
    except SystemExit:
        raise
    except Exception as exc:
        log.exception("fatal startup error")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"MediaPulse 启动失败：\n{exc}\n\n日志：{LOG_PATH}",
                "MediaPulse · 启动失败",
                0x10,
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
