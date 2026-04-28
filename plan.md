# AIxWeather_Paper_Daily 改造计划

## 目标

将当前项目从“气象 × AI arXiv RSS 自动抓取”升级为“AI 地球系统预报论文日报”。

最终应实现：

1. GitHub Actions 每天自动运行。
2. 从 arXiv 检索 AI 天气、气候、海洋、地球系统预报相关论文。
3. 对论文进行更严格的主题筛选，减少误报。
4. 输出 RSS：`docs/index.xml`。
5. 输出 Markdown 日报：
   - `docs/latest.md`
   - `docs/daily/YYYY-MM-DD.md`
6. 使用 state 文件避免重复推送。
7. README 与 workflow、脚本配置保持一致。
8. 可以在 GitHub Pages 和 RSS 阅读器中使用。

---

## 当前项目状态

当前仓库已有基础能力：

- `.github/workflows/build-rss.yml` 已配置每日 `02:00 UTC` 自动运行，即北京时间/新加坡时间 10:00。
- workflow 已支持 `workflow_dispatch` 手动触发。
- workflow 已授予 `contents: write`，可以自动提交生成文件。
- `scripts/arxiv_meteo_ai_rss.py` 已包含：
  - arXiv 检索；
  - lookback 时间窗口；
  - blacklist；
  - DeepSeek 摘要；
  - RSS 构建；
  - `state/state.json` 去重。
- `requirements.txt` 已包含 `arxiv`、`feedgen`、`python-dateutil`、`pytz`。

当前需要优化的地方：

1. README 仍偏模板化，订阅地址还是 `arxiv-meteo-ai-rss`。
2. workflow 只提交 `docs/index.xml` 和 `state/state.json`，还没有提交 Markdown 日报。
3. workflow 没有语法检查步骤。
4. workflow 中只传入 `DEEPSEEK_API_KEY`，README 中却写的是 `OPENAI_API_KEY`，需要统一。
5. 检索范围目前偏“气象 × AI”，需要扩展到“AI 地球系统预报”。
6. 脚本只有 RSS 输出，没有 `docs/latest.md` 和 `docs/daily/YYYY-MM-DD.md`。
7. `RSS_CHANNEL['link']` 仍是 example 地址，需要改成真实 GitHub Pages 地址。

---

## 推荐分支策略

新建开发分支：

```bash
git checkout -b feature/daily-report
```

每完成一个阶段就提交一次，便于回滚：

```bash
git add .
git commit -m "feat: improve arxiv query for earth system forecasting"
```

---

## Phase 1：先保证当前项目可运行

### 1.1 本地安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 1.2 检查脚本语法

```bash
python -m py_compile scripts/arxiv_meteo_ai_rss.py
```

### 1.3 手动运行脚本

```bash
TZ=Asia/Shanghai \
LOOKBACK_HOURS=72 \
ARXIV_MAX_RESULTS=120 \
MAX_ITEMS_PER_RUN=20 \
python scripts/arxiv_meteo_ai_rss.py
```

### 1.4 检查输出

```bash
ls docs
ls state
```

预期至少生成：

```text
docs/index.xml
state/state.json
```

---

## Phase 2：优化 arXiv 检索范围

编辑：

```text
scripts/arxiv_meteo_ai_rss.py
```

### 2.1 替换 CATEGORIES

将当前类别扩展为：

```python
CATEGORIES = [
    "physics.ao-ph",   # Atmospheric and Oceanic Physics
    "physics.geo-ph", # Geophysics
    "cs.LG",          # Machine Learning
    "cs.AI",          # Artificial Intelligence
    "stat.ML",        # Machine Learning statistics
]
```

### 2.2 将关键词拆成分层列表

新增或替换为：

```python
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
```

### 2.3 保留一个宽松 query，后处理严格筛选

建议 `build_query()` 不要写得太窄，否则 arXiv API 层面会漏掉论文。

```python
def build_query():
    cat_expr = " OR ".join([f"cat:{c}" for c in CATEGORIES])
    broad_terms = sorted(set(DOMAIN_TERMS + FORECAST_TERMS + MODEL_NAMES))
    kw_expr = " OR ".join([f'ti:"{k}" OR abs:"{k}"' for k in broad_terms])
    return f"({cat_expr}) AND ({kw_expr})"
```

注意：如果 arXiv query 对引号支持不稳定，可以退回到不加引号的写法，但要优先测试。

---

## Phase 3：新增相关性评分与分类

### 3.1 新增 relevance_score

在 `topic_ok()` 附近添加：

```python
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
```

### 3.2 修改 topic_ok

```python
def topic_ok(item):
    return relevance_score(item) >= int(os.getenv("MIN_RELEVANCE_SCORE", 7))
```

### 3.3 新增主题分类

```python
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
```

---

## Phase 4：扩展 item 字段

在 `main()` 生成 `items` 的地方，把每篇论文保存更多结构化信息。

当前代码大致是：

```python
items.append({
    "guid": p["id"],
    "title": p["title"],
    "link": p["link"],
    "authors": p["authors"],
    "pubDate": p["updated"] or p["published"],
    "summary_html": summ,
})
```

改成：

```python
summary_text = summarize(p["title"], p["summary"])

items.append({
    "guid": p["id"],
    "title": p["title"],
    "link": p["link"],
    "authors": p["authors"],
    "pubDate": p["updated"] or p["published"],
    "raw_summary": p["summary"],
    "summary_text": summary_text,
    "summary_html": summary_text.replace("\n", "<br/>"),
    "score": relevance_score(p),
    "topic": classify_topic(p),
})
```

同时建议在 fresh 排序前按相关性排序：

```python
fresh = sorted(fresh, key=relevance_score, reverse=True)
fresh = fresh[:MAX_ITEMS_PER_RUN]
```

---

## Phase 5：新增 Markdown 日报输出

### 5.1 新增路径配置

在路径配置区添加：

```python
DAILY_DIR = pathlib.Path("docs/daily")
LATEST_MD_PATH = pathlib.Path("docs/latest.md")
```

### 5.2 新增 Markdown 构建函数

```python
def build_markdown_report(items):
    local = pytz.timezone(TIMEZONE)
    now = datetime.now(local)
    date_str = now.strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# AI地球系统预报 arXiv 日报｜{date_str}")
    lines.append("")
    lines.append("## 今日概览")
    lines.append("")
    lines.append(f"- 新增论文数：{len(items)}")
    lines.append(f"- 检索时间窗口：最近 {LOOKBACK_HOURS} 小时")
    lines.append(f"- 最低相关性分数：{os.getenv('MIN_RELEVANCE_SCORE', '7')}")
    lines.append("- 范围：AI天气预报、气候预测、海洋预报、资料同化、地球系统模型")
    lines.append("")

    if not items:
        lines.append("今日未检索到新的强相关论文。")
        lines.append("")
    else:
        lines.append("## 今日重点论文")
        lines.append("")

        for i, it in enumerate(items, 1):
            authors = ", ".join(it["authors"][:6])
            if len(it["authors"]) > 6:
                authors += " et al."

            pub_date = it["pubDate"].strftime("%Y-%m-%d") if hasattr(it["pubDate"], "strftime") else str(it["pubDate"])

            lines.append(f"### {i}. {it['title']}")
            lines.append("")
            lines.append(f"- 类型：{it.get('topic', '未分类')}")
            lines.append(f"- 相关性分数：{it.get('score', 'NA')}")
            lines.append(f"- arXiv：[{it['guid']}]({it['link']})")
            lines.append(f"- 作者：{authors}")
            lines.append(f"- 日期：{pub_date}")
            lines.append("")
            lines.append("**摘要与要点：**")
            lines.append("")
            lines.append(it.get("summary_text", "").strip())
            lines.append("")
            lines.append("**对当前研究的可能启发：**")
            lines.append("")
            lines.append("- 是否涉及长期 autoregressive rollout 稳定性？")
            lines.append("- 是否涉及海气耦合、海洋变量约束、资料同化或神经算子？")
            lines.append("- 是否可迁移到 ORCA-DL-Daily 的逐日海洋预报任务？")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Thank you to arXiv for use of its open access interoperability.")

    return "\n".join(lines)
```

### 5.3 在 main() 中写出日报

在写出 RSS 后添加：

```python
DAILY_DIR.mkdir(parents=True, exist_ok=True)
date_str = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
daily_path = DAILY_DIR / f"{date_str}.md"

md = build_markdown_report(items)
daily_path.write_text(md, encoding="utf-8")
LATEST_MD_PATH.write_text(md, encoding="utf-8")
```

最后打印：

```python
print(f"Generated {len(items)} items → {OUTPUT_PATH}, {LATEST_MD_PATH}, {daily_path}")
```

---

## Phase 6：优化 RSS 元信息

修改 `RSS_CHANNEL`：

```python
RSS_CHANNEL = {
    "title": "AI地球系统预报 arXiv 精选论文",
    "link": "https://rowenxu.github.io/AIxWeather_Paper_Daily/",
    "description": "每日自动更新 · AI天气、气候、海洋与地球系统预报论文精选",
}
```

---

## Phase 7：优化 GitHub Actions workflow

编辑：

```text
.github/workflows/build-rss.yml
```

建议改为：

```yaml
name: Build AIxWeather Daily

on:
  schedule:
    - cron: "0 2 * * *"   # 每日 02:00 UTC = 北京/新加坡 10:00
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: aixweather-paper-daily
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Check Python syntax
        run: |
          python -m py_compile scripts/arxiv_meteo_ai_rss.py

      - name: Run generator
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          TZ: Asia/Shanghai
          LOOKBACK_HOURS: "48"
          ARXIV_MAX_RESULTS: "120"
          MAX_ITEMS_PER_RUN: "25"
          MIN_RELEVANCE_SCORE: "7"
        run: |
          python scripts/arxiv_meteo_ai_rss.py

      - name: Commit & Push
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore(daily): update AIxWeather paper feed"
          commit_user_name: aixweather-bot
          commit_user_email: aixweather-bot@example.com
          file_pattern: |
            docs/index.xml
            docs/latest.md
            docs/daily/*.md
            state/state.json
```

---

## Phase 8：更新 requirements.txt

当前如果使用 DeepSeek 的 OpenAI-compatible API，需要显式添加 `openai`。

建议改为：

```txt
arxiv==2.1.0
feedgen==0.9.0
python-dateutil==2.9.0.post0
pytz==2024.1
openai>=1.40.0
```

---

## Phase 9：更新 README

README 需要从模板说明改为本仓库说明。

建议结构：

```markdown
# AIxWeather_Paper_Daily

每日自动追踪 AI 天气、气候、海洋与地球系统预报相关 arXiv 新论文，生成 RSS 与 Markdown 日报。

## 输出

- RSS: https://rowenxu.github.io/AIxWeather_Paper_Daily/index.xml
- 最新日报: https://rowenxu.github.io/AIxWeather_Paper_Daily/latest.md
- 历史日报: https://rowenxu.github.io/AIxWeather_Paper_Daily/daily/YYYY-MM-DD.md

## 自动运行

GitHub Actions 每天北京时间 10:00 运行，也支持手动触发。

## 配置

可通过 workflow 环境变量调整：

- `LOOKBACK_HOURS`
- `ARXIV_MAX_RESULTS`
- `MAX_ITEMS_PER_RUN`
- `MIN_RELEVANCE_SCORE`
- `TZ`

可选 secret：

- `DEEPSEEK_API_KEY`

如果未设置 `DEEPSEEK_API_KEY`，脚本会使用规则式摘要回退。

## 本地测试

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m py_compile scripts/arxiv_meteo_ai_rss.py
TZ=Asia/Shanghai LOOKBACK_HOURS=72 python scripts/arxiv_meteo_ai_rss.py
```
```

---

## Phase 10：GitHub Pages 设置

在 GitHub 仓库页面设置：

```text
Settings → Pages
Build and deployment: Deploy from a branch
Branch: main
Folder: /docs
```

确认以下地址可访问：

```text
https://rowenxu.github.io/AIxWeather_Paper_Daily/index.xml
https://rowenxu.github.io/AIxWeather_Paper_Daily/latest.md
```

---

## Phase 11：测试清单

### 11.1 本地测试

```bash
python -m py_compile scripts/arxiv_meteo_ai_rss.py
TZ=Asia/Shanghai LOOKBACK_HOURS=168 ARXIV_MAX_RESULTS=120 MAX_ITEMS_PER_RUN=10 python scripts/arxiv_meteo_ai_rss.py
```

检查：

```bash
ls docs/index.xml
ls docs/latest.md
ls docs/daily/
cat docs/latest.md
```

### 11.2 GitHub Actions 测试

1. 打开 GitHub 仓库。
2. 进入 Actions。
3. 选择 `Build AIxWeather Daily`。
4. 点击 `Run workflow`。
5. 查看日志是否成功。
6. 检查是否自动提交：
   - `docs/index.xml`
   - `docs/latest.md`
   - `docs/daily/YYYY-MM-DD.md`
   - `state/state.json`

### 11.3 RSS 测试

用浏览器打开：

```text
https://rowenxu.github.io/AIxWeather_Paper_Daily/index.xml
```

用 RSS 阅读器或 Folo 订阅该地址。

---

## Phase 12：后续增强，可暂缓

以下不是第一阶段必须完成：

1. 保留历史 RSS 条目，而不是只输出当天新条目。
2. 自动下载重点论文 PDF。
3. 对 PDF 进行全文解析。
4. 增加 `docs/weekly/YYYY-WW.md` 周报。
5. 增加 JSON 输出：`docs/latest.json`。
6. 增加 Telegram、邮件或 Notion 推送。
7. 引入 OpenClaw 读取 `docs/latest.md` 并做二次科研解读。
8. 加入单元测试，例如测试 `relevance_score()` 和 `classify_topic()`。

---

## Copilot 执行顺序建议

建议一次只让 Copilot 完成一个小任务。

### Prompt 1

```text
请根据 plan.md 的 Phase 2 和 Phase 3，修改 scripts/arxiv_meteo_ai_rss.py：
1. 扩展 CATEGORIES；
2. 将关键词拆分为 DOMAIN_TERMS、AI_TERMS、FORECAST_TERMS、MODEL_NAMES；
3. 增加 relevance_score 和 classify_topic；
4. 修改 topic_ok，使其基于 MIN_RELEVANCE_SCORE。
保持现有 RSS 输出逻辑不变。
```

### Prompt 2

```text
请根据 plan.md 的 Phase 4 和 Phase 5，给 scripts/arxiv_meteo_ai_rss.py 增加 Markdown 日报输出：
1. 输出 docs/latest.md；
2. 输出 docs/daily/YYYY-MM-DD.md；
3. 日报中包含标题、作者、链接、主题分类、相关性分数、摘要与研究启发；
4. 保留 docs/index.xml RSS 输出。
```

### Prompt 3

```text
请根据 plan.md 的 Phase 7 和 Phase 8，更新 GitHub Actions workflow 和 requirements.txt：
1. workflow 增加 Python 语法检查；
2. workflow 增加 concurrency；
3. workflow 提交 docs/latest.md 和 docs/daily/*.md；
4. requirements.txt 增加 openai 依赖。
```

### Prompt 4

```text
请根据 plan.md 的 Phase 9，更新 README.md，使其准确描述当前项目：
1. 项目目标改为 AI 地球系统预报 arXiv 日报；
2. 更新 GitHub Pages 输出地址；
3. 更新本地测试命令；
4. 更新 Secrets 和环境变量说明。
```

---

## 完成标准

当以下条件全部满足时，第一版改造完成：

- [ ] `python -m py_compile scripts/arxiv_meteo_ai_rss.py` 通过。
- [ ] 本地运行脚本不会报错。
- [ ] GitHub Actions 手动运行成功。
- [ ] `docs/index.xml` 正常生成。
- [ ] `docs/latest.md` 正常生成。
- [ ] `docs/daily/YYYY-MM-DD.md` 正常生成。
- [ ] `state/state.json` 正常更新。
- [ ] GitHub Pages 可以访问 RSS 和 latest.md。
- [ ] README 中的地址、Secrets、环境变量与代码一致。

---

## 第一阶段不要做的事

为了避免复杂度过高，第一阶段暂时不要做：

1. 不要自动下载 PDF。
2. 不要自动执行论文或网页中的任何命令。
3. 不要把 API Key 写入代码或 README。
4. 不要引入数据库。
5. 不要同时接入太多推送渠道。
6. 不要让 workflow 依赖本地文件路径。

先完成稳定的“检索 → 筛选 → RSS → Markdown 日报 → GitHub Pages”。
