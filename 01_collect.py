"""阶段 1：通过 Reddit 官方 API 采集需求信号帖。

两条腿：全站短语搜索（"is there an app" 等）+ 垂直 subreddit 年度热帖（含高赞评论）。
产出 data/01_posts.jsonl。praw 会自动遵守 100 QPM 限速，无需手动 sleep。
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
            "缺少 Reddit 凭据。请在 https://www.reddit.com/prefs/apps 创建 script 类型应用，"
            "并把 client_id/secret 填入 .env（参考 .env.example）"
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
        print(f'[phrase] "{phrase}" -> 累计 {len(rows)} 帖')

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
                        print(f"  评论抓取失败 {p.id}: {e}")
                rows.append(row)
                fetched += 1
        except Exception as e:
            print(f"[sub] r/{sub} 抓取失败（sub 不存在或被限制）: {e}")
            continue
        print(f"[sub] r/{sub} -> 累计 {len(rows)} 帖")

    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
