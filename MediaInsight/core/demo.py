"""演示数据生成器：无需登录即可体验全部功能。

数据带有真实运营中常见的规律（晚间发布更好、5-15 分钟中长视频转粉更高、
偶发爆款、账号逐步成长等），并生成 90 天的历史快照用于趋势与生命周期分析。
"""
import math
import random
from datetime import datetime, timedelta

from .storage import FetchResult, Storage

TOPICS = ["Python", "视频剪辑", "摄影", "AI绘画", "显卡", "咖啡", "露营", "Excel", "机械键盘",
          "考研", "健身", "日语", "吉他", "副业", "ChatGPT", "装机", "手冲", "租房"]
TITLE_TEMPLATES = [
    "【干货】{n}个{t}技巧，第{k}个太实用了", "为什么{t}这么难？看完你就懂了", "{t}入门全攻略（2026最新）",
    "我用{n}天学会了{t}，结果……", "{t}实测：{n}款对比，差距太大", "别再这样做{t}了！", "{t}的{n}个误区",
    "花了{n}000块，我终于搞懂了{t}", "{t}｜新手必看", "一个视频讲清楚{t}", "{t}vlog：普通的一天",
    "{t}翻车现场 hhh", "如何零基础开始{t}？", "【{t}】从0到1完整教程",
]
CATEGORIES = {
    "bilibili": {"知识": 1.25, "科技": 1.15, "生活": 0.9, "游戏": 1.0, "影视": 0.8},
    "youtube": {"教育": 1.25, "科学与技术": 1.15, "人物与博客": 0.85, "游戏": 1.0, "娱乐": 0.9},
}
POS = ["讲得太清楚了，收藏了", "up主太良心了！", "三连支持", "终于有人讲明白了", "干货满满，感谢分享",
       "这期质量好高", "剪辑节奏很舒服", "已关注，期待更新", "从头看到尾，学到了", "太实用了吧"]
NEG = ["前面铺垫太长了，直接快进", "声音有点小", "广告有点多", "节奏有点拖", "字幕有错别字",
       "标题党了吧", "画质有点糊"]
ASK = ["能出一期进阶教程吗？", "求出{t}的续集", "请问用的什么软件？", "可以讲讲{t}怎么入门吗？",
       "催更催更！", "求BGM", "下期能做{t}对比吗"]
NEUTRAL = ["来了来了", "第一", "打卡", "已阅", "看完了", "hhhh"]


def _hour_mult(h):
    return {19: 1.45, 20: 1.55, 21: 1.5, 18: 1.3, 22: 1.25, 12: 1.15, 13: 1.1}.get(h, 0.85 if h < 9 else 1.0)


def _dur_mult(d, platform):
    if d < 60:
        return 1.25 if platform == "youtube" else 0.75
    if d < 180:
        return 0.95
    if d < 900:
        return 1.35
    if d < 1800:
        return 1.1
    return 0.8


def _views_at(final, age_days, tau):
    if age_days <= 0:
        return 0
    return final * (1 - math.exp(-age_days / tau)) * (0.85 + 0.15 * min(age_days / 180, 1))


def _make_videos(platform, rng, now, n=110, scale=1.0):
    cats = CATEGORIES[platform]
    videos, t = [], now - timedelta(days=520)
    for i in range(n):
        t += timedelta(days=rng.uniform(2, 7.5))
        if t > now - timedelta(hours=10):
            break
        hour = rng.choices(range(24), weights=[1, 0, 0, 0, 0, 0, 1, 2, 3, 3, 4, 5, 8, 6, 4, 4, 5, 7, 10, 12, 12, 10, 6, 3])[0]
        pub = t.replace(hour=hour, minute=rng.choice([0, 0, 30, 15, 45]), second=0, microsecond=0)
        dur = int(rng.choice([rng.uniform(25, 59), rng.lognormvariate(6.1, 0.6), rng.lognormvariate(6.4, 0.5)]))
        dur = max(15, min(dur, 4200))
        cat = rng.choice(list(cats))
        topic = rng.choice(TOPICS)
        title = rng.choice(TITLE_TEMPLATES).format(n=rng.randint(3, 12), k=rng.randint(2, 5), t=topic)
        quality = rng.lognormvariate(0, 0.45)
        growth = 0.55 + 0.9 * (i / n)
        mult = (_hour_mult(pub.hour) * (1.18 if pub.weekday() >= 5 else 1.0) * _dur_mult(dur, platform)
                * cats[cat] * (1.12 if any(ch.isdigit() for ch in title) else 1) * growth * quality)
        if rng.random() < 0.05:
            mult *= rng.uniform(5, 10)   # 爆款
        final = 9000 * scale * mult * rng.lognormvariate(0, 0.35)
        q = min(quality, 2.5)
        pct = max(0.12, min(0.92, 0.78 - 0.17 * math.log10(max(dur, 20) / 30) + 0.06 * (q - 1) + rng.gauss(0, 0.04)))
        bounce = max(0.05, min(0.6, 0.3 - 0.07 * (q - 1) + (0.08 if dur > 900 else 0) + rng.gauss(0, 0.04)))
        conv = 0.0035 * (1.6 if 300 <= dur <= 1200 else 1.0) * (0.6 if dur < 60 else 1) * q
        ctr = max(0.015, min(0.18, 0.055 * q ** 0.5 + rng.gauss(0, 0.012)))
        videos.append({"pub": pub, "dur": dur, "cat": cat, "title": title, "final": final, "pct": pct,
                       "bounce": bounce, "conv": conv, "ctr": ctr, "q": q, "topic": topic,
                       "tau": rng.uniform(2, 9), "idx": i})
    return videos


def _video_record(platform, v, views, rng):
    vid = f"BV1Demo{v['idx']:04d}" if platform == "bilibili" else f"ytDemo{v['idx']:05d}"
    q = v["q"]
    rec = {
        "video_id": vid, "title": v["title"],
        "url": (f"https://www.bilibili.com/video/{vid}" if platform == "bilibili"
                else f"https://www.youtube.com/watch?v={vid}"),
        "publish_time": v["pub"].isoformat(), "duration": v["dur"], "category": v["cat"],
        "tags": ",".join([v["topic"], v["cat"], "教程" if "教程" in v["title"] or "攻略" in v["title"] else "分享"]),
        "views": int(views),
        "likes": int(views * 0.055 * q ** 0.6), "comments": int(views * 0.006 * q ** 0.5),
        "shares": int(views * 0.004 * q),
        "avg_view_pct": round(v["pct"], 4), "avg_view_duration": round(v["pct"] * v["dur"], 1),
        "bounce_3s": round(v["bounce"], 4),
        "subs_gained": int(views * v["conv"]), "subs_lost": int(views * v["conv"] * 0.12),
        "impressions": int(views / v["ctr"] * 0.75), "ctr": round(v["ctr"], 4),
    }
    if platform == "bilibili":
        rec.update(coins=int(views * 0.018 * q ** 0.8), favorites=int(views * 0.025 * q ** 0.7),
                   danmaku=int(views * 0.012 * q ** 0.5))
    return rec


def _retention_curve(v, rng):
    pts, pct, b = [], v["pct"], v["bounce"]
    k = max(0.2, (1 - b - pct) * 3.2)
    dip_at = rng.uniform(0.3, 0.7)
    for i in range(1, 101):
        x = i / 100
        y = (1 - b * min(1, x * 15)) * math.exp(-k * x)
        if x > dip_at:
            y *= 0.88
        if 0.4 < x < 0.45:
            y *= 1.06    # 观众回看的高光片段
        if x > 0.93:
            y *= 0.8     # 片尾流失
        pts.append([round(x, 2), round(max(y + rng.gauss(0, 0.006), 0.01), 4)])
    return pts


def _comments(rng, topic, q):
    out = []
    for _ in range(30):
        r = rng.random()
        pos_p = 0.45 + 0.1 * min(q - 1, 1)
        if r < pos_p:
            out.append(rng.choice(POS))
        elif r < pos_p + 0.13:
            out.append(rng.choice(NEG))
        elif r < pos_p + 0.33:
            out.append(rng.choice(ASK).format(t=topic))
        else:
            out.append(rng.choice(NEUTRAL))
    return out


def generate(storage: Storage, platform="bilibili", competitor=False, seed=None):
    rng = random.Random(seed if seed is not None else (7 if platform == "bilibili" else 11) + int(competitor) * 100)
    now = datetime.now().replace(second=0, microsecond=0)
    scale = 1.6 if competitor else 1.0
    raw = _make_videos(platform, rng, now, scale=scale)
    if competitor:
        name = "演示竞品·科技区同行" if platform == "bilibili" else "Demo Competitor"
        acc_id = f"demo-competitor-{platform}"
    else:
        name = "演示账号·B站" if platform == "bilibili" else "Demo Channel (YouTube)"
        acc_id = f"demo-{platform}"

    followers0 = int(48000 * scale)
    history_days = 90
    followers = followers0
    daily = []
    for d in range(history_days, -1, -1):
        day = now - timedelta(days=d)
        vids, day_views = [], 0
        for v in raw:
            age = (day - v["pub"]).total_seconds() / 86400
            if age <= 0:
                continue
            views = _views_at(v["final"], age, v["tau"])
            prev = _views_at(v["final"], age - 1, v["tau"])
            day_views += views - prev
            if d % 3 == 0 or d == 0 or age < 14:      # 模拟定时监控的快照
                vids.append(_video_record(platform, v, views, rng))
        gained = int(day_views * 0.0045 * rng.uniform(0.8, 1.2))
        lost = int(gained * rng.uniform(0.08, 0.18))
        followers += gained - lost
        if d > 0:
            daily.append({"date": day.strftime("%Y-%m-%d"), "views": int(day_views), "subs_gained": gained,
                          "subs_lost": lost, "likes": int(day_views * 0.05), "comments": int(day_views * 0.006),
                          "shares": int(day_views * 0.004), "watch_minutes": int(day_views * 3.1)})
        r = FetchResult(platform=platform, account_id=acc_id, name=name, followers=followers,
                        total_views=sum(x["views"] for x in vids), videos=vids)
        r.total_likes = sum(x["likes"] for x in vids)
        if d == 0:
            r.daily = daily
            _extras(r, raw, rng, platform)
        storage.save(r, is_demo=True, is_competitor=competitor, ts=day.isoformat(timespec="seconds"))
    return f"{platform}:{acc_id}"


def _extras(r, raw, rng, platform):
    ordered = sorted(r.videos, key=lambda x: x["views"], reverse=True)
    by_idx = {v["idx"]: v for v in raw}
    lookup = {x["video_id"]: by_idx[int(x["video_id"][-4:] if platform == "bilibili" else x["video_id"][-5:])]
              for x in r.videos}
    for rec in ordered[:15]:
        r.retention[rec["video_id"]] = _retention_curve(lookup[rec["video_id"]], rng)
    for rec in ordered[:8]:
        src = lookup[rec["video_id"]]
        r.comments[rec["video_id"]] = _comments(rng, src["topic"], src["q"])
    if platform == "bilibili":
        r.breakdowns = {
            "traffic": {"推荐/首页": 46, "搜索": 21, "相关推荐": 14, "空间": 7, "动态": 6, "外链": 3, "其他": 3},
            "device": {"手机": 71, "电脑": 22, "平板": 4, "电视": 3},
            "age": {"18 岁以下": 9, "18–24 岁": 41, "25–30 岁": 28, "31–40 岁": 15, "40 岁以上": 7},
            "gender": {"男": 64, "女": 36},
            "country": {"广东": 14, "江苏": 9, "浙江": 8, "北京": 7, "上海": 7, "山东": 6, "四川": 6, "其他": 43},
            "subscribed": {"已关注": 38, "未关注": 62},
        }
    else:
        r.breakdowns = {
            "traffic": {"推荐视频": 38, "首页/浏览功能": 27, "YouTube 搜索": 17, "Shorts 信息流": 8,
                        "外部链接": 4, "订阅内容": 4, "其他": 2},
            "device": {"手机": 63, "电脑": 25, "电视": 9, "平板": 3},
            "age": {"13–17 岁": 6, "18–24 岁": 34, "25–34 岁": 33, "35–44 岁": 16, "45 岁以上": 11},
            "gender": {"男": 72, "女": 28},
            "country": {"US": 24, "TW": 15, "HK": 11, "MY": 9, "SG": 8, "CA": 7, "JP": 5, "其他": 21},
            "subscribed": {"已订阅": 31, "未订阅": 69},
        }
