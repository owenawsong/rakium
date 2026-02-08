#!/usr/bin/env python3
"""
AI Benchmark Aggregator Scraper
Extracts data from multiple AI leaderboard sources.
- LiveBench: HuggingFace API (HTTP)
- Arena/LM Arena: Playwright (JS-rendered)
- YUPP: Playwright (JS-rendered)
- Artificial Analysis: HTTP (JSON API)
- OpenRouter: HTTP
- EQ Bench: HTTP
"""

import json
import re
import time
import os
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import requests
import pandas as pd

# For JavaScript-rendered sites
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

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
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise e
    return None

def fetch_with_playwright(url, wait_for_selector=None, timeout=30000):
    """Fetch page content using Playwright (handles JavaScript rendering)."""
    if not PLAYWRIGHT_AVAILABLE:
        raise ImportError("Playwright not installed. Run: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers(HEADERS)

        try:
            page.goto(url, wait_until="networkidle", timeout=timeout)

            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=10000)

            # Wait for dynamic content
            time.sleep(3)

            content = page.content()
            browser.close()
            return content
        except Exception as e:
            browser.close()
            raise e

def extract_json_from_html(html, start_marker, max_length=500000):
    """Extract JSON array/object from HTML by finding start marker."""
    start_idx = html.find(start_marker)
    if start_idx == -1:
        return None

    start_idx += len(start_marker)
    json_str = html[start_idx:start_idx + max_length]

    # Find matching closing bracket
    depth = 0
    in_string = False
    end_idx = 0

    for i, char in enumerate(json_str):
        if char == '"' and (i == 0 or json_str[i-1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
            elif char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

    json_str = json_str[:end_idx]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Try to fix common issues
        json_str = json_str.replace('\\"', '"').replace('\\\\', '\\')
        try:
            return json.loads(json_str)
        except:
            return None

# =============================================================================
# ARTIFICIAL ANALYSIS - HTTP (Direct JSON API)
# =============================================================================
def scrape_artificial_analysis():
    """
    Scrape ALL benchmarks from Artificial Analysis.
    Data is available via their data endpoints.
    """
    print("Scraping Artificial Analysis...")

    results = {
        "source": "artificialanalysis.ai",
        "scraped_at": datetime.utcnow().isoformat(),
        "models": [],
        "benchmarks": {}
    }

    url = "https://artificialanalysis.ai/leaderboards/models"

    try:
        html = fetch_with_retry(url)

        # Look for models data in the page
        models_data = extract_json_from_html(html, '"models":')

        if models_data and isinstance(models_data, list):
            results["models"] = models_data
            print(f"  Found {len(models_data)} models")
        else:
            # Try alternative markers
            for marker in ['"models":[', 'models = [', 'window.models =']:
                models_data = extract_json_from_html(html, marker)
                if models_data:
                    break

            if models_data and isinstance(models_data, list):
                results["models"] = models_data
                print(f"  Found {len(models_data)} models")
            else:
                print("  Could not extract models data")

        # Look for benchmark data
        benchmarks_data = extract_json_from_html(html, '"benchmarkData":')
        if benchmarks_data:
            results["benchmarks"] = benchmarks_data
            print(f"  Found benchmark data")

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results

# =============================================================================
# LIVEBENCH - HuggingFace API (HTTP, no browser needed)
# =============================================================================
def scrape_livebench():
    """
    Scrape LiveBench from HuggingFace datasets.
    Categories: reasoning, coding, math, data_analysis, instruction_following, language
    """
    print("Scraping LiveBench...")

    results = {
        "source": "livebench.ai (via HuggingFace)",
        "scraped_at": datetime.utcnow().isoformat(),
        "categories": {}
    }

    # Main leaderboard dataset
    leaderboard_url = "https://datasets-server.huggingface.co/parquet?dataset=livebench/model_judgment"

    try:
        # Get leaderboard data
        response = requests.get(leaderboard_url, headers=HEADERS, timeout=30)
        data = response.json()

        if data.get("parquet_files"):
            parquet_url = data["parquet_files"][0]["url"]

            # Download and process parquet
            import urllib.request
            urllib.request.urlretrieve(parquet_url, "/tmp/livebench_leaderboard.parquet")
            df = pd.read_parquet("/tmp/livebench_leaderboard.parquet")

            # Get unique categories
            categories = df["category"].unique().tolist()
            results["categories"]["categories_found"] = categories

            # Calculate leaderboards
            for category in categories:
                cat_df = df[df["category"] == category]

                # Group by model and calculate average score
                leaderboard = cat_df.groupby("model").agg({
                    "score": ["mean", "count"]
                }).round(4)
                leaderboard.columns = ["avg_score", "num_evaluations"]
                leaderboard = leaderboard.reset_index()
                leaderboard = leaderboard.sort_values("avg_score", ascending=False)

                results["categories"][category] = {
                    "models": leaderboard.to_dict(orient="records"),
                    "num_models": len(leaderboard)
                }

            # Overall leaderboard
            overall = df.groupby("model").agg({
                "score": ["mean", "count"]
            }).round(4)
            overall.columns = ["avg_score", "num_evaluations"]
            overall = overall.sort_values("avg_score", ascending=False)

            results["categories"]["overall"] = {
                "models": overall.head(100).to_dict(orient="records"),
                "num_models": len(overall)
            }

            print(f"  Found {len(categories)} categories")
            print(f"  Total models: {df['model'].nunique()}")

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results

# =============================================================================
# ARENA / LM ARENA - Playwright (JS-rendered, blocked by Cloudflare)
# =============================================================================
def scrape_arena():
    """
    Scrape Arena/LM Arena leaderboards using Playwright.
    Categories: text, vision, image, video, search, coding, and text subcategories.
    """
    print("Scraping Arena/LM Arena (Playwright)...")

    results = {
        "source": "arena.ai (formerly lmarena.ai)",
        "scraped_at": datetime.utcnow().isoformat(),
        "categories": {}
    }

    if not PLAYWRIGHT_AVAILABLE:
        results["error"] = "Playwright not available"
        return results

    # Categories to scrape
    categories = [
        {"url": "https://arena.ai/leaderboard", "name": "overall"},
        {"url": "https://arena.ai/leaderboard/text", "name": "text"},
        {"url": "https://arena.ai/leaderboard/vision", "name": "vision"},
        {"url": "https://arena.ai/leaderboard/image", "name": "image"},
        {"url": "https://arena.ai/leaderboard/video", "name": "video"},
        {"url": "https://arena.ai/leaderboard/coding", "name": "coding"},
        {"url": "https://arena.ai/leaderboard/search", "name": "search"},
    ]

    for cat in categories:
        print(f"  Scraping: {cat['name']}...")
        try:
            html = fetch_with_playwright(cat["url"], wait_for_selector="body", timeout=60000)

            # Extract model data from the page
            models = extract_models_from_arena_html(html)

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
                    "html_size": len(html),
                    "note": "Could not extract models, raw HTML saved"
                }
                # Save raw HTML for inspection
                with open(DATA_DIR / f"arena_{cat['name']}.html", "w", encoding="utf-8") as f:
                    f.write(html)

        except Exception as e:
            print(f"    Error: {e}")
            results["categories"][cat["name"]] = {
                "url": cat["url"],
                "error": str(e)
            }

    return results

def extract_models_from_arena_html(html):
    """Extract model data from Arena HTML."""
    models = []

    # Try various patterns to find model data
    patterns = [
        ('"modelDisplayName":"', '"'),
        ('"displayName":"', '"'),
        ('"name":"', '"'),
    ]

    for start_marker, end_marker in patterns:
        idx = html.find(start_marker)
        if idx != -1:
            # Found data, try to extract
            while idx != -1:
                idx += len(start_marker)
                end_idx = html.find(end_marker, idx)
                if end_idx == -1:
                    break
                model_name = html[idx:end_idx]
                if model_name and len(model_name) > 3:
                    if model_name not in [m.get("name") for m in models]:
                        models.append({"name": model_name})
                idx = html.find(start_marker, end_idx)
            break

    return models

# =============================================================================
# YUPP - Playwright (JS-rendered)
# =============================================================================
def scrape_yupp():
    """Scrape YUPP leaderboard using Playwright."""
    print("Scraping YUPP (Playwright)...")

    results = {
        "source": "yupp.ai",
        "scraped_at": datetime.utcnow().isoformat(),
        "categories": {}
    }

    if not PLAYWRIGHT_AVAILABLE:
        results["error"] = "Playwright not available"
        return results

    categories = [
        {"url": "https://yupp.ai/leaderboard", "name": "overall"},
        {"url": "https://yupp.ai/leaderboard/text", "name": "text"},
        {"url": "https://yupp.ai/leaderboard/image", "name": "image"},
        {"url": "https://yupp.ai/leaderboard/search", "name": "search"},
        {"url": "https://yupp.ai/leaderboard/coding", "name": "coding"},
    ]

    for cat in categories:
        print(f"  Scraping: {cat['name']}...")
        try:
            html = fetch_with_playwright(cat["url"], wait_for_selector="body", timeout=60000)

            # Try to extract model data
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
                    "html_size": len(html)
                }

        except Exception as e:
            print(f"    Error: {e}")
            results["categories"][cat["name"]] = {
                "url": cat["url"],
                "error": str(e)
            }

    return results

def extract_models_from_yupp_html(html):
    """Extract model data from YUPP HTML."""
    models = []

    # Try to find model data
    patterns = [
        ('"model":"', '"'),
        ('"name":"', '"'),
        ('"displayName":"', '"'),
    ]

    for start_marker, end_marker in patterns:
        idx = html.find(start_marker)
        if idx != -1:
            while idx != -1:
                idx += len(start_marker)
                end_idx = html.find(end_marker, idx)
                if end_idx == -1:
                    break
                model_name = html[idx:end_idx]
                if model_name and len(model_name) > 3:
                    if model_name not in [m.get("name") for m in models]:
                        models.append({"name": model_name})
                idx = html.find(start_marker, end_idx)
            break

    return models

# =============================================================================
# OPENROUTER - HTTP
# =============================================================================
def scrape_openrouter():
    """Scrape OpenRouter rankings."""
    print("Scraping OpenRouter...")

    results = {
        "source": "openrouter.ai",
        "scraped_at": datetime.utcnow().isoformat(),
        "rankings": []
    }

    url = "https://openrouter.ai/rankings"

    try:
        html = fetch_with_retry(url)

        # Look for rankings data
        rankings_data = extract_json_from_html(html, '"rankings":')

        if rankings_data:
            results["rankings"] = rankings_data if isinstance(rankings_data, list) else []
            print(f"  Found {len(results['rankings'])} models")
        else:
            # Try alternative extraction
            print("  Could not extract rankings data from HTML")

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
        "scraped_at": datetime.utcnow().isoformat(),
        "models": []
    }

    url = "https://eqbench.com/"

    try:
        html = fetch_with_retry(url)

        # Try to extract model data
        models_data = extract_json_from_html(html, '"models":')

        if models_data:
            results["models"] = models_data if isinstance(models_data, list) else []
            print(f"  Found {len(results['models'])} models")
        else:
            print("  Could not extract models from HTML")

    except Exception as e:
        print(f"  Error: {e}")
        results["error"] = str(e)

    return results

# =============================================================================
# MAIN
# =============================================================================
def main():
    """Main function to scrape all sources."""
    print("=" * 60)
    print("AI Benchmark Aggregator Scraper")
    print("=" * 60)

    results = {
        "scraped_at": datetime.utcnow().isoformat(),
        "sources": {}
    }

    # Sources configuration
    # LiveBench uses HuggingFace API (no browser needed)
    sources = [
        ("livebench", scrape_livebench),
        ("artificial_analysis", scrape_artificial_analysis),
        ("arena", scrape_arena),
        ("yupp", scrape_yupp),
        ("openrouter", scrape_openrouter),
        ("eqbench", scrape_eqbench),
    ]

    for name, func in sources:
        print(f"\n{'='*40}")
        try:
            results["sources"][name] = func()
        except Exception as e:
            print(f"Error scraping {name}: {e}")
            results["sources"][name] = {
                "error": str(e),
                "source": name
            }

    # Save combined results
    output_file = DATA_DIR / "all_sources.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"Results saved to: {output_file}")
    print("=" * 60)

    # Also save individual files for convenience
    for name, data in results["sources"].items():
        if "error" not in data:
            individual_file = DATA_DIR / f"{name}.json"
            with open(individual_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            print(f"Saved: {individual_file}")

if __name__ == "__main__":
    main()
