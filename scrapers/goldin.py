"""
Goldin Auction Scraper
----------------------
Goldin is now owned by eBay. Hosts weekly and monthly auctions.
Key for high-end card pricing data.

URL: https://goldin.co/auctions
Search: https://goldin.co/browse/all?q=QUERY&status=sold
"""

import httpx
import re
import json
from typing import List
from urllib.parse import quote_plus


GOLDIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://goldin.co/",
    "Origin": "https://goldin.co",
}

HERITAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_goldin(search_query: str) -> List[dict]:
    """
    Scrape Goldin auction results for a card.
    
    Goldin uses a React/Next.js frontend. Options:
    1. Try their internal API (discovered via network analysis)
    2. Playwright for full JS rendering
    
    Production tip: Goldin's search API endpoint (from network analysis):
    GET https://goldin.co/_next/data/{buildId}/browse/all.json?q=QUERY&status=sold
    
    The buildId changes on deploys — extract it from the page source first.
    """
    results = []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Step 1: Get current build ID from homepage
        build_id = await _get_goldin_build_id(client)

        if build_id:
            results = await _goldin_next_api(client, search_query, build_id)

        if not results:
            results = await _goldin_page_scrape(client, search_query)

    return results


async def _get_goldin_build_id(client: httpx.AsyncClient) -> str:
    """Extract Next.js build ID from Goldin homepage."""
    try:
        resp = await client.get("https://goldin.co", headers=GOLDIN_HEADERS)
        if resp.status_code == 200:
            match = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
            if match:
                return match.group(1)
    except Exception:
        pass
    return ""


async def _goldin_next_api(client: httpx.AsyncClient, query: str, build_id: str) -> List[dict]:
    """Use Goldin's Next.js data API."""
    encoded = quote_plus(query)
    url = f"https://goldin.co/_next/data/{build_id}/browse/all.json?q={encoded}&status=sold"

    try:
        resp = await client.get(url, headers=GOLDIN_HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            items = (data.get("pageProps", {})
                        .get("initialData", {})
                        .get("lots", []))
            return [_parse_goldin_item(item) for item in items if item.get("sold_price")]
    except Exception:
        pass
    return []


async def _goldin_page_scrape(client: httpx.AsyncClient, query: str) -> List[dict]:
    """Fallback: scrape Goldin search page."""
    encoded = quote_plus(query)
    url = f"https://goldin.co/browse/all?q={encoded}&status=sold"

    try:
        resp = await client.get(url, headers=GOLDIN_HEADERS)
        if resp.status_code != 200:
            return []

        html = resp.text

        # Look for embedded JSON data
        json_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                lots = (data.get("props", {})
                           .get("pageProps", {})
                           .get("initialData", {})
                           .get("lots", []))
                return [_parse_goldin_item(lot) for lot in lots if lot.get("sold_price")]
            except Exception:
                pass

    except Exception:
        pass
    return []


def _parse_goldin_item(item: dict) -> dict:
    """Normalize Goldin lot data."""
    price_raw = item.get("sold_price", item.get("current_bid", 0))
    try:
        price = float(str(price_raw).replace("$", "").replace(",", ""))
    except Exception:
        price = 0

    return {
        "source": "Goldin",
        "title": item.get("title", item.get("lot_title", "")),
        "price": price,
        "currency": "USD",
        "date": item.get("end_date", item.get("sold_date", item.get("close_date", ""))),
        "url": f"https://goldin.co/lots/{item.get('slug', item.get('lot_id', ''))}",
        "image_url": item.get("image_url", item.get("primary_image", "")),
        "lot_id": item.get("id", item.get("lot_id", "")),
        "auction_title": item.get("auction_title", ""),
    }


# ============================================================
# HERITAGE AUCTIONS SCRAPER
# ============================================================

async def scrape_heritage(search_query: str) -> List[dict]:
    """
    Scrape Heritage Auctions sold results.
    Heritage has relatively static HTML — easier to scrape than most.
    
    Search URL: https://sports.ha.com/c/search-results.zx?N=794+4294967131&Ntt=QUERY
    Past auctions: https://sports.ha.com/itm/search?q=QUERY&ic2=ListSearch-051413
    
    Heritage also has a semi-public JSON endpoint discovered via network analysis.
    """
    results = []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Try Heritage search
        encoded = quote_plus(search_query)

        # Heritage's auction archive search
        urls_to_try = [
            f"https://sports.ha.com/c/search-results.zx?N=794+4294967131&Ntt={encoded}",
            f"https://sports.ha.com/itm/search?q={encoded}&type=s",
        ]

        for url in urls_to_try:
            try:
                resp = await client.get(url, headers=HERITAGE_HEADERS)
                if resp.status_code == 200:
                    parsed = _parse_heritage_html(resp.text)
                    if parsed:
                        results.extend(parsed)
                        break
            except Exception:
                continue

        # Try Heritage's JSON API
        if not results:
            json_results = await _heritage_json_api(client, search_query)
            results.extend(json_results)

    return results


async def _heritage_json_api(client: httpx.AsyncClient, query: str) -> List[dict]:
    """Try Heritage's internal search API."""
    encoded = quote_plus(query)
    # Heritage has an AJAX search endpoint
    api_url = f"https://sports.ha.com/c/search-results.zx?N=794+4294967131&Ntt={encoded}&ic4=SearchResults-070213-GI"

    try:
        resp = await client.get(api_url, headers={
            **HERITAGE_HEADERS,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, */*",
        })
        if resp.status_code == 200:
            try:
                data = resp.json()
                items = data.get("items", data.get("results", []))
                return [_parse_heritage_item(item) for item in items if item.get("price")]
            except Exception:
                pass
    except Exception:
        pass
    return []


def _parse_heritage_html(html: str) -> List[dict]:
    """Parse Heritage search results HTML."""
    results = []

    # Heritage uses relatively clean HTML with lot items
    # Look for structured data first
    json_ld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for match in json_ld_matches:
        try:
            data = json.loads(match)
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") in ["Product", "Offer"]:
                        results.append(_parse_schema_item(item, "Heritage"))
            elif data.get("@type") in ["Product", "Offer"]:
                results.append(_parse_schema_item(data, "Heritage"))
        except Exception:
            continue

    if results:
        return results

    # Regex fallback for Heritage lot pages
    lot_blocks = re.findall(
        r'<div[^>]*class="[^"]*lot[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html, re.DOTALL
    )

    for block in lot_blocks[:20]:
        try:
            title_m = re.search(r'<a[^>]*class="[^"]*lot-title[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

            price_m = re.search(r'Realized[^$]*\$\s*([\d,]+)', block)
            if not price_m:
                price_m = re.search(r'\$\s*([\d,]+(?:\.\d{2})?)', block)
            price = float(price_m.group(1).replace(",", "")) if price_m else 0

            url_m = re.search(r'href="(https?://[^"]*ha\.com[^"]*)"', block)
            url = url_m.group(1) if url_m else ""

            date_m = re.search(r'(\w+\s+\d+,\s+\d{4})', block)
            date_str = date_m.group(1) if date_m else ""

            if price > 0:
                results.append({
                    "source": "Heritage",
                    "title": title,
                    "price": price,
                    "currency": "USD",
                    "date": date_str,
                    "url": url,
                })
        except Exception:
            continue

    return results


def _parse_heritage_item(item: dict) -> dict:
    """Parse Heritage JSON item."""
    return {
        "source": "Heritage",
        "title": item.get("title", item.get("description", "")),
        "price": float(str(item.get("price", item.get("realized", 0))).replace("$", "").replace(",", "")),
        "currency": "USD",
        "date": item.get("saleDate", item.get("date", "")),
        "url": item.get("url", item.get("link", "")),
        "image_url": item.get("image", ""),
        "lot_number": item.get("lotNumber", ""),
    }


def _parse_schema_item(item: dict, source: str) -> dict:
    """Parse schema.org structured data item."""
    offer = item.get("offers", {})
    if isinstance(offer, list):
        offer = offer[0] if offer else {}

    return {
        "source": source,
        "title": item.get("name", ""),
        "price": float(str(offer.get("price", 0)).replace("$", "").replace(",", "") or 0),
        "currency": offer.get("priceCurrency", "USD"),
        "date": offer.get("validFrom", ""),
        "url": item.get("url", ""),
        "image_url": item.get("image", ""),
    }
