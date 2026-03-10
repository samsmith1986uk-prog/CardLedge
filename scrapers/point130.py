"""
130point.com Scraper
--------------------
130point aggregates sold data from: eBay, Goldin, Fanatics Collect,
MySlabs, Pristine Auction, Heritage Auctions.

Key advantage: Exposes eBay Best Offer prices that eBay's own API hides.
Trusted by 160K+ collectors. 15M+ sold items indexed.

URL format: https://130point.com/sales/?s=SEARCH+QUERY&source=all

NOTE: 130point uses Cloudflare protection. Options:
1. Use rotating proxies + cloudscraper library
2. Use Playwright with stealth mode
3. Use their mobile app API (requires traffic analysis)

This implementation uses cloudscraper for the initial attempt,
falls back to httpx with browser-like headers.
"""

import httpx
import re
import json
from typing import List
from urllib.parse import quote_plus


SEARCH_URL = "https://130point.com/sales/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


async def scrape_130point(search_query: str) -> List[dict]:
    """
    Search 130point for sold comps across all sources.
    Returns list of standardized sale records.
    
    Production recommendation: Use Playwright with stealth plugin for reliability:
    
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0...",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()
            await stealth_async(page)
            await page.goto(f"https://130point.com/sales/?s={quote_plus(search_query)}&source=all")
            await page.wait_for_selector(".result-item", timeout=10000)
            content = await page.content()
            # Parse content...
    """
    encoded = quote_plus(search_query)
    url = f"{SEARCH_URL}?s={encoded}&source=all"

    results = []

    # Try cloudscraper if available
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
        resp = scraper.get(url, timeout=20)
        if resp.status_code == 200:
            results = _parse_130point_html(resp.text, search_query)
            if results:
                return results
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: httpx
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=HEADERS
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                results = _parse_130point_html(resp.text, search_query)
    except Exception as e:
        results = [{"source": "130point", "error": str(e), "price": 0}]

    return results


def _parse_130point_html(html: str, query: str) -> List[dict]:
    """Parse 130point search results HTML."""
    results = []

    # 130point renders results in a table/list with class="result-item" or similar
    # The exact structure may change — this targets their typical output

    # Try to find JSON data embedded in page
    json_match = re.search(r'var salesData\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            for item in data:
                results.append(_normalize_130point_item(item))
            return results
        except Exception:
            pass

    # Parse HTML table rows
    rows = re.findall(r'<tr[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</tr>', html, re.DOTALL)

    if not rows:
        # Try alternate structure
        rows = re.findall(r'<div[^>]*class="[^"]*sale-item[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)

    for row in rows[:30]:
        try:
            # Title/description
            title_m = re.search(r'class="[^"]*title[^"]*"[^>]*>(.*?)</', row, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

            # Price
            price_m = re.search(r'\$\s*([\d,]+\.?\d*)', row)
            price = float(price_m.group(1).replace(",", "")) if price_m else 0

            # Date
            date_m = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})', row)
            date_str = date_m.group(1) if date_m else ""

            # Source marketplace
            source_m = re.search(r'class="[^"]*source[^"]*"[^>]*>(.*?)</', row, re.DOTALL)
            marketplace = re.sub(r'<[^>]+>', '', source_m.group(1)).strip() if source_m else "130point"

            # URL
            url_m = re.search(r'href="(https?://[^"]+)"', row)
            url = url_m.group(1) if url_m else ""

            if price > 0:
                results.append({
                    "source": f"130point ({marketplace})",
                    "title": title or query,
                    "price": price,
                    "currency": "USD",
                    "date": date_str,
                    "url": url,
                    "marketplace": marketplace,
                })
        except Exception:
            continue

    return results


def _normalize_130point_item(item: dict) -> dict:
    """Normalize a 130point JSON item."""
    return {
        "source": f"130point ({item.get('source', 'unknown')})",
        "title": item.get("title", item.get("name", "")),
        "price": float(item.get("price", item.get("sale_price", 0))),
        "currency": "USD",
        "date": item.get("date", item.get("sale_date", "")),
        "url": item.get("url", item.get("link", "")),
        "marketplace": item.get("source", ""),
    }
