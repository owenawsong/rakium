#!/usr/bin/env python3
"""
Rakium Generator - Creates HTML from scraped data.
Updated to use new data format from scraper.py
"""

import json
import os
from pathlib import Path
from datetime import datetime

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

def generate_html():
    """Generate the main HTML page."""

    # Load data from new format
    livebench_data = load_json("livebench.json")
    arena_data = load_json("arena.json")
    yupp_data = load_json("yupp.json")
    artificial_data = load_json("artificial_analysis.json")

    # Handle missing data
    livebench_categories = {}
    if livebench_data and "categories" in livebench_data:
        for cat_name, cat_data in livebench_data.get("categories", {}).items():
            if isinstance(cat_data, dict) and "models" in cat_data:
                livebench_categories[cat_name] = cat_data["models"]

    arena_models = arena_data.get("categories", {}).get("overall", {}).get("models", []) if arena_data else []
    yupp_models = yupp_data.get("categories", {}).get("overall", {}).get("models", []) if yupp_data else []

    artificial_models = artificial_data.get("models", []) if artificial_data else []

    # Get stats
    stats = {
        "total_models_arena": len(arena_models),
        "total_models_livebench": len(livebench_categories.get("overall", [])),
        "total_models_yupp": len(yupp_models),
        "livebench_categories": list(livebench_categories.keys()),
        "arena_categories": list(arena_data.get("categories", {}).keys()) if arena_data else [],
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rakium - AI Benchmark Aggregator</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0f; color: #e0e0e0; min-height: 100vh; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{ text-align: center; padding: 40px 0; border-bottom: 1px solid #222; margin-bottom: 30px; }}
        header h1 {{ font-size: 2.5em; background: linear-gradient(135deg, #00ff88, #00aaff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }}
        header p {{ color: #888; font-size: 1.1em; }}
        .tabs {{ display: flex; gap: 10px; margin-bottom: 30px; border-bottom: 1px solid #222; padding-bottom: 20px; flex-wrap: wrap; }}
        .tab {{ padding: 12px 24px; background: #1a1a1f; border: 1px solid #333; border-radius: 8px; cursor: pointer; transition: all 0.3s; color: #888; }}
        .tab:hover {{ background: #25252a; }}
        .tab.active {{ background: linear-gradient(135deg, #00ff88, #00aaff); border-color: transparent; color: #000; font-weight: 600; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: #1a1a1f; border: 1px solid #333; border-radius: 12px; padding: 20px; text-align: center; }}
        .stat-card h3 {{ font-size: 2em; color: #00ff88; margin-bottom: 5px; }}
        .stat-card p {{ color: #666; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; }}
        .section {{ display: none; }}
        .section.active {{ display: block; }}
        .benchmark-nav {{ display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }}
        .benchmark-btn {{ padding: 8px 16px; background: #1a1a1f; border: 1px solid #333; border-radius: 6px; cursor: pointer; color: #888; transition: all 0.2s; }}
        .benchmark-btn:hover, .benchmark-btn.active {{ background: #25252a; border-color: #00ff88; color: #00ff88; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #222; }}
        th {{ background: #1a1a1f; color: #00ff88; font-weight: 600; text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.5px; }}
        tr:hover {{ background: #12121a; }}
        .rank {{ color: #00ff88; font-weight: 600; }}
        .model-name {{ color: #fff; font-weight: 500; }}
        .org {{ color: #666; font-size: 0.9em; }}
        .score {{ color: #00aaff; font-weight: 600; }}
        .votes {{ color: #888; }}
        .category-header {{ margin: 30px 0 20px; padding-bottom: 15px; border-bottom: 1px solid #222; }}
        .category-header h2 {{ color: #fff; font-size: 1.5em; }}
        .category-header p {{ color: #666; margin-top: 5px; }}
        .view-toggle {{ display: flex; gap: 10px; margin-bottom: 20px; }}
        .view-btn {{ padding: 8px 16px; background: #1a1a1f; border: 1px solid #333; border-radius: 6px; cursor: pointer; color: #888; }}
        .view-btn.active {{ background: #00aaff; border-color: #00aaff; color: #000; }}
        .chart-container {{ height: 500px; margin-top: 20px; background: #1a1a1f; border-radius: 12px; padding: 20px; }}
        .update-time {{ text-align: center; color: #444; font-size: 0.85em; margin-top: 40px; padding-top: 20px; border-top: 1px solid #222; }}
        .comparison {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 20px; }}
        .compare-card {{ background: #1a1a1f; border: 1px solid #333; border-radius: 12px; padding: 20px; }}
        .compare-card h4 {{ margin-bottom: 15px; color: #00ff88; }}
        .compare-row {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #222; }}
        .compare-row:last-child {{ border-bottom: none; }}
        .compare-label {{ color: #666; }}
        .compare-value {{ color: #fff; font-weight: 500; }}
        footer {{ text-align: center; padding: 30px; margin-top: 50px; border-top: 1px solid #222; color: #444; }}
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
            <button class="tab" onclick="showTab('artificial')">Artificial Analysis</button>
            <button class="tab" onclick="showTab('arena')">Arena</button>
            <button class="tab" onclick="showTab('livebench')">LiveBench</button>
            <button class="tab" onclick="showTab('yupp')">YUPP</button>
            <button class="tab" onclick="showTab('compare')">Compare</button>
        </div>

        <!-- Overview Section -->
        <div id="overview" class="section active">
            <div class="stats">
                <div class="stat-card">
                    <h3>{stats['total_models_arena']}</h3>
                    <p>Arena Models</p>
                </div>
                <div class="stat-card">
                    <h3>{stats['total_models_livebench']}</h3>
                    <p>LiveBench Models</p>
                </div>
                <div class="stat-card">
                    <h3>{stats['total_models_yupp']}</h3>
                    <p>YUPP Models</p>
                </div>
                <div class="stat-card">
                    <h3>{len(stats['livebench_categories'])}</h3>
                    <p>LiveBench Categories</p>
                </div>
            </div>

            <h3 style="margin-bottom: 20px; color: #fff;">Top 10 Arena Models</h3>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Rating</th>
                        <th>Organization</th>
                        <th>Votes</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add top 10 from arena
    for i, model in enumerate(arena_models[:10], 1):
        html += f"""
                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{model.get('name', 'Unknown')}</td>
                        <td class="score">{model.get('rating', 'N/A')}</td>
                        <td class="org">{model.get('organization', 'Unknown')}</td>
                        <td class="votes">{model.get('votes', 0):,}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>

        <!-- Artificial Analysis Section -->
        <div id="artificial" class="section">
            <h3 style="margin-bottom: 20px; color: #fff;">Artificial Analysis Benchmarks</h3>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Organization</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add artificial analysis models
    for i, model in enumerate(artificial_models[:20], 1):
        html += f"""
                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{model.get('name', 'Unknown')}</td>
                        <td class="org">{model.get('model_creators', 'Unknown')}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>

        <!-- Arena Section -->
        <div id="arena" class="section">
            <h3 style="margin-bottom: 20px; color: #fff;">Arena Leaderboard</h3>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Rating</th>
                        <th>Organization</th>
                        <th>Votes</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(arena_models, 1):
        html += f"""
                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{model.get('name', 'Unknown')}</td>
                        <td class="score">{model.get('rating', 'N/A')}</td>
                        <td class="org">{model.get('organization', 'Unknown')}</td>
                        <td class="votes">{model.get('votes', 0):,}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>

        <!-- LiveBench Section -->
        <div id="livebench" class="section">
"""

    # Add LiveBench categories
    for cat_name in ["overall", "language", "coding", "instruction_following"]:
        if cat_name in livebench_categories:
            models = livebench_categories[cat_name]
            html += f"""
            <div class="category-header">
                <h2>{cat_name.replace('_', ' ').title()}</h2>
                <p>Top models in {cat_name.replace('_', ' ')} category</p>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                        <th>Avg Score</th>
                        <th>Evaluations</th>
                    </tr>
                </thead>
                <tbody>
"""

            for i, model in enumerate(models[:20], 1):
                html += f"""
                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{model.get('model', 'Unknown')}</td>
                        <td class="score">{model.get('avg_score', 'N/A')}</td>
                        <td class="votes">{model.get('num_evaluations', 0)}</td>
                    </tr>
"""

            html += """
                </tbody>
            </table>
"""

    html += """
        </div>

        <!-- YUPP Section -->
        <div id="yupp" class="section">
            <h3 style="margin-bottom: 20px; color: #fff;">YUPP Leaderboard</h3>
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Model</th>
                    </tr>
                </thead>
                <tbody>
"""

    for i, model in enumerate(yupp_models[:20], 1):
        html += f"""
                    <tr>
                        <td class="rank">#{i}</td>
                        <td class="model-name">{model.get('name', 'Unknown')}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>

        <!-- Compare Section -->
        <div id="compare" class="section">
            <h3 style="margin-bottom: 20px; color: #fff;">Model Comparison</h3>
            <p style="color: #666; margin-bottom: 20px;">Select two models to compare side-by-side (coming soon)</p>
            <div class="comparison">
                <div class="compare-card">
                    <h4>Model 1</h4>
                    <p style="color: #666;">Select a model from the dropdown above</p>
                </div>
                <div class="compare-card">
                    <h4>Model 2</h4>
                    <p style="color: #666;">Select a model from the dropdown above</p>
                </div>
            </div>
        </div>

        <div class="update-time">
            Last updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M UTC") + """<br>
            Data sources: Arena, LiveBench, YUPP, Artificial Analysis
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
    </script>
</body>
</html>
"""

    with open(OUTPUT_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated {OUTPUT_DIR / 'index.html'}")

if __name__ == "__main__":
    generate_html()