"""冒烟测试：生成演示数据并跑完整分析。用法：python tests/smoke_test.py"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import analytics, charts, demo, report  # noqa: E402
from core.storage import Storage  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    st = Storage(tmp)
    t0 = time.time()
    keys = [demo.generate(st, "bilibili"), demo.generate(st, "youtube"),
            demo.generate(st, "bilibili", competitor=True)]
    print(f"demo generated in {time.time() - t0:.1f}s", keys)
    for key in keys[:2]:
        ds = st.load(key)
        comps = [st.load(keys[2])]
        res = analytics.analyze(ds, comps)
        print("=" * 60, ds.name, len(ds.videos), "videos")
        for name in analytics.MODULES + ["health", "competitors"]:
            r = res[name]
            print(f"[{name}] ok={r.get('ok')}")
            for s in r.get("insights", []):
                print("   -", s)
        for r in res["recommendations"]:
            print("  *", r)
        p = analytics.predict(res["df"], 5, 20, 480, None)
        print("predict:", p[:3] if p else None)
        out_dir = Path(__file__).resolve().parent / "out"
        out_dir.mkdir(exist_ok=True)
        for k, title, builder in charts.PAGES:
            (out_dir / f"{ds.platform}_{k}.png").write_bytes(charts.to_png(builder(res)))
        report.html_report(res, out_dir / f"{ds.platform}_report.html")
        report.excel_report(res, out_dir / f"{ds.platform}_report.xlsx")
        (out_dir / f"{ds.platform}_report.txt").write_text(report.text_report(res), encoding="utf-8")
        print("charts & reports written to", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
