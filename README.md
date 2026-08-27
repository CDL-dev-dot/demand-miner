# demand-miner

一套用于发现 App Store 产品翻新机会的四阶段调研流水线：
采集低星用户评论，通过 LLM 提取和聚类重复出现的未满足需求，
再验证当前竞品情况，最终对最有潜力的候选方向评分并生成报告。

本项目的数据源已从 Reddit 切换为 Apple App Store，无需 Reddit API 权限。

```text
01_collect.py   搜索 App 并采集低星评论       -> data/01_reviews.jsonl
02_extract.py   使用 LLM 提取、聚类未满足需求 -> data/02_needs.jsonl
                                            -> data/02_clusters.jsonl
03_validate.py  验证当前 App Store 竞争情况   -> data/03_validated.jsonl
04_report.py    候选方向评分并生成报告         -> data/04_report.md
                                            -> data/04_report.csv
```

它是筛选工具，不是自动决策工具。评论中的抱怨可以证明产品存在摩擦，
但不能直接证明市场规模、获客成本或用户迁移意愿。

## 数据来源

- Apple iTunes Search API：根据 `config.yaml` 中的种子关键词发现相关 App。
- Apple 公开的用户评论 RSS/JSON：读取各 App 在指定国家商店中的近期评论，
  无需 API Key；每款 App、每个国家商店最多可读取 10 页。
- Firecrawl：可选，仅在阶段 3 中补充通用网页竞品搜索。

阶段 1 默认只保留 1–3 星评论。评论者昵称在写入本地文件前会被转换成
不可直接识别的哈希值。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中选择一种 LLM 后端。

### 使用 Cursor CLI

首次使用先登录：

```bash
cursor-agent login
```

然后设置：

```dotenv
LLM_BACKEND=cursor
```

该模式通过本地 `cursor-agent` CLI 使用你的 Cursor 订阅，无需额外 API Key。
可以按任务类型指定模型：

```dotenv
CURSOR_MODEL_FAST=
CURSOR_MODEL_REASONING=
```

- `CURSOR_MODEL_FAST`：需求提取、聚类和竞品相关性判断。
- `CURSOR_MODEL_REASONING`：最终商业价值定性判断。
- 留空时使用 Cursor Auto；`CURSOR_MODEL` 是两类任务共用的兜底配置。

### 使用 OpenAI 兼容接口

```dotenv
LLM_BACKEND=openai
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

直接使用 OpenAI 时，`OPENAI_BASE_URL` 可以留空。

### 可选配置 Firecrawl

```dotenv
FIRECRAWL_API_KEY=
```

不填写时，阶段 3 会自动跳过网页侧竞品搜索。

## 配置市场扫描范围

`config.yaml` 中的 `app_search_terms` 是最主要的调研入口：

```yaml
country: us
app_search_terms:
  - subscription tracker
  - pet medication
  - ADHD planner
apps_per_search_term: 3
review_pages_per_app: 2
review_ratings: [1, 2, 3]
max_reviews_per_app: 20
```

建议使用具体的 App 类别或待办任务关键词。`productivity` 之类的宽泛词会产生
大量噪声。第一次运行时应控制范围，检查聚类结果后再逐步增加相邻关键词。

## 运行完整流水线

```bash
.venv/bin/python 01_collect.py
.venv/bin/python 02_extract.py
.venv/bin/python 03_validate.py
.venv/bin/python 04_report.py
```

阶段 2 消耗的 LLM 调用最多。阶段 3 会在 iTunes Search 请求之间主动等待，
避免超过其软性请求频率限制。

也可以先使用仓库内的合成样例验证流程：

```bash
.venv/bin/python 02_extract.py --input data/sample_reviews.jsonl
.venv/bin/python 03_validate.py --input data/sample_clusters.jsonl
.venv/bin/python 04_report.py --skip-llm
```

运行单元测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 评分逻辑

- **需求热度（40%）**：独立评论用户数、付费相关证据，以及需求是否跨月出现。
- **竞争窗口（35%）**：存在强势健康头部或近期新品蜂群时降分；
  头部产品低分或长期不更新时加分。
- **付费证据（25%）**：用竞品评论量粗略代表产品采用规模；
  同时保留评论中涉及订阅、购买、退款、价格敏感度的原文作为辅助证据。

### 报告标记

- **蜂群警报**：配置的 18 个月窗口内，至少出现 3 款直接相关的新竞品。
  需求可能真实存在，但进入时机较差。
- **头部老化**：直接竞品头部至少有 500 条评论，且评分低于 4.2，
  或超过一年没有更新。这是翻新机会信号，并不代表用户一定会迁移。

## 已知限制

- 种子关键词决定了可发现的范围。本工具更适合发现相邻机会和产品翻新机会，
  不是对所有 App 创意的无偏扫描。
- 低星评论会刻意放大不满意用户的声音。正式开发前必须同时检查好评、
  总评论量和近期版本变化。
- 公开评论源仅返回近期窗口，每款 App、每个国家商店最多 10 页，
  不能替代完整历史数据。
- iTunes 关键词搜索是近似匹配。阶段 3 会优先使用 LLM 保留直接竞品；
  未配置 LLM 时会退化为名称关键词启发式判断。
- App Store 评论量只能代表采用规模，不能直接代表收入、客单价或转化率。
- `formattedPrice` 仅代表下载价格，显示 `Free` 不代表 App 内没有订阅或内购。
- LLM 可能错误合并无关抱怨，也可能把单个 App 的 Bug 过度泛化。
  对高分候选必须回看报告中的来源链接。

## 数据处理与合规

- 原始评论文件仅保存在本地，生成的数据文件默认被 Git 忽略。
- 不要公开转载评论原文或评论者信息。报告如需对外分享，应先删除原文引用。
- 公开接口可访问不等于获得内容再分发权，使用者仍需遵守 Apple 相关条款
  以及后续接口规则变化。
- 采集器使用保守的数量限制和可配置延迟，不应绕过接口限制，
  也不应尝试突破公开评论源的最大分页数。

## 常见调整

- 修改 `country`，切换目标国家商店。
- 替换 `app_search_terms`，聚焦高客单价或特定垂直品类。
- 提高 `minimum_app_rating_count`，研究成熟市场。
- 降低该阈值，观察较新的细分市场，但需要谨慎处理样本不足。
- 每周定时运行并比较需求簇数量，发现持续出现的新抱怨。
