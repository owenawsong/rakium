# Rakium

Multi-source AI benchmark aggregator. Automatically updated every 6 hours.

## How it works

1. GitHub Actions runs scripts/scraper.py every 6 hours
2. Scraper fetches data from Artificial Analysis and LM Arena
3. scripts/generator.py builds a static HTML dashboard
4. Output is committed to output/ and deployed to Cloudflare Pages

## Manual update

Go to Actions tab → \
Update
Rakium
Data\ → \Run
workflow\
