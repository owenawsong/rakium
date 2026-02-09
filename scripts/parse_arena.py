#!/usr/bin/env python3
"""
Parse the Arena.ai HTML file to extract model data
"""

import json
import re
from pathlib import Path

DATA_DIR = Path("data")

# Read the HTML file
with open(DATA_DIR / "arena_steel.html", "r", encoding="utf-8", errors="ignore") as f:
    html = f.read()

print(f"HTML file size: {len(html):,} characters")

# Try different patterns to find model data

# Pattern 1: modelDisplayName with rating
pattern1 = r'"modelDisplayName":"([^"]+)".*?"rating":\s*([0-9]+\.?[0-9]*)'
matches1 = re.findall(pattern1, html, re.DOTALL)
print(f"\nPattern 1 (modelDisplayName + rating): {len(matches1)} matches")

if matches1:
    for name, rating in matches1[:10]:
        print(f"  {name}: {rating}")

# Pattern 2: Any model name pattern
pattern2 = r'"([a-zA-Z][-a-zA-Z0-9_]*[-:][0-9a-zA-Z][-a-zA-Z0-9_]*)"'
matches2 = re.findall(pattern2, html)
print(f"\nPattern 2 (model-like names): {len(matches2)} matches")
unique_names = list(set(matches2))
print(f"Unique names: {len(unique_names)}")

# Filter to likely model names
likely_models = [n for n in unique_names if len(n) > 5 and not n.isdigit()]
print(f"Likely models: {len(likely_models)}")
for name in likely_models[:20]:
    print(f"  {name}")

# Pattern 3: Look for JSON data structure
print("\n\nLooking for JSON data structures...")

# Look for large JSON objects
json_patterns = [
    r'"leaderboardData"\s*:\s*(\[.*?\]|\{.*?\})',
    r'"models"\s*:\s*(\[.*?\])',
    r'"data"\s*:\s*(\[.*?\])',
]

for p in json_patterns:
    matches = re.findall(p, html)
    if matches:
        print(f"\nFound {len(matches)} matches for '{p[:30]}...'")
        # Try to parse
        for m in matches[:2]:
            if len(m) < 5000:  # Only try small ones
                try:
                    parsed = json.loads(m)
                    print(f"  Parsed successfully: {type(parsed)}")
                    if isinstance(parsed, list):
                        print(f"  List length: {len(parsed)}")
                        if parsed:
                            print(f"  First item: {str(parsed[0])[:200]}")
                    elif isinstance(parsed, dict):
                        print(f"  Dict keys: {list(parsed.keys())[:10]}")
                except:
                    pass

# Save a sample of the HTML for inspection
print("\n\nSaving sample HTML for inspection...")
sample_start = html[:50000]
sample_end = html[-50000:]

with open(DATA_DIR / "arena_sample_start.html", "w", encoding="utf-8") as f:
    f.write(sample_start)
with open(DATA_DIR / "arena_sample_end.html", "w", encoding="utf-8") as f:
    f.write(sample_end)

print(f"Saved: arena_sample_start.html (first 50K chars)")
print(f"Saved: arena_sample_end.html (last 50K chars)")