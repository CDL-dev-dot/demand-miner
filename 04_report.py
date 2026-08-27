"""Stage 4: scoring and report.

Deterministic scores (demand heat / competition window / payment evidence) plus an
optional LLM qualitative pass (fake-need risk, Apple policy risk, differentiation).
Output: data/04_report.md and .csv. Report labels are intentionally in Chinese
(the tool author's reading language); code and logs are English.
"""
import argparse
import csv
import json
import math

from common import DATA, llm_json, read_jsonl

QUALITATIVE_PROMPT = """You are advising a solo iOS developer. For the unmet-need cluster below (mined from low-rated US App Store reviews and validated against current competitors), give a hard-nosed judgment.

Reply JSON:
- fake_need_risk: low | medium | high, with one-line reason (is this recurring across reviewers/apps or just app-specific venting?)
- apple_policy_risk: low | medium | high, with one-line reason (App Review guidelines: medical claims, adult, copyright, financial data...)
- solo_feasibility: low | medium | high, with one-line reason (can one person build & operate an MVP?)
- differentiation: one concrete angle given the competitor situation
- verdict: one of GO | WATCH | SKIP, with one-line reason

Each field must be an object: {"level": "...", "reason": "..."} (for verdict use
{"decision": "...", "reason": "..."}). Write every reason in Chinese; keep
level/decision values as the English enums above.

Cluster data:
"""


def fmt_q(v):
    """Render a qualitative field that may be a dict or a plain string."""
    if isinstance(v, dict):
        level = v.get("level") or v.get("decision") or ""
        reason = v.get("reason", "")
        return f"{level}（{reason}）" if reason else str(level)
    return v


def deterministic_scores(c):
    a = c.get("appstore", {})
    demand = min(6, c.get("distinct_reviewers", 0)) + min(2, c.get("payment_signals", 0))
    if c.get("first_seen") and c.get("last_seen") and c["first_seen"][:7] != c["last_seen"][:7]:
        demand += 2  # spans multiple months, not a one-off spike

    window = 10
    if a.get("swarm"):
        window -= 5
    leader = (a.get("top_apps") or [None])[0]
    if leader and leader["reviews"] >= 10000 and leader["rating"] >= 4.5 and not a.get("leader_stale"):
        window -= 3  # strong, healthy incumbent leader present
    if a.get("leader_stale"):
        window += 2  # stale/low-rated leader = renovation opening
    window = max(0, min(10, window))

    leader_reviews = leader["reviews"] if leader else 0
    evidence = min(10, round(math.log10(leader_reviews + 1) * 2.5, 1))  # built at scale = payment evidence

    total = round(demand * 0.4 + window * 0.35 + evidence * 0.25, 1)
    return demand, window, evidence, total


def verdict_by_rule(total, swarm):
    if swarm:
        return "WATCH-（蜂群已至）" if total >= 7 else "SKIP（蜂群已至）"
    if total >= 7:
        return "GO 候选"
    if total >= 5:
        return "WATCH 观望"
    return "SKIP 放弃"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DATA / "03_validated.jsonl"))
    parser.add_argument("--skip-llm", action="store_true", help="skip the LLM qualitative pass (auto-skipped without a key)")
    parser.add_argument("--llm-top-n", type=int, default=8)
    args = parser.parse_args()

    clusters = read_jsonl(args.input)
    scored = []
    for c in clusters:
        demand, window, evidence, total = deterministic_scores(c)
        c["scores"] = {"demand": demand, "window": window, "evidence": evidence, "total": total}
        c["verdict"] = verdict_by_rule(total, c.get("appstore", {}).get("swarm"))
        scored.append(c)
    scored.sort(key=lambda c: -c["scores"]["total"])

    from common import llm_available

    use_llm = not args.skip_llm and llm_available()
    if use_llm:
        from common import llm_client

        client = llm_client()
        for c in scored[: args.llm_top_n]:
            try:
                c["qualitative"] = llm_json(client, QUALITATIVE_PROMPT + json.dumps(c, ensure_ascii=False), purpose="reasoning")
            except Exception as e:
                print(f"  qualitative pass failed {c['name']}: {e}")
    else:
        print("skipping LLM qualitative pass (--skip-llm or no LLM backend configured)")

    md = ["# 需求挖掘报告\n", "| # | 需求簇 | 独立评论用户 | 付费证据 | 竞品 | 新品 | 总分 | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(scored, 1):
        a = c.get("appstore", {})
        md.append(
            f"| {i} | {c['name']} | {c.get('distinct_reviewers', 0)} | {c.get('payment_signals', 0)} "
            f"| {a.get('relevant_matched', a.get('total_matched', 0))} | {a.get('new_apps_count', 0)} | {c['scores']['total']} | {c['verdict']} |"
        )

    for c in scored:
        a = c.get("appstore", {})
        md += [
            f"\n## {c['name']}\n",
            f"- 需求陈述：{c['need_statement']}",
            f"- 信号：{c.get('distinct_reviewers', 0)} 个独立评论用户，来自 {c.get('source_app_count', 0)} 款 App，"
            f"{c.get('first_seen', '?')} ~ {c.get('last_seen', '?')}，付费证据 {c.get('payment_signals', 0)} 条，"
            f"评论星级均值 {c.get('avg_source_rating', '-')}，情绪均值 {c.get('avg_emotion', '-')}",
            f"- 竞争：相关竞品 {a.get('relevant_matched', 0)} 款（原始匹配 {a.get('total_matched', 0)}）；近 18 月相关新品 {a.get('new_apps_count', 0)} 款"
            f"{'（蜂群警报）' if a.get('swarm') else ''}{'；头部竞品老旧/低分（翻新机会）' if a.get('leader_stale') else ''}",
            f"- 评分：需求 {c['scores']['demand']}/10 · 窗口 {c['scores']['window']}/10 · 付费证据 {c['scores']['evidence']}/10 · **总分 {c['scores']['total']}** → {c['verdict']}",
        ]
        if a.get("top_apps"):
            md.append("- 头部竞品：")
            for t in a["top_apps"]:
                md.append(f"  - {t['name']}｜评分 {t['rating']}｜评论 {t['reviews']}｜{t['price']}｜上架 {t['released']}｜更新 {t['last_update']}")
        if c.get("source_apps"):
            md.append("- 需求来源 App：" + "、".join(c["source_apps"][:8]))
        if c.get("payment_quotes"):
            md.append("- 付费证据原文：" + "；".join(f"「{q}」" for q in c["payment_quotes"]))
        if c.get("qualitative"):
            q = c["qualitative"]
            md.append(
                f"- LLM 判定：伪需求风险 {fmt_q(q.get('fake_need_risk'))}｜政策风险 {fmt_q(q.get('apple_policy_risk'))}"
                f"｜单人可行性 {fmt_q(q.get('solo_feasibility'))}｜差异化：{fmt_q(q.get('differentiation'))}｜结论：{fmt_q(q.get('verdict'))}"
            )
        if c.get("example_permalinks"):
            md.append("- 溯源：" + " ".join(c["example_permalinks"]))

    report_path = DATA / "04_report.md"
    report_path.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {report_path}")

    csv_path = DATA / "04_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "distinct_reviewers", "payment_signals", "source_app_count", "total_matched", "new_apps", "swarm", "demand", "window", "evidence", "total", "verdict"])
        for c in scored:
            a = c.get("appstore", {})
            s = c["scores"]
            w.writerow([c["name"], c.get("distinct_reviewers", 0), c.get("payment_signals", 0), c.get("source_app_count", 0), a.get("total_matched", 0),
                        a.get("new_apps_count", 0), a.get("swarm", False), s["demand"], s["window"], s["evidence"], s["total"], c["verdict"]])
    print(f"CSV -> {csv_path}")


if __name__ == "__main__":
    main()
