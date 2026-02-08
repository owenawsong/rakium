"""
Rakium Scraper - Fetches AI benchmark data from multiple sources.
Saves structured JSON to the data/ directory.
Run manually or via GitHub Actions on a schedule.
"""

import requests
import json
import os
import sys
import time
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

TIMEOUT = 45  # seconds per request
MAX_RETRIES = 3
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def safe_request(url, retries=MAX_RETRIES):
    """GET a URL with retries and exponential backoff."""
    for attempt in range(1, retries + 1):
        try:
            print(f"  Fetching {url} (attempt {attempt}/{retries})...")
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            print(f"  ⚠ Attempt {attempt} failed: {exc}")
            if attempt < retries:
                wait = 5 * attempt
                print(f"  Waiting {wait}s before retry...")
                time.sleep(wait)
    print(f"  ✗ All {retries} attempts failed for {url}")
    return None


def extract_json_array(text, marker):
    """
    Find *marker* inside *text*, then extract the JSON array that starts
    right after it.  Handles the escaped-JSON-inside-HTML pattern where
    quotes appear as \\" in the page source.
    """
    pos = text.find(marker)
    if pos == -1:
        return None

    # Advance past the marker to the opening bracket
    start = text.find("[", pos)
    if start == -1:
        return None

    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        # Skip escaped backslashes
        if text[i : i + 2] == "\\\\":
            i += 2
            continue
        # Skip escaped quotes
        if text[i : i + 2] == '\\"':
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                raw = text[start : i + 1]
                # Un-escape the common HTML-embedded patterns
                raw = raw.replace('\\"', '"').replace("\\\\", "\\")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
        i += 1
    return None


def save_json(filename, data):
    """Write *data* as formatted JSON into DATA_DIR/filename."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"  ✓ Saved {path} ({len(json.dumps(data))} bytes)")


# ---------------------------------------------------------------------------
# Source: Artificial Analysis
# ---------------------------------------------------------------------------

# The benchmarks we care about and how to display them.
AA_BENCHMARKS = {
    "intelligence_index": {"label": "Intelligence Index", "pct": False},
    "agentic_index":      {"label": "Agentic Index",      "pct": False},
    "coding_index":       {"label": "Coding Index",        "pct": False},
    "math_index":         {"label": "Math Index",          "pct": False},
    "aime25":             {"label": "AIME 2025",           "pct": True},
    "gpqa":               {"label": "GPQA Diamond",        "pct": True},
    "hle":                {"label": "HLE",                 "pct": True},
    "mmlu_pro":           {"label": "MMLU Pro",            "pct": True},
    "humaneval":          {"label": "HumanEval",           "pct": True},
    "livecodebench":      {"label": "LiveCodeBench",       "pct": True},
}


def get_creator(model):
    """Pull a human-readable creator name from the model dict."""
    creators = model.get("model_creators")
    if not creators:
        return "Unknown"
    if isinstance(creators, str):
        return creators
    if isinstance(creators, dict):
        return creators.get("name", "Unknown")
    if isinstance(creators, list) and creators:
        first = creators[0]
        return first.get("name", str(first)) if isinstance(first, dict) else str(first)
    return "Unknown"


def fetch_artificial_analysis():
    """Scrape the Artificial Analysis leaderboard page."""
    print("\n[1/2] Artificial Analysis")
    resp = safe_request("https://artificialanalysis.ai/leaderboards/models")
    if resp is None:
        return None

    text = resp.text
    models = extract_json_array(text, '\\"models\\":[{')

    if not models:
        # Fallback: try unescaped variant
        models = extract_json_array(text, '"models":[{')

    if not models:
        print("  ✗ Could not locate model data in page source")
        return None

    print(f"  Found {len(models)} raw models")

    # ---- Build per-benchmark leaderboards --------------------------------
    benchmarks = {}
    for field, meta in AA_BENCHMARKS.items():
        entries = [m for m in models if m.get(field) is not None]
        entries.sort(key=lambda m: m.get(field, 0), reverse=True)
        entries = entries[:40]  # top 40 per benchmark

        benchmarks[field] = {
            "label": meta["label"],
            "pct": meta["pct"],
            "models": [
                {
                    "rank": i + 1,
                    "name": (m.get("name") or "N/A")[:40],
                    "score": m.get(field),
                    "creator": get_creator(m)[:25],
                    "context_window": m.get("context_window_tokens", 0),
                }
                for i, m in enumerate(entries)
            ],
        }

    # ---- Build a flat list for the comparator ----------------------------
    all_models = []
    for m in models[:100]:
        entry = {
            "name": (m.get("name") or "N/A")[:45],
            "creator": get_creator(m)[:25],
        }
        for field in AA_BENCHMARKS:
            entry[field] = m.get(field)
        all_models.append(entry)

    return {"benchmarks": benchmarks, "models": all_models}


# ---------------------------------------------------------------------------
# Source: LM Arena
# ---------------------------------------------------------------------------


def fetch_lm_arena():
    """Scrape the LM Arena (Chatbot Arena) leaderboard page."""
    print("\n[2/2] LM Arena")
    resp = safe_request("https://lmarena.ai/leaderboard")
    if resp is None:
        return None

    text = resp.text

    # The page embeds JSON data in a Next.js payload.  Try several markers.
    data = None
    for marker in ['[{\\"rank\\":', '[{\\"rankUpper\\":', '[{"rank":', '[{"rankUpper":']:
        data = extract_json_array(text, marker)
        if data:
            break

    if not data:
        print("  ✗ Could not locate leaderboard data in page source")
        return None

    print(f"  Found {len(data)} raw entries")

    results = []
    for item in data[:50]:
        results.append(
            {
                "rank": item.get("rank") or item.get("rankUpper", "-"),
                "name": (
                    item.get("modelDisplayName")
                    or item.get("model_display_name")
                    or item.get("name")
                    or "N/A"
                )[:40],
                "rating": item.get("rating") or item.get("elo", 0),
                "organization": (
                    item.get("modelOrganization")
                    or item.get("organization")
                    or "Unknown"
                )[:25],
                "votes": item.get("votes") or item.get("num_battles", 0),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("Rakium Scraper")
    print(f"Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    success_count = 0

    # --- Artificial Analysis ---
    aa = fetch_artificial_analysis()
    if aa:
        save_json("artificial_analysis.json", aa)
        success_count += 1
    else:
        print("  ✗ Artificial Analysis: no data saved")

    # --- LM Arena ---
    lma = fetch_lm_arena()
    if lma:
        save_json("lm_arena.json", lma)
        success_count += 1
    else:
        print("  ✗ LM Arena: no data saved")

    # --- Metadata ---
    meta = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "sources": {
            "artificial_analysis": aa is not None,
            "lm_arena": lma is not None,
        },
    }
    save_json("meta.json", meta)

    print(f"\nDone. {success_count}/2 sources succeeded.")

    # Exit with error if BOTH sources failed — this tells GitHub Actions
    # to skip the deploy step so the site keeps serving the previous good build.
    if success_count == 0:
        print("All sources failed. Exiting with error.")
        sys.exit(1)


if __name__ == "__main__":
    main()