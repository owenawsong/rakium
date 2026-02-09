#!/usr/bin/env python3
"""
Rakium Generator - Creates HTML from scraped data.
Reads JSON files produced by scraper.py and generates output/index.html.

Data format from scraper.py:
  - arena.json:              { categories: { text, code, vision, text-to-image, image-edit, search, text-to-video, image-to-video: { models: [{name, rating, organization, votes, rank, ci, license}] } } }
  - livebench.json:          { categories: { overall: { models: [{name, score, scores: {global_avg, reasoning, coding, agentic_coding, math, data_analysis, language, if}}] } } }
  - yupp.json:               { categories: { overall, text, image, image-new, image-edit, search, svg, coding: { models: [{name, score, rank, wins, losses}] } } }
  - artificial_analysis.json:{ models: [{name, additional_text, model_creators: [{id, name}], ...}] }
  - openrouter.json:         { rankings: [{name, slug, author, request_count, p50_latency, p50_throughput, provider_count, total_tokens, total_requests}] }
  - eqbench.json:            { models: [{name, elo, score, traits: {abilities, humanlike, safety, assertive, social_iq, warm, analytic, insight, empathy, compliant, moralising, pragmatic}}] }
"""

import json
import html as html_module
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def load_json(filename):
    filepath = DATA_DIR / filename
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def esc(text):
    if text is None:
        return ""
    return html_module.escape(str(text))


def fmt_number(val):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        if val > 100:
            return f"{val:,.0f}"
        return f"{val:.2f}".rstrip('0').rstrip('.')
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def fmt_big_number(val):
    if val is None:
        return "N/A"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return str(val)
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return f"{val:,.0f}"


def fmt_latency(val):
    if val is None:
        return "N/A"
    try:
        return f"{float(val):,.0f}ms"
    except (ValueError, TypeError):
        return str(val)


def fmt_throughput(val):
    if val is None:
        return "N/A"
    try:
        return f"{float(val):,.1f} t/s"
    except (ValueError, TypeError):
        return str(val)


def get_creator_name(model):
    creators = model.get("model_creators") or model.get("organization") or ""
    if isinstance(creators, list):
        names = []
        for c in creators:
            if isinstance(c, dict):
                names.append(c.get("name", c.get("id", str(c))))
            else:
                names.append(str(c))
        return ", ".join(names)
    return str(creators)


def generate_html():
    # Load all data
    arena_data = load_json("arena.json")
    livebench_data = load_json("livebench.json")
    yupp_data = load_json("yupp.json")
    artificial_data = load_json("artificial_analysis.json")
    openrouter_data = load_json("openrouter.json")
    eqbench_data = load_json("eqbench.json")

    # Arena categories
    arena_categories = {}
    if arena_data and "categories" in arena_data:
        for cat_name, cat_data in arena_data["categories"].items():
            if isinstance(cat_data, dict) and "models" in cat_data:
                arena_categories[cat_name] = cat_data["models"]
    arena_overall = arena_categories.get("text", [])  # text is the main/largest category

    # LiveBench
    livebench_models = []
    if livebench_data and "categories" in livebench_data:
        lb_overall = livebench_data["categories"].get("overall", {})
        if isinstance(lb_overall, dict):
            livebench_models = lb_overall.get("models", [])

    # YUPP categories
    yupp_categories = {}
    if yupp_data and "categories" in yupp_data:
        for cat_name, cat_data in yupp_data["categories"].items():
            if isinstance(cat_data, dict) and "models" in cat_data:
                yupp_categories[cat_name] = cat_data["models"]
    yupp_overall = yupp_categories.get("overall", [])

    # Artificial Analysis
    artificial_models = artificial_data.get("models", []) if artificial_data else []

    # OpenRouter
    openrouter_models = openrouter_data.get("rankings", []) if openrouter_data else []

    # EQ Bench
    eqbench_models = eqbench_data.get("models", []) if eqbench_data else []

    # Totals
    arena_total = sum(len(m) for m in arena_categories.values())
    yupp_total = sum(len(m) for m in yupp_categories.values())

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # =========================================================================
    # BUILD HTML
    # =========================================================================
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rakium - AI Benchmark Aggregator</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0f; color: #e0e0e0; min-height: 100vh; }}
        .container {{ max-width: 1600px; margin: 0 auto; padding: 20px; }}
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
        .table-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #222; white-space: nowrap; }}
        th {{ background: #1a1a1f; color: #00ff88; font-weight: 600; text-transform: uppercase; font-size: 0.75em; letter-spacing: 0.5px; position: sticky; top: 0; }}
        tr:hover {{ background: #12121a; }}
        .rank {{ color: #00ff88; font-weight: 600; }}
        .model-name {{ color: #fff; font-weight: 500; white-space: normal; max-width: 300px; }}
        .org {{ color: #666; font-size: 0.9em; }}
        .score {{ color: #00aaff; font-weight: 600; }}
        .dim {{ color: #888; }}
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
                    <h3>{yupp_total}</h3>
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
"""

    # =========================================================================
    # ARENA SECTION (with sub-navigation)
    # =========================================================================
    html += """
        <!-- Arena Section -->
        <div id="arena" class="section">
            <div class="category-header">
                <h2>Arena / LM Arena Leaderboard</h2>
                <p>Sourced from lmarena.ai via Tavily</p>
            </div>
            <div class="sub-nav">
"""

    arena_cat_order = ["text", "code", "vision", "text-to-image", "image-edit", "search", "text-to-video", "image-to-video"]
    arena_cat_display = {
        "text": "Text", "code": "Code", "vision": "Vision",
        "text-to-image": "Text-to-Image", "image-edit": "Image Edit",
        "search": "Search", "text-to-video": "Text-to-Video",
        "image-to-video": "Image-to-Video",
    }
    for cat_name in arena_cat_order:
        if cat_name in arena_categories:
            active = " active" if cat_name == "text" else ""
            count = len(arena_categories[cat_name])
            display = arena_cat_display.get(cat_name, cat_name.title())
            html += f'                <button class="sub-btn{active}" onclick="showSub(\'arena\', \'{cat_name}\')">{display} ({count})</button>\n'

    html += "            </div>\n"

    for cat_name in arena_cat_order:
        if cat_name not in arena_categories:
            continue
        models = arena_categories[cat_name]
        active = " active" if cat_name == "text" else ""
        html += f"""            <div id="arena-{cat_name}" class="sub-section{active}">
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <div class="table-wrap">
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
        for i, model in enumerate(models[:200], 1):
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
            </div>
"""

    html += """        </div>
"""

    # =========================================================================
    # LIVEBENCH SECTION (with all score columns)
    # =========================================================================
    lb_score_cols = [
        ("global_avg", "Global Avg"),
        ("reasoning", "Reasoning"),
        ("coding", "Coding"),
        ("agentic_coding", "Agentic Coding"),
        ("math", "Math"),
        ("data_analysis", "Data Analysis"),
        ("language", "Language"),
        ("if", "IF"),
    ]

    html += """
        <!-- LiveBench Section -->
        <div id="livebench" class="section">
            <div class="category-header">
                <h2>LiveBench Leaderboard</h2>
                <p>Sourced from livebench.ai via Steel browser</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
"""

    for _, label in lb_score_cols:
        html += f"                        <th>{label}</th>\n"

    html += """                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(livebench_models[:200], 1):
        scores = model.get("scores", {})
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
"""
        for col_key, _ in lb_score_cols:
            val = scores.get(col_key) if scores else model.get(col_key)
            css = "score" if col_key == "global_avg" else "dim"
            html += f'                        <td class="{css}">{fmt_number(val)}</td>\n'
        html += "                    </tr>\n"

    html += """                </tbody>
            </table>
            </div>
        </div>
"""

    # =========================================================================
    # YUPP SECTION (with sub-navigation for categories)
    # =========================================================================
    html += """
        <!-- YUPP Section -->
        <div id="yupp" class="section">
            <div class="category-header">
                <h2>YUPP Leaderboard</h2>
                <p>Sourced from yupp.ai via Steel browser</p>
            </div>
            <div class="sub-nav">
"""

    yupp_cat_order = ["overall", "text", "image", "image-new", "image-edit", "search", "svg", "coding"]
    for cat_name in yupp_cat_order:
        if cat_name in yupp_categories:
            active = " active" if cat_name == "overall" else ""
            count = len(yupp_categories[cat_name])
            html += f'                <button class="sub-btn{active}" onclick="showSub(\'yupp\', \'{cat_name}\')">{cat_name.title()} ({count})</button>\n'

    html += "            </div>\n"

    for cat_name in yupp_cat_order:
        if cat_name not in yupp_categories:
            continue
        models = yupp_categories[cat_name]
        active = " active" if cat_name == "overall" else ""
        html += f"""            <div id="yupp-{cat_name}" class="sub-section{active}">
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <div class="table-wrap">
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
        for i, model in enumerate(models[:200], 1):
            html += f"""                    <tr>
                        <td class="rank">#{model.get('rank', i)}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(model.get('score'))}</td>
                        <td class="dim">{fmt_number(model.get('wins'))}</td>
                        <td class="dim">{fmt_number(model.get('losses'))}</td>
                    </tr>
"""
        html += """                </tbody>
            </table>
            </div>
            </div>
"""

    html += """        </div>
"""

    # =========================================================================
    # ARTIFICIAL ANALYSIS SECTION (with proper creator name extraction)
    # =========================================================================
    html += """
        <!-- Artificial Analysis Section -->
        <div id="artificial" class="section">
            <div class="category-header">
                <h2>Artificial Analysis</h2>
                <p>Sourced from artificialanalysis.ai</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Model</th>
                        <th>Creator</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(artificial_models[:200], 1):
        name = model.get("name") or model.get("additional_text") or "Unknown"
        creator = get_creator_name(model)
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(name)}</td>
                        <td class="org">{esc(creator)}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
            </div>
        </div>
"""

    # =========================================================================
    # OPENROUTER SECTION (with ranking data: requests, latency, throughput, tokens)
    # =========================================================================
    html += """
        <!-- OpenRouter Section -->
        <div id="openrouter" class="section">
            <div class="category-header">
                <h2>OpenRouter Rankings</h2>
                <p>Sourced from openrouter.ai/rankings (popularity &amp; usage data)</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Model</th>
                        <th>Author</th>
                        <th>Requests</th>
                        <th>P50 Latency</th>
                        <th>P50 Throughput</th>
                        <th>Total Tokens</th>
                        <th>Providers</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(openrouter_models[:200], 1):
        name = model.get("name") or model.get("slug", "Unknown")
        author = model.get("author", "")
        html += f"""                    <tr>
                        <td class="rank">{i}</td>
                        <td class="model-name">{esc(name)}</td>
                        <td class="org">{esc(author)}</td>
                        <td class="score">{fmt_big_number(model.get('request_count'))}</td>
                        <td class="dim">{fmt_latency(model.get('p50_latency'))}</td>
                        <td class="dim">{fmt_throughput(model.get('p50_throughput'))}</td>
                        <td class="dim">{fmt_big_number(model.get('total_tokens'))}</td>
                        <td class="dim">{fmt_number(model.get('provider_count'))}</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
            </div>
        </div>
"""

    # =========================================================================
    # EQ BENCH SECTION (with Elo + all 11 trait columns)
    # =========================================================================
    eq_trait_cols = [
        ("abilities", "Abilities"),
        ("humanlike", "Humanlike"),
        ("safety", "Safety"),
        ("assertive", "Assertive"),
        ("social_iq", "Social IQ"),
        ("warm", "Warm"),
        ("analytic", "Analytic"),
        ("insight", "Insight"),
        ("empathy", "Empathy"),
        ("compliant", "Compliant"),
        ("moralising", "Moralising"),
        ("pragmatic", "Pragmatic"),
    ]

    html += """
        <!-- EQ Bench Section -->
        <div id="eqbench" class="section">
            <div class="category-header">
                <h2>EQ Bench Leaderboard</h2>
                <p>Sourced from eqbench.com</p>
            </div>
            <input type="text" class="search-box" placeholder="Search models..." oninput="filterTable(this)">
            <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Elo Score</th>
"""

    for _, label in eq_trait_cols:
        html += f"                        <th>{label}</th>\n"

    html += """                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(eqbench_models[:200], 1):
        traits = model.get("traits", {})
        elo = model.get("elo") or model.get("score")
        html += f"""                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{esc(model.get('name'))}</td>
                        <td class="score">{fmt_number(elo)}</td>
"""
        for col_key, _ in eq_trait_cols:
            val = traits.get(col_key) if traits else None
            html += f'                        <td class="dim">{fmt_number(val)}</td>\n'
        html += "                    </tr>\n"

    html += f"""                </tbody>
            </table>
            </div>
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

        function showSub(parentId, cat) {{
            var parent = document.getElementById(parentId);
            parent.querySelectorAll('.sub-section').forEach(s => s.classList.remove('active'));
            parent.querySelectorAll('.sub-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(parentId + '-' + cat).classList.add('active');
            event.target.classList.add('active');
        }}

        function filterTable(input) {{
            var filter = input.value.toLowerCase();
            var container = input.parentElement;
            var table = container.querySelector('table');
            if (!table) {{
                var wrap = input.nextElementSibling;
                if (wrap) table = wrap.querySelector('table');
            }}
            if (!table) return;
            var rows = table.querySelectorAll('tbody tr');
            rows.forEach(function(row) {{
                var text = row.textContent.toLowerCase();
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
    print(f"  YUPP: {yupp_total} models across {len(yupp_categories)} categories")
    print(f"  Artificial Analysis: {len(artificial_models)} models")
    print(f"  OpenRouter: {len(openrouter_models)} models")
    print(f"  EQ Bench: {len(eqbench_models)} models")


if __name__ == "__main__":
    generate_html()
