"""阶段 3：竞争验证。

对每个需求簇用 App Store 官方搜索接口（iTunes Search API，免费无需 key）扫竞品：
数量、评分、评论数、上架时间、最近更新——重点判定"蜂群"（近期新品扎堆）与
"翻新机会"（头部竞品体量大但评分低/久未更新）。可选 Firecrawl 做 web 端补充扫描。
产出 data/03_validated.jsonl。
"""
import argparse
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from common import DATA, load_config, read_jsonl, write_jsonl

ITUNES_URL = "https://itunes.apple.com/search"


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
        print(f"  firecrawl 扫描失败（不影响主流程）: {e}")
        return None


def parse_date(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def validate_cluster(cluster, cfg):
    country = cfg.get("country", "us")
    new_cutoff = datetime.now(timezone.utc) - timedelta(days=30 * cfg.get("new_app_months", 18))
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    apps = {}
    for kw in cluster.get("appstore_keywords", [])[: cfg.get("keywords_per_cluster", 3)]:
        try:
            results = search_appstore(kw, country)
        except Exception as e:
            print(f"  iTunes 查询失败 '{kw}': {e}")
            continue
        for a in results:
            apps[a["trackId"]] = a
        time.sleep(3.1)  # iTunes Search API 软限速约 20 次/分钟

    parsed = []
    for a in apps.values():
        parsed.append(
            {
                "name": a.get("trackName"),
                "rating": round(a.get("averageUserRating") or 0, 2),
                "reviews": a.get("userRatingCount") or 0,
                "price": a.get("formattedPrice") or "Free",
                "released": (a.get("releaseDate") or "")[:10],
                "last_update": (a.get("currentVersionReleaseDate") or "")[:10],
                "track_id": a["trackId"],
            }
        )
    parsed.sort(key=lambda x: -x["reviews"])

    new_apps = [a for a in parsed if (d := parse_date(a["released"])) and d >= new_cutoff]
    leader = parsed[0] if parsed else None
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
        "new_apps_count": len(new_apps),
        "swarm": len(new_apps) >= cfg.get("swarm_threshold", 3),
        "leader_stale": leader_stale,
        "paid_price_points": sorted({a["price"] for a in parsed if a["price"] != "Free"}),
        "top_apps": parsed[:5],
        "new_apps_sample": [a["name"] for a in new_apps[:5]],
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
    rows = []
    for i, c in enumerate(clusters):
        print(f"[{i + 1}/{len(clusters)}] 验证: {c['name']}")
        rows.append(validate_cluster(c, cfg))
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
