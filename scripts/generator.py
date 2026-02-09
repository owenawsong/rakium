#!/usr/bin/env python3
"""
Rakium Generator - Creates HTML from scraped data.
Reads JSON files produced by scraper.py and generates output/index.html.

Data format from scraper.py:
  - arena.json:              { categories: { overall: { models: [{name, rating, organization, votes, rank}] }, text: {...}, ... } }
  - livebench.json:          { categories: { overall: { models: [{name, score, organization, num_scores}] } } }
  - yupp.json:               { categories: { overall: { models: [{name, score, rank, wins, losses, ci_lower, ci_upper}] } } }
  - artificial_analysis.json:{ models: [{name, additional_text, model_creators, ...}] }
  - openrouter.json:         { rankings: [{id, name, pricing, ...}] }
  - eqbench.json:            { models: [{name, score}] }
"""

import json
import html as html_module
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def load_json(filename):
    """Load JSON file."""
    filepath = DATA_DIR / filename
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def esc(text):
    """HTML-escape a string safely."""
    if text is None:
        return ""
    return html_module.escape(str(text))


def fmt_number(val):
    """Format a number for display. Returns 'N/A' if None."""
    if val is None:
        return "N/A"
    if isinstance(val, float):
        # Show up to 2 decimal places, strip trailing zeros
        if val > 100:
            return f"{val:,.0f}"
        return f"{val:.2f}".rstrip('0').rstrip('.')
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def generate_html():
    """Generate the main HTML page."""

    # Load all data sources
    arena_data = load_json("arena.json")
    livebench_data = load_json("livebench.json")
    yupp_data = load_json("yupp.json")
    artificial_data = load_json("artificial_analysis.json")
    openrouter_data = load_json("openrouter.json")
    eqbench_data = load_json("eqbench.json")

    # Extract models from each source
    # Arena: categories -> {overall, text, vision, image, video, coding} -> models
    arena_categories = {}
    if arena_data and "categories" in arena_data:
        for cat_name, cat_data in arena_data["categories"].items():
            if isinstance(cat_data, dict) and "models" in cat_data:
                arena_categories[cat_name] = cat_data["models"]
    arena_overall = arena_categories.get("overall", [])

    # LiveBench: categories -> {overall} -> models [{name, score, organization, num_scores}]
    livebench_models = []
    if livebench_data and "categories" in livebench_data:
        lb_overall = livebench_data["categories"].get("overall", {})
        if isinstance(lb_overall, dict):
            livebench_models = lb_overall.get("models", [])

    # YUPP: categories -> {overall} -> models [{name, score, rank, wins, losses}]
    yupp_models = []
    if yupp_data and "categories" in yupp_data:
        yupp_overall = yupp_data["categories"].get("overall", {})
        if isinstance(yupp_overall, dict):
            yupp_models = yupp_overall.get("models", [])

    # Artificial Analysis: models [{name, additional_text, model_creators, ...}]
    artificial_models = artificial_data.get("models", []) if artificial_data else []

    # OpenRouter: rankings [{id, name, pricing, context_length, ...}]
    openrouter_models = openrouter_data.get("rankings", []) if openrouter_data else []

    # EQ Bench: models [{name, score}]
    eqbench_models = eqbench_data.get("models", []) if eqbench_data else []

    # Count totals
    arena_total = sum(len(m) for m in arena_categories.values())

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rakium - AI Benchmark Aggregator</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0f; color: #e0e0e0; min-height: 100vh; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{ text-align: center; padding: 40px 0; border-bottom: 1px solid #222; margin-bottom: 30px; }}
        header h1 {{ font-size: 2.5em; background: linear-gradient(135deg, #00ff88, #00aaff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }}
        header p {{ color: #888; font-size: 1.1em; }}
        .tabs {{ display: flex; gap: 10px; margin-bottom: 30px; border-bottom: 1px solid #222; padding-bottom: 20px; flex-wrap: wrap; }}
        .tab {{ padding: 12px 24px; background: #1a1a1f; border: 1px solid #333; border-radius: 8px; cursor: pointer; transition: all 0.3s; color: #888; font-size: 0.95em; }}
        .tab:hover {{ background: #25252a; }}
        .tab.active {{ background: linear-gradient(135deg, #00ff88, #00aaff); border-color: transparent; color: #000; font-weight: 600; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: #1a1a1f; border: 1px solid #333; border-radius: 12px; padding: 20px; text-align: center; }}
        .stat-card h3 {{ font-size: 2em; color: #00ff88; margin-bottom: 5px; }}
        .stat-card p {{ color: #666; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; }}
        .section {{ display: none; }}
        .section.active {{ display: block; }}
        .sub-nav {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }}
        .sub-btn {{ padding: 6px 14px; background: #1a1a1f; border: 1px solid #333; border-radius: 6px; cursor: pointer; color: #888; transition: all 0.2s; font-size: 0.85em; }}
        .sub-btn:hover, .sub-btn.active {{ background: #25252a; border-color: #00ff88; color: #00ff88; }}
        .sub-section {{ display: none; }}
        .sub-section.active {{ display: block; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #222; }}
        th {{ background: #1a1a1f; color: #00ff88; font-weight: 600; text-transform: uppercase; font-size: 0.8em; letter-spacing: 0.5px; position: sticky; top: 0; }}
        tr:hover {{ background: #12121a; }}
        .rank {{ color: #00ff88; font-weight: 600; }}
        .model-name {{ color: #fff; font-weight: 500; }}
        .org {{ color: #666; font-size: 0.9em; }}
        .score {{ color: #00aaff; font-weight: 600; }}
        .votes {{ color: #888; }}
        .category-header {{ margin: 30px 0 15px; padding-bottom: 10px; border-bottom: 1px solid #222; }}
        .category-header h2 {{ color: #fff; font-size: 1.4em; }}
        .category-header p {{ color: #666; margin-top: 5px; font-size: 0.9em; }}
        .update-time {{ text-align: center; color: #444; font-size: 0.85em; margin-top: 40px; padding-top: 20px; border-top: 1px solid #222; }}
        footer {{ text-align: center; padding: 30px; margin-top: 50px; border-top: 1px solid #222; color: #444; }}
        .search-box {{ width: 100%; padding: 10px 15px; background: #1a1a1f; border: 1px solid #333; border-radius: 8px; color: #e0e0e0; font-size: 0.95em; margin-bottom: 15px; }}
        .search-box::placeholder {{ color: #555; }}
        .search-box:focus {{ outline: none; border-color: #00ff88; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Rakium</h1>
            <p>Multi-Source AI Benchmark Aggregator</p>
        </header>

        <div class="tabs">
            <button class="tab active" onclick="showTab('overview')">Overview</button>
            <button class="tab" onclick="showTab('arena')">Arena</button>
            <button class="tab" onclick="showTab('livebench')">LiveBench</button>
            <button class="tab" onclick="showTab('yupp')">YUPP</button>
            <button class="tab" onclick="showTab('artificial')">Artificial Analysis</button>
            <button class="tab" onclick="showTab('openrouter')">OpenRouter</button>
            <button class="tab" onclick="showTab('eqbench')">EQ Bench</button>
        </div>

        <!-- Overview Section -->
        <div id="overview" class="section active">
            <div class="stats">
                <div class="stat-card">
                    <h3>{arena_total:,}</h3>
                    <p>Arena Models</p>
                </div>
                <div class="stat-card">
                    <h3>{len(livebench_models)}</h3>
                    <p>LiveBench Models</p>
                </div>
                <div class="stat-card">
                    <h3>{len(yupp_models)}</h3>
                    <p>YUPP Models</p>
                </div>
                <div class="stat-card">
                    <h3>{len(artificial_models)}</h3>
                    <p>AA Models</p>
                </div>
                <div class="stat-card">
                    <h3>{len(openrouter_models)}</h3>
                    <p>OpenRouter Models</p>
                </div>
                <div class="stat-card">
                    <h3>{len(eqbench_models)}</h3>
                    <p>EQ Bench Models</p>
                </div>
            </div>

            <div class="category-header">
                <h2>Top 10 Arena Models (Overall)</h2>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Rating</th>
                        <th>Organization</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(arena_overall[:10], 1):
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(model.get('rating'))}</td>
                        <td class="org">{esc(model.get('organization'))}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
        </div>

        <!-- Arena Section -->
        <div id="arena" class="section">
            <div class="category-header">
                <h2>Arena / LM Arena Leaderboard</h2>
                <p>Sourced from lmarena.ai via Tavily</p>
            </div>
            <div class="sub-nav">
"""

    # Arena sub-navigation
    arena_cat_order = ["overall", "text", "vision", "image", "video", "coding"]
    for cat_name in arena_cat_order:
        if cat_name in arena_categories:
            active = " active" if cat_name == "overall" else ""
            label = cat_name.title()
            count = len(arena_categories[cat_name])
            html += f'                <button class="sub-btn{active}" onclick="showArena(\'{cat_name}\')">{label} ({count})</button>\n'

    html += "            </div>\n"

    # Arena sub-sections
    for cat_name in arena_cat_order:
        if cat_name not in arena_categories:
            continue
        models = arena_categories[cat_name]
        active = " active" if cat_name == "overall" else ""
        html += f"""            <div id="arena-{cat_name}" class="sub-section{active}">
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Rating</th>
                        <th>Organization</th>
                    </tr>
                </thead>
                <tbody>
"""
        for i, model in enumerate(models[:100], 1):
            html += f"""                    <tr>
                        <td class="rank">#{model.get('rank', i)}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(model.get('rating'))}</td>
                        <td class="org">{esc(model.get('organization'))}</td>
                    </tr>
"""
        html += """                </tbody>
            </table>
            </div>
"""

    html += """        </div>

        <!-- LiveBench Section -->
        <div id="livebench" class="section">
            <div class="category-header">
                <h2>LiveBench Leaderboard</h2>
                <p>Sourced from livebench.ai via HuggingFace Dataset Viewer</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Score</th>
                        <th>Organization</th>
                        <th>Evaluations</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(livebench_models[:100], 1):
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(model.get('score'))}</td>
                        <td class="org">{esc(model.get('organization'))}</td>
                        <td class="votes">{fmt_number(model.get('num_scores'))}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
        </div>

        <!-- YUPP Section -->
        <div id="yupp" class="section">
            <div class="category-header">
                <h2>YUPP Leaderboard</h2>
                <p>Sourced from yupp.ai via Steel browser</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Rating</th>
                        <th>Wins</th>
                        <th>Losses</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(yupp_models[:100], 1):
        html += f"""                    <tr>
                        <td class="rank">#{model.get('rank', i)}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(model.get('score'))}</td>
                        <td class="votes">{fmt_number(model.get('wins'))}</td>
                        <td class="votes">{fmt_number(model.get('losses'))}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
        </div>

        <!-- Artificial Analysis Section -->
        <div id="artificial" class="section">
            <div class="category-header">
                <h2>Artificial Analysis</h2>
                <p>Sourced from artificialanalysis.ai</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Creator</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(artificial_models[:100], 1):
        name = model.get("name") or model.get("additional_text") or "Unknown"
        creator = model.get("model_creators") or model.get("organization") or ""
        # model_creators can be a list
        if isinstance(creator, list):
            creator = ", ".join(str(c) for c in creator)
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(name)}</td>
                        <td class="org">{esc(creator)}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
        </div>

        <!-- OpenRouter Section -->
        <div id="openrouter" class="section">
            <div class="category-header">
                <h2>OpenRouter Models</h2>
                <p>Sourced from openrouter.ai API</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Model</th>
                        <th>Context</th>
                        <th>Prompt $/M</th>
                        <th>Completion $/M</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(openrouter_models[:100], 1):
        name = model.get("name") or model.get("id", "Unknown")
        ctx = model.get("context_length")
        ctx_str = f"{ctx:,}" if ctx else "N/A"
        pricing = model.get("pricing", {})
        if isinstance(pricing, dict):
            prompt_price = pricing.get("prompt", "N/A")
            completion_price = pricing.get("completion", "N/A")
        else:
            prompt_price = "N/A"
            completion_price = "N/A"
        html += f"""                    <tr>
                        <td class="rank">{i}</td>
                        <td class="model-name">{esc(name)}</td>
                        <td class="votes">{ctx_str}</td>
                        <td class="votes">{esc(str(prompt_price))}</td>
                        <td class="votes">{esc(str(completion_price))}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
        </div>

        <!-- EQ Bench Section -->
        <div id="eqbench" class="section">
            <div class="category-header">
                <h2>EQ Bench Leaderboard</h2>
                <p>Sourced from eqbench.com</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Score</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(eqbench_models[:100], 1):
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(model.get('score'))}</td>
                    </tr>
"""

    html += f"""                </tbody>
            </table>
        </div>

        <div class="update-time">
            Last updated: {now}<br>
            Data sources: Arena, LiveBench, YUPP, Artificial Analysis, OpenRouter, EQ Bench
        </div>
    </div>

    <footer>
        <p>Rakium - AI Benchmark Aggregator</p>
    </footer>

    <script>
        function showTab(tabId) {{
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }}

        function showArena(cat) {{
            document.querySelectorAll('#arena .sub-section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('#arena .sub-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('arena-' + cat).classList.add('active');
            event.target.classList.add('active');
        }}

        function filterTable(input) {{
            const filter = input.value.toLowerCase();
            const table = input.nextElementSibling;
            if (!table || table.tagName !== 'TABLE') return;
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {{
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(filter) ? '' : 'none';
            }});
        }}
    </script>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated {output_path}")
    print(f"  Arena: {arena_total} models across {len(arena_categories)} categories")
    print(f"  LiveBench: {len(livebench_models)} models")
    print(f"  YUPP: {len(yupp_models)} models")
    print(f"  Artificial Analysis: {len(artificial_models)} models")
    print(f"  OpenRouter: {len(openrouter_models)} models")
    print(f"  EQ Bench: {len(eqbench_models)} models")


if __name__ == "__main__":
    generate_html()
