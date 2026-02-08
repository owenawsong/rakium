"""
Rakium Generator - Reads JSON from data/ and writes a static
HTML dashboard into output/index.html.
"""

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE, "data")
OUTPUT_DIR = os.path.join(BASE, "output")


def load_json(filename):
    """Load a JSON file from DATA_DIR, returning None on failure."""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  ⚠ Missing {path}")
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ── helper: turn any value into safe JSON for embedding in <script> ───────
def js(obj):
    return json.dumps(obj, ensure_ascii=False)


def build_html(aa_data, lma_data, meta):
    """Return the full HTML string for the dashboard."""

    last_updated = "Unknown"
    if meta:
        last_updated = meta.get("last_updated", "Unknown")

    # ── Benchmark metadata for the frontend ──────────────────────────
    benchmarks_js = js(aa_data["benchmarks"]) if aa_data else "{}"
    models_js = js(aa_data["models"][:80]) if aa_data else "[]"
    lma_js = js(lma_data[:40]) if lma_data else "[]"

    aa_count = len(aa_data["models"]) if aa_data else 0
    bench_count = len(aa_data["benchmarks"]) if aa_data else 0
    lma_count = len(lma_data) if lma_data else 0

    # ── Benchmark nav buttons (built server-side so first paint is fast)
    nav_buttons = ""
    if aa_data:
        for field, info in aa_data["benchmarks"].items():
            nav_buttons += (
                f'<button onclick="showBench(\'{field}\')" '
                f'id="btn-{field}">{info["label"]}</button>\n'
            )

    # ── LM Arena table rows ──────────────────────────────────────────
    lma_rows = ""
    if lma_data:
        for m in lma_data[:40]:
            rating = round(m["rating"], 1) if isinstance(m["rating"], float) else m["rating"]
            votes = f'{m["votes"]:,}' if isinstance(m["votes"], (int, float)) else m["votes"]
            lma_rows += (
                f'<tr><td>{m["rank"]}</td>'
                f'<td>{m["name"]}</td>'
                f'<td class="sc">{rating}</td>'
                f'<td>{m["organization"]}</td>'
                f'<td>{votes}</td></tr>\n'
            )

    # ── Model selector options ───────────────────────────────────────
    model_options = '<option value="">— pick —</option>\n'
    if aa_data:
        for i, m in enumerate(aa_data["models"][:80]):
            model_options += f'<option value="{i}">{m["name"]}</option>\n'

    # ── The full HTML page ───────────────────────────────────────────
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rakium — AI Benchmark Aggregator</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
/* ── Reset & base ─────────────────────────────────────── */
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#09090b;color:#e4e4e7}}
a{{color:#60a5fa}}

/* ── Layout ───────────────────────────────────────────── */
.wrap{{max-width:1420px;margin:0 auto;padding:16px}}
header{{text-align:center;padding:24px 0 8px}}
header h1{{font-size:2rem;letter-spacing:.05em;color:#fff}}
header p{{color:#71717a;font-size:.85rem;margin-top:4px}}
.updated{{text-align:center;color:#52525b;font-size:.75rem;margin-bottom:18px}}

/* ── Stat cards ───────────────────────────────────────── */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}}
.stat{{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:14px;text-align:center}}
.stat b{{display:block;font-size:1.7rem;color:#4ade80}}
.stat span{{color:#a1a1aa;font-size:.75rem}}

/* ── Tabs ─────────────────────────────────────────────── */
.tabs{{display:flex;gap:4px;margin-bottom:14px}}
.tabs button{{padding:9px 18px;border:none;background:#18181b;color:#a1a1aa;cursor:pointer;border-radius:6px 6px 0 0;font-size:.85rem;transition:background .15s}}
.tabs button:hover{{background:#27272a}}
.tabs button.on{{background:#27272a;color:#fff}}
.sec{{display:none}}.sec.on{{display:block}}

/* ── Benchmark nav ────────────────────────────────────── */
.nav{{display:flex;flex-wrap:wrap;gap:5px;padding:10px;background:#18181b;border-radius:8px;margin-bottom:12px}}
.nav button{{padding:5px 12px;border:1px solid #27272a;background:#09090b;color:#a1a1aa;cursor:pointer;border-radius:5px;font-size:.78rem;transition:all .15s}}
.nav button:hover{{background:#27272a;color:#e4e4e7}}
.nav button.on{{background:#2563eb;border-color:#2563eb;color:#fff}}

/* ── View toggle ──────────────────────────────────────── */
.vt{{margin-bottom:10px}}
.vt button{{padding:5px 14px;border:1px solid #27272a;background:#18181b;color:#a1a1aa;cursor:pointer;font-size:.8rem;transition:all .15s}}
.vt button.on{{background:#27272a;color:#fff}}

/* ── Tables ───────────────────────────────────────────── */
table{{width:100%;border-collapse:collapse;background:#18181b;border-radius:8px;overflow:hidden;margin-bottom:10px}}
th,td{{padding:9px 10px;text-align:left;font-size:.82rem;border-bottom:1px solid #27272a}}
th{{background:#111113;color:#71717a;font-weight:600}}
tr:hover{{background:#1c1c1f}}
.sc{{font-weight:700;color:#4ade80}}

/* ── Chart container ──────────────────────────────────── */
.chart-wrap{{background:#18181b;border-radius:8px;padding:14px;height:380px;margin-bottom:10px}}

/* ── Compare section ──────────────────────────────────── */
.cmp-bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}}
.cmp-bar select{{padding:8px;background:#18181b;color:#e4e4e7;border:1px solid #27272a;border-radius:6px;min-width:240px;font-size:.85rem}}
.cmp-bar button{{padding:8px 20px;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:.85rem}}
.cmp-bar button:hover{{background:#1d4ed8}}

/* ── Footer ───────────────────────────────────────────── */
footer{{text-align:center;padding:30px 0 18px;color:#3f3f46;font-size:.75rem}}
</style>
</head>
<body>
<div class="wrap">

<!-- ─── Header ──────────────────────────────────────── -->
<header>
  <h1>RAKIUM</h1>
  <p>Multi-source AI benchmark aggregator</p>
</header>
<div class="updated">Last data update: {last_updated}</div>

<!-- ─── Stats ───────────────────────────────────────── -->
<div class="stats">
  <div class="stat"><b>{aa_count}</b><span>Models Tracked</span></div>
  <div class="stat"><b>{bench_count}</b><span>Benchmarks</span></div>
  <div class="stat"><b>{lma_count}</b><span>Arena Rankings</span></div>
  <div class="stat"><b>2</b><span>Data Sources</span></div>
</div>

<!-- ─── Section tabs ────────────────────────────────── -->
<div class="tabs">
  <button class="on" onclick="tab('aa',this)">Benchmarks</button>
  <button onclick="tab('lma',this)">LM Arena</button>
  <button onclick="tab('cmp',this)">Compare</button>
</div>

<!-- ════════════════════════════════════════════════════ -->
<!-- SECTION: Benchmarks                                 -->
<!-- ════════════════════════════════════════════════════ -->
<div id="sec-aa" class="sec on">
  <div class="nav" id="bnav">{nav_buttons}</div>
  <div class="vt">
    <button class="on" id="vt-t" onclick="view('t')">Table</button>
    <button id="vt-c" onclick="view('c')">Chart</button>
  </div>
  <div id="aa-tbl">
    <table>
      <thead><tr><th>#</th><th>Model</th><th>Score</th><th>Creator</th><th>Context</th></tr></thead>
      <tbody id="aa-tb"></tbody>
    </table>
  </div>
  <div id="aa-cht" class="chart-wrap" style="display:none">
    <canvas id="aa-cv"></canvas>
  </div>
</div>

<!-- ════════════════════════════════════════════════════ -->
<!-- SECTION: LM Arena                                   -->
<!-- ════════════════════════════════════════════════════ -->
<div id="sec-lma" class="sec">
  <div class="vt">
    <button class="on" id="lv-t" onclick="lview('t')">Table</button>
    <button id="lv-c" onclick="lview('c')">Chart</button>
  </div>
  <div id="lma-tbl">
    <table>
      <thead><tr><th>#</th><th>Model</th><th>ELO</th><th>Organization</th><th>Votes</th></tr></thead>
      <tbody>{lma_rows}</tbody>
    </table>
  </div>
  <div id="lma-cht" class="chart-wrap" style="display:none">
    <canvas id="lma-cv"></canvas>
  </div>
</div>

<!-- ════════════════════════════════════════════════════ -->
<!-- SECTION: Compare                                    -->
<!-- ════════════════════════════════════════════════════ -->
<div id="sec-cmp" class="sec">
  <div class="cmp-bar">
    <select id="m1">{model_options}</select>
    <select id="m2">{model_options}</select>
    <button onclick="compare()">Compare</button>
  </div>
  <div id="cmp-out"></div>
</div>

<footer>Rakium · Data sourced from Artificial Analysis &amp; LM Arena · Auto-updated every 6 hours</footer>
</div>

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- JAVASCRIPT                                                     -->
<!-- ═══════════════════════════════════════════════════════════════ -->
<script>
/* ── Data (embedded at build time) ──────────────────── */
const B = {benchmarks_js};
const M = {models_js};
const L = {lma_js};
const BK = Object.keys(B);

/* ── State ──────────────────────────────────────────── */
let curBench = BK[0] || "";
let curView  = "t";
let aaChart  = null;
let lmaChart = null;

/* ── Tab switching ──────────────────────────────────── */
function tab(id, btn) {{
  document.querySelectorAll(".sec").forEach(e => e.classList.remove("on"));
  document.querySelectorAll(".tabs button").forEach(e => e.classList.remove("on"));
  document.getElementById("sec-" + id).classList.add("on");
  btn.classList.add("on");
}}

/* ── Benchmark switching ────────────────────────────── */
function showBench(f) {{
  curBench = f;
  document.querySelectorAll("#bnav button").forEach(b => b.classList.remove("on"));
  const el = document.getElementById("btn-" + f);
  if (el) el.classList.add("on");
  render();
}}

/* ── View toggle (table / chart) ────────────────────── */
function view(v) {{
  curView = v;
  document.getElementById("vt-t").classList.toggle("on", v === "t");
  document.getElementById("vt-c").classList.toggle("on", v === "c");
  document.getElementById("aa-tbl").style.display = v === "t" ? "" : "none";
  document.getElementById("aa-cht").style.display = v === "c" ? "" : "none";
  if (v === "c") renderChart();
}}

/* ── Render benchmark table ─────────────────────────── */
function render() {{
  const b = B[curBench];
  if (!b) return;
  const tb = document.getElementById("aa-tb");
  tb.innerHTML = b.models.map(m => {{
    const s = b.pct ? (m.score * 100).toFixed(1) + "%" : m.score.toFixed(2);
    const ctx = m.context_window ? m.context_window.toLocaleString() : "—";
    return "<tr><td>" + m.rank + "</td><td>" + m.name + "</td><td class=\\"sc\\">" + s + "</td><td>" + m.creator + "</td><td>" + ctx + "</td></tr>";
  }}).join("");
  if (curView === "c") renderChart();
}}

/* ── Render benchmark chart ─────────────────────────── */
function renderChart() {{
  const b = B[curBench];
  if (!b) return;
  const ctx = document.getElementById("aa-cv").getContext("2d");
  if (aaChart) aaChart.destroy();
  const top = b.models.slice(0, 14);
  const labels = top.map(m => m.name.substring(0, 20));
  const vals   = top.map(m => b.pct ? m.score * 100 : m.score);
  aaChart = new Chart(ctx, {{
    type: "bar",
    data: {{ labels, datasets: [{{ label: b.label, data: vals, backgroundColor: "rgba(74,222,128,.7)", borderColor: "rgba(74,222,128,1)", borderWidth: 1 }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false, indexAxis: "y",
      plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: b.label, color: "#fff" }} }},
      scales: {{ x: {{ ticks: {{ color: "#888" }}, grid: {{ color: "#222" }} }}, y: {{ ticks: {{ color: "#ccc" }}, grid: {{ color: "#222" }} }} }}
    }}
  }});
}}

/* ── LM Arena view toggle ───────────────────────────── */
function lview(v) {{
  document.getElementById("lv-t").classList.toggle("on", v === "t");
  document.getElementById("lv-c").classList.toggle("on", v === "c");
  document.getElementById("lma-tbl").style.display = v === "t" ? "" : "none";
  document.getElementById("lma-cht").style.display = v === "c" ? "" : "none";
  if (v === "c" && !lmaChart) renderLmaChart();
}}

function renderLmaChart() {{
  const ctx = document.getElementById("lma-cv").getContext("2d");
  const top = L.slice(0, 12);
  lmaChart = new Chart(ctx, {{
    type: "bar",
    data: {{ labels: top.map(m => m.name.substring(0, 24)), datasets: [{{ label: "ELO", data: top.map(m => m.rating), backgroundColor: "rgba(96,165,250,.7)", borderColor: "rgba(96,165,250,1)", borderWidth: 1 }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false, indexAxis: "y",
      plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: "LM Arena ELO Ratings", color: "#fff" }} }},
      scales: {{ x: {{ ticks: {{ color: "#888" }}, grid: {{ color: "#222" }} }}, y: {{ ticks: {{ color: "#ccc" }}, grid: {{ color: "#222" }} }} }}
    }}
  }});
}}

/* ── Comparator ─────────────────────────────────────── */
function compare() {{
  const i1 = document.getElementById("m1").value;
  const i2 = document.getElementById("m2").value;
  const out = document.getElementById("cmp-out");
  if (!i1 || !i2) {{ out.innerHTML = '<p style="color:#f87171">Select both models.</p>'; return; }}
  const a = M[i1], b = M[i2];
  const bms = BK.map(k => ({{ key: k, label: B[k].label, pct: B[k].pct }}));
  let h = '<table><thead><tr><th>Benchmark</th><th>' + a.name.substring(0,22) + '</th><th>' + b.name.substring(0,22) + '</th><th>Winner</th></tr></thead><tbody>';
  bms.forEach(bm => {{
    const v1 = a[bm.key], v2 = b[bm.key];
    const f = v => v == null ? "—" : (bm.pct ? (v * 100).toFixed(1) + "%" : v.toFixed(2));
    let w = "—";
    if (v1 != null && v2 != null) w = v1 > v2 ? a.name.substring(0,14) : (v2 > v1 ? b.name.substring(0,14) : "Tie");
    h += "<tr><td>" + bm.label + "</td><td class=\\"sc\\">" + f(v1) + "</td><td class=\\"sc\\">" + f(v2) + "</td><td>" + w + "</td></tr>";
  }});
  h += "</tbody></table>";
  out.innerHTML = h;
}}

/* ── Init ───────────────────────────────────────────── */
if (BK.length) {{
  document.getElementById("btn-" + BK[0])?.classList.add("on");
  render();
}}
</script>
</body>
</html>'''


def main():
    print("=" * 60)
    print("Rakium Generator")
    print("=" * 60)

    aa = load_json("artificial_analysis.json")
    lma = load_json("lm_arena.json")
    meta = load_json("meta.json")

    if not aa and not lma:
        print("No data files found. Run scraper.py first.")
        sys.exit(1)

    html = build_html(aa, lma, meta)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    size_kb = len(html.encode("utf-8")) / 1024
    print(f"\n✓ Generated {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()