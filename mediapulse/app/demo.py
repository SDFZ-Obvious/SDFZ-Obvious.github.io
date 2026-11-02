"""Deterministic, realistic demo dataset so every screen is useful before login."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from .store import Store, now_iso

BILI_TITLES = [
    "我用 300 行代码，复刻了小时候的电子宠物",
    "48 小时不睡觉，我做出了一个会自己写周报的 AI",
    "别再乱买显示器了，这 5 个参数才是关键",
    "为什么你的视频没人看？算法其实只关心这 3 件事",
    "把 20 年前的旧电脑改成 NAS，成本不到 300 元",
    "开箱一台 1999 元的「电子垃圾」，居然能跑 3A？",
    "从零搭建家庭服务器：保姆级避坑指南",
    "我花了 7 天，把出租屋改成了赛博朋克工作室",
    "这可能是今年最被低估的生产力工具",
    "实测 10 款 AI 写作工具，只有 2 款值得留下",
    "一块树莓派，如何接管我的整个房间",
    "深夜实测：城市光污染到底有多严重？",
    "我让 AI 连续工作 24 小时，结果它开始撒谎",
    "99% 的人都没用对微信这个隐藏功能",
    "把手机变成显微镜，只需要一个塑料瓶",
    "一个月涨粉 5 万，我做对了哪三件事？",
    "这 8 个免费网站，建议每个创作者收藏",
    "拆解一台 10 万元的电影机，里面到底有什么",
    "为什么日本街头的声音这么好听？",
    "挑战用 100 元吃遍城市凌晨三点",
    "我在废弃工厂里，搭了一个全景声影院",
    "当程序员开始做木工，会发生什么",
    "用 1 张照片，生成一整部短片",
    "全网都在吹的「氛围感」，到底是什么",
    "连续记录 30 天，我发现了时间的秘密",
    "这台 15 年前的相机，拍出了我最满意的照片",
    "把 1000 首歌喂给 AI，它写出的旋律让我沉默",
    "为什么你的房间总是很乱？问题可能不在收纳",
    "我复刻了电影里的「钢铁侠」工作台",
    "从 0 到 1 做一个播客，需要花多少钱",
    "这可能是 B 站最详细的灯光入门教程",
    "别再收藏吃灰了，这套学习方法真的有用",
    "我用 3 个月，把通勤时间变成了第二份收入",
    "一个人做视频，如何把效率提升 3 倍",
    "当所有 App 都在偷听我们说话",
    "实测：把路由器放进冰箱，网速会变快吗",
    "我用 AI 给奶奶做了一本会说话的书",
    "凌晨四点的菜市场，藏着城市最真实的样子",
    "花 1 万块改造老破小，房东看完不想租了",
    "为什么我们越来越难读完一本书",
    "这 5 个镜头语言，让普通画面立刻高级",
    "我把童年零食做成了米其林摆盘",
    "一年后，我终于关掉了所有消息通知",
    "用数据拆解 100 个爆款视频，我找到了共同点",
    "第一次用胶片拍人像，翻车了吗",
    "在县城开一家影像店，能活下去吗",
    "这台机器能把你写的字变成声音",
    "为什么 B 站的学习区让人上瘾",
]

BILI_TAGS = [
    ["科技", "数码", "DIY"], ["AI", "效率", "测评"], ["摄影", "生活", "记录"],
    ["知识", "运营", "自媒体"], ["数码", "开箱", "避坑"], ["家居", "改造", "出租屋"],
    ["编程", "树莓派", "智能家居"], ["影视", "幕后", "器材"], ["美食", "城市", "夜宵"],
    ["学习", "方法", "成长"], ["音乐", "AI", "创作"], ["剪辑", "教程", "干货"],
]

YT_TITLES = [
    "I Built an AI Studio in 48 Hours (Full Process)",
    "Why Your Videos Aren't Getting Views — The Real Reason",
    "Testing 10 AI Tools So You Don't Have To",
    "From Zero to Home Server: A Beginner's Guide",
    "This $200 Camera Changed How I Shoot",
    "I Automated My Entire Apartment with One Raspberry Pi",
    "The 5 Settings Every Creator Should Change",
    "I Gave an AI 24 Hours and It Started Lying",
    "How I Gained 50K Subscribers in 30 Days",
    "The Hidden Cost of Free Software",
    "I Rebuilt My Childhood PC — 20 Years Later",
    "A Cinematic Tour of an Abandoned Factory",
    "Why Japanese Streets Sound Different",
    "I Tried Living Without Notifications for 30 Days",
    "The Art of Lighting: A Complete Beginner Guide",
    "Can a 15-Year-Old Camera Still Compete?",
    "I Fed 1,000 Songs to an AI. Here's What Happened",
    "The Productivity System That Actually Works",
    "Building a Podcast from Scratch: What It Really Costs",
    "I Turned a Phone into a Microscope",
    "The Problem With 'Aesthetic' Content",
    "How to Edit Faster: My 3-Pass Workflow",
    "I Made a Talking Book for My Grandma",
    "What 100 Viral Videos Have in Common",
    "The Truth About Algorithm Changes",
    "I Spent $10,000 on a Film Camera Rig",
    "Why We Can't Finish Books Anymore",
    "A Day in the Life of a Full-Time Creator",
    "I Tried the Cheapest 3D Printer on Amazon",
    "The Most Underrated Tool for Creators",
    "I Built a Smart Mirror with Spare Parts",
    "What I Learned From 365 Days of Daily Vlogging",
    "The Physics of a Perfect Cup of Coffee",
    "Inside a 100-Year-Old Repair Shop",
    "I Recreated a Movie Scene with $50",
    "The Quiet Rise of Analog Photography",
    "How Algorithms Decide What You See",
    "I Tried Working in Complete Silence",
    "The Best Budget Microphone in 2026",
    "Why Small Channels Are Winning",
]

YT_TAGS = [
    ["tech", "diy", "ai"], ["creator", "youtube", "growth"], ["review", "tools", "productivity"],
    ["camera", "filmmaking", "gear"], ["smart home", "raspberry pi", "automation"],
    ["tutorial", "lighting", "cinematography"], ["experiment", "ai", "story"], ["vlog", "lifestyle"],
]

BILI_COMMENTS = [
    "这也太强了吧，收藏了慢慢看", "前排！制作质量越来越高", "看完立刻去翻工具箱",
    "求一个详细教程，跪谢", "这期节奏有点慢，但内容很扎实", "BGM 叫什么名字？",
    "三连了，希望多更这种", "标题有点夸张，内容其实一般", "看到最后竟然有点感动",
    "建议下次把参数表放简介", "这个思路真的没想到", "已经照着做了，成功了！",
    "画质和声音都很舒服", "更新频率能不能稳定一点", "讲得太快了吧，暂停了好几次",
    "这才是我想看的科技区", "有没有同款链接？", "从首页推荐来的，关注了",
    "说实话有点水", "细节拉满，必须支持", "这个系列什么时候出下一期",
    "看完感觉学到了很多", "能不能出一期避坑版", "这个选题太懂了",
]

YT_COMMENTS = [
    "The production quality is insane!", "Came from the algorithm, stayed for the story.",
    "Could you share the full build guide?", "This deserves way more views.",
    "I tried this and it actually worked.", "The pacing in the middle felt a bit slow.",
    "Best explanation I've seen so far.", "What camera are you using?",
    "Subscribed — excited for the next one.", "The thumbnail got me, the content kept me.",
    "Please make a part two!", "There is a small mistake at 4:32.",
    "This is criminally underrated.", "I disagree with the conclusion, but great video.",
    "The editing is so clean.", "Watching this at 2am was a mistake.",
]

SENTIMENT_POS = ["强", "喜欢", "舒服", "感动", "支持", "学到", "成功", "拉满", "收藏", "关注", "厉害", "赞"]
SENTIMENT_NEG = ["水", "一般", "慢", "夸张", "错", " disagree", "mistake", "slow", "wrong", "hate"]


def _sentiment(text: str) -> float:
    score = 0.0
    for word in SENTIMENT_POS:
        if word in text:
            score += 0.35
    for word in SENTIMENT_NEG:
        if word in text.lower():
            score -= 0.45
    return max(-1.0, min(1.0, score))


def _weekday_factor(dt: datetime) -> float:
    return [0.86, 0.94, 1.0, 1.02, 1.10, 1.18, 1.06][dt.weekday()]


def _pick_publish_time(rng: random.Random, platform: str, day: datetime) -> datetime:
    if platform == "bilibili":
        slots = [(19, 0.22), (20, 0.20), (21, 0.16), (18, 0.12), (12, 0.10),
                 (22, 0.08), (17, 0.05), (10, 0.04), (15, 0.03)]
    else:
        slots = [(17, 0.20), (18, 0.18), (16, 0.14), (20, 0.13), (15, 0.10),
                 (14, 0.08), (21, 0.07), (12, 0.06), (11, 0.04)]
    r = rng.random()
    acc = 0.0
    hour = slots[0][0]
    for h, p in slots:
        acc += p
        if r <= acc:
            hour = h
            break
    return day.replace(hour=hour, minute=rng.choice([0, 5, 10, 15, 20, 30, 40, 45]), second=0)


def _make_titles(rng: random.Random, platform: str, count: int) -> list[dict]:
    pool = BILI_TITLES if platform == "bilibili" else YT_TITLES
    items = []
    for i in range(count):
        base = pool[i % len(pool)]
        title = base
        if i >= len(pool):
            suffix = rng.choice(["（实战篇）", "｜复盘", " · 下集", " [2026]", "（完整版）"])
            title = base + suffix
        tags = rng.choice(BILI_TAGS if platform == "bilibili" else YT_TAGS).copy()
        if rng.random() < 0.3:
            extra = "教程" if platform == "bilibili" else "tutorial"
            if extra not in tags:
                tags.append(extra)
        category = tags[0]
        duration = int(rng.choice([
            rng.randint(35, 70), rng.randint(70, 180), rng.randint(180, 300),
            rng.randint(300, 600), rng.randint(600, 1200), rng.randint(1200, 1800),
        ]))
        items.append({"title": title, "tags": tags, "category": category, "duration": duration})
    return items


def _curve(d: int, half_life: float) -> float:
    return 0.34 * math.exp(-d / max(1.0, half_life * 0.42)) + 0.12 * math.exp(-d / 18.0) + 0.012 * math.exp(-d / 160.0)


def seed_demo(store: Store, force: bool = False) -> list[int]:
    existing = [a for a in store.list_accounts() if a["platform"] == "bilibili" and a["is_demo"]]
    if existing and not force:
        return [a["id"] for a in store.list_accounts() if a["is_demo"]]

    rng = random.Random(20261102)
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    account_ids: list[int] = []

    configs = [
        {
            "platform": "bilibili", "uid": "88481234", "name": "星野研究所", "avatar": "",
            "followers0": 112600, "views0": 14840000, "likes0": 782000, "coins0": 146000,
            "favorites0": 244000, "comments0": 49000, "shares0": 41000, "danmaku0": 138000,
            "videos": 74, "days": 180, "viral_rate": 0.09, "base_peak": 18500,
            "conv": 0.00125, "color": "#fb7299",
        },
        {
            "platform": "youtube", "uid": "UCnova_lab_demo", "name": "Nova Lab", "avatar": "",
            "followers0": 70600, "views0": 9420000, "likes0": 512000, "coins0": 0,
            "favorites0": 128000, "comments0": 38600, "shares0": 54000, "danmaku0": 0,
            "videos": 48, "days": 170, "viral_rate": 0.11, "base_peak": 22500,
            "conv": 0.00105, "color": "#ff4d4d",
        },
    ]

    for cfg in configs:
        platform = cfg["platform"]
        is_bili = platform == "bilibili"
        account_id = store.create_account(
            platform=platform,
            uid=cfg["uid"],
            name=cfg["name"],
            avatar=cfg["avatar"],
            meta={
                "signature": "把复杂的世界，讲成看得懂的故事。" if is_bili else "Making complex things simple.",
                "level": 6 if is_bili else "",
                "demo": True,
                "color": cfg["color"],
            },
            followers=cfg["followers0"],
            total_views=cfg["views0"],
            is_demo=True,
        )
        account_ids.append(account_id)
        meta = _make_titles(rng, platform, cfg["videos"])
        videos = []
        for i, item in enumerate(meta):
            if i < 8:
                days_ago = rng.randint(8, 16)
            else:
                days_ago = int(7 + (cfg["days"] - 12) * (1 - (i - 8) / max(1, cfg["videos"] - 9)) ** 1.12)
                days_ago += rng.randint(-3, 3)
            days_ago = max(2, min(cfg["days"] - 1, days_ago))
            publish_day = today - timedelta(days=days_ago)
            published = _pick_publish_time(rng, platform, publish_day)
            viral = rng.random() < cfg["viral_rate"]
            peak = cfg["base_peak"] * rng.lognormvariate(0, 0.55)
            if viral:
                peak *= rng.uniform(4.2, 10.5)
            if item["duration"] < 90:
                peak *= 1.35
            elif item["duration"] > 900:
                peak *= 0.68
            if any(ch.isdigit() for ch in item["title"]):
                peak *= 1.10
            peak = max(1800, peak)
            video = {
                "vid": (f"BV1{rng.choice('abcdefghjkmnpqrstuvwxyz')}{rng.randint(1000000, 9999999)}" if is_bili
                        else f"yt_{i:03d}_{rng.randint(10000, 99999)}"),
                "aid": str(rng.randint(100000000, 999999999)) if is_bili else "",
                "title": item["title"],
                "cover": "",
                "url": (f"https://www.bilibili.com/video/BV1{rng.choice('abcdefghjkmnpqrstuvwxyz')}{rng.randint(1000000, 9999999)}"
                        if is_bili else f"https://youtu.be/demo{i:03d}"),
                "published_at": published.isoformat(timespec="seconds"),
                "duration": item["duration"],
                "category": item["category"],
                "tags": item["tags"],
                "description": item["title"] + ("  #科技 #创作" if is_bili else " #creator #tech"),
                "stats": {},
            }
            videos.append({
                "meta": video, "peak": peak, "age": days_ago, "viral": viral,
                "base_peak": peak, "conv": cfg["conv"] * rng.uniform(0.65, 1.35),
                "engage": rng.uniform(0.7, 1.3),
            })

        # Lifetime daily gains, used both for per-video snapshots and account aggregates.
        start = (today - timedelta(days=cfg["days"] - 1)).date()
        totals = {
            "views": 0, "likes": 0, "coins": 0, "favorites": 0, "comments": 0,
            "shares": 0, "danmaku": 0, "watch_minutes": 0.0, "impressions": 0,
        }
        cumulative: dict[int, dict] = {}
        daily = {start + timedelta(days=d): {
            "views": 0, "likes": 0, "coins": 0, "favorites": 0, "comments": 0,
            "shares": 0, "danmaku": 0, "watch_minutes": 0.0, "gained": 0,
            "impressions": 0, "lost": 0,
        } for d in range(cfg["days"])}
        video_rows = []
        for idx, v in enumerate(videos):
            meta_v = v["meta"]
            video_id = store.upsert_video(account_id, meta_v)
            video_rows.append((video_id, v))
            published = datetime.fromisoformat(meta_v["published_at"])
            cum = {k: 0 for k in ("views", "likes", "coins", "favorites", "comments", "shares", "danmaku")}
            cum["watch_minutes"] = 0.0
            cum["impressions"] = 0
            half_life = 3.2 if v["viral"] else rng.uniform(2.2, 5.6)
            total_views = 0
            for d in range((today.date() - published.date()).days + 1):
                dt = published.date() + timedelta(days=d)
                if dt not in daily:
                    continue
                if d == 0:
                    frac = 0.55
                else:
                    frac = 1.0
                gain = v["peak"] * _curve(d, half_life) * frac
                gain *= _weekday_factor(datetime.combine(dt, datetime.min.time())) * rng.uniform(0.82, 1.22)
                if d > 45 and rng.random() < 0.035:
                    gain *= rng.uniform(2.0, 6.0)  # evergreen resurgence
                gain = int(max(0, gain))
                total_views += gain
                rates = {
                    "likes": rng.uniform(0.034, 0.062) * v["engage"],
                    "coins": (rng.uniform(0.008, 0.026) if is_bili else 0) * v["engage"],
                    "favorites": rng.uniform(0.010, 0.032) * v["engage"],
                    "comments": rng.uniform(0.0020, 0.0065) * v["engage"],
                    "shares": rng.uniform(0.0015, 0.0050) * v["engage"],
                    "danmaku": (rng.uniform(0.005, 0.014) if is_bili else 0) * v["engage"],
                }
                row = daily[dt]
                row["views"] += gain
                for key, rate in rates.items():
                    inc = int(gain * rate)
                    cum[key] += inc
                    row[key] += inc
                    totals[key] += inc
                avg_dur = min(meta_v["duration"] * rng.uniform(0.32, 0.66), meta_v["duration"])
                watch_min = gain * avg_dur / 60.0
                cum["watch_minutes"] += watch_min
                row["watch_minutes"] += watch_min
                totals["watch_minutes"] += watch_min
                ctr = rng.uniform(0.045, 0.105) if not is_bili else rng.uniform(0.06, 0.13)
                impressions = int(gain / ctr) if gain > 0 else 0
                cum["impressions"] += impressions
                row["impressions"] += impressions
                totals["impressions"] += impressions
                gained = int(gain * v["conv"] * rng.uniform(0.55, 1.45))
                row["gained"] += gained
                totals["views"] += gain
            cum["views"] = total_views
            stats = {
                "views": total_views,
                "likes": cum["likes"], "coins": cum["coins"], "favorites": cum["favorites"],
                "comments": cum["comments"], "shares": cum["shares"], "danmaku": cum["danmaku"],
                "watch_minutes": round(cum["watch_minutes"], 1),
                "impressions": cum["impressions"],
                "ctr": round(100 * total_views / cum["impressions"], 2) if cum["impressions"] else 0,
                "followers_gained": int(total_views * v["conv"]),
            }
            meta_v["stats"] = stats
            store.upsert_video(account_id, meta_v)
            cum["watch_minutes"] = round(cum["watch_minutes"], 1)
            cumulative[idx] = cum

            # snapshot only the recent window, enough for period comparisons and detail charts
            snap_start = max(published.date(), today.date() - timedelta(days=120))
            running = {k: 0 for k in ("views", "likes", "coins", "favorites", "comments", "shares", "danmaku")}
            running["watch_minutes"] = 0.0
            running["impressions"] = 0
            skip_days = max(0, (snap_start - published.date()).days)
            if skip_days:
                for d in range(skip_days):
                    dt = published.date() + timedelta(days=d)
                    frac = 0.55 if d == 0 else 1.0
                    g = int(v["peak"] * _curve(d, half_life) * frac)
                    running["views"] += g
                    for key in ("likes", "coins", "favorites", "comments", "shares", "danmaku"):
                        running[key] += int(g * (stats.get(key, 0) / max(1, stats["views"])))
                    running["watch_minutes"] += g * min(meta_v["duration"] * 0.5, meta_v["duration"]) / 60
                    running["impressions"] += int(g / 0.08)
            snap_rows = []
            for offset in range((today.date() - snap_start).days + 1):
                dt = snap_start + timedelta(days=offset)
                row = daily.get(dt)
                if not row:
                    continue
                d = (dt - published.date()).days
                frac = 0.55 if d == 0 else 1.0
                g = int(v["peak"] * _curve(d, half_life) * frac *
                        _weekday_factor(datetime.combine(dt, datetime.min.time())))
                # snapshot uses the account-level actual proportion only for shape; totals stay close
                if d >= 0:
                    running["views"] += g
                    for key in ("likes", "coins", "favorites", "comments", "shares", "danmaku"):
                        running[key] += int(g * (stats.get(key, 0) / max(1, stats["views"])))
                    running["watch_minutes"] += g * min(meta_v["duration"] * 0.5, meta_v["duration"]) / 60
                    running["impressions"] += int(g / 0.08)
                snap_rows.append((dt.strftime("%Y-%m-%d"), {
                    **running,
                    "watch_minutes": round(running["watch_minutes"], 1),
                    "followers_gained": int(g * v["conv"]) if d >= 0 else 0,
                }))
            store.save_video_snapshots(video_id, snap_rows)

            # retention curve
            base3 = (rng.gauss(0.68, 0.075) if not is_bili else rng.gauss(0.645, 0.085))
            base3 = max(0.44, min(0.84, base3))
            if meta_v["duration"] > 900:
                base3 -= 0.07
            elif meta_v["duration"] < 90:
                base3 += 0.025
            if v["viral"]:
                base3 += 0.03
            points = []
            for j in range(31):
                t = j / 30.0
                if is_bili:
                    retain = 0.94 - (1 - base3) * (1 - math.exp(-t / 0.055)) - 0.30 * (t ** 1.35)
                else:
                    retain = 1.0 - (1 - base3) * (1 - math.exp(-t / 0.028)) - 0.34 * (t ** 1.2)
                retain = max(0.06, min(1.0, retain + rng.uniform(-0.006, 0.006)))
                points.append({
                    "point": round(t, 4),
                    "audience_ratio": round(retain, 5),
                    "relative_ratio": round(retain / max(0.01, base3), 4),
                })
            store.replace_retention(video_id, points, "model" if is_bili else "platform")

            if idx < 74:
                pool = BILI_COMMENTS if is_bili else YT_COMMENTS
                comments = []
                for _ in range(rng.randint(6, 12)):
                    text = rng.choice(pool)
                    comments.append({
                        "author": ("用户" + str(rng.randint(1000, 9999))) if is_bili else ("@user" + str(rng.randint(100, 9999))),
                        "content": text,
                        "likes": int(rng.randint(0, 400) * (1.5 if v["viral"] else 1)),
                        "sentiment": _sentiment(text),
                        "created_at": (published + timedelta(days=rng.randint(0, 20))).isoformat(timespec="seconds"),
                    })
                store.save_comments(video_id, comments)

        # aggregate daily + cumulative account snapshots
        followers = cfg["followers0"]
        total_views = cfg["views0"]
        totals_l = {k: v for k, v in totals.items()}
        for d in range(cfg["days"]):
            day = start + timedelta(days=d)
            row = daily[day]
            gained = int(row["gained"] * rng.uniform(0.85, 1.18))
            lost = int(gained * rng.uniform(0.18, 0.36)) + rng.randint(0, 8)
            followers += gained - lost
            total_views += row["views"]
            store.save_daily_metric(account_id, day.strftime("%Y-%m-%d"), {
                "views": row["views"], "watch_minutes": round(row["watch_minutes"], 1),
                "followers_gained": gained, "followers_lost": lost,
                "likes": row["likes"], "coins": row["coins"], "favorites": row["favorites"],
                "comments": row["comments"], "shares": row["shares"], "danmaku": row["danmaku"],
                "impressions": row["impressions"],
                "ctr": round(100 * row["views"] / row["impressions"], 2) if row["impressions"] else 0,
                "avg_view_duration": round(row["watch_minutes"] * 60 / row["views"], 1) if row["views"] else 0,
                "avg_view_pct": round(100 * row["watch_minutes"] * 60 / row["views"] / 420, 2) if row["views"] else 0,
            })
            store.save_account_snapshot(account_id, day.strftime("%Y-%m-%d"), {
                "followers": followers, "total_views": total_views,
                "likes": cfg["likes0"] + totals_l["likes"], "coins": cfg["coins0"] + totals_l["coins"],
                "favorites": cfg["favorites0"] + totals_l["favorites"],
                "comments": cfg["comments0"] + totals_l["comments"],
                "shares": cfg["shares0"] + totals_l["shares"],
                "danmaku": cfg["danmaku0"] + totals_l["danmaku"],
                "watch_minutes": round(totals_l["watch_minutes"] * (d + 1) / cfg["days"], 1),
                "impressions": int(totals_l["impressions"] * (d + 1) / cfg["days"]),
            })

        # Sync per-video current stats to the exact account totals (demo consistency)
        store.update_account(account_id, followers=followers, total_views=total_views, last_sync=now_iso())

        period_end = today.strftime("%Y-%m-%d")
        if is_bili:
            sources = [
                ("推荐信息流", 0.461), ("相关推荐", 0.213), ("搜索", 0.128),
                ("动态", 0.081), ("个人空间", 0.064), ("站外", 0.053),
            ]
            province = [("广东", 0.174), ("江苏", 0.123), ("浙江", 0.117), ("上海", 0.098),
                        ("北京", 0.091), ("山东", 0.073), ("四川", 0.064), ("湖北", 0.052),
                        ("河南", 0.047), ("福建", 0.041), ("湖南", 0.035), ("陕西", 0.030)]
            traffic_total = int(sum(r["views"] for r in daily.values()) * 0.92)
            store.replace_traffic_sources(account_id, period_end, [
                {"source": s, "views": int(traffic_total * p), "watch_minutes": int(traffic_total * p * 1.7)}
                for s, p in sources
            ])
            store.replace_demographics(account_id, period_end, [
                *({"dimension": "province", "bucket": k, "value": int(followers * 0.34 * p)} for k, p in province),
                {"dimension": "age", "bucket": "18-24", "value": 0.41},
                {"dimension": "age", "bucket": "25-30", "value": 0.32},
                {"dimension": "age", "bucket": "31-40", "value": 0.18},
                {"dimension": "age", "bucket": "18以下", "value": 0.06},
                {"dimension": "age", "bucket": "40以上", "value": 0.03},
                {"dimension": "gender", "bucket": "男", "value": 0.78},
                {"dimension": "gender", "bucket": "女", "value": 0.22},
                {"dimension": "device", "bucket": "安卓", "value": 0.51},
                {"dimension": "device", "bucket": "iOS", "value": 0.29},
                {"dimension": "device", "bucket": "PC网页", "value": 0.15},
                {"dimension": "device", "bucket": "其他", "value": 0.05},
            ])
        else:
            sources = [
                ("浏览功能", 0.312), ("推荐视频", 0.246), ("YouTube 搜索", 0.183),
                ("外部链接", 0.094), ("播放列表", 0.071), ("通知", 0.052), ("其他", 0.042),
            ]
            countries = [("美国", 0.286), ("英国", 0.121), ("加拿大", 0.097), ("德国", 0.089),
                         ("澳大利亚", 0.074), ("印度", 0.068), ("荷兰", 0.053), ("法国", 0.047),
                         ("日本", 0.041), ("巴西", 0.036)]
            traffic_total = int(sum(r["views"] for r in daily.values()) * 0.94)
            store.replace_traffic_sources(account_id, period_end, [
                {"source": s, "views": int(traffic_total * p),
                 "watch_minutes": int(traffic_total * p * (3.4 if "搜索" in s else 2.6))}
                for s, p in sources
            ])
            store.replace_demographics(account_id, period_end, [
                *({"dimension": "country", "bucket": k, "value": int(followers * 0.7 * p)} for k, p in countries),
                {"dimension": "age", "bucket": "18-24", "value": 0.24},
                {"dimension": "age", "bucket": "25-34", "value": 0.39},
                {"dimension": "age", "bucket": "35-44", "value": 0.22},
                {"dimension": "age", "bucket": "45-54", "value": 0.10},
                {"dimension": "age", "bucket": "55+", "value": 0.05},
                {"dimension": "gender", "bucket": "男", "value": 0.71},
                {"dimension": "gender", "bucket": "女", "value": 0.27},
                {"dimension": "gender", "bucket": "其他", "value": 0.02},
                {"dimension": "device", "bucket": "手机", "value": 0.63},
                {"dimension": "device", "bucket": "电脑", "value": 0.24},
                {"dimension": "device", "bucket": "电视", "value": 0.09},
                {"dimension": "device", "bucket": "平板", "value": 0.04},
            ])
    return account_ids
