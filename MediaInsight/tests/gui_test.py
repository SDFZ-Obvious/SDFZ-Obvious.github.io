"""界面自动化测试：在临时数据目录中启动程序，加载演示数据，遍历所有页签并截图。

用法：python tests/gui_test.py  （截图输出到 tests/out/gui_*.png）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab  # noqa: E402

from gui import app as gui_app  # noqa: E402

OUT = ROOT / "tests" / "out"
OUT.mkdir(exist_ok=True)
errors = []


def main():
    gui_app._enable_dpi_awareness()
    a = gui_app.App()
    orig = a.log
    a.log = lambda m: (orig(m), errors.append(m) if "Traceback" in m else None)
    tabs = list(range(a.nb.index("end")))
    state = {"i": 0, "phase": "wait_demo"}

    def shot(name):
        a.update()
        x, y = a.winfo_rootx(), a.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + a.winfo_width(), y + a.winfo_height())).save(OUT / f"gui_{name}.png")

    def step():
        if state["phase"] == "wait_demo":
            if a.res is not None and a._busy == 0:
                state["phase"] = "tabs"
            a.after(300, step)
            return
        if state["phase"] == "tabs":
            i = state["i"]
            if i >= len(tabs):
                state["phase"] = "sim"
                a.nb.select(len(a.pages))
                a.sim_title.insert(0, "【干货】8个AI绘画技巧，新手必看")
                a.simulate()
                a.after(500, step)
                return
            a.nb.select(i)
            a.after(700, lambda: (shot(f"{i:02d}"), state.update(i=i + 1), a.after(100, step)))
            return
        if state["phase"] == "sim":
            shot("simulator")
            a.destroy()

    a.after(500, a.load_demo)
    a.after(800, step)
    a.mainloop()
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
