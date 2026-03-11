"""
SGC (Sportscard Guaranty) Cert Scraper
---------------------------------------
SGC cert verification via their public lookup page.
SGC doesn't have a public API, so we scrape their cert page.
"""

import httpx
import re
from typing import Optional

SGC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_sgc_cert(cert_number: str) -> dict:
    """Fetch SGC cert details."""
    cert = cert_number.strip()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Try SGC's cert verification page
        result = await _scrape_sgc_page(client, cert)
        if result and not result.get("error"):
            return result

        # Try alternate URL format
        result2 = await _scrape_sgc_alt(client, cert)
        if result2 and not result2.get("error"):
            return result2

        return result or _error_result(cert, "Could not fetch SGC cert data")


async def _scrape_sgc_page(client: httpx.AsyncClient, cert_number: str) -> Optional[dict]:
    """Scrape SGC cert verification page."""
    url = f"https://www.gosgc.com/card/{cert_number}"

    try:
        resp = await client.get(url, headers=SGC_HEADERS)
        if resp.status_code != 200:
            return _error_result(cert_number, f"HTTP {resp.status_code}")

        html = resp.text

        # Try JSON-LD or embedded data
        json_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if json_match:
            import json
            try:
                ld = json.loads(json_match.group(1))
                if isinstance(ld, dict) and ld.get("name"):
                    return _parse_sgc_ld(ld, cert_number)
            except Exception:
                pass

        # Regex extraction from page
        def extract(pattern, default=""):
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else default

        subject = extract(r'(?:player|subject|name)["\s:]*(?:</[^>]+>)?\s*([^<]+)', '')
        year = extract(r'(?:year)["\s:]*(?:</[^>]+>)?\s*(\d{4})', '')
        brand = extract(r'(?:set|brand|manufacturer)["\s:]*(?:</[^>]+>)?\s*([^<]+)', '')
        grade = extract(r'(?:grade|score)["\s:]*(?:</[^>]+>)?\s*([\d.]+)', '')
        card_number = extract(r'(?:card\s*#|number)["\s:]*(?:</[^>]+>)?\s*#?(\w+)', '')
        image = extract(r'<img[^>]*src="(https://[^"]*(?:sgc|gosgc)[^"]*\.(jpg|png|webp))"', '')

        if not subject and not grade:
            # Try meta tags
            subject = extract(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"')
            if subject:
                # Parse title like "1993 Topps #98 Derek Jeter SGC 10"
                parts = re.match(r'(\d{4})\s+(.+?)\s+#(\S+)\s+(.+?)\s+SGC\s+([\d.]+)', subject)
                if parts:
                    return {
                        "cert_number": cert_number,
                        "grading_company": "SGC",
                        "grade": parts.group(5),
                        "subject": parts.group(4),
                        "year": parts.group(1),
                        "brand": parts.group(2),
                        "card_number": parts.group(3),
                        "variety": "",
                        "category": "Sports",
                        "image_url": image or extract(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"'),
                        "pop": 0,
                        "pop_higher": None,
                        "source": "SGC page scrape",
                    }

        if subject or grade:
            return {
                "cert_number": cert_number,
                "grading_company": "SGC",
                "grade": grade,
                "subject": subject,
                "year": year,
                "brand": brand,
                "card_number": card_number,
                "variety": "",
                "category": "Sports",
                "image_url": image,
                "pop": 0,
                "pop_higher": None,
                "source": "SGC page scrape",
            }

        return None

    except Exception as e:
        return _error_result(cert_number, str(e))


async def _scrape_sgc_alt(client: httpx.AsyncClient, cert_number: str) -> Optional[dict]:
    """Try alternate SGC URL format."""
    url = f"https://www.gosgc.com/verifycard?cert={cert_number}"
    try:
        resp = await client.get(url, headers=SGC_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            def extract(pattern, default=""):
                m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
                return m.group(1).strip() if m else default

            grade = extract(r'(?:grade|score)["\s:]*(?:</[^>]+>)?\s*([\d.]+)')
            subject = extract(r'(?:player|subject)["\s:]*(?:</[^>]+>)?\s*([^<]+)')
            if grade:
                return {
                    "cert_number": cert_number,
                    "grading_company": "SGC",
                    "grade": grade,
                    "subject": subject,
                    "year": extract(r'(\d{4})\s'),
                    "brand": "",
                    "card_number": "",
                    "variety": "",
                    "category": "Sports",
                    "image_url": "",
                    "pop": 0,
                    "pop_higher": None,
                    "source": "SGC alt page",
                }
    except Exception:
        pass
    return None


def _parse_sgc_ld(ld: dict, cert_number: str) -> dict:
    """Parse JSON-LD structured data from SGC page."""
    name = ld.get("name", "")
    image = ld.get("image", "")
    if isinstance(image, list):
        image = image[0] if image else ""

    # Parse name: "1993 Topps #98 Derek Jeter SGC 10"
    parts = re.match(r'(\d{4})\s+(.+?)\s+#(\S+)\s+(.+?)\s+SGC\s+([\d.]+)', name)
    if parts:
        return {
            "cert_number": cert_number,
            "grading_company": "SGC",
            "grade": parts.group(5),
            "subject": parts.group(4),
            "year": parts.group(1),
            "brand": parts.group(2),
            "card_number": parts.group(3),
            "variety": "",
            "category": "Sports",
            "image_url": image,
            "pop": 0,
            "pop_higher": None,
            "source": "SGC JSON-LD",
        }

    return {
        "cert_number": cert_number,
        "grading_company": "SGC",
        "grade": "",
        "subject": name,
        "year": "",
        "brand": "",
        "card_number": "",
        "variety": "",
        "category": "Sports",
        "image_url": image,
        "pop": 0,
        "pop_higher": None,
        "source": "SGC JSON-LD",
    }


def _error_result(cert_number: str, error: str) -> dict:
    return {
        "cert_number": cert_number,
        "grading_company": "SGC",
        "error": error,
        "grade": "",
        "subject": "",
        "source": "SGC (failed)",
    }
