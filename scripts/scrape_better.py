#!/usr/bin/env python3
"""
Better scraper - waits for dynamic content to load
"""

import json
import time
from pathlib import Path
from steel import Steel
from playwright.sync_api import sync_playwright

STEEL_API_KEY = "ste-TF2eYXABEwRGRdc01EvsyMp0KWnMY9jZUOpV2AfPivGVnQfTxv6u4viYaAVuz61OB8glEvu92fUsRTcFl4dqUd3VRmyJdn7XFkd"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

def scrape_arena_better():
    """Scrape Arena with better content extraction"""
    
    print("Starting Steel session...")
    client = Steel(steel_api_key=STEEL_API_KEY)
    session = client.sessions.create()
    print(f"Session: {session.session_viewer_url}")
    
    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(
        f"wss://connect.steel.dev?apiKey={STEEL_API_KEY}&sessionId={session.id}"
    )
    
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    
    print("\nLoading Arena.ai...")
    page.goto("https://arena.ai/leaderboard", wait_until="networkidle", timeout=180000)
    
    # Wait MUCH longer for JavaScript
    print("Waiting for content to load...")
    time.sleep(15)  # 15 seconds!
    
    # Try to find and click "Show More" buttons
    print("Looking for 'Show More' buttons...")
    
    try:
        # Look for any buttons
        buttons = page.locator("button").all()
        print(f"Found {len(buttons)} buttons")
        for btn in buttons[:5]:
            text = btn.text_content()
            print(f"  Button: {text[:50]}")
    except:
        pass
    
    # Take screenshot
    page.screenshot(path="data/arena_screenshot2.png")
    print("Screenshot saved")
    
    # Get page content AFTER JavaScript
    html = page.content()
    
    with open("data/arena_steel2.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML saved (size: {len(html):,} chars)")
    
    # Now try to find actual data
    import re
    
    # Pattern: look for model data with ratings
    print("\nLooking for model data...")
    
    # Look for "model" followed by numbers
    patterns = [
        r'"model[^"]*"\s*:\s*"([^"]+)"',
        r'"rating"\s*:\s*([0-9]+\.?\d*)',
        r'"votes"\s*:\s*([0-9]+)',
        r'"[a-z]+"\s*:\s*([0-9]{4})',  # 4-digit ratings
    ]
    
    for p in patterns:
        matches = re.findall(p, html)
        if matches:
            print(f"  {p[:50]}: {len(matches)} matches")
            print(f"    Sample: {matches[:5]}")
    
    browser.close()
    client.sessions.release(session.id)
    playwright.stop()
    
    print("\nDone!")

if __name__ == "__main__":
    scrape_arena_better()
