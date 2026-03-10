"""PSA Scraper - clean version using api.psacard.com"""
import httpx
import os

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
            if resp.status_code == 200:
                data = resp.json()
                c = data.get("PSACert", {})
                if c:
                    grade_raw = c.get("CardGrade", "")
                    cn = cert.zfill(8)
                    return {
                        "cert_number": cert,
                        "grading_company": "PSA",
                        "grade": grade_raw.split()[-1] if grade_raw else "",
                        "full_grade": grade_raw,
                        "subject": c.get("Subject", ""),
                        "year": c.get("Year", ""),
                        "brand": c.get("Brand", ""),
                        "variety": c.get("Variety", ""),
                        "card_number": c.get("CardNumber", ""),
                        "category": c.get("Category", ""),
                        "image_url": "",
                        "pop": c.get("TotalPopulation", 0),
                        "pop_higher": c.get("PopulationHigher", 0),
                        "source": "PSA API",
                    }
            return {"cert_number": cert, "grading_company": "PSA", "error": f"HTTP {resp.status_code}", "grade": "", "subject": ""}
        except Exception as e:
            return {"cert_number": cert, "grading_company": "PSA", "error": str(e), "grade": "", "subject": ""}
