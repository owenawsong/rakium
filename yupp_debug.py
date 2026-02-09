"""Quick diagnostic: what does YUPP's escaped JSON actually look like?"""
import json, re, sys

# Read the saved raw HTML from last run
try:
    with open("data/yupp_overall.html", "r", encoding="utf-8") as f:
        html = f.read()
except FileNotFoundError:
    print("ERROR: data/yupp_overall.html not found. Run scraper.py first.")
    sys.exit(1)

print(f"HTML size: {len(html)} chars")

# Check all possible markers
markers = [
    '\\"leaderboardData\\":',
    '\\"models\\":',
    '\\"rankings\\":',
    '\\"leaderboard\\":',
    '\\"data\\":',
    '\\"model_rating\\":',
    '\\"model_name\\":',
    '\\"elo_score\\":',
]

print("\n=== MARKER SEARCH ===")
for m in markers:
    idx = html.find(m)
    if idx != -1:
        print(f"  FOUND '{m}' at index {idx}")
        # Show 200 chars around the marker
        start = max(0, idx - 50)
        end = min(len(html), idx + len(m) + 200)
        snippet = html[start:end]
        print(f"    Context: ...{snippet}...")
    else:
        print(f"  NOT FOUND: '{m}'")

# Now try to find what __next_f.push calls contain
print("\n=== __next_f.push ANALYSIS ===")
pushes = list(re.finditer(r'self\.__next_f\.push\(\[', html))
print(f"Found {len(pushes)} __next_f.push calls")

# Find the push that contains model data
for i, match in enumerate(pushes):
    start = match.start()
    snippet = html[start:start+500]
    if 'model' in snippet.lower():
        print(f"\n  Push #{i} at index {start} contains 'model':")
        print(f"    First 500 chars: {snippet[:500]}")
        # Show more context to see the actual data structure
        bigger = html[start:start+2000]
        # Find first occurrence of model-related data
        for key in ['model_rating', 'model_name', 'elo_score', 'models']:
            escaped_key = f'\\"{key}\\"'
            pos = bigger.find(escaped_key)
            if pos != -1:
                print(f"\n    Found '{escaped_key}' at offset +{pos}")
                print(f"    Context: {bigger[max(0,pos-20):pos+200]}")
        break  # Just show the first relevant push

# Try a broader approach: find ANY array after \"models\":
print("\n=== MANUAL EXTRACTION ATTEMPT ===")
models_idx = html.find('\\"models\\":')
if models_idx == -1:
    # Try without the colon
    models_idx = html.find('\\"models\\"')
    if models_idx != -1:
        print(f"Found '\\\"models\\\"' (without colon) at {models_idx}")
        print(f"  Next 100 chars: {html[models_idx:models_idx+100]}")

if models_idx != -1:
    after = html[models_idx:models_idx+500]
    print(f"Found '\\\"models\\\":' at index {models_idx}")
    print(f"First 500 chars after marker:\n{after}")

    # Check what character comes after the marker
    marker_end = models_idx + len('\\"models\\":')
    next_chars = html[marker_end:marker_end+20]
    print(f"\nChars right after marker: {repr(next_chars)}")

    # Check if it starts with [ or something else
    stripped = next_chars.lstrip()
    print(f"First non-whitespace char: {repr(stripped[0]) if stripped else 'EMPTY'}")
else:
    print("'\\\"models\\\":' NOT FOUND anywhere!")

    # Try alternate patterns
    for alt in ['models":', '"models":', 'models\\u0022:']:
        idx = html.find(alt)
        if idx != -1:
            print(f"  Found alternate pattern '{alt}' at {idx}")
            print(f"  Context: {html[idx:idx+300]}")
