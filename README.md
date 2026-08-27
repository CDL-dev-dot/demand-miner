# demand-miner

> **For Reddit API reviewers:** This is a personal, non-commercial, **read-only** research
> script built on [PRAW](https://praw.readthedocs.io). It searches public posts for
> need-expressing phrases (e.g. "is there an app that") and reads top posts/comments from a
> few public subreddits, to analyze recurring user needs for product research. It never
> posts, comments, votes, or messages; it stays within free-tier rate limits (PRAW's
> built-in throttling); Reddit content is analyzed locally and never republished, resold,
> or used for AI model training. Credentials live in an untracked `.env` file.

从 Reddit 挖掘 app 需求信号 → LLM 提炼聚类 → App Store 竞品验证 → 评分报告的四阶段流水线。
定位：**筛选器而非决策器**——把几千条帖子压缩成十几个带证据的候选，最终判断仍需人工深挖。

```
01_collect.py   Reddit 官方 API 采集        -> data/01_posts.jsonl
02_extract.py   LLM 提取需求 + 聚类         -> data/02_needs.jsonl + 02_clusters.jsonl
03_validate.py  App Store 竞品扫描（免费）   -> data/03_validated.jsonl
04_report.py    评分 + LLM 定性判定         -> data/04_report.md + .csv
```

## 快速开始

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # 按下述说明填写
```

`.env` 需要三组凭据：

1. **Reddit**（免费）：在 https://www.reddit.com/prefs/apps 创建 **script** 类型应用，
   拿到 client_id（应用名下方一串字符）和 secret。用途如实填写"个人研究"。
   免费档限速 100 次/分钟，praw 会自动遵守，无需处理。
2. **LLM**：任意 OpenAI 兼容端点。公司网关就填网关的 BASE_URL + KEY + 模型名。
3. **Firecrawl**（可选）：填了则阶段 3 附带 web 端竞品扫描，不填自动跳过。

完整跑一轮：

```bash
.venv/bin/python 01_collect.py     # 约 10-30 分钟，取决于 config 里的量
.venv/bin/python 02_extract.py     # token 消耗大户，反正你免费
.venv/bin/python 03_validate.py    # 每个关键词 3 秒限速
.venv/bin/python 04_report.py      # 看 data/04_report.md
```

不配 Reddit 凭据也能先试跑后半程（阶段 3/4 完全免费无需任何 key）：

```bash
.venv/bin/python 02_extract.py --input data/sample_posts.jsonl     # 需 LLM key
.venv/bin/python 03_validate.py --input data/sample_clusters.jsonl # 无需任何 key
.venv/bin/python 04_report.py --skip-llm
```

## 判定规则（04 报告怎么读）

- **蜂群警报（swarm）**：近 18 个月上架的竞品 ≥ 3 款 → 需求真但已被独立开发者围攻，强制降级。
  这是历史上两次实证的死亡原因（宠物用药、旧货估价类目都是几个月内 5+ 同质新品）。
- **翻新机会（leader_stale）**：头部竞品评论 ≥ 500 但评分 < 4.2 或超过一年未更新 → 最佳信号。
- **付费证据**：用头部竞品的真实评论量做代理（有人做出规模 = 有人付费），Reddit 上的
  "I'd pay" 口头承诺只作辅助，不可采信。
- 三项加权：需求热度 40% + 竞争窗口 35% + 付费证据 25%。

## 已知局限（务必知道）

- **关键词粒度决定阶段 3 的精度**：宽泛关键词（如 "carb counting app"）会把整个大品类
  （MyFitnessPal 等）拉进来，把垂直缝隙误判成红海。差异化缝隙要靠阶段 4 的 LLM 定性判定
  （看竞品定位与需求陈述是否错位）+ 人工复核。可在 02 产物里手动改 `appstore_keywords` 后重跑 03。
- iTunes Search API 只反映搜索头部，长尾竞品可能漏；swarm 判定基于 `releaseDate`（原始上架日）。
- Reddit 单 listing 上限约 1000 条，靠多短语 × 多 sub × 改 time_filter 切分覆盖。
- 阶段 2 的提取质量依赖模型；换模型后先用 sample_posts 对比输出再跑全量。

## 合规红线

- 仅限个人研究用途（Reddit 免费档明确覆盖），注册 app 时如实申报，勿伪装 UA、勿绕 robots.txt
  抓网页（Reddit 正在起诉绕行抓取的公司）。
- 帖子内容仅用于分析洞察，**不要把 Reddit 内容复制进你的产品**；商业化使用 Reddit 数据本身需
  书面许可。
- 挖出的需求、你写的代码和产品，都是你的。

## 常用改造点

- 换领域：改 `config.yaml` 的 `vertical_subreddits`（这是最主要的方向盘）
- 换国家：`country: us` → 其他 App Store 国家码
- 抓"已付费但不满"信号：往 `phrases` 加 `"alternative to X"` / `"X is too expensive"`（X 替换成具体竞品名）
- 批量历史数据：接入 Arctic Shift 社区存档替代阶段 1（研究用途更干净）
- 定时跑：crontab 每周一轮，diff 两次报告看新出现的簇
