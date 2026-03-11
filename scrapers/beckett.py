"""
Beckett BGS/BVG/BCCG Cert Scraper
----------------------------------
Uses Beckett's internal Next.js API for reliable cert lookup.
Endpoint: /api/grading/lookup?category=BGS&serialNumber=XXXXX

Falls back to Playwright page scraping if API fails.
"""

import httpx
import re
import json
import asyncio
from typing import Optional


BECKETT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.beckett.com/grading/cert-verification",
}


async def scrape_beckett_cert(cert_number: str) -> dict:
    """Fetch BGS cert details from Beckett."""
    cert_clean = cert_number.strip().lstrip("0") or cert_number.strip()
    cert_full = cert_number.strip()

    # Method 1: Beckett Next.js API (most reliable)
    for category in ["BGS", "BVG", "BCCG"]:
        result = await _try_beckett_api(cert_clean, cert_full, category)
        if result and result.get("grade") and not result.get("error"):
            return result

    # Method 2: Try Playwright as fallback
    result = await _try_playwright_beckett(cert_full)
    if result and result.get("grade") and result["grade"] != "Unknown":
        return result

    return _error_result(cert_full, "Could not fetch BGS cert data. Cert may not exist or Beckett may be down.")


async def _try_beckett_api(cert_number: str, cert_full: str, category: str = "BGS") -> Optional[dict]:
    """Try Beckett's internal API endpoint."""
    url = f"https://www.beckett.com/api/grading/lookup?category={category}&serialNumber={cert_number}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=BECKETT_HEADERS)

            if resp.status_code != 200:
                return None

            data = resp.json()

            # API returns a dict with card data or an error
            if not data or isinstance(data, list) and not data:
                return None

            # Handle list response (take first item)
            if isinstance(data, list):
                data = data[0] if data else {}

            if not data.get("final_grade") and not data.get("player_name") and not data.get("set_name"):
                return None

            return _parse_api_response(data, cert_full, category)

    except Exception as e:
        print(f"[beckett/api] {category} {cert_number}: {e}")
        return None


def _parse_api_response(data: dict, cert_number: str, category: str = "BGS") -> dict:
    """Parse Beckett API JSON response into standardized format."""
    # Extract grade
    grade = str(data.get("final_grade", ""))
    if grade == "0" or grade == "0.0":
        grade = ""

    # Extract subgrades
    def _sub(key):
        v = data.get(key, "")
        s = str(v) if v else ""
        return s if s and s not in ("0", "0.0") else ""

    subgrades = {
        "centering": _sub("center_grade"),
        "corners": _sub("corners_grade"),
        "edges": _sub("edges_grade"),
        "surface": _sub("surface_grade"),
    }

    # Auto grade
    auto_grade = _sub("autograph_grade")

    # Black label detection: all subgrades are 10 and final grade is 10
    has_subgrades = any(v for v in subgrades.values())
    is_black_label = (
        has_subgrades
        and grade in ("10", "10.0")
        and all(v in ("10", "10.0") for v in subgrades.values() if v)
    )

    # Label type (silver, gold, pristine, black)
    label = data.get("label", "")

    # Extract year from set_name: "2024-25 Panini Revolution Kaboom Vertical"
    set_name = data.get("set_name", "")
    year = ""
    brand = set_name
    year_m = re.match(r'^(\d{4}(?:-\d{2,4})?)\s+(.*)', set_name)
    if year_m:
        year = year_m.group(1)
        brand = year_m.group(2)

    # Player name
    player_name = data.get("player_name", "")

    # Card number
    card_number = str(data.get("card_key", ""))

    # Image
    image_url = data.get("front_image_url", "")
    # Filter out the "no image" placeholder
    if image_url and "no-image" in image_url:
        image_url = ""

    # Sport / category
    sport = data.get("sport_name", "Sports")

    # Pop data
    pop = data.get("pop_report", 0) or 0
    pop_higher = data.get("pop_higher", None)
    grade_pop = data.get("grade_pop_report", 0) or 0

    # Determine grading company from category
    gc = category if category in ("BGS", "BVG", "BCCG") else "BGS"

    return {
        "cert_number": cert_number,
        "grading_company": gc,
        "grade": grade,
        "subgrades": subgrades,
        "auto_grade": auto_grade,
        "is_black_label": is_black_label,
        "label": label,
        "subject": player_name,
        "year": year,
        "brand": brand,
        "series": set_name,
        "card_number": card_number,
        "variety": "",
        "category": sport,
        "image_url": image_url,
        "pop": pop,
        "pop_higher": pop_higher,
        "grade_pop": grade_pop,
        "date_graded": data.get("date_graded", ""),
        "source": f"Beckett API ({gc})",
    }


async def _try_playwright_beckett(cert_number: str) -> Optional[dict]:
    """Fallback: use Playwright to render Beckett cert verification page."""
    try:
        from playwright.async_api import async_playwright

        url = f"https://www.beckett.com/grading/cert-verification/{cert_number}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                user_agent=BECKETT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            # Intercept the API call the page makes
            api_data = {}

            async def handle_response(response):
                nonlocal api_data
                if "/api/grading/lookup" in response.url:
                    try:
                        api_data = await response.json()
                    except Exception:
                        pass

            page.on("response", handle_response)

            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await asyncio.sleep(3)
            except Exception:
                pass

            await browser.close()

            if api_data:
                if isinstance(api_data, list) and api_data:
                    api_data = api_data[0]
                if isinstance(api_data, dict) and (api_data.get("final_grade") or api_data.get("player_name")):
                    return _parse_api_response(api_data, cert_number)

    except ImportError:
        print("[beckett] Playwright not installed, skipping browser fallback")
    except Exception as e:
        print(f"[beckett/playwright] error: {e}")

    return None


def _error_result(cert_number: str, error: str) -> dict:
    return {
        "cert_number": cert_number,
        "grading_company": "BGS",
        "error": error,
        "grade": "",
        "subject": "",
        "subgrades": {},
        "source": "Beckett (failed)",
    }
