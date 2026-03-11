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
from scrapers.cardladder import search_player, search_cards_by_player, match_card as match_card_ladder


app = FastAPI(title="SLABIQ API", version="8.0.0")

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

    # Pass card identity to frontend for building correct external links
    if resolved.get("card_identity"):
        result["card_identity"] = resolved["card_identity"]

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

    # Steps 4-11: Analytics (wrapped to never crash the lookup)
    try:
        result["momentum"] = _compute_momentum(all_sales)
    except Exception as e:
        print(f"[analytics] momentum error: {e}")
        result["momentum"] = {"direction": "unknown", "pct_change": 0, "label": "Error"}

    try:
        result["liquidity"] = _compute_liquidity(all_sales)
    except Exception as e:
        print(f"[analytics] liquidity error: {e}")
        result["liquidity"] = {"avg_days_between": None, "score": 0, "label": "Error"}

    try:
        result["market_efficiency"] = _compute_market_efficiency(all_sales)
    except Exception as e:
        print(f"[analytics] efficiency error: {e}")
        result["market_efficiency"] = {"score": 0, "label": "Error"}

    if result["market_summary"]:
        avg = result["market_summary"].get("avg_price", 0)
        median = result["market_summary"].get("median_price", 0)
        for sale in all_sales:
            try:
                sale["deal_score"] = _compute_deal_score(sale.get("price", 0), avg, median)
            except Exception:
                pass

    try:
        result["investment"] = _compute_investment_metrics(all_sales, result["market_summary"], result["momentum"], result["liquidity"], result.get("card_details", {}))
    except Exception as e:
        print(f"[analytics] investment error: {e}")
        result["investment"] = {}

    try:
        result["fair_value"] = _compute_fair_value(all_sales)
    except Exception as e:
        print(f"[analytics] fair_value error: {e}")
        result["fair_value"] = {}

    try:
        result["price_distribution"] = _compute_price_distribution(all_sales)
    except Exception as e:
        print(f"[analytics] distribution error: {e}")
        result["price_distribution"] = {"buckets": []}

    try:
        result["timing"] = _compute_timing_signal(all_sales, result["momentum"], result["market_summary"])
    except Exception as e:
        print(f"[analytics] timing error: {e}")
        result["timing"] = {"signal": "hold", "reason": "Error"}

    # Step 12: Card Ladder enrichment (player index + card match)
    try:
        card = result.get("card_details") or {}
        subject = card.get("subject", "")
        if subject:
            cl_player, cl_card = await asyncio.gather(
                search_player(subject),
                match_card_ladder(
                    subject, card.get("year", ""), card.get("brand", ""),
                    card.get("card_number", ""), card.get("grade", ""),
                    grading_company.lower(),
                ),
                return_exceptions=True,
            )
            if isinstance(cl_player, dict):
                result["player_index"] = cl_player
            if isinstance(cl_card, dict):
                result["cardladder_match"] = cl_card
                # Include Card Ladder's full sales history for charting
                cl_sales = cl_card.get("all_sales", [])
                if cl_sales:
                    result["cardladder_sales"] = cl_sales[:100]  # Up to 100 data points
                    print(f"[cardladder] {len(cl_sales)} sales history points for chart")
    except Exception as e:
        print(f"[analytics] cardladder error: {e}")

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


# ── PLAYER SEARCH (Card Ladder + 130point) ──
@app.get("/search/players")
async def search_players(q: str = Query(..., min_length=2, description="Player name")):
    """Search for a player and get their cards with real pricing data from Card Ladder."""
    player_name = q.strip()

    # Parallel: Card Ladder player index + cards + 130point search
    cl_player_task = search_player(player_name)
    cl_cards_task = search_cards_by_player(player_name, limit=15)
    results = await asyncio.gather(cl_player_task, cl_cards_task, return_exceptions=True)

    player_index = results[0] if isinstance(results[0], dict) else None
    cl_cards = results[1] if isinstance(results[1], list) else []

    # Sort cards by num_sales descending (most traded first)
    cl_cards.sort(key=lambda c: c.get("num_sales", 0), reverse=True)

    return {
        "query": player_name,
        "player_index": player_index,
        "cards": cl_cards[:15],
        "total_cards": player_index.get("total_cards", 0) if player_index else len(cl_cards),
        "source": "Card Ladder",
    }


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


def _parse_sale_date(d: str):
    """Parse a date string to timezone-aware datetime. Returns None on failure."""
    from datetime import datetime, timezone
    if not d:
        return None
    # Try ISO format first (YYYY-MM-DD)
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    # Try RFC 2822 (from 130point: "Wed 14 Jan 2026 08:00:10 GMT")
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(d)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Try common formats
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(d.strip(), fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


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
        dt = _parse_sale_date(d)
        if not dt:
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
    dates = []
    for s in sales:
        dt = _parse_sale_date(s.get("date", ""))
        if dt:
            dates.append(dt)

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


def _compute_market_efficiency(sales: list) -> dict:
    """Card Ladder-style Market Efficiency Score — measures price stability."""
    prices = [s["price"] for s in sales if s.get("price") and s["price"] > 5]
    if len(prices) < 3:
        return {"score": 0, "label": "Insufficient data", "volatility": 0, "consistency": 0}

    import statistics
    avg = statistics.mean(prices)
    if avg == 0:
        return {"score": 0, "label": "No data", "volatility": 0, "consistency": 0}

    stdev = statistics.stdev(prices)
    cv = stdev / avg  # coefficient of variation

    # Consistency: what % of sales fall within 25% of median
    median = statistics.median(prices)
    within_band = sum(1 for p in prices if abs(p - median) / median <= 0.25)
    consistency = round((within_band / len(prices)) * 100, 1)

    # Score: lower CV = more efficient market
    if cv < 0.10:
        score, label = 10, "Highly efficient"
    elif cv < 0.15:
        score, label = 9, "Very efficient"
    elif cv < 0.20:
        score, label = 8, "Efficient"
    elif cv < 0.30:
        score, label = 7, "Moderately efficient"
    elif cv < 0.40:
        score, label = 6, "Fair"
    elif cv < 0.50:
        score, label = 5, "Moderate volatility"
    elif cv < 0.65:
        score, label = 4, "Volatile"
    elif cv < 0.80:
        score, label = 3, "Very volatile"
    else:
        score, label = 2, "Highly volatile"

    return {
        "score": score,
        "label": label,
        "volatility": round(cv * 100, 1),
        "consistency": consistency,
        "stdev": round(stdev, 2),
        "sample_size": len(prices),
    }


def _compute_deal_score(price: float, avg: float, median: float) -> dict:
    """Fanatics-style deal classification for a sale price."""
    if not price or not avg or avg == 0:
        return {"rating": "unknown", "pct_vs_avg": 0}

    pct = round(((price - avg) / avg) * 100, 1)
    pct_med = round(((price - median) / median) * 100, 1) if median else pct

    if pct <= -25:
        rating = "steal"
    elif pct <= -10:
        rating = "great_deal"
    elif pct <= -3:
        rating = "good_deal"
    elif pct <= 5:
        rating = "fair"
    elif pct <= 15:
        rating = "above_avg"
    else:
        rating = "overpriced"

    return {"rating": rating, "pct_vs_avg": pct, "pct_vs_median": pct_med}


def _compute_investment_metrics(sales: list, summary: dict, momentum: dict, liquidity: dict, card: dict) -> dict:
    """Comprehensive investment metrics inspired by Card Ladder + Alt."""
    prices = [s["price"] for s in sales if s.get("price") and s["price"] > 5]
    if not prices or not summary:
        return {}

    avg = summary.get("avg_price", 0) or 0
    low = summary.get("low_price", 0) or 0
    high = summary.get("high_price", 0) or 0

    # Market cap estimate (avg price * estimated pop at this grade)
    try:
        pop = int(card.get("pop", 0) or 0)
    except (ValueError, TypeError):
        pop = 0
    market_cap = round(avg * pop) if pop and avg else None

    # 30-day ROI: if you bought at median 30 days ago vs current avg
    roi_30d = momentum.get("pct_change", 0) if momentum else 0

    # Spread (bid-ask proxy): range as % of avg
    spread = round(((high - low) / avg) * 100, 1) if avg and high > low else 0

    # Value rating: is current avg above or below fair value?
    # Simple model: avg of recent sales vs all-time avg
    recent_prices = prices[:min(5, len(prices))]
    recent_avg = sum(recent_prices) / len(recent_prices) if recent_prices else avg
    all_avg = sum(prices) / len(prices) if prices else avg
    value_pct = round(((recent_avg - all_avg) / all_avg) * 100, 1) if all_avg else 0

    if value_pct < -15:
        value_label = "Undervalued"
    elif value_pct < -5:
        value_label = "Below avg"
    elif value_pct <= 5:
        value_label = "Fair value"
    elif value_pct <= 15:
        value_label = "Above avg"
    else:
        value_label = "Overvalued"

    # Hot/Cold score (Market Movers-style)
    mom_score = min(10, max(0, 5 + (momentum.get("pct_change", 0) / 10))) if momentum else 5
    liq_score = liquidity.get("score", 5) if liquidity else 5
    hot_cold = round((mom_score * 0.6 + liq_score * 0.4), 1)

    if hot_cold >= 8:
        temp_label = "HOT"
    elif hot_cold >= 6:
        temp_label = "WARM"
    elif hot_cold >= 4:
        temp_label = "NEUTRAL"
    elif hot_cold >= 2:
        temp_label = "COOL"
    else:
        temp_label = "COLD"

    return {
        "market_cap": market_cap,
        "roi_30d": roi_30d,
        "spread_pct": spread,
        "value_rating": value_label,
        "value_pct": value_pct,
        "hot_cold_score": hot_cold,
        "hot_cold_label": temp_label,
        "recent_avg": round(recent_avg, 2),
        "all_time_avg": round(all_avg, 2),
    }


def _compute_fair_value(sales: list) -> dict:
    """Estimate fair value using weighted recent sales + trend regression."""
    prices = [s["price"] for s in sales if s.get("price") and s["price"] > 5]
    if len(prices) < 3:
        return {"estimate": None, "confidence": "low", "method": "insufficient_data"}

    import statistics

    # Weighted average: recent sales weighted more heavily
    weights = [1.0 / (i + 1) for i in range(len(prices))]  # sales already sorted recent-first
    weighted_sum = sum(p * w for p, w in zip(prices, weights))
    weight_total = sum(weights)
    weighted_avg = weighted_sum / weight_total

    median = statistics.median(prices)
    avg = statistics.mean(prices)

    # Fair value = blend of weighted avg (60%), median (25%), simple avg (15%)
    fair = round(weighted_avg * 0.60 + median * 0.25 + avg * 0.15, 2)

    # Confidence based on sample size and consistency
    stdev = statistics.stdev(prices) if len(prices) > 1 else 0
    cv = stdev / avg if avg else 1
    if len(prices) >= 10 and cv < 0.25:
        confidence = "high"
    elif len(prices) >= 5 and cv < 0.40:
        confidence = "medium"
    else:
        confidence = "low"

    # How does last sale compare to fair value?
    last_price = prices[0]
    vs_fair = round(((last_price - fair) / fair) * 100, 1) if fair else 0

    return {
        "estimate": fair,
        "confidence": confidence,
        "vs_last_sale": vs_fair,
        "last_sale": last_price,
        "method": "weighted_blend",
        "sample_size": len(prices),
    }


def _compute_price_distribution(sales: list) -> dict:
    """Bucket prices into ranges for distribution visualization."""
    prices = [s["price"] for s in sales if s.get("price") and s["price"] > 5]
    if len(prices) < 3:
        return {"buckets": []}

    lo, hi = min(prices), max(prices)
    if hi == lo:
        return {"buckets": [{"label": f"${int(lo)}", "count": len(prices), "pct": 100}]}

    n_buckets = min(6, max(3, len(prices) // 3))
    step = (hi - lo) / n_buckets
    buckets = []
    for i in range(n_buckets):
        blo = lo + i * step
        bhi = lo + (i + 1) * step if i < n_buckets - 1 else hi + 1
        count = sum(1 for p in prices if blo <= p < bhi)
        buckets.append({
            "label": f"${int(blo)}-${int(bhi)}",
            "low": round(blo),
            "high": round(bhi),
            "count": count,
            "pct": round(count / len(prices) * 100, 1),
        })
    return {"buckets": buckets, "total": len(prices)}


def _compute_timing_signal(sales: list, momentum: dict, summary: dict) -> dict:
    """Generate buy/sell timing signal based on momentum + price position."""
    if not sales or not summary or not momentum:
        return {"signal": "hold", "reason": "Insufficient data", "confidence": "low"}

    avg = summary.get("avg_price", 0) or 0
    low = summary.get("low_price", 0) or 0
    pct_change = momentum.get("pct_change", 0) or 0
    direction = momentum.get("direction", "unknown")

    prices = [s["price"] for s in sales if s.get("price") and s["price"] > 5]
    if not prices or not avg:
        return {"signal": "hold", "reason": "No price data", "confidence": "low"}

    last = prices[0]
    vs_avg = ((last - avg) / avg * 100) if avg else 0

    # Buy signals: price trending down but near historical low
    if vs_avg < -15 and direction == "down":
        return {"signal": "strong_buy", "reason": f"Price {vs_avg:.0f}% below avg & declining — potential bottom", "confidence": "medium"}
    if vs_avg < -10:
        return {"signal": "buy", "reason": f"Price {vs_avg:.0f}% below avg — good entry point", "confidence": "medium"}
    if direction == "down" and pct_change < -15:
        return {"signal": "buy", "reason": f"Momentum {pct_change}% — dip buy opportunity", "confidence": "low"}

    # Sell signals: price well above average and rising
    if vs_avg > 20 and direction == "up":
        return {"signal": "strong_sell", "reason": f"Price {vs_avg:.0f}% above avg & rising — consider taking profits", "confidence": "medium"}
    if vs_avg > 15:
        return {"signal": "sell", "reason": f"Price {vs_avg:.0f}% above avg — elevated", "confidence": "low"}

    # Hold
    return {"signal": "hold", "reason": f"Price near fair value ({vs_avg:+.0f}% vs avg)", "confidence": "medium"}


# ── CURRENCY CONVERSION ──
_fx_cache = {"ts": 0, "rates": {}}

@app.get("/fx/rates")
async def get_fx_rates():
    """Get USD exchange rates for multi-currency support."""
    now = time.time()
    if now - _fx_cache["ts"] < 3600 and _fx_cache["rates"]:
        return _fx_cache["rates"]

    # Hardcoded fallback rates (updated periodically)
    rates = {"USD": 1, "GBP": 0.79, "EUR": 0.92, "CAD": 1.36, "AUD": 1.53, "JPY": 149.5}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("rates"):
                    for curr in ["GBP", "EUR", "CAD", "AUD", "JPY"]:
                        if curr in data["rates"]:
                            rates[curr] = round(data["rates"][curr], 4)
    except Exception:
        pass

    _fx_cache["ts"] = now
    _fx_cache["rates"] = rates
    return rates


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
    return {"status": "ok", "version": "8.0.0", "cache_entries": len(_cache)}


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
