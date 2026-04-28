import os
import json
import pathlib
import textwrap
from datetime import datetime, timedelta
from email.utils import format_datetime

import pytz
from dateutil import tz
from feedgen.feed import FeedGenerator
import arxiv


# ---------------------- 配置区（可按需改动） ----------------------
TIMEZONE = os.getenv("TZ", "Asia/Shanghai")
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", 36))
MAX_RESULTS = int(os.getenv("ARXIV_MAX_RESULTS", 30))
MAX_ITEMS_PER_RUN = int(os.getenv("MAX_ITEMS_PER_RUN", 20))
MIN_RELEVANCE_SCORE = int(os.getenv("MIN_RELEVANCE_SCORE", 7))

# Phase 2.1 — 扩展检索类别
CATEGORIES = [
    "physics.ao-ph",   # Atmospheric and Oceanic Physics
    "physics.geo-ph",  # Geophysics
    "cs.LG",           # Machine Learning
    "cs.AI",           # Artificial Intelligence
    "stat.ML",         # Machine Learning statistics
]

# Phase 2.2 — 分层关键词
DOMAIN_TERMS = [
    "weather", "climate", "atmosphere", "ocean", "earth system",
    "precipitation", "temperature", "wind", "sst", "sea surface temperature",
    "enso", "mjo", "monsoon", "typhoon", "cyclone", "teleconnection",
    "subseasonal", "seasonal", "s2s",
]

AI_TERMS = [
    "machine learning", "deep learning", "artificial intelligence", "ai",
    "neural network", "transformer", "diffusion", "foundation model",
    "neural operator", "graph neural network", "emulator", "surrogate",
]

FORECAST_TERMS = [
    "forecast", "forecasting", "prediction", "predict", "nowcasting", "hindcast",
    "data assimilation", "downscaling", "reanalysis",
]

MODEL_NAMES = [
    "graphcast", "panguweather", "pangu-weather", "fengwu", "fourcastnet",
    "aurora", "neuralgcm", "climax", "fuxi", "swinrnn", "weathergfm",
]

BLACKLIST_TERMS = ["quantum field", "string theory"]

RSS_CHANNEL = {
    "title": "arXiv · 气象 × AI 精选论文",
    "link": "https://example.github.io/arxiv-meteo-ai-rss/",
    "description": "每日10:00自动更新 · 气象与AI交叉最新论文与要点",
}
OUTPUT_PATH = pathlib.Path("docs/index.xml")
STATE_PATH = pathlib.Path("state/state.json")

# ---------------------- 工具函数 ----------------------

def ensure_state():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        STATE_PATH.write_text(json.dumps({"seen_ids": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# Phase 2.3 — 宽松 query，后处理用 relevance_score 严格筛选
def build_query():
    cat_expr = " OR ".join([f"cat:{c}" for c in CATEGORIES])
    broad_terms = sorted(set(DOMAIN_TERMS + FORECAST_TERMS + MODEL_NAMES))
    kw_expr = " OR ".join([f'ti:"{k}" OR abs:"{k}"' for k in broad_terms])
    return f"({cat_expr}) AND ({kw_expr})"


def fetch_arxiv():
    query = build_query()
    client = arxiv.Client(page_size=5, delay_seconds=5, num_retries=5)
    search = arxiv.Search(
        query=query,
        max_results=MAX_RESULTS,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    for r in client.results(search):
        yield {
            "id": r.get_short_id(),
            "title": r.title.strip(),
            "summary": r.summary.strip(),
            "authors": [a.name for a in r.authors],
            "updated": r.updated,
            "published": r.published,
            "link": r.entry_id,
        }


def within_lookback(item, hours=LOOKBACK_HOURS, tzname=TIMEZONE):
    local = pytz.timezone(tzname)
    now = datetime.now(local)
    threshold = now - timedelta(hours=hours)
    ts = item["updated"] or item["published"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz.UTC)
    return ts >= threshold


# Phase 3.1 — 相关性评分
def relevance_score(item):
    text = (item["title"] + " " + item["summary"]).lower()

    if any(b.lower() in text for b in BLACKLIST_TERMS):
        return 0

    domain_hit = sum(1 for t in DOMAIN_TERMS if t.lower() in text)
    ai_hit = sum(1 for t in AI_TERMS if t.lower() in text)
    forecast_hit = sum(1 for t in FORECAST_TERMS if t.lower() in text)
    model_hit = sum(1 for t in MODEL_NAMES if t.lower() in text)

    score = 0
    score += 3 * min(model_hit, 2)
    score += 2 * min(domain_hit, 3)
    score += 2 * min(ai_hit, 3)
    score += 2 * min(forecast_hit, 3)

    if domain_hit and ai_hit:
        score += 3
    if domain_hit and forecast_hit:
        score += 2
    if domain_hit and ai_hit and forecast_hit:
        score += 4

    return score


# Phase 3.3 — 主题分类
def classify_topic(item):
    text = (item["title"] + " " + item["summary"]).lower()

    if any(x in text for x in ["ocean", "sst", "sea surface temperature", "marine"]):
        return "AI海洋/海气预报"
    if any(x in text for x in ["weather", "atmosphere", "precipitation", "wind", "typhoon", "cyclone"]):
        return "AI天气预报"
    if any(x in text for x in ["climate", "earth system", "seasonal", "subseasonal", "s2s"]):
        return "AI气候/地球系统预测"
    if "data assimilation" in text or "assimilation" in text:
        return "资料同化/融合"
    return "相关AI方法"


# Phase 3.2 — topic_ok 基于 MIN_RELEVANCE_SCORE
def topic_ok(item):
    return relevance_score(item) >= MIN_RELEVANCE_SCORE


def summarize(title, abstract):
    # 优先走 DeepSeek，如无密钥则使用回退规则式摘要
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
            prompt = f"""
你是"气象×AI"论文解读者。请基于以下标题与摘要，输出：
1) 80–150字中文精炼摘要；
2) 3–5条要点（方法/数据/结论/局限）；
3) 关键词：3–5个。
务必中立、基于文本，不要杜撰。
标题：{title}
摘要：{abstract[:5000]}
"""
            chat = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=600,
            )
            return chat.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error calling DeepSeek API: {e}")
            pass
    # 回退：提取摘要的前2~3句
    sents = abstract.replace("\n", " ").split(". ")
    head = ". ".join(sents[:3])[:600]
    bullets = []
    low = abstract.lower()
    if "dataset" in low or "era5" in low or "reanalysis" in low:
        bullets.append("数据：包含再分析/卫星/观测等来源。")
    if "model" in low or "neural" in low or "transformer" in low:
        bullets.append("方法：采用机器学习/深度学习模型。")
    if "downscal" in low or "forecast" in low or "nowcast" in low:
        bullets.append("任务：降尺度/预报/临近预测等应用场景。")
    if not bullets:
        bullets = ["摘要未提供更多细节，建议阅读原文。"]
    return f"{head}\n\n要点：\n- " + "\n- ".join(bullets)


def to_rfc822(dt_obj):
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=tz.UTC)
    return format_datetime(dt_obj)


def build_rss(channel, items):
    fg = FeedGenerator()
    fg.title(channel["title"])
    fg.link(href=channel["link"], rel='alternate')
    fg.description(channel["description"])
    fg.language('zh-CN')

    for it in items:
        fe = fg.add_entry()
        fe.id(it["guid"])
        fe.title(it["title"])
        fe.link(href=it["link"])
        fe.pubDate(to_rfc822(it["pubDate"]))
        authors = ", ".join(it["authors"][:8])
        desc_html = f"<p><b>Authors:</b> {authors}</p><p>{it['summary_html']}</p>"
        fe.description(desc_html)

    return fg.rss_str(pretty=True)


def main():
    state = ensure_state()
    seen = set(state.get("seen_ids", []))

    # 拉取 & 过滤（topic_ok 现在基于 relevance_score）
    papers = [p for p in fetch_arxiv() if within_lookback(p) and topic_ok(p)]
    fresh = [p for p in papers if p["id"] not in seen]
    fresh = fresh[:MAX_ITEMS_PER_RUN]

    # 生成条目
    items = []
    for p in fresh:
        summ = summarize(p["title"], p["summary"]).replace("\n", "<br/>")
        items.append({
            "guid": p["id"],
            "title": p["title"],
            "link": p["link"],
            "authors": p["authors"],
            "pubDate": p["updated"] or p["published"],
            "summary_html": summ,
        })

    # 读取历史 RSS（若需保留历史，可在此合并旧条；此处简单用"只生成当日条目"也足够）
    rss_bytes = build_rss(RSS_CHANNEL, items)

    # 写出 RSS
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(rss_bytes)

    # 更新 state（保留上限）
    state["seen_ids"] = list((seen | {p["id"] for p in fresh}))[-5000:]
    save_state(state)

    print(f"Generated {len(items)} items → {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
