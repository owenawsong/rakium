"""Run from your rakium folder - prints key info about the saved HTML files."""
import re, os

data_dir = "data"

def check(name, filename, searches):
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        print(f"\n[{name}] FILE NOT FOUND: {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    print(f"\n[{name}] {len(html)} chars")
    for label, pattern in searches:
        count = html.count(pattern)
        if count > 0:
            idx = html.find(pattern)
            snippet = html[idx:idx+150].replace('\n', ' ')
            print(f"  {label}: {count}x — first at {idx}: {snippet}")
        else:
            print(f"  {label}: NOT FOUND")

# LiveBench
check("LiveBench", "livebench_raw.html", [
    ("table tag", "<table"),
    ("<tr> rows", "<tr"),
    ("escaped models", '\\"models\\":'),
    ("normal models", '"models":'),
    ("self.__next_f", "self.__next_f.push"),
    ("__NEXT_DATA__", "__NEXT_DATA__"),
])

# YUPP overall
check("YUPP overall", "yupp_overall.html", [
    ("escaped leaderboardData", '\\"leaderboardData\\":'),
    ("normal leaderboardData", '"leaderboardData":'),
    ("escaped model_rating", '\\"model_rating\\":'),
    ("escaped taxonomy_label", '\\"taxonomy_label\\":'),
    ("self.__next_f", "self.__next_f.push"),
    ("table tag", "<table"),
])

# YUPP text (sub-category)
check("YUPP text", "yupp_text.html", [
    ("escaped leaderboardData", '\\"leaderboardData\\":'),
    ("normal leaderboardData", '"leaderboardData":'),
    ("escaped model_rating", '\\"model_rating\\":'),
    ("escaped taxonomy_label", '\\"taxonomy_label\\":'),
    ("escaped highlights", '\\"highlights\\":'),
    ("escaped rating", '\\"rating\\":'),
    ("self.__next_f", "self.__next_f.push"),
])

# OpenRouter - fetch fresh since we don't save debug HTML
print(f"\n[OpenRouter] Fetching /rankings page...")
try:
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get("https://openrouter.ai/rankings", headers=headers, timeout=30)
    html = resp.text
    print(f"  Size: {len(html)} chars")
    for label, pattern in [
        ("escaped models", '\\"models\\":'),
        ("normal models", '"models":'),
        ("escaped rankingData", '\\"rankingData\\":'),
        ("normal rankingData", '"rankingData":'),
        ("self.__next_f", "self.__next_f.push"),
        ("__NEXT_DATA__", "__NEXT_DATA__"),
        ("escaped rankings", '\\"rankings\\":'),
        ("normal rankings", '"rankings":'),
        ("escaped permaslug", '\\"model_permaslug\\":'),
        ("normal permaslug", '"model_permaslug":'),
        ("escaped request_count", '\\"request_count\\":'),
    ]:
        count = html.count(pattern)
        if count > 0:
            idx = html.find(pattern)
            snippet = html[idx:idx+150].replace('\n', ' ')
            print(f"  {label}: {count}x — first at {idx}: {snippet}")
        else:
            print(f"  {label}: NOT FOUND")
except Exception as e:
    print(f"  Error: {e}")

# EQ Bench
check("EQ Bench", "eqbench_raw.html", [
    ("table tag", "<table"),
    ("<th>", "<th"),
    ("Elo", "Elo"),
    ("elo", "elo"),
    ("Humanlike", "Humanlike"),
    ("humanlike", "humanlike"),
])

print("\nDone.")
