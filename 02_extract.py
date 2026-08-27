"""阶段 2：LLM 提炼需求信号并聚类成"需求簇"。

每帖提取 0..n 条需求（含付费信号、情绪强度），再跨帖聚类。
产出 data/02_needs.jsonl（明细）与 data/02_clusters.jsonl（需求簇，进入阶段 3）。
"""
import argparse
import json
from datetime import datetime, timezone

from common import DATA, llm_client, llm_json, load_config, read_jsonl, write_jsonl

EXTRACT_PROMPT = """For each Reddit post below, identify explicit or implicit UNMET NEEDS that could plausibly be solved by a mobile app.
Ignore jokes, memes, politics, and needs already perfectly served by well-known apps UNLESS the poster expresses dissatisfaction with existing options.

For each need found, output an object:
- post_id: the post id it came from
- need_summary: <=15 words, English, describing the job-to-be-done
- audience: who has this need
- frequency: one of daily | weekly | occasional | one_off
- existing_solutions: what the poster tried or mentioned (string, may be empty)
- dissatisfaction: why current options fail them (string, may be empty)
- pay_signal: verbatim quote if any willingness to pay is expressed, else null
- emotion: pain intensity 1-5
- app_shaped: true if an iOS app could realistically address it

A post may yield zero needs. Reply JSON: {"needs": [...]}

Posts:
"""

CLUSTER_PROMPT_TEMPLATE = """Group these app-need statements into clusters where members describe the SAME underlying need (same job-to-be-done for a similar audience). Do not force unrelated needs together; singleton clusters are fine.

For each cluster output:
- name: short cluster name (English)
- need_statement: one sentence describing the need
- member_idx: list of input idx values belonging to this cluster
- appstore_keywords: {kw_n} US App Store search keywords a user with this need would type

Reply JSON: {{"clusters": [...]}}

Needs:
{payload}
"""

MERGE_PROMPT = """Some of these clusters (produced from separate chunks) may describe the same underlying need. Group cluster ids that should merge; clusters that stand alone form their own group.
Reply JSON: {"groups": [[cid, cid, ...], [cid], ...]}

Clusters:
"""


def extract_needs(client, posts, batch_size):
    needs = []
    post_by_id = {p["id"]: p for p in posts}
    for i in range(0, len(posts), batch_size):
        batch = posts[i : i + batch_size]
        payload = [
            {
                "post_id": p["id"],
                "subreddit": p["subreddit"],
                "title": p["title"],
                "text": p["selftext"][:1500],
                "top_comments": " | ".join(p.get("top_comments", []))[:1000],
            }
            for p in batch
        ]
        try:
            result = llm_json(client, EXTRACT_PROMPT + json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print(f"  批次 {i} 提取失败，跳过: {e}")
            continue
        for n in result.get("needs", []):
            src = post_by_id.get(n.get("post_id"))
            if not src or not n.get("app_shaped"):
                continue
            n["author"] = src["author"]
            n["created_utc"] = src["created_utc"]
            n["permalink"] = src["permalink"]
            needs.append(n)
        print(f"  进度 {min(i + batch_size, len(posts))}/{len(posts)}，累计需求 {len(needs)} 条")
    return needs


def cluster_needs(client, needs, kw_n):
    def one_pass(indexed):
        payload = json.dumps(
            [{"idx": i, "need": n["need_summary"], "audience": n.get("audience", "")} for i, n in indexed],
            ensure_ascii=False,
        )
        return llm_json(client, CLUSTER_PROMPT_TEMPLATE.format(kw_n=kw_n, payload=payload))["clusters"]

    indexed = list(enumerate(needs))
    if len(indexed) <= 150:
        return one_pass(indexed)

    # 超过单次上下文合理规模时：分块粗聚类，再做一次合并
    chunk_clusters = []
    for i in range(0, len(indexed), 120):
        chunk_clusters.extend(one_pass(indexed[i : i + 120]))
    merge_payload = json.dumps(
        [{"cid": i, "name": c["name"], "statement": c["need_statement"]} for i, c in enumerate(chunk_clusters)],
        ensure_ascii=False,
    )
    groups = llm_json(client, MERGE_PROMPT + merge_payload)["groups"]
    merged = []
    for group in groups:
        base = dict(chunk_clusters[group[0]])
        base["member_idx"] = [idx for cid in group for idx in chunk_clusters[cid]["member_idx"]]
        merged.append(base)
    return merged


def enrich(clusters, needs):
    rows = []
    for i, c in enumerate(clusters):
        members = [needs[idx] for idx in c.get("member_idx", []) if 0 <= idx < len(needs)]
        if not members:
            continue
        created = [m["created_utc"] for m in members]
        pay_quotes = [m["pay_signal"] for m in members if m.get("pay_signal")]
        rows.append(
            {
                "cluster_id": i,
                "name": c["name"],
                "need_statement": c["need_statement"],
                "appstore_keywords": c.get("appstore_keywords", [])[:5],
                "distinct_authors": len({m["author"] for m in members}),
                "need_count": len(members),
                "first_seen": datetime.fromtimestamp(min(created), tz=timezone.utc).date().isoformat(),
                "last_seen": datetime.fromtimestamp(max(created), tz=timezone.utc).date().isoformat(),
                "pay_signals": len(pay_quotes),
                "pay_quotes": pay_quotes[:3],
                "avg_emotion": round(sum(m.get("emotion", 3) for m in members) / len(members), 1),
                "frequencies": sorted({m.get("frequency", "occasional") for m in members}),
                "example_permalinks": [m["permalink"] for m in members[:3]],
            }
        )
    rows.sort(key=lambda r: (-r["distinct_authors"], -r["pay_signals"]))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DATA / "01_posts.jsonl"))
    args = parser.parse_args()

    cfg = load_config()
    client = llm_client()
    posts = read_jsonl(args.input)
    print(f"读入 {len(posts)} 帖，开始提取…")

    needs = extract_needs(client, posts, cfg.get("extract_batch_size", 5))
    write_jsonl(DATA / "02_needs.jsonl", needs)
    if not needs:
        print("未提取到任何需求，检查输入数据或 LLM 配置")
        return

    clusters = cluster_needs(client, needs, cfg.get("keywords_per_cluster", 3))
    write_jsonl(DATA / "02_clusters.jsonl", enrich(clusters, needs))


if __name__ == "__main__":
    main()
