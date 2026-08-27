"""Shared helpers: config loading, JSONL IO, OpenAI-compatible LLM client."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
load_dotenv(ROOT / ".env")


def load_config():
    import yaml

    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows -> {path}")


def llm_client():
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("OPENAI_API_KEY not set: copy .env.example to .env and fill in your LLM endpoint")
    return OpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL") or None)


def _parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        s, e = text.find(open_ch), text.rfind(close_ch)
        if s != -1 and e > s:
            return json.loads(text[s : e + 1])
    raise ValueError(f"no valid JSON in LLM reply: {text[:200]}")


def llm_json(client, prompt, system="You are a precise analyst. Reply with valid JSON only, no prose.", retries=2):
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    last_err = None
    for _ in range(retries + 1):
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        try:
            return _parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise last_err
