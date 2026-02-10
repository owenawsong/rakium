#!/usr/bin/env python3
"""
AI Benchmark Aggregator Scraper (Rakium)
Extracts data from multiple AI leaderboard sources.

Sources & Methods:
- Arena/LM Arena: Steel browser (arena.ai Next.js SPA)
- LiveBench: Direct CSV + categories JSON from livebench.ai (no Steel needed!)
- YUPP: Direct tRPC API at yupp.ai (no Steel needed!)
- Artificial Analysis: HTTP (escaped JSON in Next.js RSC streaming format)
- OpenRouter: Public API (/api/frontend/models + /api/frontend/all-providers)
"""

import json
import re
import time
import os
import csv
from io import StringIO
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
from bs4 import BeautifulSoup
import requests

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
def fetch_with_steel(url, timeout=60, wait_for=None):
    """
    Fetch page content using Steel.dev's /scrape endpoint.
    This handles JS rendering automatically - no need to create sessions manually.
    Returns the HTML content of the fully-rendered page.

    Args:
        url: URL to scrape
        timeout: HTTP request timeout in seconds
        wait_for: Milliseconds to wait for JS to render before scraping (e.g. 15000 = 15s)
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

    if wait_for is not None:
        payload["waitFor"] = wait_for

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
    Scrape Arena/LM Arena leaderboard from arena.ai.

    Arena.ai is a Next.js app that server-renders the leaderboard table in the HTML.
    Strategy:
      1. Try plain HTTP first (SSR HTML contains the full table)
      2. Fall back to Steel browser if Cloudflare blocks plain HTTP

    Table columns: Rank, Rank Spread, Model, Score, 95% CI (±), Votes, Organization, License
    """
    print("Scraping Arena/LM Arena...")

    results = {
        "source": "arena.ai",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }

    # Categories to scrape (URLs from arena.ai navigation)
    categories = [
        {"url": "https://arena.ai/leaderboard/text", "name": "text"},
        {"url": "https://arena.ai/leaderboard/code", "name": "code"},
        {"url": "https://arena.ai/leaderboard/vision", "name": "vision"},
        {"url": "https://arena.ai/leaderboard/text-to-image", "name": "text-to-image"},
        {"url": "https://arena.ai/leaderboard/image-edit", "name": "image-edit"},
        {"url": "https://arena.ai/leaderboard/search", "name": "search"},
        {"url": "https://arena.ai/leaderboard/text-to-video", "name": "text-to-video"},
        {"url": "https://arena.ai/leaderboard/image-to-video", "name": "image-to-video"},
    ]

    for cat in categories:
        print(f"  Scraping: {cat['name']}...")
        try:
            html = None

            # Strategy 1: Try plain HTTP (arena.ai server-renders the table)
            try:
                html = fetch_with_retry(cat["url"], timeout=30)
                if html and len(html) > 50000:
                    print(f"    Got {len(html)} chars via HTTP")
                else:
                    print(f"    HTTP response too small ({len(html) if html else 0} chars), trying Steel...")
                    html = None
            except Exception as e:
                print(f"    HTTP failed ({e}), trying Steel...")

            # Strategy 2: Fall back to Steel browser
            if not html and STEEL_API_KEY:
                html = fetch_with_steel(cat["url"], timeout=120, wait_for=30000)
                if html:
                    print(f"    Got {len(html)} chars via Steel")

            if not html:
                print(f"    No HTML for {cat['name']}")
                results["categories"][cat["name"]] = {
                    "url": cat["url"], "models": [], "num_models": 0,
                    "error": "Could not fetch HTML"
                }
                continue

            models = _extract_arena_models_from_html(html)

            if models:
                results["categories"][cat["name"]] = {
                    "url": cat["url"],
                    "models": models,
                    "num_models": len(models)
                }
                print(f"    Found {len(models)} models")
            else:
                print(f"    WARNING: No models found for {cat['name']}")
                results["categories"][cat["name"]] = {
                    "url": cat["url"], "models": [], "num_models": 0,
                    "error": "Could not extract models from HTML"
                }

        except Exception as e:
            print(f"    Error: {e}")
            results["categories"][cat["name"]] = {
                "url": cat["url"], "error": str(e)
            }

    return results


def _extract_arena_models_from_html(html):
    """
    Extract model data from Arena.ai server-rendered HTML.

    Arena.ai table structure:
      <table>
        <thead><tr><th>Rank</th><th>Rank Spread</th><th>Model</th><th>Score</th>
               <th>95% CI (±)</th><th>Votes</th><th>Organization</th><th>License</th></tr></thead>
        <tbody>
          <tr>
            <td>1</td>
            <td>1◄─►2</td>
            <td>...<a title="claude-opus-4-6">claude-opus-4-6</a>...</td>
            <td>1496</td>
            <td>±11</td>
            <td>2,829</td>
            <td>Anthropic</td>
            <td>Proprietary</td>
          </tr>
          ...
        </tbody>
      </table>

    The model name is best extracted from the <a> tag's title attribute or text,
    as get_text() on the cell concatenates the org SVG title with the model name.
    """
    models = []

    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        # Fallback: try escaped JSON (older method)
        return _extract_arena_models_escaped_json(html)

    rows = table.find_all("tr")
    if len(rows) < 2:
        return models

    # Detect column indices from headers
    header_row = rows[0]
    headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

    col_map = {}
    print(f"    Table headers: {headers}")
    for i, h in enumerate(headers):
        if ("rank" in h) and "rank" not in col_map and "spread" not in h:
            col_map["rank"] = i
        elif "spread" in h:
            pass  # skip "rank spread" column
        elif "model" in h or "name" in h:
            col_map["model"] = i
        elif "score" in h or "elo" in h or "rating" in h:
            col_map["score"] = i
        elif "ci" in h or "±" in h or "confidence" in h:
            col_map["ci"] = i
        elif "vote" in h:
            col_map["votes"] = i
        elif "organization" in h or "org" in h or "provider" in h or "developer" in h:
            col_map["org"] = i
        elif "license" in h:
            col_map["license"] = i
    print(f"    Column map: {col_map}")

    model_idx = col_map.get("model", 2)
    score_idx = col_map.get("score", 3)
    rank_idx = col_map.get("rank", 0)
    ci_idx = col_map.get("ci")
    votes_idx = col_map.get("votes")
    org_idx = col_map.get("org")
    license_idx = col_map.get("license")

    # Parse data rows
    first_row_logged = False
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(model_idx, score_idx):
            continue
        if not first_row_logged:
            cell_texts = [c.get_text(strip=True)[:40] for c in cells]
            print(f"    First row cells ({len(cells)} cols): {cell_texts}")
            first_row_logged = True

        # --- Extract model name, organization, and license from the model cell ---
        model_cell = cells[model_idx]
        a_tag = model_cell.find("a")
        if a_tag:
            # Clean model name from <a> tag title or text
            name = a_tag.get("title") or a_tag.get_text(strip=True)
        else:
            name = model_cell.get_text(strip=True)

        if not name or len(name) < 2:
            continue

        # Extract org + license from model cell (they're embedded, not in separate columns)
        # Full cell text pattern: "[SVG org]model-name[Org · License]"
        # e.g. "Anthropicclaude-opus-4-6-thinkingAnthropic · Proprietary"
        # Strategy: split full text by the <a> tag's text content, take what comes AFTER
        organization = ""
        license_text = ""
        if a_tag:
            a_text = a_tag.get_text(strip=True)
            full_text = model_cell.get_text(strip=True)
            # Split by the <a> tag's visible text and take the part after it
            if a_text and a_text in full_text:
                after = full_text.split(a_text, 1)[1].strip()
            else:
                after = ""
            if after:
                # Format is typically "OrgName · License" or just "OrgName"
                if " · " in after:
                    parts = after.split(" · ", 1)
                    organization = parts[0].strip()
                    license_text = parts[1].strip()
                elif "·" in after:
                    parts = after.split("·", 1)
                    organization = parts[0].strip()
                    license_text = parts[1].strip()
                else:
                    organization = after

        # --- Extract score and CI from the score cell ---
        # Score cell format: "1504±10" or "1576+20/-20" or "1289±9" or "1400±10Preliminary"
        score_text = cells[score_idx].get_text(strip=True)
        # Remove trailing text like "Preliminary"
        score_text = re.sub(r'[A-Za-z]+$', '', score_text).strip()
        score = None
        ci = None
        if "±" in score_text:
            parts = score_text.split("±", 1)
            try:
                score = float(parts[0].replace(",", ""))
            except (ValueError, TypeError):
                pass
            try:
                ci = float(parts[1].replace(",", ""))
            except (ValueError, TypeError):
                pass
        elif "+" in score_text and "/" in score_text:
            # Format: "1576+20/-20"
            match = re.match(r'([0-9,]+)\+([0-9]+)/-([0-9]+)', score_text)
            if match:
                try:
                    score = float(match.group(1).replace(",", ""))
                    ci = (float(match.group(2)) + float(match.group(3))) / 2
                except (ValueError, TypeError):
                    pass
        else:
            try:
                score = float(score_text.replace(",", ""))
            except (ValueError, TypeError):
                pass

        entry = {
            "name": name,
            "rating": score,
        }
        if ci is not None:
            entry["ci"] = ci

        # Extract rank
        try:
            rank_text = cells[rank_idx].get_text(strip=True)
            entry["rank"] = int(rank_text)
        except (ValueError, IndexError):
            pass

        # Extract votes
        if votes_idx is not None and votes_idx < len(cells):
            votes_text = cells[votes_idx].get_text(strip=True).replace(",", "")
            try:
                entry["votes"] = int(votes_text)
            except (ValueError, TypeError):
                pass

        # Use org from model cell if no separate org column exists
        if org_idx is not None and org_idx < len(cells):
            entry["organization"] = cells[org_idx].get_text(strip=True)
        elif organization:
            entry["organization"] = organization

        # Use license from model cell if no separate license column exists
        if license_idx is not None and license_idx < len(cells):
            entry["license"] = cells[license_idx].get_text(strip=True)
        elif license_text:
            entry["license"] = license_text

        models.append(entry)

    return models


def _extract_arena_models_escaped_json(html):
    """Fallback: try to extract Arena model data from escaped JSON in HTML."""
    models = []
    for marker in ['\\"leaderboard\\":', '\\"models\\":', '\\"data\\":', '\\"rankings\\":']:
        data = extract_escaped_json_array(html, marker)
        if data and isinstance(data, list) and len(data) > 5:
            sample = data[0] if data else {}
            if isinstance(sample, dict) and any(
                k in sample for k in ("model", "name", "score", "elo", "rating")
            ):
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("model", item.get("name", ""))
                        if name:
                            models.append({
                                "name": name,
                                "rating": item.get("elo", item.get("score", item.get("rating"))),
                                "rank": item.get("rank"),
                                "organization": item.get("organization", item.get("org", "")),
                            })
                if models:
                    return models
    return models


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
# LIVEBENCH - Direct CSV + JSON (no Steel needed!)
# =============================================================================
def _discover_livebench_csv_url():
    """
    Discover the current LiveBench CSV URL by fetching the homepage and finding
    the table_YYYY_MM_DD.csv filename. Falls back to known recent URL.
    """
    try:
        html = fetch_with_retry("https://livebench.ai", timeout=30)
        # Look for table_YYYY_MM_DD.csv pattern in the HTML
        match = re.search(r'table_(\d{4}_\d{2}_\d{2})\.csv', html)
        if match:
            date_str = match.group(1)
            csv_url = f"https://livebench.ai/table_{date_str}.csv"
            categories_url = f"https://livebench.ai/categories_{date_str}.json"
            print(f"  Discovered LiveBench date: {date_str}")
            return csv_url, categories_url
    except Exception as e:
        print(f"  Could not discover LiveBench CSV URL: {e}")

    # Fallback to known recent URL
    csv_url = "https://livebench.ai/table_2026_01_08.csv"
    categories_url = "https://livebench.ai/categories_2026_01_08.json"
    print("  Using fallback LiveBench date: 2026_01_08")
    return csv_url, categories_url


def scrape_livebench():
    """
    Scrape LiveBench leaderboard using direct CSV + JSON fetching (NO Steel needed!).

    LiveBench hosts static files:
      - table_YYYY_MM_DD.csv: Raw benchmark scores per model per task
      - categories_YYYY_MM_DD.json: Maps category names to task column names

    We fetch both, compute category averages from per-task scores, and produce
    the same output structure the generator expects.
    """
    print("Scraping LiveBench (direct CSV)...")

    results = {
        "source": "livebench.ai (CSV)",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }

    try:
        csv_url, categories_url = _discover_livebench_csv_url()

        # Fetch both files
        print(f"  Fetching CSV: {csv_url}")
        csv_text = fetch_with_retry(csv_url, timeout=30)
        print(f"  Fetched CSV: {len(csv_text)} chars")

        print(f"  Fetching categories: {categories_url}")
        categories_text = fetch_with_retry(categories_url, timeout=30)
        categories_map = json.loads(categories_text)
        print(f"  Categories: {list(categories_map.keys())}")

        # Parse CSV and compute scores
        models = _parse_livebench_csv(csv_text, categories_map)

        if models:
            results["categories"]["overall"] = {
                "models": models,
                "num_models": len(models)
            }
            print(f"  SUCCESS: Found {len(models)} models")
        else:
            print("  WARNING: No models parsed from CSV")
            results["categories"]["overall"] = {
                "models": [], "num_models": 0,
                "note": "Could not parse models from CSV"
            }

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results


def _parse_livebench_csv(csv_text, categories_map):
    """
    Parse LiveBench CSV file.

    CSV columns: model, task1, task2, task3, ...
    Categories JSON: {"Reasoning": ["theory_of_mind", "zebra_puzzle", ...], ...}

    We compute:
      - Each category score = average of its task scores
      - Global average = average of all category scores
    """
    models = []

    reader = csv.DictReader(StringIO(csv_text))
    csv_columns = reader.fieldnames
    if not csv_columns or "model" not in csv_columns:
        print("  ERROR: CSV missing 'model' column")
        return models

    # Category name mapping for output (display names -> internal keys)
    category_display_to_key = {
        "Reasoning": "reasoning",
        "Coding": "coding",
        "Agentic Coding": "agentic_coding",
        "Mathematics": "math",
        "Data Analysis": "data_analysis",
        "Language": "language",
        "IF": "if",
    }

    for row in reader:
        name = row.get("model", "").strip()
        if not name:
            continue

        scores = {}
        category_scores = []

        for cat_display, tasks in categories_map.items():
            cat_key = category_display_to_key.get(cat_display, cat_display.lower().replace(" ", "_"))

            # Compute average of task scores for this category
            task_values = []
            for task in tasks:
                val_str = row.get(task, "").strip()
                if val_str:
                    try:
                        task_values.append(float(val_str))
                    except ValueError:
                        pass

            if task_values:
                cat_avg = round(sum(task_values) / len(task_values), 2)
                scores[cat_key] = cat_avg
                category_scores.append(cat_avg)
            else:
                scores[cat_key] = None

        # Global average = average of all category averages
        global_avg = None
        if category_scores:
            global_avg = round(sum(category_scores) / len(category_scores), 2)
        scores["global_avg"] = global_avg

        models.append({
            "name": name,
            "scores": scores,
            "score": global_avg,
        })

    # Sort by global average descending
    models.sort(key=lambda x: (x.get("score") or 0), reverse=True)
    return models


# =============================================================================
# YUPP - Direct tRPC API (no Steel needed!)
# =============================================================================
def _fetch_yupp_category(category_name, extra_filters=None, num_results=500):
    """
    Fetch a single category from YUPP's public tRPC API.

    The tRPC endpoint uses batch format:
      URL: /api/trpc/leaderboard.getLeaderboard?batch=1&input={"0":{"json":{...}}}
      Response: [{"result":{"data":{"json":{"models":[...], ...}}}}]

    Categories are NOT controlled by backendTier (always "stable").
    Instead, boolean filter flags select different subsets:
      - text/overall: no special filter
      - image: imageGenerationModels=true
      - image-new: newImageGenerations=true
      - image-edit: imageEditModels=true
      - search: liveModels=true
      - svg: svgModels=true
      - coding: codingModels=true

    Args:
        category_name: Display name for logging (e.g. "overall", "text")
        extra_filters: Dict of boolean filter flags (e.g. {"imageGenerationModels": True})
        num_results: Max models to fetch (default 500)

    Returns:
        List of normalized model dicts, or empty list on failure.
    """
    # Build the tRPC batch input - base params always the same
    json_params = {
        "offset": 0,
        "numResults": num_results,
        "collectStats": True,
        "backendTier": "stable",
    }

    # Add category-specific filter flags
    if extra_filters:
        json_params.update(extra_filters)

    trpc_params = {
        "0": {
            "json": json_params
        }
    }

    encoded_input = quote(json.dumps(trpc_params, separators=(",", ":")))
    url = f"https://yupp.ai/api/trpc/leaderboard.getLeaderboard?batch=1&input={encoded_input}"

    headers = {
        **HEADERS,
        "Accept": "application/json",
        "Referer": f"https://yupp.ai/leaderboard/{category_name}" if category_name != "overall" else "https://yupp.ai/leaderboard",
    }

    response_text = fetch_with_retry(url, headers=headers, timeout=30)
    data = json.loads(response_text)

    if not isinstance(data, list) or len(data) == 0:
        print(f"    Unexpected tRPC response format for {category_name}")
        return []

    # Navigate to the leaderboard data: data[0].result.data.json
    try:
        lb_data = data[0]["result"]["data"]["json"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"    Could not navigate tRPC response for {category_name}: {e}")
        if isinstance(data[0], dict) and "error" in data[0]:
            print(f"    tRPC error: {data[0]['error']}")
        return []

    raw_models = lb_data.get("models", [])
    total = lb_data.get("total_count", len(raw_models))
    print(f"    tRPC returned {len(raw_models)} models (total_count={total}) for {category_name}")

    # Normalize model data
    models = []
    for item in raw_models:
        parsed = _extract_yupp_model_from_rating(item)
        if parsed:
            models.append(parsed)

    # Sort by rank
    models.sort(key=lambda x: x.get("rank") or 99999)
    return models


def scrape_yupp():
    """
    Scrape YUPP leaderboard using their public tRPC API endpoint (NO Steel needed!).

    YUPP has 8 leaderboard categories: overall + 7 sub-categories.
    All use backendTier="stable" but different boolean filter flags select subsets.
    """
    print("Scraping YUPP (tRPC API)...")

    results = {
        "source": "yupp.ai (tRPC API)",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "categories": {}
    }

    # Categories: name -> extra filter flags for the tRPC API
    # All categories use backendTier="stable"; the filter flags select the subset
    categories = [
        {"name": "overall",    "filters": None},
        {"name": "text",       "filters": None},  # text = default (same as overall)
        {"name": "image",      "filters": {"imageGenerationModels": True}},
        {"name": "image-new",  "filters": {"newImageGenerations": True}},
        {"name": "image-edit", "filters": {"imageEditModels": True}},
        {"name": "search",     "filters": {"liveModels": True}},
        {"name": "svg",        "filters": {"svgModels": True}},
        {"name": "coding",     "filters": {"codingModels": True}},
    ]

    for cat in categories:
        filter_desc = cat["filters"] if cat["filters"] else "default"
        print(f"  Fetching: {cat['name']} ({filter_desc})...")
        try:
            models = _fetch_yupp_category(cat["name"], cat["filters"])

            results["categories"][cat["name"]] = {
                "url": f"https://yupp.ai/leaderboard/{cat['name']}" if cat["name"] != "overall" else "https://yupp.ai/leaderboard",
                "models": models,
                "num_models": len(models)
            }

            if models:
                print(f"    Found {len(models)} models")
            else:
                print(f"    WARNING: No models for {cat['name']}")

        except Exception as e:
            print(f"    Error: {e}")
            results["categories"][cat["name"]] = {
                "url": f"https://yupp.ai/leaderboard/{cat['name']}",
                "error": str(e)
            }

    return results


def _extract_yupp_model_from_rating(item):
    """
    Extract a normalized model dict from a YUPP leaderboard item.

    YUPP tRPC response structure per model:
      {
        "model_rating": {
          "taxonomy_label": "GPT-5.1 Search (High)",  <-- display name
          "rating": 1249.68,                            <-- ELO score
          "rank": 1,
          "global_rank": 1,
          "wins": 8705,
          "losses": 5790,
          "rating_lower": 1245.95,
          "rating_upper": 1253.03,
          ...
        },
        "model_info": {
          "model_publisher": "OpenAI",
          "model_family": "GPT",
          ...
        },
        "model_stats": { ... }
      }
    """
    if not isinstance(item, dict):
        return None

    mr = item.get("model_rating")
    if not isinstance(mr, dict):
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

    score = mr.get("rating") or item.get("rating") or item.get("elo_score") or item.get("score")

    result = {
        "name": name,
        "score": score,
        "rank": mr.get("rank") or mr.get("global_rank"),
    }

    # Extra fields from model_rating
    if "wins" in mr:
        result["wins"] = mr["wins"]
    if "losses" in mr:
        result["losses"] = mr["losses"]
    if mr.get("rating_lower") and mr.get("rating_upper"):
        result["ci_lower"] = mr["rating_lower"]
        result["ci_upper"] = mr["rating_upper"]

    # Extra fields from model_info
    mi = item.get("model_info")
    if isinstance(mi, dict):
        if mi.get("model_publisher"):
            result["organization"] = mi["model_publisher"]
        if mi.get("model_family"):
            result["model_family"] = mi["model_family"]

    return result


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
# OPENROUTER - Public API endpoints
# =============================================================================

def scrape_openrouter():
    """
    Scrape OpenRouter model catalog via public API endpoints.

    Primary: /api/frontend/models  — full model catalog with pricing, context, etc.
    Secondary: /api/frontend/all-providers — provider metadata
    Fallback: /rankings HTML page (legacy escaped JSON parsing)

    Output format:
      rankings: [{name, slug, author, context_length, prompt_price, completion_price,
                  provider_count, modality, request_count (if available), ...}]
    """
    print("Scraping OpenRouter...")

    results = {
        "source": "openrouter.ai",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "rankings": []
    }

    # --- Strategy 1: Public API endpoints ---
    try:
        api_url = "https://openrouter.ai/api/frontend/models"
        print(f"  Fetching {api_url}...")
        api_text = fetch_with_retry(api_url, timeout=30)
        api_data = json.loads(api_text)

        # Response is either {"data": [...]} or just [...]
        if isinstance(api_data, dict) and "data" in api_data:
            models_list = api_data["data"]
        elif isinstance(api_data, list):
            models_list = api_data
        else:
            models_list = []

        print(f"  API returned {len(models_list)} models")

        if models_list and len(models_list) > 5:
            # Also fetch provider info for enrichment
            providers_lookup = {}
            try:
                prov_url = "https://openrouter.ai/api/frontend/all-providers"
                prov_text = fetch_with_retry(prov_url, timeout=20)
                prov_data = json.loads(prov_text)
                if isinstance(prov_data, list):
                    for p in prov_data:
                        if isinstance(p, dict) and p.get("slug"):
                            providers_lookup[p["slug"]] = p
                elif isinstance(prov_data, dict) and "data" in prov_data:
                    for p in prov_data["data"]:
                        if isinstance(p, dict) and p.get("slug"):
                            providers_lookup[p["slug"]] = p
                print(f"  Fetched {len(providers_lookup)} providers")
            except Exception as pe:
                print(f"  Could not fetch providers: {pe}")

            # Process each model
            merged = []
            for model in models_list:
                if not isinstance(model, dict):
                    continue

                slug = model.get("slug") or model.get("id") or ""
                name = model.get("name") or slug
                author = model.get("author") or ""

                # Pricing lives inside endpoint.pricing (endpoint can be None)
                endpoint = model.get("endpoint") or {}
                if not isinstance(endpoint, dict):
                    endpoint = {}
                pricing = model.get("pricing") or endpoint.get("pricing") or {}
                if not isinstance(pricing, dict):
                    pricing = {}
                prompt_price = pricing.get("prompt") or pricing.get("input")
                completion_price = pricing.get("completion") or pricing.get("output")

                # Convert price strings to floats
                try:
                    prompt_price = float(prompt_price) if prompt_price else None
                except (ValueError, TypeError):
                    prompt_price = None
                try:
                    completion_price = float(completion_price) if completion_price else None
                except (ValueError, TypeError):
                    completion_price = None

                # Context length (top-level or from endpoint)
                context_length = model.get("context_length") or endpoint.get("context_length")

                # Provider count (from endpoint or providers_lookup)
                provider_count = endpoint.get("provider_count")
                if provider_count is None and slug in providers_lookup:
                    provider_count = providers_lookup[slug].get("provider_count")

                # Modality: use input_modalities/output_modalities arrays
                input_mods = model.get("input_modalities") or []
                output_mods = model.get("output_modalities") or []
                if input_mods or output_mods:
                    modality = "+".join(input_mods) + "→" + "+".join(output_mods)
                else:
                    modality = model.get("modality") or model.get("type") or ""

                entry = {
                    "name": name,
                    "slug": slug,
                    "author": author,
                    "context_length": context_length,
                    "prompt_price": prompt_price,
                    "completion_price": completion_price,
                    "provider_count": provider_count,
                    "modality": modality,
                }

                merged.append(entry)

            # Sort: models with pricing first (by context_length desc),
            # then models without pricing (by context_length desc)
            merged.sort(key=lambda x: (
                1 if x.get("prompt_price") is not None else 0,
                x.get("context_length") or 0,
            ), reverse=True)

            results["rankings"] = merged
            print(f"  SUCCESS: {len(merged)} models from API")
            return results

    except Exception as e:
        print(f"  API method failed: {e}")

    # --- Strategy 2: Fallback to /rankings HTML parsing ---
    print("  Falling back to /rankings HTML...")
    try:
        html = fetch_with_retry("https://openrouter.ai/rankings")
        print(f"  Fetched {len(html)} chars from /rankings")

        # Try escaped JSON markers
        for key in ['\\"models\\":', '\\"rankings\\":', '\\"rankedModels\\":']:
            data = extract_escaped_json_array(html, key)
            if data and isinstance(data, list) and len(data) > 5:
                sample = data[0] if data else {}
                if isinstance(sample, dict) and any(
                    k in sample for k in ("request_count", "slug", "name")
                ):
                    results["rankings"] = data
                    print(f"  Found {len(data)} models from HTML escaped JSON")
                    return results

        # Try non-escaped JSON
        for marker in ['"models":', '"rankings":']:
            data = extract_json_from_html(html, marker)
            if data and isinstance(data, list) and len(data) > 5:
                results["rankings"] = data
                print(f"  Found {len(data)} models from HTML JSON")
                return results

        print("  Could not extract data from /rankings HTML either")

    except Exception as e2:
        print(f"  HTML fallback also failed: {e2}")
        results["error"] = str(e2)

    return results


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
    # - Arena uses Steel browser (arena.ai Next.js SPA)
    # - LiveBench uses direct CSV + categories JSON (fast, no Steel!)
    # - YUPP uses direct tRPC API (fast, no Steel!)
    # - Others use plain HTTP
    sources = [
        ("arena", scrape_arena),
        ("livebench", scrape_livebench),
        ("yupp", scrape_yupp),
        ("artificial_analysis", scrape_artificial_analysis),
        ("openrouter", scrape_openrouter),
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
