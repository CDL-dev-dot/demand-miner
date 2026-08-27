"""Stage 3: competition validation.

Scans App Store competitors for each need cluster via the official iTunes Search API
(free, no key): count, ratings, review volume, release and last-update dates. Focus:
"swarm" detection (recent same-niche launches piling up) and "stale leader" detection
(big but low-rated / long-unmaintained incumbent). Optional Firecrawl web-side scan.
Output: data/03_validated.jsonl.
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from common import DATA, llm_available, llm_client, llm_json, load_config, read_jsonl, write_jsonl

ITUNES_URL = "https://itunes.apple.com/search"

RELEVANCE_PROMPT = """You are screening App Store keyword-search results for competitor analysis.

Need being validated: {need}

Below are apps returned by keyword search. Identify which ones are DIRECT competitors:
an app whose PRIMARY job overlaps this specific need. Exclude apps that merely share a
broad category (a general calorie counter is not a direct competitor to a
diabetes-specific carb estimator; a clothing store app is never a competitor to a
laundry-tag scanner). When a name is ambiguous, use the genre as a hint and lean toward
excluding.

Reply JSON: {{"direct_idx": [i, ...]}}

Apps: {apps}
"""


def search_appstore(term, country, limit=25):
    resp = requests.get(
        ITUNES_URL,
        params={"term": term, "entity": "software", "country": country, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def firecrawl_web_scan(keyword):
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return None
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v2/search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": f"best {keyword} app iphone", "limit": 5},
            timeout=60,
        )
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("web", []) or []
        return [{"title": it.get("title"), "url": it.get("url")} for it in items]
    except Exception as e:
        print(f"  firecrawl scan failed (non-fatal): {e}")
        return None


STOPWORDS = {"app", "apps", "the", "a", "an", "for", "and", "my", "no", "of", "to", "on", "in", "with"}


def keyword_tokens(keywords):
    """Content tokens from cluster keywords, used to filter out irrelevant store matches."""
    toks = set()
    for kw in keywords:
        for t in kw.lower().split():
            if t not in STOPWORDS and len(t) > 2:
                toks.add(t)
    return toks


def parse_date(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def llm_filter_competitors(client, need_statement, candidates):
    """Ask the LLM which search results are direct competitors. Returns None on failure."""
    payload = [{"i": i, "name": a["name"], "genre": a.get("genre", "")} for i, a in enumerate(candidates)]
    try:
        result = llm_json(client, RELEVANCE_PROMPT.format(need=need_statement, apps=json.dumps(payload, ensure_ascii=False)))
        idx = result.get("direct_idx", [])
        return [candidates[i] for i in idx if isinstance(i, int) and 0 <= i < len(candidates)]
    except Exception as e:
        print(f"  LLM relevance filter failed, falling back to token filter: {e}")
        return None


def validate_cluster(cluster, cfg, client=None, use_llm=False):
    country = cfg.get("country", "us")
    new_cutoff = datetime.now(timezone.utc) - timedelta(days=30 * cfg.get("new_app_months", 18))
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    apps = {}
    for kw in cluster.get("appstore_keywords", [])[: cfg.get("keywords_per_cluster", 3)]:
        try:
            results = search_appstore(kw, country)
        except Exception as e:
            print(f"  iTunes lookup failed '{kw}': {e}")
            continue
        for a in results:
            apps[a["trackId"]] = a
        time.sleep(3.1)  # iTunes Search API soft limit ~20 req/min

    parsed = []
    for a in apps.values():
        parsed.append(
            {
                "name": a.get("trackName"),
                "genre": a.get("primaryGenreName") or "",
                "rating": round(a.get("averageUserRating") or 0, 2),
                "reviews": a.get("userRatingCount") or 0,
                "price": a.get("formattedPrice") or "Free",
                "released": (a.get("releaseDate") or "")[:10],
                "last_update": (a.get("currentVersionReleaseDate") or "")[:10],
                "track_id": a["trackId"],
            }
        )
    parsed.sort(key=lambda x: -x["reviews"])

    # iTunes search matches loosely (e.g. clothing stores for "clothing care tags").
    # Preferred: LLM judges which results are direct competitors; fallback: name-token filter.
    relevant = None
    if use_llm:
        fresh = [a for a in parsed if (d := parse_date(a["released"])) and d >= new_cutoff]
        candidates = (parsed[:30] + [a for a in fresh if a not in parsed[:30]])[:45]
        picked = llm_filter_competitors(client, cluster.get("need_statement", cluster["name"]), candidates)
        if picked is not None:
            relevant = sorted(picked, key=lambda x: -x["reviews"])
    if relevant is None:
        tokens = keyword_tokens(cluster.get("appstore_keywords", []))
        relevant = [a for a in parsed if any(t in a["name"].lower() for t in tokens)] or parsed

    new_apps = [a for a in relevant if (d := parse_date(a["released"])) and d >= new_cutoff]
    leader = relevant[0] if relevant else None
    leader_stale = bool(
        leader
        and leader["reviews"] >= 500
        and (
            leader["rating"] < 4.2
            or ((d := parse_date(leader["last_update"])) and d < stale_cutoff)
        )
    )

    out = dict(cluster)
    out["appstore"] = {
        "total_matched": len(parsed),
        "relevant_matched": len(relevant),
        "new_apps_count": len(new_apps),
        "swarm": len(new_apps) >= cfg.get("swarm_threshold", 3),
        "leader_stale": leader_stale,
        "paid_price_points": sorted({a["price"] for a in relevant if a["price"] != "Free"}),
        "top_apps": relevant[:5],
        "new_apps_sample": [a["name"] for a in new_apps[:5]],
        "category_leaders": [a["name"] for a in parsed[:3]],  # unfiltered context
    }
    web = firecrawl_web_scan(cluster["appstore_keywords"][0]) if cluster.get("appstore_keywords") else None
    if web is not None:
        out["web_scan"] = web
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DATA / "02_clusters.jsonl"))
    parser.add_argument("--output", default=str(DATA / "03_validated.jsonl"))
    args = parser.parse_args()

    cfg = load_config()
    clusters = read_jsonl(args.input)
    use_llm = llm_available()
    client = llm_client() if use_llm else None
    if not use_llm:
        print("no LLM configured: competitor relevance uses the name-token heuristic only")
    rows = []
    for i, c in enumerate(clusters):
        print(f"[{i + 1}/{len(clusters)}] validating: {c['name']}")
        rows.append(validate_cluster(c, cfg, client, use_llm))
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
