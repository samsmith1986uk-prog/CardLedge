"""PSA Scraper - clean version using api.psacard.com"""
import asyncio
import httpx
import os
import re

def _load_token():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("PSA_API_TOKEN="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        pass
    return os.getenv("PSA_API_TOKEN", "")

def _extract_variety_from_brand(brand: str, variety: str) -> tuple:
    """If PSA puts the variety in the brand field, split them.
    Returns (clean_brand, variety)."""
    if variety:
        return brand, variety
    if not brand:
        return brand, variety

    # Known variety patterns that PSA sometimes embeds in brand
    variety_patterns = [
        # Color parallels
        r'\b(COPPER|SILVER|GOLD|RED|BLUE|GREEN|ORANGE|PINK|PURPLE|BLACK|WHITE)\s+(PRIZM|CHROME|WAVE|SHIMMER|ICE)\b',
        r'\b(DISCO|TIGER|CAMO|MOJO|HYPER|NEON|HOLO|SCOPE|SNAKESKIN|VELOCITY|GENESIS|MARBLE)\b',
        # Named parallels
        r'\b(RETRO NET MARVELS|NET MARVELS|FAST BREAK|LAZER|LASER)\b',
        # Numbered parallels
        r'\b(COPPER)\s+PRIZM\b',
        # Insert sets often merged into brand
        r'\b(RATED ROOKIE|DOWNTOWN|KABOOM|CASE HIT)\b',
    ]

    brand_upper = brand.upper()
    for pat in variety_patterns:
        m = re.search(pat, brand_upper)
        if m:
            matched = m.group(0)
            # Remove the variety from brand
            clean_brand = brand[:m.start()].strip() + ' ' + brand[m.end():].strip()
            clean_brand = re.sub(r'\s+', ' ', clean_brand).strip()
            return clean_brand, matched
    return brand, variety


async def scrape_psa_cert(cert_number: str) -> dict:
    cert = cert_number.strip()
    token = _load_token()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Authorization": f"bearer {token}",
    }
    url = f"https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=headers)
            # Retry once on 429 after brief delay
            if resp.status_code == 429:
                print(f"[psa] 429 rate limit, retrying in 2s...")
                await asyncio.sleep(2)
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                c = data.get("PSACert", {})
                if c:
                    grade_raw = c.get("CardGrade", "")
                    cn = cert.zfill(8)
                    raw_brand = c.get("Brand", "")
                    raw_variety = c.get("Variety", "")
                    clean_brand, variety = _extract_variety_from_brand(raw_brand, raw_variety)
                    return {
                        "cert_number": cert,
                        "grading_company": "PSA",
                        "grade": grade_raw.split()[-1] if grade_raw else "",
                        "full_grade": grade_raw,
                        "subject": c.get("Subject", ""),
                        "year": c.get("Year", ""),
                        "brand": clean_brand,
                        "variety": variety,
                        "card_number": c.get("CardNumber", ""),
                        "category": c.get("Category", ""),
                        "image_url": "",
                        "pop": c.get("TotalPopulation", 0),
                        "pop_higher": c.get("PopulationHigher", 0),
                        "source": "PSA API",
                    }
            error_msg = f"HTTP {resp.status_code}"
            if resp.status_code == 429:
                error_msg = "PSA API rate limit reached — try again in a few minutes"
            elif resp.status_code == 401:
                error_msg = "PSA API authentication failed"
            return {"cert_number": cert, "grading_company": "PSA", "error": error_msg, "grade": "", "subject": ""}
        except Exception as e:
            return {"cert_number": cert, "grading_company": "PSA", "error": str(e), "grade": "", "subject": ""}
