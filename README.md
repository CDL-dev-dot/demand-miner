# demand-miner

> **For Reddit API reviewers:** This is a personal, non-commercial, **read-only** research
> script built on [PRAW](https://praw.readthedocs.io). It searches public posts for
> need-expressing phrases (e.g. "is there an app that") and reads top posts/comments from a
> few public subreddits, to analyze recurring user needs for product research. It never
> posts, comments, votes, or messages; it stays within free-tier rate limits (PRAW's
> built-in throttling); Reddit content is analyzed locally and never republished, resold,
> or used for AI model training. Credentials live in an untracked `.env` file.

A four-stage pipeline: mine app-need signals from public Reddit posts → extract and
cluster needs with an LLM → validate each need cluster against the US App Store →
score and report. It is a **screening tool, not a decision maker** — it compresses
thousands of posts into a dozen evidence-backed candidates; the final judgment is still
done by a human.

```
01_collect.py   Collect via official Reddit API   -> data/01_posts.jsonl
02_extract.py   LLM need extraction + clustering  -> data/02_needs.jsonl + 02_clusters.jsonl
03_validate.py  App Store competitor scan (free)  -> data/03_validated.jsonl
04_report.py    Scoring + LLM qualitative pass    -> data/04_report.md + .csv
```

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in credentials, see below
```

`.env` takes three groups of credentials:

1. **Reddit** (free tier): create a **script**-type app at
   https://www.reddit.com/prefs/apps to get the client id (the string shown under
   "personal use script") and secret. Describe the use case honestly ("personal
   research"). The free tier allows 100 queries/minute; PRAW throttles automatically.
2. **LLM**: any OpenAI-compatible endpoint (`OPENAI_BASE_URL` + `OPENAI_API_KEY` +
   `OPENAI_MODEL`).
3. **Firecrawl** (optional): if set, stage 3 adds a web-side competitor scan;
   otherwise it is skipped automatically.

Full run:

```bash
.venv/bin/python 01_collect.py     # 10-30 min depending on config volume
.venv/bin/python 02_extract.py     # the token-hungry stage
.venv/bin/python 03_validate.py    # ~3s per keyword (iTunes API soft limit)
.venv/bin/python 04_report.py      # read data/04_report.md
```

Try the second half without any Reddit credentials (stages 3/4 need no keys at all):

```bash
.venv/bin/python 02_extract.py --input data/sample_posts.jsonl     # needs LLM key
.venv/bin/python 03_validate.py --input data/sample_clusters.jsonl # needs nothing
.venv/bin/python 04_report.py --skip-llm
```

## How to read the report (stage 4 rules)

- **Swarm alert**: >= 3 competitor apps released in the last 18 months. The need is
  real but indie developers are already flooding it — forced downgrade. This is the
  empirically most common cause of death for "opportunity list" ideas.
- **Stale leader** (renovation opportunity): the top competitor has >= 500 reviews but
  a rating < 4.2 or has not been updated for over a year — the best signal to enter.
- **Payment evidence**: uses the top competitor's review count as a proxy (someone
  built it at scale = someone pays). "I'd pay for this" comments on Reddit are
  recorded but never trusted on their own.
- Weighted total: demand 40% + competition window 35% + payment evidence 25%.

## Known limitations

- **Keyword granularity drives stage-3 precision**: broad keywords (e.g. "carb
  counting app") pull in an entire category (MyFitnessPal etc.) and can misjudge a
  vertical niche as a red ocean. Catch vertical wedges with the stage-4 LLM pass
  (positioning mismatch between competitors and the need statement) plus human review;
  you can also hand-edit `appstore_keywords` in `02_clusters.jsonl` and rerun stage 3.
- The iTunes Search API only reflects the search head; long-tail competitors may be
  missed. Swarm detection is based on each app's original `releaseDate`.
- Reddit listings cap at ~1000 items each; coverage comes from combining multiple
  phrases × subreddits × time filters.
- Stage-2 extraction quality depends on the model; after switching models, compare
  outputs on `data/sample_posts.jsonl` before a full run.

## Compliance

- Personal research use only (explicitly covered by Reddit's free tier). Register the
  app truthfully, never fake the user agent, never scrape web pages around robots.txt.
- Reddit content is used for analytical insight only — never copy Reddit content into
  a product; commercializing Reddit data itself requires written approval.
- The needs you discover, the code you write, and the products you build are yours.

## Common customizations

- Change domains: edit `vertical_subreddits` in `config.yaml` (the main steering wheel)
- Change storefront: `country: us` → any App Store country code
- Hunt "paying but unhappy" signals: add phrases like `"alternative to X"` /
  `"X is too expensive"` (replace X with a competitor name)
- Bulk history: swap stage 1 for the Arctic Shift community archive (cleaner for research)
- Scheduled runs: weekly cron + diff two reports to spot newly emerging clusters
