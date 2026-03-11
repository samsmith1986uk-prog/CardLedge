"""
SLABIQ Backend API v3
Scrapes PSA/BGS/SGC cert data, eBay sold listings, and multiple card marketplaces
to provide comprehensive card investment intelligence.
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
import json
import re
import time
from typing import Optional
from urllib.parse import quote_plus
from scrapers.psa import scrape_psa_cert
from scrapers.card_resolver import resolve_card, build_card_identity, resolve_sales_data, BROWSER_HEADERS
from scrapers.beckett import scrape_beckett_cert
from scrapers.sgc import scrape_sgc_cert


app = FastAPI(title="SLABIQ API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── IN-MEMORY CACHE (1 hour TTL) ──
_cache = {}
CACHE_TTL = 3600  # seconds


def _cache_key(gc: str, cert: str) -> str:
    return f"{gc}:{cert}"


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, data: dict):
    if len(_cache) > 500:
        oldest = min(_cache, key=lambda k: _cache[k]["ts"])
        del _cache[oldest]
    _cache[key] = {"data": data, "ts": time.time()}


# ── MAIN LOOKUP ──
@app.get("/lookup/{grading_company}/{cert_number}")
async def lookup_card(grading_company: str, cert_number: str, include_sales: bool = True):
    """Main endpoint: cert number -> card details + sales data."""
    grading_company = grading_company.upper()

    if grading_company not in ["PSA", "BGS", "SGC"]:
        raise HTTPException(status_code=400, detail="Grading company must be PSA, BGS, or SGC")

    ck = _cache_key(grading_company, cert_number)
    cached = _cache_get(ck)
    if cached:
        cached["_cached"] = True
        return cached

    result = {
        "cert_number": cert_number,
        "grading_company": grading_company,
        "card_details": None,
        "sales_data": [],
        "market_summary": None,
        "momentum": None,
        "liquidity": None,
        "errors": []
    }

    # Step 1: Get card details from grading company
    try:
        if grading_company == "PSA":
            card_details = await scrape_psa_cert(cert_number)
        elif grading_company == "BGS":
            card_details = await scrape_beckett_cert(cert_number)
        elif grading_company == "SGC":
            card_details = await scrape_sgc_cert(cert_number)
        else:
            card_details = {"cert_number": cert_number, "grade": "", "error": "Unknown grading company"}
        result["card_details"] = card_details
    except Exception as e:
        result["errors"].append(f"Card details fetch failed: {str(e)}")

    if not include_sales:
        _cache_set(ck, result)
        return result

    # Step 2: Resolve image + sales via unified card resolver
    resolved = await resolve_card(result["card_details"] or {})

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

    # Step 4: Compute momentum
    result["momentum"] = _compute_momentum(all_sales)

    # Step 5: Compute liquidity
    result["liquidity"] = _compute_liquidity(all_sales)

    _cache_set(ck, result)
    return result


# ── PLAYER SEARCH / AUTOCOMPLETE ──
@app.get("/search")
async def search_cards(q: str = Query(..., min_length=2, description="Player name or card search")):
    """Search for cards by player name. Returns matching sold listings."""
    query = q.strip()

    # Search 130point for matching cards
    results = []
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.post(
                "https://back.130point.com/sales/",
                data={"query": query},
                headers={
                    "User-Agent": BROWSER_HEADERS["User-Agent"],
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://130point.com/sales/",
                    "Origin": "https://130point.com",
                },
            )
            if r.status_code == 200 and len(r.text) > 500:
                html = r.text
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)

                seen_titles = set()
                for row in rows[:50]:
                    price_attr = re.search(r'data-price="([^"]+)"', row)
                    if not price_attr:
                        continue
                    try:
                        price = float(price_attr.group(1))
                    except (ValueError, TypeError):
                        continue
                    if price < 5:
                        continue

                    title_m = re.search(r"id='titleText'[^>]*>(?:<a[^>]*>)?(.*?)(?:</a>)?</span>", row, re.DOTALL)
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
                    if not title:
                        continue

                    # Deduplicate similar titles
                    title_key = re.sub(r'[^a-zA-Z0-9]', '', title.lower())[:60]
                    if title_key in seen_titles:
                        continue
                    seen_titles.add(title_key)

                    date_m = re.search(r"id='dateText'[^>]*>(?:<b>Date:</b>)?\s*(.*?)</span>", row, re.DOTALL)
                    date_str = re.sub(r'<[^>]+>', '', date_m.group(1)).strip() if date_m else ""

                    img_m = re.search(r"src='(https://i\.ebayimg\.com/[^']+)'", row)
                    image = img_m.group(1) if img_m else ""
                    if image and "s-l150" in image:
                        image = image.replace("s-l150", "s-l300")

                    # Parse grade from title
                    grade_m = re.search(r'(?:PSA|BGS|SGC|BVG)\s*([\d.]+)', title, re.IGNORECASE)
                    grade_info = grade_m.group(0) if grade_m else ""

                    # Parse player name from title
                    player = _extract_player_from_title(title)

                    results.append({
                        "title": title,
                        "price": price,
                        "date": date_str,
                        "image_url": image,
                        "grade": grade_info,
                        "player": player,
                    })

    except Exception as e:
        print(f"[search] 130point error: {e}")

    return {"query": query, "results": results[:30], "total": len(results)}


@app.get("/search/suggest")
async def search_suggest(q: str = Query(..., min_length=2)):
    """Quick autocomplete suggestions from eBay typeahead."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://autosug.ebay.com/autosug",
                params={"kwd": f"{q} card", "sId": "0", "fmt": "osr"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                suggestions = data.get("res", {}).get("sug", [])
                # Filter to card-related suggestions
                filtered = [s for s in suggestions if any(kw in s.lower() for kw in
                    ["card", "psa", "bgs", "sgc", "topps", "panini", "prizm", "chrome",
                     "rookie", "auto", "bowman", "select", "mosaic", "optic", "megacracks"])]
                if not filtered:
                    filtered = suggestions[:8]
                return {"suggestions": filtered[:10]}
    except Exception:
        pass
    return {"suggestions": []}


# ── GRADE COMPARISON ──
@app.get("/grades/compare")
async def grade_comparison(
    player: str = Query(..., description="Player name"),
    year: str = Query("", description="Card year"),
    brand: str = Query("", description="Card brand/set"),
    card_number: str = Query("", description="Card number"),
):
    """Get price comparison across PSA grades 7-10 for a card."""
    base_query = f"{player} {year} {brand} {card_number}".strip()

    grades = ["7", "8", "9", "10"]
    tasks = []
    for grade in grades:
        query = f"{base_query} PSA {grade}"
        tasks.append(_fetch_grade_prices(query, grade))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    grade_data = {}
    for grade, result in zip(grades, results):
        if isinstance(result, Exception):
            grade_data[grade] = {"avg": None, "low": None, "high": None, "count": 0}
        else:
            grade_data[grade] = result

    return {"player": player, "year": year, "brand": brand, "grades": grade_data}


async def _fetch_grade_prices(query: str, grade: str) -> dict:
    """Fetch prices for a specific grade from 130point."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.post(
                "https://back.130point.com/sales/",
                data={"query": query},
                headers={
                    "User-Agent": BROWSER_HEADERS["User-Agent"],
                    "Accept": "*/*",
                    "Referer": "https://130point.com/sales/",
                    "Origin": "https://130point.com",
                },
            )
            if r.status_code != 200 or len(r.text) < 500:
                return {"avg": None, "low": None, "high": None, "count": 0}

            prices = []
            rows = re.findall(r'data-price="([^"]+)"', r.text)
            for p in rows:
                try:
                    price = float(p)
                    if price >= 5:
                        prices.append(price)
                except (ValueError, TypeError):
                    continue

            if not prices:
                return {"avg": None, "low": None, "high": None, "count": 0}

            # Filter outliers (>10x median)
            prices.sort()
            median = prices[len(prices) // 2]
            prices = [p for p in prices if p <= median * 10]

            if not prices:
                return {"avg": None, "low": None, "high": None, "count": 0}

            return {
                "avg": round(sum(prices) / len(prices), 2),
                "low": min(prices),
                "high": max(prices),
                "count": len(prices),
            }
    except Exception:
        return {"avg": None, "low": None, "high": None, "count": 0}


def _extract_player_from_title(title: str) -> str:
    """Extract player name from a card sale title."""
    # Remove common prefixes (year, brand)
    cleaned = re.sub(r'^\d{4}[-/]?\d{0,2}\s+', '', title)
    cleaned = re.sub(r'^(Topps|Panini|Bowman|Upper Deck|Donruss|Prizm|Select|Fleer|Score|Megacracks)\s+', '', cleaned, flags=re.IGNORECASE)

    # Try to find name before card identifiers
    name_m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', cleaned)
    if name_m:
        return name_m.group(1)

    # Fallback: take first 2-3 capitalized words
    words = cleaned.split()
    name_words = []
    for w in words:
        if w[0:1].isupper() and not w.startswith('#') and not re.match(r'^\d', w):
            name_words.append(w)
            if len(name_words) >= 3:
                break
        elif name_words:
            break

    return ' '.join(name_words) if name_words else ""


def _compute_momentum(sales: list) -> dict:
    """Compute 30-day price momentum from sales data."""
    from datetime import datetime, timedelta, timezone
    if not sales:
        return {"direction": "unknown", "pct_change": 0, "label": "No data"}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    recent = []
    older = []
    for s in sales:
        p = s.get("price")
        d = s.get("date", "")
        if not p or p < 5:
            continue
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(d)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        if dt >= cutoff:
            recent.append(p)
        else:
            older.append(p)

    if not recent or not older:
        priced = [s["price"] for s in sales if s.get("price") and s["price"] > 5]
        if len(priced) < 4:
            return {"direction": "unknown", "pct_change": 0, "label": "Insufficient data"}
        mid = len(priced) // 2
        recent = priced[:mid]
        older = priced[mid:]

    avg_recent = sum(recent) / len(recent)
    avg_older = sum(older) / len(older)

    if avg_older == 0:
        return {"direction": "unknown", "pct_change": 0, "label": "No baseline"}

    pct = round(((avg_recent - avg_older) / avg_older) * 100, 1)
    if pct > 5:
        direction, label = "up", f"+{pct}% trending up"
    elif pct < -5:
        direction, label = "down", f"{pct}% trending down"
    else:
        direction, label = "stable", f"{pct}% stable"

    return {
        "direction": direction,
        "pct_change": pct,
        "recent_avg": round(avg_recent, 2),
        "older_avg": round(avg_older, 2),
        "recent_count": len(recent),
        "label": label,
    }


def _compute_liquidity(sales: list) -> dict:
    """Compute average days between sales."""
    from datetime import datetime, timezone

    dates = []
    for s in sales:
        d = s.get("date", "")
        if not d:
            continue
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            dates.append(dt)
        except Exception:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(d)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dates.append(dt)
            except Exception:
                continue

    if len(dates) < 2:
        return {"avg_days_between": None, "score": 0, "label": "No data"}

    dates.sort(reverse=True)
    gaps = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
    avg_gap = sum(gaps) / len(gaps) if gaps else 999

    if avg_gap <= 3:
        score, label = 10, "Extremely liquid"
    elif avg_gap <= 7:
        score, label = 8, "Very liquid"
    elif avg_gap <= 14:
        score, label = 6, "Liquid"
    elif avg_gap <= 30:
        score, label = 4, "Moderate"
    elif avg_gap <= 60:
        score, label = 2, "Low liquidity"
    else:
        score, label = 1, "Illiquid"

    return {
        "avg_days_between": round(avg_gap, 1),
        "total_sales": len(dates),
        "score": score,
        "label": label,
    }


# ── PSA POPULATION ──
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


# ── CACHE STATUS ──
@app.get("/cache/stats")
async def cache_stats():
    """Return cache statistics."""
    now = time.time()
    active = sum(1 for v in _cache.values() if now - v["ts"] < CACHE_TTL)
    return {"total_entries": len(_cache), "active": active, "ttl_seconds": CACHE_TTL}


@app.delete("/cache/clear")
async def cache_clear():
    """Clear the lookup cache."""
    _cache.clear()
    return {"status": "cleared"}


# ── HEALTH ──
@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0.0", "cache_entries": len(_cache)}


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
    token = os.getenv("PSA_API_TOKEN", "")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"https://api.psacard.com/publicapi/cert/GetImageByCertNumber/{cert_number}",
            headers={"Authorization": f"bearer {token}"}
        )
        if resp.status_code == 200:
            return Response(content=resp.content, media_type="image/jpeg")

    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"https://www.psacard.com/cert/{cert_number}")
