"""
eBay Sold Listings Scraper
--------------------------
Uses eBay's Finding API + Browse API to get completed/sold listing data.

Two methods:
1. eBay Finding API (official, free OAuth) - completed listings
2. Direct page scrape of eBay sold search as fallback

Setup:
    1. Register at https://developer.ebay.com/
    2. Create app → get App ID (Client ID) for Finding API
    3. For Browse API: get OAuth token

Environment variables:
    EBAY_APP_ID     - Your eBay Developer App ID
    EBAY_OAUTH_TOKEN - OAuth token (for Browse API)
    
Finding API docs: https://developer.ebay.com/devzone/finding/callref/findCompletedItems.html
"""

import httpx
import re
import os
import json
from typing import List, Optional
from datetime import datetime


EBAY_FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def scrape_ebay_sold(search_query: str, cert_number: str, grading_company: str) -> List[dict]:
    """
    Fetch eBay sold listings for a given card.
    Tries official API first, falls back to page scraping.
    """
    # Always include cert number and grading company in search for precision
    full_query = f"{search_query} {grading_company} {cert_number}".strip()
    # Also try without cert for broader comps
    general_query = search_query

    results = []

    if EBAY_APP_ID:
        # Use official Finding API
        cert_results = await _ebay_finding_api(full_query, limit=10)
        general_results = await _ebay_finding_api(general_query, limit=20)
        results = cert_results + [r for r in general_results if r not in cert_results]
    else:
        # Fallback: scrape eBay sold search page
        results = await _scrape_ebay_sold_page(full_query)
        if len(results) < 5:
            general = await _scrape_ebay_sold_page(general_query)
            results.extend(general)

    # Deduplicate by item ID
    seen = set()
    deduped = []
    for r in results:
        if r.get("item_id") not in seen:
            seen.add(r.get("item_id"))
            deduped.append(r)

    return deduped[:30]  # Cap at 30 results


async def _ebay_finding_api(query: str, limit: int = 20) -> List[dict]:
    """Use eBay Finding API to search completed items."""
    if not EBAY_APP_ID:
        return []

    params = {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "keywords": query,
        "sortOrder": "EndTimeSoonest",
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "ListingType",
        "itemFilter(1).value": "AuctionWithBIN",
        "paginationInput.entriesPerPage": str(limit),
        "outputSelector(0)": "SellerInfo",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(EBAY_FINDING_API, params=params, headers=HEADERS)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = (data.get("findCompletedItemsResponse", [{}])[0]
                        .get("searchResult", [{}])[0]
                        .get("item", []))

            return [_parse_ebay_item(item) for item in items]
    except Exception:
        return []


def _parse_ebay_item(item: dict) -> dict:
    """Parse eBay API item into standardized format."""
    price_data = item.get("sellingStatus", [{}])[0]
    current_price = price_data.get("currentPrice", [{}])[0]
    price = float(current_price.get("__value__", 0))

    listing_info = item.get("listingInfo", [{}])[0]
    end_time = listing_info.get("endTime", [""])[0]

    image = item.get("galleryURL", [""])[0]
    item_url = item.get("viewItemURL", [""])[0]

    # Format date
    date_str = ""
    if end_time:
        try:
            dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = end_time[:10]

    return {
        "source": "eBay",
        "item_id": item.get("itemId", [""])[0],
        "title": item.get("title", [""])[0],
        "price": price,
        "currency": current_price.get("@currencyId", "USD"),
        "date": date_str,
        "url": item_url,
        "image_url": image,
        "condition": item.get("condition", [{}])[0].get("conditionDisplayName", [""])[0],
    }


async def _scrape_ebay_sold_page(query: str) -> List[dict]:
    """
    Scrape eBay completed/sold search results page.
    URL: https://www.ebay.com/sch/i.html?_nkw=QUERY&LH_Complete=1&LH_Sold=1
    """
    encoded_query = query.replace(" ", "+")
    url = (
        f"https://www.ebay.com/sch/i.html"
        f"?_nkw={encoded_query}"
        f"&LH_Complete=1&LH_Sold=1&LH_ItemCondition=3000"
        f"&_sacat=0&_sop=12"  # sort by recently ended
    )

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            })

            if resp.status_code != 200:
                return []

            html = resp.text
            return _parse_ebay_html(html)

    except Exception as e:
        return [{"source": "eBay", "error": str(e)}]


def _parse_ebay_html(html: str) -> List[dict]:
    """Parse eBay search results HTML to extract sold listings."""
    results = []

    # Find all listing blocks
    # eBay uses s-item class for listings
    item_blocks = re.findall(
        r'<li class="s-item[^"]*">(.*?)</li>',
        html, re.DOTALL
    )

    for block in item_blocks[:25]:
        try:
            # Title
            title_m = re.search(r'class="s-item__title[^"]*"[^>]*><span[^>]*>(.*?)</span>', block, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

            if not title or title.lower() == "shop on ebay":
                continue

            # Price
            price_m = re.search(r'class="s-item__price"[^>]*>\$?([\d,]+\.?\d*)', block)
            price = float(price_m.group(1).replace(",", "")) if price_m else 0

            # Date sold
            date_m = re.search(r'class="s-item__ended-date[^"]*"[^>]*>(.*?)<', block)
            if not date_m:
                date_m = re.search(r'Sold\s+([\w]+\s+\d+,\s+\d{4})', block)
            date_str = date_m.group(1).strip() if date_m else ""

            # URL
            url_m = re.search(r'href="(https://www\.ebay\.com/itm/[^"]+)"', block)
            url = url_m.group(1) if url_m else ""

            # Item ID from URL
            item_id_m = re.search(r'/itm/(\d+)', url)
            item_id = item_id_m.group(1) if item_id_m else ""

            # Image
            img_m = re.search(r'<img[^>]*src="(https://i\.ebayimg\.com[^"]+)"', block)
            image = img_m.group(1) if img_m else ""

            if price > 0:
                results.append({
                    "source": "eBay",
                    "item_id": item_id,
                    "title": title,
                    "price": price,
                    "currency": "USD",
                    "date": date_str,
                    "url": url,
                    "image_url": image,
                })

        except Exception:
            continue

    return results
