#!/usr/bin/env python3
"""
Parse all scraped HTML files to extract model data
"""

import json
import re
from pathlib import Path

DATA_DIR = Path("data")

def parse_file(filename, site_name):
    """Parse an HTML file and extract model data"""
    print(f"\n{'='*60}")
    print(f"Parsing: {filename}")
    print(f"{'='*60}")
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        print(f"  File not found: {filepath}")
        return
    
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()
    
    print(f"  File size: {len(html):,} chars")
    
    # Pattern 1: modelDisplayName + rating
    pattern1 = r'"modelDisplayName":"([^"]+)".*?"rating":\s*([0-9]+\.?[0-9]*)'
    matches1 = re.findall(pattern1, html, re.DOTALL)
    print(f"\n  Pattern 1 (modelDisplayName + rating): {len(matches1)} matches")
    if matches1:
        for name, rating in matches1[:5]:
            print(f"    {name}: {rating}")
        return [{"name": n, "rating": float(r)} for n, r in matches1]
    
    # Pattern 2: displayName + rating
    pattern2 = r'"displayName":"([^"]+)".*?"rating":\s*([0-9]+\.?[0-9]*)'
    matches2 = re.findall(pattern2, html, re.DOTALL)
    print(f"\n  Pattern 2 (displayName + rating): {len(matches2)} matches")
    if matches2:
        for name, rating in matches2[:5]:
            print(f"    {name}: {rating}")
        return [{"name": n, "rating": float(r)} for n, r in matches2]
    
    # Pattern 3: model name with numbers
    pattern3 = r'"([a-zA-Z][-a-zA-Z0-9_]*[-:][0-9a-zA-Z][-a-zA-Z0-9_]*)"'
    matches3 = re.findall(pattern3, html)
    unique_names = list(set(matches3))
    likely_models = [n for n in unique_names if len(n) > 5 and not n.isdigit()]
    print(f"\n  Pattern 3 (model-like names): {len(likely_models)} likely models")
    for name in likely_models[:10]:
        print(f"    {name}")
    
    # Pattern 4: Look for scores
    scores = re.findall(r'"score":\s*([0-9]+\.?[0-9]*)', html)
    print(f"\n  Pattern 4 (scores): {len(scores)} score values found")
    
    # Pattern 5: Look for votes
    votes = re.findall(r'"votes":\s*([0-9]+)', html)
    print(f"\n  Pattern 5 (votes): {len(votes)} vote values found")
    
    # Save sample
    sample_file = DATA_DIR / f"{filepath.stem}_sample.html"
    with open(sample_file, "w", encoding="utf-8") as f:
        f.write(html[:100000])
    print(f"\n  Saved sample: {sample_file.name}")
    
    return likely_models[:50]

# Parse all files
results = {}

# Arena
results["arena"] = parse_file("arena_steel.html", "Arena.ai")

# YUPP
results["yupp"] = parse_file("yupp_steel.html", "YUPP.ai")

# LiveBench
results["livebench"] = parse_file("livebench_steel.html", "LiveBench.ai")

# Save results
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")

with open(DATA_DIR / "parsed_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

for site, data in results.items():
    if isinstance(data, list):
        print(f"  {site}: {len(data)} items")
    else:
        print(f"  {site}: Failed to parse")