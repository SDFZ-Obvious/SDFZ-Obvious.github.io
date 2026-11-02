"""中文/英文文本处理：分词、关键词、情感与观众诉求识别（无需联网的词典方法）。"""
import re
from collections import Counter

try:
    import jieba
    jieba.setLogLevel(60)
    _HAS_JIEBA = True
except ImportError:  # pragma: no cover
    _HAS_JIEBA = False

STOPWORDS = set("""
的 了 是 我 你 他 她 它 们 这 那 个 在 有 和 与 就 都 也 还 吗 吧 啊 呢 哦 嗯 呀 么 什么 怎么 一个 一下
没有 不是 可以 真的 还是 就是 这个 那个 自己 我们 你们 他们 看 说 到 会 要 能 去 来 上 下 把 被 给 让
很 太 更 最 又 再 才 啦 哈 哈哈 hhh hhhh 不 没 好 对 比 但 而 或 及 等 第 之 其 中 为 从 以 于 着 过
有人 有点 第一 up up主 主太 已阅 来了 一期 视频 这期 出来 觉得 感觉 知道 现在 已经 时候 因为 所以
the a an and or of to in on for is are was it this that with you i my your be at as by from
""".split())

POSITIVE = ["好", "棒", "赞", "喜欢", "爱", "支持", "感谢", "谢谢", "清楚", "实用", "干货", "良心", "优秀", "厉害",
            "牛", "三连", "收藏", "学到", "舒服", "精彩", "期待", "关注", "有用", "nice", "great", "love", "awesome",
            "helpful", "thanks", "amazing", "good", "best", "cool"]
NEGATIVE = ["差", "烂", "垃圾", "无聊", "拖", "广告", "标题党", "错别字", "糊", "失望", "难看", "声音小", "吵", "水视频",
            "快进", "尬", "看不懂", "bad", "boring", "worst", "clickbait", "hate", "annoying", "wrong"]
NEGATORS = ["不", "没", "别", "not", "no", "don't"]
REQUEST_PAT = re.compile(r"(求|能不能|可以.{0,6}吗|希望|出一期|下期|续集|催更|教程|请问|怎么|如何|\?|？|please|could you|next video|tutorial|how to)", re.I)
STRONG_REQUEST_PAT = re.compile(r"(求|能不能|可以.{0,6}吗|出一期|下期|续集|请问|\?|？|could you|please)", re.I)


def tokenize(text: str) -> list[str]:
    text = re.sub(r"\[.*?\]|https?://\S+|@\S+", " ", str(text))
    if _HAS_JIEBA:
        words = jieba.lcut(text)
    else:
        words = re.findall(r"[A-Za-z]+|[一-鿿]{2,4}|\d+", text)
    out = []
    for w in words:
        w = w.strip().lower()
        if len(w) < 2 or w in STOPWORDS or w.isdigit() or not re.search(r"[\w一-鿿]", w):
            continue
        out.append(w)
    return out


def keywords(texts, top=20):
    c = Counter()
    for t in texts:
        c.update(set(tokenize(t)))
    return c.most_common(top)


def sentiment(text: str) -> float:
    """返回 -1~1 的情感分。"""
    t = str(text).lower()
    score = 0
    for w in POSITIVE:
        for m in re.finditer(re.escape(w), t):
            neg = any(t[max(0, m.start() - 3):m.start()].endswith(n) for n in NEGATORS)
            score += -1 if neg else 1
    for w in NEGATIVE:
        if w in t:
            score -= 1
    return max(-1.0, min(1.0, score / 2))


def is_request(text: str) -> bool:
    return bool(REQUEST_PAT.search(str(text)))


def request_strength(text: str) -> int:
    """越像具体的提问/选题需求，分数越高（用于排序）。"""
    return len(STRONG_REQUEST_PAT.findall(str(text))) * 2 + len(REQUEST_PAT.findall(str(text)))


def title_features(title: str) -> dict:
    t = str(title)
    return {
        "含数字": bool(re.search(r"\d", t)),
        "含问句": bool(re.search(r"[?？]|为什么|如何|怎么|吗", t)),
        "含感叹": bool(re.search(r"[!！]", t)),
        "含【】括号": bool(re.search(r"[【】\[\]]", t)),
        "含年份/最新": bool(re.search(r"20\d\d|最新", t)),
        "含教程类词": bool(re.search(r"教程|攻略|入门|技巧|干货|指南|tutorial|guide|how to", t, re.I)),
        "含情绪词": bool(re.search(r"太|竟然|居然|震惊|绝了|离谱|翻车|后悔|终于", t)),
    }
