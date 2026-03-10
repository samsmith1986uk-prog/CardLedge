"""
CARDLEDGE Backend API
Scrapes PSA cert data, eBay sold listings, and multiple card marketplaces
to provide comprehensive card investment intelligence.
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
import json
import re
from typing import Optional
from scrapers.psa import scrape_psa_cert
from scrapers.card_resolver import resolve_card, build_card_identity
from scrapers.beckett import scrape_beckett_cert


app = FastAPI(title="CARDLEDGE API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CardLookupRequest(BaseModel):
    cert_number: str
    grading_company: str  # "PSA" or "BGS" or "SGC"
    include_sales: bool = True
    include_comps: bool = True




@app.get("/lookup/{grading_company}/{cert_number}")
async def lookup_card(grading_company: str, cert_number: str, include_sales: bool = True):
    """
    Main endpoint: given a cert number, fetch card details + sales data from multiple sources.
    """
    grading_company = grading_company.upper()

    if grading_company not in ["PSA", "BGS", "SGC"]:
        raise HTTPException(status_code=400, detail="Grading company must be PSA, BGS, or SGC")

    result = {
        "cert_number": cert_number,
        "grading_company": grading_company,
        "card_details": None,
        "sales_data": [],
        "market_summary": None,
        "errors": []
    }

    # Step 1: Get card details from grading company
    try:
        if grading_company == "PSA":
            card_details = await scrape_psa_cert(cert_number)
        elif grading_company == "BGS":
            card_details = await scrape_beckett_cert(cert_number)
        else:
            card_details = {"cert_number": cert_number, "grade": "Unknown", "error": "SGC scraping not yet implemented"}
        result["card_details"] = card_details
    except Exception as e:
        result["errors"].append(f"Card details fetch failed: {str(e)}")

    if not include_sales:
        return result

    # Step 2: Gather sales data concurrently from multiple sources
    card_name = ""
    if result["card_details"]:
        d = result["card_details"]
        # Build search query from card details
        parts = []
        if d.get("year"): parts.append(d["year"])
        if d.get("brand"): parts.append(d["brand"])
        if d.get("subject"): parts.append(d["subject"])
        if d.get("variety"): parts.append(d["variety"])
        if d.get("grade"): parts.append(f"{grading_company} {d['grade']}")
        card_name = " ".join(parts)

    if not card_name:
        card_name = f"{grading_company} {cert_number}"

    # Step 2b: Resolve image + sales via unified card resolver
    resolved = await resolve_card(result["card_details"] or {})

    # Inject resolved image into card_details
    if resolved.get("image_url") and result["card_details"]:
        result["card_details"]["image_url"] = resolved["image_url"]

    all_sales = resolved.get("sales", [])
    result["sales_data"] = all_sales

    # Step 3: Compute market summary
    stats = resolved.get("stats", {})
    if stats:
        result["market_summary"] = {
            "avg_price": stats.get("avg_price"),
            "median_price": stats.get("median_price"),
            "low_price": stats.get("low_price"),
            "high_price": stats.get("high_price"),
            "total_sales_found": stats.get("total_sales", 0),
            "sources_checked": len(stats.get("sources", [])),
            "sources": stats.get("sources", []),
        }

    return result


@app.get("/psa/population/{set_id}")
async def get_psa_population(set_id: str):
    """Get PSA population report for a set."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://www.psacard.com/publicapi/pop/getsetsummary/{set_id}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail="PSA API error")


@app.get("/health")
async def health():
    return {"status": "ok"}

# ── AI ANALYST PROXY ──
@app.post("/ai/analyse")
async def ai_analyse(request: Request = None):
    if request is None: raise HTTPException(400, "No request")
    import os
    body = await request.json()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body
        )
        return response.json()

# ── STATIC FILES ──
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")

# ── PSA IMAGE PROXY ──
@app.get("/cert-image/{cert_number}")
async def cert_image(cert_number: str):
    import os
    from fastapi.responses import Response
    token = ""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("PSA_API_TOKEN="):
                    token = line.strip().split("=", 1)[1]
    except:
        pass
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"https://api.psacard.com/publicapi/cert/GetImageByCertNumber/{cert_number}",
            headers={"Authorization": f"bearer {token}"}
        )
        if resp.status_code == 200:
            return Response(content=resp.content, media_type="image/jpeg")
    
    # Fallback: redirect to PSA cert page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"https://www.psacard.com/cert/{cert_number}")
