"""
SGC (Sportscard Guaranty) Cert Scraper
---------------------------------------
SGC cert verification via their Azure API.
API: prod-customer-sgc-api.azurewebsites.net/v1
Requires: Origin header (CORS) + reCAPTCHA Enterprise token

Fallback: When reCAPTCHA is unavailable, returns minimal cert data.
"""

import httpx
import re
from typing import Optional

SGC_API_BASE = "https://prod-customer-sgc-api.azurewebsites.net/v1"
SGC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.gosgc.com",
    "Referer": "https://www.gosgc.com/",
}


async def scrape_sgc_cert(cert_number: str) -> dict:
    """Fetch SGC cert details via Azure API."""
    cert = cert_number.strip()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Try the Azure API (requires reCAPTCHA but may work for some requests)
        result = await _api_lookup(client, cert)
        if result and not result.get("error"):
            return result

        # Return minimal result — we know it's SGC but can't get details without reCAPTCHA
        return {
            "cert_number": cert,
            "grading_company": "SGC",
            "grade": "",
            "subject": "",
            "year": "",
            "brand": "",
            "card_number": "",
            "variety": "",
            "category": "Sports",
            "image_url": "",
            "pop": 0,
            "pop_higher": None,
            "error": "SGC requires reCAPTCHA verification — cert details unavailable via API",
            "source": "SGC (limited)",
        }


async def _api_lookup(client: httpx.AsyncClient, cert_number: str) -> Optional[dict]:
    """Try SGC Azure API for cert lookup."""
    url = f"{SGC_API_BASE}/pop-report/GetCertAuthCode"

    # Determine if cert starts with A/B (autograph)
    first_char = cert_number[0].upper() if cert_number else ""
    if first_char in ("A", "B"):
        grade = "A"
        subject = "empty"
    else:
        grade = "empty"
        subject = "empty"

    try:
        resp = await client.post(
            url,
            json={
                "authcode": cert_number,
                "grade": grade,
                "subject": subject,
                "recaptchaToken": "",
            },
            headers=SGC_HEADERS,
        )

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("popResultCount"):
                return _parse_api_response(data, cert_number)
            elif isinstance(data, str):
                print(f"[sgc] API returned string: {data[:100]}")
        else:
            print(f"[sgc] API status {resp.status_code}: {resp.text[:100]}")

    except Exception as e:
        print(f"[sgc] API error: {e}")

    return None


def _parse_api_response(data: dict, cert_number: str) -> dict:
    """Parse SGC API response."""
    # The API returns pop report style data
    return {
        "cert_number": cert_number,
        "grading_company": "SGC",
        "grade": str(data.get("grade", "")),
        "subject": data.get("subject", ""),
        "year": str(data.get("year", "")),
        "brand": data.get("setName", "") or data.get("brand", ""),
        "card_number": data.get("cardNumber", ""),
        "variety": data.get("variety", ""),
        "category": data.get("sport", "Sports"),
        "image_url": data.get("imageUrl", "") or data.get("frontImageUrl", ""),
        "pop": data.get("pop", 0),
        "pop_higher": data.get("popHigher"),
        "source": "SGC API",
    }
