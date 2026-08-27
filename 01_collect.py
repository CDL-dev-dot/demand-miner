"""Stage 1: collect need-signal posts via the official Reddit Data API (read-only).

Two legs: site-wide phrase search ("is there an app" etc.) + yearly top posts of
vertical subreddits (with top comments). Output: data/01_posts.jsonl.
PRAW enforces the 100 QPM free-tier rate limit automatically; no manual sleeps needed.
"""
import argparse
import os
import sys

from common import DATA, load_config, write_jsonl


def post_row(p, source, phrase=None):
    return {
        "id": p.id,
        "source": source,
        "matched_phrase": phrase,
        "subreddit": str(p.subreddit),
        "title": p.title,
        "selftext": (p.selftext or "")[:2000],
        "score": p.score,
        "num_comments": p.num_comments,
        "author": str(p.author),
        "created_utc": p.created_utc,
        "permalink": f"https://reddit.com{p.permalink}",
        "top_comments": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DATA / "01_posts.jsonl"))
    args = parser.parse_args()

    if not (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")):
        sys.exit(
            "Missing Reddit credentials. Create a script-type app at "
            "https://www.reddit.com/prefs/apps and fill client_id/secret into .env (see .env.example)"
        )

    import praw

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "demand-miner research script"),
    )
    reddit.read_only = True

    cfg = load_config()
    seen, rows = set(), []

    for phrase in cfg["phrases"]:
        for p in reddit.subreddit("all").search(
            f'"{phrase}"',
            sort=cfg.get("search_sort", "new"),
            time_filter=cfg.get("time_filter", "year"),
            limit=cfg.get("per_phrase_limit", 200),
        ):
            if p.id in seen:
                continue
            seen.add(p.id)
            rows.append(post_row(p, "phrase_search", phrase))
        print(f'[phrase] "{phrase}" -> {len(rows)} posts total')

    for sub in cfg.get("vertical_subreddits", []):
        fetched = 0
        try:
            for p in reddit.subreddit(sub).top(
                time_filter=cfg.get("time_filter", "year"),
                limit=cfg.get("per_sub_limit", 100),
            ):
                if p.id in seen:
                    continue
                seen.add(p.id)
                row = post_row(p, "vertical_top")
                if fetched < cfg.get("comments_for_top_n", 30):
                    try:
                        p.comments.replace_more(limit=0)
                        top = sorted(p.comments, key=lambda c: getattr(c, "score", 0), reverse=True)[:5]
                        row["top_comments"] = [c.body[:500] for c in top]
                    except Exception as e:
                        print(f"  comment fetch failed {p.id}: {e}")
                rows.append(row)
                fetched += 1
        except Exception as e:
            print(f"[sub] r/{sub} fetch failed (missing or restricted): {e}")
            continue
        print(f"[sub] r/{sub} -> {len(rows)} posts total")

    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
