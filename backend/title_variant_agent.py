"""
title_variant_agent.py

Claude-powered agent: given a single job title, returns the top 15 real-world
title variants a candidate/recruiter search should also consider, ordered
from best (closest, most standard match) to worst (loosest, still-relevant
match).

This is only ever called from routes/title_variants.py, and only on a
job_title_variants cache miss -- see that file for the caching flow. It is
not meant to be run standalone, but can be for a quick manual check:

    ANTHROPIC_API_KEY=sk-ant-... python title_variant_agent.py "AI Program Manager"
"""

import json
import sys
from typing import Optional

import anthropic

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a job title normalization engine for a job search \
platform. Given a single input job title, generate the top 15 real-world \
title variants that a person with that title would also be a strong \
candidate for, and that a job search agent should also query on their \
behalf.

Rank order matters: index 1 is the closest / most standard equivalent \
(same seniority, same core function, just different company naming \
convention). Index 15 is the loosest but still genuinely relevant variant \
(adjacent seniority or adjacent specialization, still worth searching, \
but a real candidate would need to squint a bit).

Rules:
- Do not include the exact input title itself in the list.
- No duplicates.
- No made-up or nonstandard titles that don't actually appear in job postings.
- Stay within the same general job family (don't drift into an unrelated \
discipline).
- Output ONLY valid JSON, no preamble, no markdown fences, matching this \
exact shape:

{"input_title": "<echo input>", "variants": [{"rank": 1, "title": "..."}, ...15 total...]}
"""


def get_title_variants(job_title: str, api_key: Optional[str] = None) -> dict:
    """Calls Claude and returns the parsed
    {"input_title": ..., "variants": [{"rank": 1, "title": ...}, ...]} dict.

    api_key: pass explicitly (e.g. from Flask's current_app.config) rather
    than relying on the ANTHROPIC_API_KEY env var being visible wherever this
    runs. If omitted, the SDK falls back to the env var itself.

    Raises on any failure (bad/missing key, network error, malformed model
    output) -- callers decide how to handle that (routes/title_variants.py
    falls back to trigram similarity).
    """
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": job_title}],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    # Defensive cleanup in case the model wraps output in fences anyway
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

    data = json.loads(raw_text)

    if "variants" not in data or len(data["variants"]) == 0:
        raise ValueError(f"Unexpected response shape: {data}")

    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python title_variant_agent.py \"<job title>\"", file=sys.stderr)
        sys.exit(1)

    result = get_title_variants(sys.argv[1])
    print(f"\nTop 15 variants for: {result['input_title']}\n")
    for row in result["variants"]:
        print(f"  {row['rank']:>2}. {row['title']}")
    print()
