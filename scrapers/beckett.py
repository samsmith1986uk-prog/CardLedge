"""
Beckett BGS/BVG Cert Scraper
-----------------------------
Scrapes Beckett cert lookup for graded card details including:
- Card image
- Subject, year, set
- BGS grade + subgrades (centering, corners, edges, surface)
- BGS Black Label detection

Beckett cert lookup: https://www.beckett.com/grading/submission/grade/{cert_number}
No public API available — Playwright or httpx with session cookies required.
"""

import httpx
import re
import json
from typing import Optional


BECKETT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.beckett.com/",
}


async def scrape_beckett_cert(cert_number: str) -> dict:
    """
    Fetch BGS cert details from Beckett.
    
    NOTE: Beckett's site is JS-heavy. This httpx approach works for 
    their cert lookup API endpoint. For full scraping, use Playwright.
    
    Production tip: Use playwright-python for reliable Beckett scraping:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(f"https://www.beckett.com/grading/submission/grade/{cert_number}")
            await page.wait_for_selector(".grade-result")
            content = await page.content()
    """
    cert_clean = cert_number.strip()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Try Beckett's internal API first
        result = await _try_beckett_api(client, cert_clean)
        if result:
            return result

        # Fallback to page scrape
        return await _scrape_beckett_page(client, cert_clean)


async def _try_beckett_api(client: httpx.AsyncClient, cert_number: str) -> Optional[dict]:
    """Try Beckett's internal JSON API endpoint."""
    # Beckett has an internal API used by their cert lookup page
    api_url = f"https://www.beckett.com/grading/certificate/{cert_number}/json"
    
    try:
        resp = await client.get(api_url, headers=BECKETT_HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            return _parse_beckett_data(data, cert_number)
    except Exception:
        pass

    # Try alternate endpoint format
    try:
        api_url2 = f"https://www.beckett.com/grading/submission/grade/{cert_number}"
        resp = await client.get(api_url2, headers=BECKETT_HEADERS)
        if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
            data = resp.json()
            return _parse_beckett_data(data, cert_number)
    except Exception:
        pass

    return None


def _parse_beckett_data(data: dict, cert_number: str) -> dict:
    """Parse Beckett API response."""
    grade = data.get("grade", data.get("overallGrade", ""))
    subgrades = {
        "centering": data.get("centering", data.get("centeringGrade", "")),
        "corners": data.get("corners", data.get("cornersGrade", "")),
        "edges": data.get("edges", data.get("edgesGrade", "")),
        "surface": data.get("surface", data.get("surfaceGrade", "")),
    }

    # BGS Black Label = all 10s
    is_black_label = all(str(v) == "10" for v in subgrades.values() if v)

    return {
        "cert_number": cert_number,
        "grading_company": "BGS",
        "grade": str(grade),
        "subgrades": subgrades,
        "is_black_label": is_black_label,
        "subject": data.get("playerName", data.get("subject", "")),
        "year": data.get("year", ""),
        "brand": data.get("manufacturer", data.get("brand", "")),
        "series": data.get("set", data.get("series", "")),
        "card_number": data.get("cardNumber", ""),
        "image_url": data.get("imageUrl", data.get("frontImageUrl", "")),
        "source": "Beckett API",
        "raw": data,
    }


async def _scrape_beckett_page(client: httpx.AsyncClient, cert_number: str) -> dict:
    """Scrape Beckett cert page as fallback."""
    url = f"https://www.beckett.com/grading/submission/grade/{cert_number}"
    
    try:
        resp = await client.get(url, headers=BECKETT_HEADERS)
        if resp.status_code != 200:
            return _error_result(cert_number, f"HTTP {resp.status_code}")
        
        html = resp.text

        # Extract from JSON embedded in page
        json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
        if json_match:
            try:
                state = json.loads(json_match.group(1))
                cert_data = (state.get("grading", {})
                                  .get("certificate", {})
                                  .get("data", {}))
                if cert_data:
                    return _parse_beckett_data(cert_data, cert_number)
            except Exception:
                pass

        # Regex fallback
        def extract(pattern, default=""):
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else default

        grade = extract(r'class="[^"]*overall-grade[^"]*"[^>]*>([\d.]+)<')
        subject = extract(r'class="[^"]*player-name[^"]*"[^>]*>(.*?)<')
        year = extract(r'class="[^"]*card-year[^"]*"[^>]*>([\d]+)<')
        centering = extract(r'Centering[^<]*<[^>]+>([\d.]+)<')
        corners = extract(r'Corners[^<]*<[^>]+>([\d.]+)<')
        edges = extract(r'Edges[^<]*<[^>]+>([\d.]+)<')
        surface = extract(r'Surface[^<]*<[^>]+>([\d.]+)<')
        image = extract(r'<img[^>]*class="[^"]*card-image[^"]*"[^>]*src="([^"]+)"')

        return {
            "cert_number": cert_number,
            "grading_company": "BGS",
            "grade": grade,
            "subgrades": {
                "centering": centering,
                "corners": corners,
                "edges": edges,
                "surface": surface,
            },
            "is_black_label": all([centering == "10", corners == "10", edges == "10", surface == "10"]) if grade else False,
            "subject": subject,
            "year": year,
            "image_url": image,
            "source": "Beckett page scrape",
        }

    except Exception as e:
        return _error_result(cert_number, str(e))


def _error_result(cert_number: str, error: str) -> dict:
    return {
        "cert_number": cert_number,
        "grading_company": "BGS",
        "error": error,
        "grade": "Unknown",
        "subject": "Unknown",
        "source": "Beckett (failed)",
    }
