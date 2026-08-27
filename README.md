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
2. **LLM**, two backend options via `LLM_BACKEND`:
   - `openai` (default): any OpenAI-compatible endpoint (`OPENAI_BASE_URL` +
     `OPENAI_API_KEY` + `OPENAI_MODEL`).
   - `cursor`: pipes prompts through the local [Cursor CLI](https://cursor.com/cli)
     (`cursor-agent --print --mode ask`), using your Cursor subscription — no API key.
     One-time setup: `cursor-agent login`. Optional `CURSOR_MODEL` to pin a model.
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

- **Competitor relevance is LLM-judged**: raw keyword search pulls in loosely related
  apps (clothing stores for "clothing care tags"). When an LLM backend is configured,
  stage 3 asks it to keep only direct competitors before computing swarm/leader
  metrics (name-token heuristic as fallback). Raw counts stay in `total_matched`,
  category giants in `category_leaders`. You can also hand-edit `appstore_keywords`
  in `02_clusters.jsonl` and rerun stage 3.
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
