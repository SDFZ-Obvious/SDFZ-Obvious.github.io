"""导入创作中心 / YouTube Studio 导出的表格，补全接口拿不到的深度指标。"""
import re

import pandas as pd

FIELD_ALIASES = {
    "video_id": ["bv号", "bvid", "稿件bv号", "视频id", "videoid", "video id", "content", "视频链接", "链接", "video"],
    "title": ["标题", "稿件标题", "视频标题", "video title", "title"],
    "avg_view_pct": ["完播率", "平均播放进度", "平均观看百分比", "average percentage viewed", "avg % viewed"],
    "bounce_3s": ["3秒跳出率", "三秒跳出率", "3s跳出率", "跳出率", "前3秒跳出", "bounce"],
    "subs_gained": ["涨粉", "新增粉丝", "转粉", "新增关注", "subscribers gained", "subscribers"],
    "subs_lost": ["掉粉", "取关", "subscribers lost"],
    "avg_view_duration": ["平均播放时长", "平均观看时长", "人均观看时长", "average view duration"],
    "impressions": ["曝光量", "曝光", "展现量", "impressions"],
    "ctr": ["点击率", "封面点击率", "impressions click-through rate", "click-through rate", "ctr"],
}
PCT_FIELDS = {"avg_view_pct", "bounce_3s", "ctr"}
ID_RE = re.compile(r"(BV[0-9A-Za-z]{10})|(?:v=|youtu\.be/)([\w-]{11})")


def _norm(s):
    return re.sub(r"[\s_（）()%]", "", str(s)).lower()


def _match_columns(columns):
    mapping = {}
    for field, aliases in FIELD_ALIASES.items():
        normalized = [_norm(a) for a in aliases]
        for col in columns:
            n = _norm(col)
            if any(n == a or (len(a) >= 2 and a in n) for a in normalized):
                if field not in mapping.values():
                    mapping[col] = field
                    break
    return mapping


def _to_seconds(x):
    if pd.isna(x):
        return None
    s = str(x).strip()
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        sec = 0.0
        for p in parts:
            sec = sec * 60 + p
        return sec
    try:
        return float(s.replace("秒", "").replace("s", ""))
    except ValueError:
        return None


def _to_ratio(x):
    if pd.isna(x):
        return None
    s = str(x).strip().replace(",", "")
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100
        v = float(s)
    except ValueError:
        return None
    return v / 100 if v > 1 else v


def _to_num(x):
    if pd.isna(x):
        return None
    s = str(x).strip().replace(",", "")
    mult = 1
    if s.endswith("万"):
        s, mult = s[:-1], 10000
    try:
        return float(s) * mult
    except ValueError:
        return None


def read_table(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "gbk", "utf-16"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("无法识别的文件编码")


def build_updates(df: pd.DataFrame, videos: pd.DataFrame):
    """返回 ({video_id: {字段: 值}}, 识别到的列映射)。"""
    mapping = _match_columns(df.columns)
    if not ({"video_id", "title"} & set(mapping.values())):
        raise ValueError("表格中没有找到 BV号/视频ID 或 标题 列，无法与稿件对应。")
    title_to_id = dict(zip(videos["title"].astype(str).str.strip(), videos["video_id"]))
    known = set(videos["video_id"])
    updates = {}
    for _, row in df.iterrows():
        vid = None
        for col, field in mapping.items():
            if field == "video_id" and pd.notna(row[col]):
                raw = str(row[col]).strip()
                m = ID_RE.search(raw)
                vid = (m.group(1) or m.group(2)) if m else raw
        if (not vid or vid not in known) and "title" in mapping.values():
            tcol = next(c for c, f in mapping.items() if f == "title")
            vid = title_to_id.get(str(row[tcol]).strip(), vid)
        if not vid or vid not in known:
            continue
        fields = {}
        for col, field in mapping.items():
            if field in ("video_id", "title"):
                continue
            val = row[col]
            if field in PCT_FIELDS:
                fields[field] = _to_ratio(val)
            elif field == "avg_view_duration":
                fields[field] = _to_seconds(val)
            else:
                fields[field] = _to_num(val)
        updates[vid] = fields
    return updates, mapping
