"""Stage 1: collect low-rated reviews from Apple's public App Store feeds.

The iTunes Search API discovers apps for configured seed terms. Apple's customer
review RSS/JSON feed then supplies recent 1-3 star reviews, which contain concrete
complaints and feature requests. Output: data/01_reviews.jsonl.
"""
import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone

import requests

from common import DATA, load_config, write_jsonl

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
REVIEW_FEED_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/id={app_id}/sortby={sort_order}/json"
)


def nested_label(value, default=""):
    if isinstance(value, dict):
        label = value.get("label")
        return default if label is None else label
    return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_timestamp(value):
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def entry_link(entry, fallback):
    links = entry.get("link", [])
    if isinstance(links, dict):
        links = [links]
    for link in links:
        href = link.get("attributes", {}).get("href") if isinstance(link, dict) else None
        if href:
            return href
    return fallback


def parse_review_entry(entry, app, country, matched_terms, allowed_ratings):
    """Normalize one Apple review while replacing the reviewer alias with a hash."""
    rating = safe_int(nested_label(entry.get("im:rating")))
    if not rating or rating not in allowed_ratings:
        return None

    app_id = app.get("trackId")
    review_id = nested_label(entry.get("id"))
    author = nested_label(entry.get("author", {}).get("name"))
    updated = nested_label(entry.get("updated"))
    title = nested_label(entry.get("title")).strip()
    text = nested_label(entry.get("content")).strip()
    if not app_id or not review_id or not text:
        return None

    reviewer_key = author or review_id
    reviewer_id = hashlib.sha256(f"{country}\0{reviewer_key}".encode("utf-8")).hexdigest()[:16]
    app_url = app.get("trackViewUrl") or f"https://apps.apple.com/{country}/app/id{app_id}"
    return {
        "id": f"{country}:{app_id}:{review_id}",
        "source": "app_store_review",
        "storefront": country,
        "matched_terms": sorted(set(matched_terms)),
        "app_id": app_id,
        "app_name": app.get("trackName") or "",
        "app_genre": app.get("primaryGenreName") or "",
        "app_store_rating": round(app.get("averageUserRating") or 0, 2),
        "app_store_rating_count": app.get("userRatingCount") or 0,
        "app_version": nested_label(entry.get("im:version")),
        "rating": rating,
        "title": title[:500],
        "selftext": text[:4000],
        "reviewer_id": reviewer_id,
        "created_utc": parse_timestamp(updated),
        "permalink": entry_link(entry, app_url),
        "helpful_votes": safe_int(nested_label(entry.get("im:voteSum"))),
        "total_votes": safe_int(nested_label(entry.get("im:voteCount"))),
    }


def search_appstore(term, country, limit):
    response = requests.get(
        ITUNES_SEARCH_URL,
        params={"term": term, "entity": "software", "country": country, "limit": limit},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def discover_apps(cfg):
    country = cfg.get("country", "us")
    search_limit = cfg.get("app_search_limit", 25)
    apps_per_term = cfg.get("apps_per_search_term", 5)
    min_reviews = cfg.get("minimum_app_rating_count", 100)
    search_delay = cfg.get("search_request_delay_seconds", 3.1)
    selected = {}

    for index, term in enumerate(cfg.get("app_search_terms", [])):
        try:
            results = search_appstore(term, country, search_limit)
        except Exception as error:
            print(f"  App Store search failed for '{term}': {error}")
            continue
        eligible = [
            app for app in results if (app.get("userRatingCount") or 0) >= min_reviews
        ][:apps_per_term]
        for app in eligible:
            app_id = app.get("trackId")
            if not app_id:
                continue
            if app_id not in selected:
                selected[app_id] = {"app": app, "matched_terms": set()}
            selected[app_id]["matched_terms"].add(term)
        print(f"[search] '{term}' -> {len(eligible)} apps, {len(selected)} unique total")
        if index + 1 < len(cfg.get("app_search_terms", [])):
            time.sleep(search_delay)
    return list(selected.values())


def fetch_review_page(app_id, country, page, sort_order):
    url = REVIEW_FEED_URL.format(
        country=country,
        page=page,
        app_id=app_id,
        sort_order=sort_order,
    )
    response = requests.get(url, timeout=30)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    entries = response.json().get("feed", {}).get("entry", [])
    if isinstance(entries, dict):
        return [entries]
    return entries


def collect_reviews(app_entry, cfg):
    app = app_entry["app"]
    matched_terms = app_entry["matched_terms"]
    country = cfg.get("country", "us")
    allowed_ratings = {safe_int(value) for value in cfg.get("review_ratings", [1, 2, 3])}
    page_count = min(10, max(1, cfg.get("review_pages_per_app", 2)))
    max_reviews = cfg.get("max_reviews_per_app", 40)
    sort_order = cfg.get("review_sort", "mostrecent")
    request_delay = cfg.get("review_request_delay_seconds", 0.25)
    rows = []
    seen = set()

    for page in range(1, page_count + 1):
        try:
            entries = fetch_review_page(app["trackId"], country, page, sort_order)
        except Exception as error:
            print(f"  review fetch failed for {app.get('trackName')} page {page}: {error}")
            break
        if not entries:
            break
        for entry in entries:
            row = parse_review_entry(entry, app, country, matched_terms, allowed_ratings)
            if row and row["id"] not in seen:
                rows.append(row)
                seen.add(row["id"])
                if len(rows) >= max_reviews:
                    return rows
        if page < page_count:
            time.sleep(request_delay)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DATA / "01_reviews.jsonl"))
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.get("app_search_terms"):
        sys.exit("No app_search_terms configured in config.yaml")

    apps = discover_apps(cfg)
    rows = []
    for index, app_entry in enumerate(apps, 1):
        app = app_entry["app"]
        reviews = collect_reviews(app_entry, cfg)
        rows.extend(reviews)
        print(f"[{index}/{len(apps)}] {app.get('trackName')} -> {len(reviews)} low-rated reviews")
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
