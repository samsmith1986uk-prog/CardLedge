"""
TCDB (Trading Card Database) Scraper
------------------------------------
Fetches card images and set data from tcdb.com.
Uses Playwright due to Cloudflare protection.

Image URL patterns:
  Front: /Images/Cards/{Sport}/{set_id}/{set_id}-{card_number}Fr.jpg
  Back:  /Images/Cards/{Sport}/{set_id}/{set_id}-{card_number}Bk.jpg
"""

import re
import asyncio
from typing import Optional, List
from urllib.parse import quote_plus


async def search_tcdb(player_name: str, year: str = "", brand: str = "",
                      card_number: str = "", sport: str = "") -> List[dict]:
    """Search TCDB for card images and set data using Playwright."""
    query_parts = [player_name]
    if year:
        query_parts.append(year[:4])
    if brand:
        query_parts.append(brand)
    query = " ".join(query_parts)

    url = f"https://www.tcdb.com/Search.cfm/search/{quote_plus(query)}"
    print(f"[tcdb] Searching: {url}")

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            # Navigate and wait for Cloudflare challenge to resolve
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Check if we landed on the search results or a person page
            current_url = page.url
            print(f"[tcdb] Landed on: {current_url}")

            results = await page.evaluate("""() => {
                const cards = [];
                // Look for card entries in search results
                // TCDB uses table-based layout with img.img-fluid for card images
                const imgs = document.querySelectorAll('img.img-fluid');
                for (const img of imgs) {
                    const src = img.getAttribute('data-original') || img.src || '';
                    if (!src || !src.includes('/Images/')) continue;

                    // Find parent link for card URL
                    const link = img.closest('a');
                    const href = link?.href || '';

                    // Try to extract set_id and card_id from the URL
                    const m = href.match(/ViewCard\\.cfm\\/sid\\/(\\d+)\\/cid\\/(\\d+)/);

                    // Get card text from nearby elements
                    const parent = img.closest('td') || img.closest('div');
                    const text = parent?.textContent?.trim() || '';

                    cards.push({
                        image_url: src.startsWith('http') ? src : 'https://www.tcdb.com/' + src.replace(/^\\//, ''),
                        card_url: href,
                        set_id: m ? m[1] : '',
                        card_id: m ? m[2] : '',
                        text: text.slice(0, 200),
                    });
                }

                // Also look for card links in table rows (search results format)
                const rows = document.querySelectorAll('table tr');
                for (const row of rows) {
                    const link = row.querySelector('a[href*="ViewCard.cfm"]');
                    if (!link) continue;
                    const m = link.href.match(/ViewCard\\.cfm\\/sid\\/(\\d+)\\/cid\\/(\\d+)/);
                    if (!m) continue;

                    const img = row.querySelector('img');
                    const src = img ? (img.getAttribute('data-original') || img.src || '') : '';

                    cards.push({
                        image_url: src.startsWith('http') ? src : (src ? 'https://www.tcdb.com/' + src.replace(/^\\//, '') : ''),
                        card_url: link.href,
                        set_id: m[1],
                        card_id: m[2],
                        text: link.textContent?.trim() || row.textContent?.trim()?.slice(0, 200) || '',
                    });
                }

                // Deduplicate by card_id
                const seen = new Set();
                return cards.filter(c => {
                    const key = c.card_id || c.image_url;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });
            }""")

            await browser.close()
            print(f"[tcdb] Found {len(results)} results")

            # Filter to best matches
            filtered = []
            for r in results:
                # Build front image URL if we have set_id
                if r.get("set_id") and card_number:
                    cn = card_number.strip("#").strip()
                    sport_path = _guess_sport_path(sport)
                    r["image_front"] = f"https://www.tcdb.com/Images/Cards/{sport_path}/{r['set_id']}/{r['set_id']}-{cn}Fr.jpg"
                    r["image_back"] = f"https://www.tcdb.com/Images/Cards/{sport_path}/{r['set_id']}/{r['set_id']}-{cn}Bk.jpg"
                filtered.append(r)

            return filtered[:10]

    except Exception as e:
        print(f"[tcdb] Error: {e}")
        return []


async def get_tcdb_card_image(player_name: str, year: str = "", brand: str = "",
                               card_number: str = "", sport: str = "") -> Optional[str]:
    """Get the best card image URL from TCDB."""
    results = await search_tcdb(player_name, year, brand, card_number, sport)
    if not results:
        return None

    # Prefer results with actual image URLs
    for r in results:
        if r.get("image_front"):
            return r["image_front"]
        if r.get("image_url") and "Images/Cards" in r["image_url"]:
            return r["image_url"]

    # Fall back to any image
    for r in results:
        if r.get("image_url"):
            return r["image_url"]

    return None


def _guess_sport_path(sport: str) -> str:
    """Map sport category to TCDB path component."""
    s = (sport or "").lower()
    if "basket" in s:
        return "Basketball"
    if "football" in s or "soccer" in s:
        return "Soccer"
    if "baseball" in s:
        return "Baseball"
    if "hockey" in s:
        return "Hockey"
    if "gaming" in s or "pokemon" in s or "one piece" in s or "yugioh" in s:
        return "Gaming"
    return "Basketball"  # default
