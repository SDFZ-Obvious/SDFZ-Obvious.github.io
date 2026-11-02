"""MediaInsight 启动入口。"""
import sys
import traceback


def main():
    try:
        from gui.app import run
        run()
    except Exception:  # noqa: BLE001 - 打包后没有控制台，把致命错误写入日志并弹窗
        from core.config import app_dir
        err = traceback.format_exc()
        (app_dir() / "crash.log").write_text(err, encoding="utf-8")
        try:
            from tkinter import messagebox
            messagebox.showerror("MediaInsight 启动失败", err[-1500:])
        except Exception:  # noqa: BLE001
            print(err, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
