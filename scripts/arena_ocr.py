#!/usr/bin/env python3
"""
Arena.ai Scraper using Screenshot + OCR.space API
"""

import os
import json
import base64
import time
from pathlib import Path
from datetime import datetime
import requests

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

OCR_SPACE_API = "https://api.ocr.space/parse/image"
OCR_SPACE_KEY = "K89853229688957"  # User's API key

def screenshot_arena():
    """Take screenshot of Arena.ai and extract using OCR.space"""
    
    try:
        from playwright.sync_api import sync_playwright
        PLAYWRIGHT_AVAILABLE = True
    except ImportError:
        PLAYWRIGHT_AVAILABLE = False
    
    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "Playwright not available"}
    
    print("Taking screenshot of Arena.ai...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Set large viewport for full table
        page.set_viewport_size({"width": 1920, "height": 3000})
        
        print("Loading https://arena.ai/leaderboard...")
        page.goto("https://arena.ai/leaderboard", wait_until="networkidle", timeout=120000)
        
        # Wait for content
        time.sleep(5)
        
        # Take screenshot
        screenshot_path = DATA_DIR / "arena_screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"Screenshot saved: {screenshot_path}")
        
        browser.close()
    
    return screenshot_path

def ocr_image(image_path):
    """Send image to OCR.space and get text"""
    
    print("Sending to OCR.space...")
    
    with open(image_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()
    
    payload = {
        "apikey": OCR_SPACE_KEY,
        "base64Image": f"data:image/png;base64,{img_data}",
        "language": "eng",
        "isOverlayRequired": False,
        "detectOrientation": True,
        "scale": True,
    }
    
    response = requests.post(OCR_SPACE_API, data=payload, timeout=60)
    result = response.json()
    
    print(f"OCR Result: {result}")
    
    if result.get("ParsedResults"):
        return result["ParsedResults"][0].get("ParsedText", "")
    
    return ""

def parse_arena_text(text):
    """Parse OCR text to extract model rankings"""
    models = []
    lines = text.split('\n')
    
    import re
    
    # Pattern 1: "1. model-name 1234"
    # Pattern 2: "model-name 1234 rating"
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Try to extract rank and model name
        # Common patterns: "1." or "1)" or "-"
        
        # Pattern: rank number at start
        match = re.match(r'^[\(\[\{]?(\d+)[\)\]\}]?[.\)]\s*(.+)$', line)
        if match:
            rank = int(match.group(1))
            rest = match.group(2)
            
            # Extract model name (usually first word or quoted)
            name_match = re.match(r'^["\']?([A-Za-z0-9\-\_]+)["\']?', rest)
            if name_match:
                name = name_match.group(1)
                if len(name) > 3 and name.lower() not in ['rank', 'model', 'rating', 'votes', 'arena']:
                    # Try to find rating
                    rating_match = re.search(r'(\d+\.?\d*)\s*$', rest)
                    rating = float(rating_match.group(1)) if rating_match else None
                    
                    models.append({
                        "rank": rank,
                        "name": name,
                        "rating": rating
                    })
                    continue
        
        # Pattern 2: Just model name with numbers (look at next line for rating)
        words = line.split()
        if len(words) >= 2:
            if words[0][0].isdigit() or words[0].endswith('.'):
                # Likely a ranking line
                try:
                    rank = int(words[0].replace('.', '').replace(')', ''))
                    name = words[1]
                    if len(name) > 3 and name.lower() not in ['rank', 'model']:
                        # Find rating in this line or nearby
                        for w in words[2:]:
                            if re.match(r'\d+\.?\d*', w):
                                rating = float(w)
                                models.append({
                                    "rank": rank,
                                    "name": name,
                                    "rating": rating
                                })
                                break
                except:
                    pass
    
    # Remove duplicates and sort
    seen = set()
    unique_models = []
    for m in models:
        if m["name"] not in seen:
            seen.add(m["name"])
            unique_models.append(m)
    
    # Re-rank
    for i, m in enumerate(sorted(unique_models, key=lambda x: x.get("rating") or 0, reverse=True)):
        m["rank"] = i + 1
    
    return unique_models[:50]

def scrape_arena():
    """Main function to scrape Arena.ai"""
    
    print("=" * 50)
    print("Scraping Arena.ai via Screenshot + OCR")
    print("=" * 50)
    
    results = {
        "source": "arena.ai (OCR.space extraction)",
        "scraped_at": datetime.utcnow().isoformat(),
        "models": []
    }
    
    try:
        # Step 1: Take screenshot
        screenshot_path = screenshot_arena()
        
        if not screenshot_path or not os.path.exists(screenshot_path):
            raise Exception("Screenshot failed")
        
        # Step 2: OCR
        text = ocr_image(screenshot_path)
        
        if not text:
            raise Exception("OCR failed")
        
        # Save raw OCR text
        with open(DATA_DIR / "arena_ocr_raw.txt", "w", encoding="utf-8") as f:
            f.write(text)
        
        # Step 3: Parse
        models = parse_arena_text(text)
        
        results["models"] = models
        results["raw_text_length"] = len(text)
        
        print(f"\nExtracted {len(models)} models")
        for m in models[:10]:
            print(f"  #{m['rank']}: {m['name']} - Rating: {m.get('rating', 'N/A')}")
    
    except Exception as e:
        print(f"Error: {e}")
        results["error"] = str(e)
    
    return results

if __name__ == "__main__":
    result = scrape_arena()
    
    # Save
    with open(DATA_DIR / "arena_ocr.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    
    print(f"\nSaved to data/arena_ocr.json")