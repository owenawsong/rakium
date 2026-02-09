#!/usr/bin/env python3
"""
AI Benchmark Aggregator Scraper (Rakium)
Extracts data from multiple AI leaderboard sources.

Sources & Methods:
- Arena/LM Arena: Tavily API (with include_raw_content=True)
- LiveBench: HuggingFace Dataset Viewer API (primary) / Tavily / Steel fallback
- YUPP: Steel.dev /scrape endpoint (escaped JSON with nested model_rating structure)
- Artificial Analysis: HTTP (escaped JSON in Next.js RSC streaming format)
- OpenRouter: HTTP API
- EQ Bench: HTTP + Steel fallback
"""

import json
import re
import time
import os
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import requests
import pandas as pd

# Tavily for Arena.ai
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

# Steel.dev cloud browser
STEEL_API_KEY = os.environ.get("STEEL_API_KEY")
STEEL_BASE_URL = "https://api.steel.dev/v1"

# Configuration
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# User-Agent header
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 5


def fetch_with_retry(url, headers=None, timeout=30):
    """Fetch URL with retry logic."""
    headers = headers or HEADERS
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                print(f"    Retry {attempt + 1}/{MAX_RETRIES} for {url}: {e}")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise e
    return None


# =============================================================================
# STEEL.DEV CLOUD BROWSER - /scrape endpoint
# =============================================================================
def fetch_with_steel(url, timeout=60):
    """
    Fetch page content using Steel.dev's /scrape endpoint.
    This handles JS rendering automatically - no need to create sessions manually.
    Returns the HTML content of the fully-rendered page.
    """
    if not STEEL_API_KEY:
        raise ValueError("STEEL_API_KEY not set. Get one at https://steel.dev")

    headers = {
        "Steel-Api-Key": STEEL_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "url": url,
        "format": ["html"],
    }

    try:
        response = requests.post(
            f"{STEEL_BASE_URL}/scrape",
            headers=headers,
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()
        data = response.json()

        # Steel /v1/scrape response structure:
        # {
        #   "content": { "html": "...", "cleaned_html": "...", "markdown": "...", "readability": {...} },
        #   "metadata": { "title": "...", ... },
        #   "links": [...],
        # }
        html = ""
        content = data.get("content")

        if isinstance(content, dict):
            # Correct path: content is an object with html/cleaned_html/markdown
            html = content.get("html", "") or content.get("cleaned_html", "") or ""
        elif isinstance(content, str):
            # Fallback: content might be a string in some API versions
            html = content

        if not html:
            print(f"    Steel response keys: {list(data.keys())}")
            if isinstance(content, dict):
                print(f"    Steel content keys: {list(content.keys())}")
            debug_file = DATA_DIR / f"steel_debug_{int(time.time())}.json"
            with open(debug_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            print(f"    Saved debug response to {debug_file}")

        return html

    except requests.RequestException as e:
        print(f"    Steel scrape error for {url}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"    Response status: {e.response.status_code}")
            print(f"    Response body: {e.response.text[:500]}")
        raise e


def extract_json_from_html(html, start_marker, max_length=500000):
    """Extract JSON array/object from HTML by finding start marker."""
    start_idx = html.find(start_marker)
    if start_idx == -1:
        return None

    start_idx += len(start_marker)

    # Skip whitespace
    while start_idx < len(html) and html[start_idx] in ' \t\n\r':
        start_idx += 1

    json_str = html[start_idx:start_idx + max_length]

    # Determine opening bracket
    if not json_str or json_str[0] not in '{[':
        return None

    # Find matching closing bracket
    depth = 0
    in_string = False
    escape_next = False
    end_idx = 0

    for i, char in enumerate(json_str):
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char in '{[':
                depth += 1
            elif char in '}]':
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

    if end_idx == 0:
        return None

    json_str = json_str[:end_idx]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def _extract_escaped_json_block(text, start_idx, max_length=10000000):
    """
    Extract a JSON array or object from escaped text starting at start_idx.
    Handles Next.js RSC streaming format where quotes are escaped as \\".

    The bracket matching tracks both [] and {} pairs to correctly handle
    nested structures. Escaped quotes (\\\") are skipped so brackets inside
    string values don't interfere with depth counting.

    Returns (parsed_json, end_index) or (None, start_idx) if extraction fails.
    """
    if start_idx >= len(text):
        return None, start_idx

    opener = text[start_idx]
    if opener == '[':
        closer = ']'
    elif opener == '{':
        closer = '}'
    else:
        return None, start_idx

    # Track depth for BOTH bracket types to handle nested structures correctly
    depth = 0
    i = start_idx
    end_pos = start_idx
    limit = min(start_idx + max_length, len(text))

    while i < limit:
        # Skip escaped backslash
        if text[i:i+2] == '\\\\':
            i += 2
            continue
        # Skip escaped quote (content inside strings won't affect bracket counting)
        if text[i:i+2] == '\\"':
            i += 2
            continue
        if text[i] in '[{':
            depth += 1
        elif text[i] in ']}':
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break
        i += 1

    if end_pos <= start_idx:
        return None, start_idx

    json_str = text[start_idx:end_pos]
    # Unescape the JSON string
    json_str = json_str.replace('\\"', '"').replace('\\\\', '\\')

    try:
        result = json.loads(json_str)
        return result, end_pos
    except json.JSONDecodeError:
        return None, start_idx


def extract_escaped_json_array(text, escaped_marker, max_length=10000000):
    """
    Extract a JSON array from text where the JSON is embedded with escaped quotes.
    Next.js RSC streaming format uses \\" instead of " for JSON strings.

    Args:
        text: The raw HTML/page text
        escaped_marker: The marker with escaped quotes, e.g. '\\"models\\":'
        max_length: Maximum characters to scan

    Returns:
        Parsed JSON list, or None if not found
    """
    start_idx = text.find(escaped_marker)
    if start_idx == -1:
        return None

    start_idx += len(escaped_marker)

    # Skip whitespace
    while start_idx < len(text) and text[start_idx] in ' \t\n\r':
        start_idx += 1

    if start_idx >= len(text) or text[start_idx] != '[':
        return None

    result, _ = _extract_escaped_json_block(text, start_idx, max_length)
    if isinstance(result, list):
        return result
    return None


def extract_escaped_json_object(text, escaped_marker, max_length=10000000):
    """
    Extract a JSON object from text where the JSON is embedded with escaped quotes.
    Like extract_escaped_json_array but for {} objects.

    Returns:
        Parsed JSON dict, or None if not found
    """
    start_idx = text.find(escaped_marker)
    if start_idx == -1:
        return None

    start_idx += len(escaped_marker)

    # Skip whitespace
    while start_idx < len(text) and text[start_idx] in ' \t\n\r':
        start_idx += 1

    if start_idx >= len(text) or text[start_idx] != '{':
        return None

    result, _ = _extract_escaped_json_block(text, start_idx, max_length)
    if isinstance(result, dict):
        return result
    return None


# =============================================================================
# ARENA / LM ARENA - Tavily API
# =============================================================================
def get_tavily_keys():
    """Load Tavily API keys from environment or file."""
    tavily_keys = []

    # Check environment variables
    for i in range(1, 7):
        key = os.environ.get(f"TAVILY_API_KEY_{i}")
        if key:
            tavily_keys.append(key)

    # Also check the generic key
    key = os.environ.get("TAVILY_API_KEY")
    if key and key not in tavily_keys:
        tavily_keys.append(key)

    # Try to read from file
    if not tavily_keys:
        key_file = Path("tavily_keys.txt")
        if key_file.exists():
            with open(key_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        tavily_keys.append(line)

    return tavily_keys


def scrape_arena():
    """
    Scrape Arena/LM Arena leaderboard using Tavily API.
    Uses include_raw_content=True to get the full page text,
    then parses model data from it.
    """
    print("Scraping Arena/LM Arena (Tavily)...")

    results = {
        "source": "arena.ai (via Tavily)",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }

    if not TAVILY_AVAILABLE:
        results["error"] = "Tavily not installed. Run: pip install tavily-python"
        return results

    tavily_keys = get_tavily_keys()
    if not tavily_keys:
        results["error"] = "No Tavily API key found"
        return results

    # Categories to scrape
    categories = [
        {"url": "https://lmarena.ai/leaderboard", "name": "overall"},
        {"url": "https://lmarena.ai/leaderboard/text", "name": "text"},
        {"url": "https://lmarena.ai/leaderboard/vision", "name": "vision"},
        {"url": "https://lmarena.ai/leaderboard/image", "name": "image"},
        {"url": "https://lmarena.ai/leaderboard/video", "name": "video"},
        {"url": "https://lmarena.ai/leaderboard/coding", "name": "coding"},
    ]

    for cat in categories:
        print(f"  Scraping: {cat['name']}...")
        models = []

        for api_key in tavily_keys:
            try:
                client = TavilyClient(api_key=api_key)

                response = client.search(
                    query=f"AI model leaderboard rankings from {cat['url']}",
                    max_results=5,
                    include_raw_content=True,
                    search_depth="advanced"
                )

                models = parse_tavily_arena_response(response)

                if models:
                    print(f"    Found {len(models)} models with key ...{api_key[-6:]}")
                    break
                else:
                    print(f"    No models parsed with key ...{api_key[-6:]}, trying next...")

            except Exception as e:
                print(f"    Tavily error with key ...{api_key[-6:]}: {e}")
                continue

        if models:
            results["categories"][cat["name"]] = {
                "url": cat["url"],
                "models": models,
                "num_models": len(models)
            }
        else:
            print(f"    WARNING: No models found for {cat['name']}")
            results["categories"][cat["name"]] = {
                "url": cat["url"],
                "models": [],
                "num_models": 0,
                "error": "No models found from Tavily"
            }

    return results


def parse_tavily_arena_response(response):
    """
    Parse Tavily search response for Arena leaderboard data.

    Tavily response structure:
    {
        "query": "...",
        "results": [
            {
                "title": "...",
                "url": "...",
                "content": "short snippet",
                "raw_content": "full page text (only if include_raw_content=True)",
                "score": 0.95
            },
            ...
        ]
    }
    """
    all_models = []

    results_list = response.get("results", [])

    for result in results_list:
        # Try raw_content first (full page), then fall back to content (snippet)
        for content_field in ["raw_content", "content"]:
            content = result.get(content_field)
            if not content:
                continue

            # Strategy 1: Try to find a JSON array in the content
            models = try_parse_json_array(content)
            if models:
                all_models.extend(models)
                break

            # Strategy 2: Parse tabular/structured text
            models = try_parse_structured_text(content)
            if models:
                all_models.extend(models)
                break

    # Deduplicate by model name
    seen = set()
    unique_models = []
    for model in all_models:
        name = model.get("name", model.get("model", "")).strip()
        if name and name not in seen:
            seen.add(name)
            unique_models.append(model)

    return unique_models


def try_parse_json_array(text):
    """Try to extract a JSON array of model data from text."""
    models = []

    json_matches = re.finditer(r'\[[\s\S]*?\]', text)
    for match in json_matches:
        try:
            data = json.loads(match.group())
            if isinstance(data, list) and len(data) > 0:
                first = data[0]
                if isinstance(first, dict):
                    model_keys = {"name", "model", "rank", "elo", "rating", "organization"}
                    if model_keys.intersection(set(first.keys())):
                        for item in data:
                            models.append({
                                "rank": item.get("rank"),
                                "name": item.get("model", item.get("name", "")),
                                "rating": item.get("elo", item.get("rating", item.get("score"))),
                                "organization": item.get("organization", item.get("org", "")),
                                "votes": item.get("votes", item.get("num_battles")),
                            })
                        return models
        except (json.JSONDecodeError, TypeError):
            continue

    return models


def try_parse_structured_text(text):
    """Parse structured text formats for model rankings."""
    models = []

    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        patterns = [
            # Rank. Name - Rating - Org
            r'^\s*(\d+)\.\s*(.+?)\s*[-\u2013|]\s*(\d+)\s*[-\u2013|]\s*(.+)$',
            # Rank. Name - Rating
            r'^\s*(\d+)\.\s*(.+?)\s*[-\u2013|]\s*(\d[\d.]+)',
            # Name | Rating | Org (table-like)
            r'^\s*(.+?)\s*\|\s*(\d[\d.]+)\s*\|\s*(.+)$',
            # Rank | Name | Rating
            r'^\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\d[\d.]+)',
        ]

        for i, pattern in enumerate(patterns):
            match = re.match(pattern, line)
            if match:
                groups = match.groups()
                if i == 0:  # Rank, Name, Rating, Org
                    models.append({
                        "rank": int(groups[0]),
                        "name": groups[1].strip(),
                        "rating": float(groups[2]),
                        "organization": groups[3].strip()
                    })
                elif i == 1:  # Rank, Name, Rating
                    models.append({
                        "rank": int(groups[0]),
                        "name": groups[1].strip(),
                        "rating": float(groups[2])
                    })
                elif i == 2:  # Name, Rating, Org
                    models.append({
                        "name": groups[0].strip(),
                        "rating": float(groups[1]),
                        "organization": groups[2].strip()
                    })
                elif i == 3:  # Rank, Name, Rating
                    models.append({
                        "rank": int(groups[0]),
                        "name": groups[1].strip(),
                        "rating": float(groups[2])
                    })
                break

    return models


# =============================================================================
# LIVEBENCH - HuggingFace API (primary) / Tavily (fallback) / Steel (last resort)
# =============================================================================
def scrape_livebench():
    """
    Scrape LiveBench leaderboard data.

    Strategy (3-tier):
      1. HuggingFace Dataset Viewer API (JSON, no browser needed)
         - LiveBench publishes data at livebench/model_judgment on HF
      2. Tavily search (if HF fails)
      3. Steel browser (last resort - often returns empty SPA shell)
    """
    print("Scraping LiveBench...")

    results = {
        "source": "livebench.ai",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }

    # Tier 1: HuggingFace Dataset Viewer API
    print("  Tier 1: Trying HuggingFace Dataset Viewer API...")
    models = _scrape_livebench_huggingface()
    if models:
        results["source"] = "livebench.ai (via HuggingFace API)"
        results["categories"]["overall"] = {
            "models": models,
            "num_models": len(models)
        }
        print(f"  SUCCESS: Found {len(models)} models from HuggingFace")
        return results

    # Tier 2: Tavily search
    print("  Tier 2: Trying Tavily search...")
    models = _scrape_livebench_tavily()
    if models:
        results["source"] = "livebench.ai (via Tavily)"
        results["categories"]["overall"] = {
            "models": models,
            "num_models": len(models)
        }
        print(f"  SUCCESS: Found {len(models)} models from Tavily")
        return results

    # Tier 3: Steel browser (last resort)
    print("  Tier 3: Trying Steel browser...")
    if STEEL_API_KEY:
        try:
            html = fetch_with_steel("https://livebench.ai")
            if html:
                debug_file = DATA_DIR / "livebench_raw.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  Saved raw HTML ({len(html)} chars) to {debug_file}")

                models = extract_models_from_livebench_html(html)
                if models:
                    results["source"] = "livebench.ai (via Steel)"
                    results["categories"]["overall"] = {
                        "models": models,
                        "num_models": len(models)
                    }
                    print(f"  SUCCESS: Found {len(models)} models from Steel")
                    return results
                else:
                    print("  No models extracted from Steel HTML")
        except Exception as e:
            print(f"  Steel error: {e}")
    else:
        print("  STEEL_API_KEY not set, skipping Steel")

    # All tiers failed
    print("  WARNING: All tiers failed for LiveBench")
    results["categories"]["overall"] = {
        "models": [],
        "num_models": 0,
        "note": "All extraction methods failed"
    }
    return results


def _scrape_livebench_huggingface():
    """
    Fetch LiveBench data from HuggingFace Dataset Viewer API.

    LiveBench publishes results to HuggingFace datasets. We use the
    datasets-server API to get rows without needing pyarrow/parquet.

    Endpoint: https://datasets-server.huggingface.co/rows
    """
    HF_BASE = "https://datasets-server.huggingface.co"
    DATASET = "livebench/model_judgment"

    try:
        # Step 1: Get dataset info to find available configs/splits
        info_url = f"{HF_BASE}/info?dataset={DATASET}"
        info_resp = requests.get(info_url, headers=HEADERS, timeout=30)
        info_resp.raise_for_status()
        info_data = info_resp.json()

        dataset_info = info_data.get("dataset_info", {})
        if not dataset_info:
            print("    No dataset_info found")
            return []

        # Find a config with data
        config_name = None
        split_name = None

        for cfg_name, cfg_data in dataset_info.items():
            splits = cfg_data.get("splits", {})
            if splits:
                config_name = cfg_name
                # Prefer 'train' split, otherwise take the first available
                if "train" in splits:
                    split_name = "train"
                else:
                    split_name = next(iter(splits))
                break

        if not config_name or not split_name:
            print("    No suitable config/split found in dataset")
            return []

        print(f"    Using config={config_name}, split={split_name}")

        # Step 2: Fetch rows in batches
        all_rows = []
        offset = 0
        batch_size = 100
        max_rows = 5000  # Safety limit

        while offset < max_rows:
            rows_url = (
                f"{HF_BASE}/rows?dataset={DATASET}"
                f"&config={config_name}&split={split_name}"
                f"&offset={offset}&length={batch_size}"
            )
            resp = requests.get(rows_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            rows_data = resp.json()

            rows = rows_data.get("rows", [])
            if not rows:
                break

            for row_wrapper in rows:
                row = row_wrapper.get("row", row_wrapper)
                all_rows.append(row)

            print(f"    Fetched {len(all_rows)} rows so far...")

            if len(rows) < batch_size:
                break
            offset += batch_size

        if not all_rows:
            print("    No rows returned from HuggingFace")
            return []

        print(f"    Total rows fetched: {len(all_rows)}")

        # Step 3: Aggregate scores by model
        # LiveBench data typically has per-question scores; we average them per model
        model_scores = {}
        for row in all_rows:
            model_name = row.get("model") or row.get("model_name") or row.get("name")
            if not model_name:
                continue

            score = row.get("score") or row.get("global_avg") or row.get("average")
            if score is None:
                # Try to find any numeric score field
                for key in ["accuracy", "correct", "result", "value"]:
                    if key in row and isinstance(row[key], (int, float)):
                        score = row[key]
                        break

            if model_name not in model_scores:
                model_scores[model_name] = {"scores": [], "org": row.get("organization", "")}

            if score is not None:
                try:
                    model_scores[model_name]["scores"].append(float(score))
                except (ValueError, TypeError):
                    pass

        # Build model list with averaged scores
        models = []
        for name, data in model_scores.items():
            avg_score = None
            if data["scores"]:
                avg_score = round(sum(data["scores"]) / len(data["scores"]), 2)
            models.append({
                "name": name,
                "score": avg_score,
                "organization": data["org"],
                "num_scores": len(data["scores"])
            })

        # Sort by score descending
        models.sort(key=lambda x: x.get("score") or 0, reverse=True)
        return models

    except Exception as e:
        print(f"    HuggingFace API error: {e}")
        return []


def _scrape_livebench_tavily():
    """Fallback: Try to get LiveBench data via Tavily search."""
    if not TAVILY_AVAILABLE:
        return []

    tavily_keys = get_tavily_keys()
    if not tavily_keys:
        return []

    for api_key in tavily_keys:
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query="LiveBench AI model leaderboard rankings scores site:livebench.ai",
                max_results=5,
                include_raw_content=True,
                search_depth="advanced"
            )

            models = []
            for result in response.get("results", []):
                for content_field in ["raw_content", "content"]:
                    content = result.get(content_field)
                    if not content:
                        continue

                    # Try parsing structured text
                    parsed = try_parse_structured_text(content)
                    if parsed and len(parsed) > 3:
                        models.extend(parsed)
                        break

                    # Try JSON arrays
                    parsed = try_parse_json_array(content)
                    if parsed and len(parsed) > 3:
                        models.extend(parsed)
                        break

            if models:
                # Deduplicate
                seen = set()
                unique = []
                for m in models:
                    n = m.get("name", "")
                    if n and n not in seen:
                        seen.add(n)
                        unique.append(m)
                return unique

        except Exception as e:
            print(f"    Tavily error with key ...{api_key[-6:]}: {e}")
            continue

    return []


def extract_models_from_livebench_html(html):
    """Extract model data from LiveBench HTML."""
    models = []

    # Strategy 0: Try escaped JSON (Next.js RSC streaming format)
    # Many modern Next.js sites use this instead of __NEXT_DATA__
    for marker in ['\\"models\\":', '\\"leaderboard\\":', '\\"data\\":', '\\"rankings\\":']:
        escaped_data = extract_escaped_json_array(html, marker)
        if escaped_data and isinstance(escaped_data, list) and len(escaped_data) > 3:
            first = escaped_data[0]
            if isinstance(first, dict) and any(k in first for k in ["model", "name", "model_name", "score", "global_avg"]):
                for item in escaped_data:
                    if isinstance(item, dict):
                        models.append({
                            "name": item.get("model_name", item.get("name", item.get("model", ""))),
                            "score": item.get("score", item.get("global_avg", item.get("average"))),
                            "organization": item.get("organization", item.get("org", "")),
                        })
                if models:
                    print(f"    Found via escaped JSON marker: {marker}")
                    return models

    # Strategy 1: Try Next.js __NEXT_DATA__
    next_data_match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if next_data_match:
        try:
            data = json.loads(next_data_match.group(1))
            props = data.get("props", {}).get("pageProps", {})

            for key in ["models", "leaderboard", "data", "rankings"]:
                models_data = props.get(key)
                if isinstance(models_data, list) and models_data:
                    for model in models_data:
                        if isinstance(model, dict):
                            models.append({
                                "name": model.get("model_name", model.get("name", model.get("model", ""))),
                                "score": model.get("score", model.get("global_avg", model.get("average"))),
                                "organization": model.get("organization", model.get("org", "")),
                            })
                    if models:
                        return models
        except (json.JSONDecodeError, KeyError) as e:
            print(f"    Next.js data parse error: {e}")

    # Strategy 2: Look for JSON data in script tags
    script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for script_content in script_matches:
        if 'model' in script_content.lower() and ('score' in script_content.lower() or 'elo' in script_content.lower()):
            json_arrays = re.finditer(r'\[[\s\S]{20,}?\]', script_content)
            for jm in json_arrays:
                try:
                    arr = json.loads(jm.group())
                    if isinstance(arr, list) and len(arr) > 3:
                        first = arr[0]
                        if isinstance(first, dict) and any(k in first for k in ["model", "name", "model_name"]):
                            for item in arr:
                                models.append({
                                    "name": item.get("model_name", item.get("name", item.get("model", ""))),
                                    "score": item.get("score", item.get("global_avg")),
                                })
                            return models
                except (json.JSONDecodeError, TypeError):
                    continue

    # Strategy 3: Parse table from HTML
    soup = BeautifulSoup(html, 'lxml')
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        header_row = rows[0]
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]

        name_idx = None
        score_idx = None
        for i, h in enumerate(headers):
            if any(kw in h for kw in ['model', 'name']):
                name_idx = i
            if any(kw in h for kw in ['score', 'average', 'global', 'overall']):
                score_idx = i

        if name_idx is not None:
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) > name_idx:
                    name = cells[name_idx].get_text(strip=True)
                    score = None
                    if score_idx is not None and len(cells) > score_idx:
                        score_text = cells[score_idx].get_text(strip=True)
                        try:
                            score = float(score_text)
                        except ValueError:
                            pass
                    if name and len(name) > 2:
                        models.append({"name": name, "score": score})

            if models:
                return models

    # Strategy 4: Look for known model name patterns (last resort)
    known_prefixes = ['gpt-', 'claude-', 'gemini-', 'llama-', 'mistral-', 'qwen-', 'deepseek-']
    text_content = soup.get_text()
    for prefix in known_prefixes:
        pattern = rf'({re.escape(prefix)}[\w.-]+)'
        found = re.findall(pattern, text_content, re.IGNORECASE)
        for name in found:
            if name not in [m.get("name") for m in models]:
                models.append({"name": name})

    return models


# =============================================================================
# YUPP - Steel Browser (JS-rendered)
# =============================================================================
def scrape_yupp():
    """
    Scrape YUPP leaderboard using Steel's /scrape endpoint.
    Tavily doesn't work well for this site.
    """
    print("Scraping YUPP (Steel browser)...")

    results = {
        "source": "yupp.ai (via Steel)",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }

    if not STEEL_API_KEY:
        results["error"] = "STEEL_API_KEY not set"
        print("  ERROR: STEEL_API_KEY not set, skipping YUPP")
        return results

    base_url = "https://yupp.ai"

    categories = [
        {"url": f"{base_url}/leaderboard", "name": "overall"},
    ]

    for cat in categories:
        print(f"  Scraping: {cat['name']}...")
        try:
            html = fetch_with_steel(cat["url"])

            if not html:
                print(f"    Empty response for {cat['name']}")
                continue

            # Save raw HTML for debugging
            debug_file = DATA_DIR / f"yupp_{cat['name']}.html"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"    Saved raw HTML ({len(html)} chars)")

            models = extract_models_from_yupp_html(html)

            if models:
                results["categories"][cat["name"]] = {
                    "url": cat["url"],
                    "models": models,
                    "num_models": len(models)
                }
                print(f"    Found {len(models)} models")
            else:
                results["categories"][cat["name"]] = {
                    "url": cat["url"],
                    "models": [],
                    "num_models": 0,
                    "note": "Could not extract models - HTML saved for debugging"
                }
                print(f"    No models extracted")

        except Exception as e:
            print(f"    Error: {e}")
            results["categories"][cat["name"]] = {
                "url": cat["url"],
                "error": str(e)
            }

    return results


def _extract_yupp_model_from_rating(item):
    """
    Extract a normalized model dict from a YUPP leaderboard item.

    Actual YUPP structure (from diagnostic):
      {
        "model_rating": {
          "taxonomy_id": "...",
          "taxonomy_label": "Claude Opus 4.6 (Thinking)",  <-- model name
          "rating": 1416.84,                                <-- score
          "rating_lower": 1411.87,
          "rating_upper": 1421.61,
          "rank": 1,
          "global_rank": 1,
          "active_rank": 1,
          "wins": 3720,
          "losses": 1305,
          "ties": 0,
          "downvotes": 60,
          "win_notes": {"Informative": 1776, ...},
          ...
        }
      }

    The model data is ALL inside the model_rating sub-object.
    """
    if not isinstance(item, dict):
        return None

    mr = item.get("model_rating")
    if not isinstance(mr, dict):
        # Maybe the item itself IS the model_rating (no wrapper)
        mr = item

    # Model name: taxonomy_label is the display name
    name = (
        mr.get("taxonomy_label")
        or mr.get("model_name")
        or mr.get("model_id")
        or item.get("model_name")
        or item.get("name")
        or item.get("model")
        or ""
    )

    if not name:
        return None

    # Score: rating is the ELO-like rating
    score = mr.get("rating") or item.get("rating") or item.get("elo_score") or item.get("score")

    result = {
        "name": name,
        "score": score,
        "rank": mr.get("rank") or mr.get("global_rank"),
    }

    # Extra fields
    if "wins" in mr:
        result["wins"] = mr["wins"]
    if "losses" in mr:
        result["losses"] = mr["losses"]
    if mr.get("rating_lower") and mr.get("rating_upper"):
        result["ci_lower"] = mr["rating_lower"]
        result["ci_upper"] = mr["rating_upper"]

    # Top-level extras
    for key in ["organization", "license", "knowledge_cutoff", "vibe_score"]:
        if key in item:
            result[key] = item[key]

    return result


def _walk_for_models(obj, depth=0):
    """
    Recursively walk a parsed JSON structure to find ALL 'models' arrays.
    Returns a flat list of all model items found anywhere in the structure.
    """
    if depth > 10:
        return []

    results = []

    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "models" and isinstance(val, list):
                results.extend(val)
            else:
                results.extend(_walk_for_models(val, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_walk_for_models(item, depth + 1))

    return results


def extract_models_from_yupp_html(html):
    """
    Extract model data from YUPP HTML.

    YUPP's data structure is:
      "leaderboardData": {
        "highlights": [
          {"title": "Most preferred", "models": [...]},
          {"title": "Best text models", "models": [...]},
          ...
        ],
        "best_and_worst": [...],
        ...
      }

    Each "models" array contains items with a nested "model_rating" object
    where the actual data lives (taxonomy_label=name, rating=score).
    """
    models = []

    # Strategy 0: Extract the full leaderboardData object, then walk it
    # to find ALL model arrays (highlights, best_and_worst, etc.)
    print("      Trying leaderboardData object extraction...")
    leaderboard_data = extract_escaped_json_object(html, '\\"leaderboardData\\":')
    if leaderboard_data and isinstance(leaderboard_data, dict):
        print(f"      Extracted leaderboardData with keys: {list(leaderboard_data.keys())}")

        # Walk the entire structure to find ALL "models" arrays
        all_model_items = _walk_for_models(leaderboard_data)
        print(f"      Found {len(all_model_items)} total model items across all sections")

        seen_names = set()
        for item in all_model_items:
            parsed = _extract_yupp_model_from_rating(item)
            if parsed and parsed["name"] not in seen_names:
                seen_names.add(parsed["name"])
                models.append(parsed)

        if models:
            # Sort by rank if available, otherwise by score
            models.sort(key=lambda x: x.get("rank") or 99999)
            print(f"      Deduplicated to {len(models)} unique models")
            return models

    # Strategy 1: Find ALL \"models\": arrays across the entire HTML
    # (fallback if leaderboardData extraction fails)
    print("      Trying all \\\"models\\\": occurrences...")
    search_start = 0
    marker = '\\"models\\":'
    all_model_items = []

    while True:
        idx = html.find(marker, search_start)
        if idx == -1:
            break

        arr_start = idx + len(marker)
        # Skip whitespace
        while arr_start < len(html) and html[arr_start] in ' \t\n\r':
            arr_start += 1

        if arr_start < len(html) and html[arr_start] == '[':
            result, end_pos = _extract_escaped_json_block(html, arr_start)
            if isinstance(result, list):
                all_model_items.extend(result)
                print(f"      Found models array at index {idx} with {len(result)} items")
            search_start = end_pos if end_pos > arr_start else arr_start + 1
        else:
            search_start = arr_start + 1

    if all_model_items:
        seen_names = set()
        for item in all_model_items:
            parsed = _extract_yupp_model_from_rating(item)
            if parsed and parsed["name"] not in seen_names:
                seen_names.add(parsed["name"])
                models.append(parsed)

        if models:
            models.sort(key=lambda x: x.get("rank") or 99999)
            print(f"      Deduplicated to {len(models)} unique models from all arrays")
            return models

    # Strategy 2: BeautifulSoup table parsing
    soup = BeautifulSoup(html, 'lxml')
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]

        name_idx = None
        score_idx = None
        for i, h in enumerate(headers):
            if any(kw in h for kw in ['model', 'name']):
                name_idx = i
            if any(kw in h for kw in ['score', 'elo', 'rating']):
                score_idx = i

        if name_idx is not None:
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) > name_idx:
                    name = cells[name_idx].get_text(strip=True)
                    score = None
                    if score_idx is not None and len(cells) > score_idx:
                        try:
                            score = float(cells[score_idx].get_text(strip=True))
                        except ValueError:
                            pass
                    if name and len(name) > 2:
                        models.append({"name": name, "score": score})

            if models:
                return models

    return models


# =============================================================================
# ARTIFICIAL ANALYSIS - HTTP (Direct)
# =============================================================================
def scrape_artificial_analysis():
    """
    Scrape Artificial Analysis.
    The site uses Next.js RSC streaming with escaped JSON:
      self.__next_f.push([1,"..."]) containing \\"models\\":[{...}]
    The JSON has escaped quotes (\\") that need to be unescaped before parsing.
    """
    print("Scraping Artificial Analysis...")

    results = {
        "source": "artificialanalysis.ai",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "models": []
    }

    url = "https://artificialanalysis.ai/leaderboards/models"

    try:
        html = fetch_with_retry(url)
        print(f"  Fetched {len(html)} chars from HTTP")

        # Primary method: Extract escaped JSON from Next.js RSC streaming format
        # The HTML contains: \\"models\\":[{\\"additional_text\\"... (escaped quotes)
        models_data = extract_escaped_json_array(html, '\\"models\\":')
        if not models_data:
            # Try a more specific marker that confirms it's the right array
            specific_idx = html.find('\\"models\\":[{\\"additional_text\\"')
            if specific_idx != -1:
                models_data = extract_escaped_json_array(
                    html[specific_idx:], '\\"models\\":'
                )

        if models_data and isinstance(models_data, list) and len(models_data) > 5:
            results["models"] = models_data
            print(f"  Found {len(models_data)} models from escaped JSON")
            return results

        # Fallback: Try normal (non-escaped) JSON markers
        models_data = extract_json_from_html(html, '"models":')
        if models_data and isinstance(models_data, list) and len(models_data) > 5:
            results["models"] = models_data
            print(f"  Found {len(models_data)} models from normal JSON")
            return results

        print("  Could not extract models data from HTTP response")

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results


# =============================================================================
# OPENROUTER - HTTP
# =============================================================================
def scrape_openrouter():
    """Scrape OpenRouter rankings."""
    print("Scraping OpenRouter...")

    results = {
        "source": "openrouter.ai",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "rankings": []
    }

    url = "https://openrouter.ai/rankings"

    try:
        html = fetch_with_retry(url)

        rankings_data = extract_json_from_html(html, '"rankings":')
        if rankings_data and isinstance(rankings_data, list):
            results["rankings"] = rankings_data
            print(f"  Found {len(results['rankings'])} models from 'rankings' key")
            return results

        # Try the API endpoint directly
        api_url = "https://openrouter.ai/api/v1/models"
        try:
            api_response = fetch_with_retry(api_url)
            api_data = json.loads(api_response)
            if "data" in api_data:
                results["rankings"] = api_data["data"]
                print(f"  Found {len(results['rankings'])} models from API")
                return results
        except Exception:
            pass

        print("  Could not extract rankings data")

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results


# =============================================================================
# EQ BENCH - HTTP
# =============================================================================
def scrape_eqbench():
    """Scrape EQ Bench."""
    print("Scraping EQ Bench...")

    results = {
        "source": "eqbench.com",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "models": []
    }

    url = "https://eqbench.com/"

    try:
        html = fetch_with_retry(url)

        for marker in ['"models":', '"results":', '"leaderboard":']:
            models_data = extract_json_from_html(html, marker)
            if models_data and isinstance(models_data, list) and len(models_data) > 0:
                results["models"] = models_data
                print(f"  Found {len(models_data)} models from '{marker}' key")
                return results

        # Fallback: parse table from HTTP HTML
        models_from_table = _parse_tables_for_models(html)
        if models_from_table:
            results["models"] = models_from_table
            print(f"  Found {len(models_from_table)} models from HTTP table")
            return results

        print("  HTTP didn't find data, trying Steel browser...")

        # Fallback: Try Steel for JS-rendered content
        if STEEL_API_KEY:
            try:
                steel_html = fetch_with_steel(url)
                if steel_html:
                    debug_file = DATA_DIR / "eqbench_raw.html"
                    with open(debug_file, "w", encoding="utf-8") as f:
                        f.write(steel_html)
                    print(f"  Saved Steel HTML ({len(steel_html)} chars)")

                    # Try JSON markers on Steel HTML
                    for marker in ['"models":', '"results":', '"leaderboard":']:
                        models_data = extract_json_from_html(steel_html, marker)
                        if models_data and isinstance(models_data, list) and len(models_data) > 0:
                            results["models"] = models_data
                            print(f"  Found {len(models_data)} models from Steel '{marker}'")
                            return results

                    # Try table parsing on Steel HTML
                    models_from_table = _parse_tables_for_models(steel_html)
                    if models_from_table:
                        results["models"] = models_from_table
                        print(f"  Found {len(models_from_table)} models from Steel table")
                        return results
            except Exception as e2:
                print(f"  Steel fallback error: {e2}")

        print("  Could not extract models")

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results


def _parse_tables_for_models(html):
    """Helper: extract model names/scores from HTML tables."""
    models = []
    soup = BeautifulSoup(html, 'lxml')
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        if len(rows) > 2:
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    name = cells[0].get_text(strip=True)
                    score = cells[1].get_text(strip=True)
                    if name and len(name) > 2:
                        try:
                            score = float(score)
                        except ValueError:
                            score = None
                        models.append({"name": name, "score": score})
            if models:
                return models
    return models


# =============================================================================
# MAIN
# =============================================================================
def main():
    """Main function to scrape all sources."""
    print("=" * 60)
    print("AI Benchmark Aggregator Scraper (Rakium)")
    print(f"Time: {datetime.now(timezone.utc).isoformat()} UTC")
    print("=" * 60)
    print(f"Steel browser:  {'Available' if STEEL_API_KEY else 'NOT CONFIGURED (set STEEL_API_KEY)'}")
    print(f"Tavily:         {'Available' if TAVILY_AVAILABLE else 'NOT INSTALLED (pip install tavily-python)'}")
    print(f"Tavily keys:    {len(get_tavily_keys())} found")
    print("=" * 60)

    results = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "sources": {}
    }

    # Sources configuration:
    # - Arena uses Tavily (BEST for this site, per user testing)
    # - YUPP and LiveBench use Steel browser (JS-rendered SPAs)
    # - Others use plain HTTP
    sources = [
        ("arena", scrape_arena),
        ("livebench", scrape_livebench),
        ("yupp", scrape_yupp),
        ("artificial_analysis", scrape_artificial_analysis),
        ("openrouter", scrape_openrouter),
        ("eqbench", scrape_eqbench),
    ]

    for name, func in sources:
        print(f"\n{'=' * 40}")
        try:
            results["sources"][name] = func()
        except Exception as e:
            print(f"FATAL error scraping {name}: {e}")
            results["sources"][name] = {
                "error": str(e),
                "source": name
            }

    # Save combined results
    output_file = DATA_DIR / "all_sources.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"Results saved to: {output_file}")
    print("=" * 60)

    # Summary
    print("\nSUMMARY:")
    for name, data in results["sources"].items():
        if "error" in data and not any(k for k in data if k not in ("error", "source", "scraped_at")):
            print(f"  {name}: ERROR - {data['error']}")
        elif "categories" in data:
            total = sum(
                cat.get("num_models", 0)
                for cat in data["categories"].values()
                if isinstance(cat, dict)
            )
            print(f"  {name}: {total} models across {len(data['categories'])} categories")
        elif "models" in data:
            print(f"  {name}: {len(data['models'])} models")
        elif "rankings" in data:
            print(f"  {name}: {len(data['rankings'])} rankings")
        else:
            print(f"  {name}: Unknown structure")

    # Save individual files
    for name, data in results["sources"].items():
        individual_file = DATA_DIR / f"{name}.json"
        with open(individual_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Saved: {individual_file}")

    return results


if __name__ == "__main__":
    main()
