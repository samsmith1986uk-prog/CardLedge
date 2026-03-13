"""
Card Ladder Data Client
-----------------------
Reads from Card Ladder's Firestore database (publicly accessible).
Project: cardladder-71d53

Collections:
  - players: Player index data (daily values, percent changes, key cards)
  - cards: Individual card profiles (values, pop, daily sales history)
"""

import httpx
from typing import Optional, List

FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/cardladder-71d53/databases/(default)/documents"


def _val(field):
    """Extract a Python value from a Firestore field."""
    if not field or not isinstance(field, dict):
        return None
    if "stringValue" in field:
        return field["stringValue"]
    if "integerValue" in field:
        return int(field["integerValue"])
    if "doubleValue" in field:
        v = field["doubleValue"]
        return None if (isinstance(v, float) and v != v) else float(v)  # NaN check
    if "booleanValue" in field:
        return field["booleanValue"]
    if "timestampValue" in field:
        return field["timestampValue"]
    if "nullValue" in field:
        return None
    if "mapValue" in field:
        return {k: _val(v) for k, v in field["mapValue"].get("fields", {}).items()}
    if "arrayValue" in field:
        return [_val(v) for v in field["arrayValue"].get("values", [])]
    return None


def _parse_player(doc: dict) -> dict:
    """Parse a Firestore player document."""
    f = doc.get("fields", {})

    key_card = _val(f.get("keyCard"))
    kc = None
    if isinstance(key_card, dict) and key_card.get("label"):
        kc = {
            "id": key_card.get("id", ""),
            "label": key_card.get("label", ""),
            "value": key_card.get("currentValue"),
            "market_cap": key_card.get("marketCap"),
            "image": key_card.get("image", ""),
        }

    return {
        "name": _val(f.get("player")) or _val(f.get("label")) or "",
        "player_id": _val(f.get("playerId")) or "",
        "category": _val(f.get("category")) or "",
        "total_cards": _val(f.get("totalCards")) or 0,
        "total_value": _val(f.get("totalValue")) or 0,
        "total_market_cap": _val(f.get("totalMarketCap")) or 0,
        "daily_index": _val(f.get("dailyIndex")) or 0,
        "daily_sales_volume": _val(f.get("dailySales")) or 0,
        "daily_sales_count": _val(f.get("dailySalesCount")) or 0,
        "key_card": kc,
        "pct_change": {
            "daily": _val(f.get("dailyPercentChange")),
            "weekly": _val(f.get("weeklyPercentChange")),
            "monthly": _val(f.get("monthlyPercentChange")),
            "quarterly": _val(f.get("quarterlyPercentChange")),
            "half_annual": _val(f.get("halfAnnualPercentChange")),
            "ytd": _val(f.get("yearToDatePercentChange")),
            "annual": _val(f.get("annualPercentChange")),
            "five_year": _val(f.get("fiveYearPercentChange")),
            "all_time": _val(f.get("allTimePercentChange")),
        },
        "source": "Card Ladder",
    }


def _parse_card(doc: dict) -> dict:
    """Parse a Firestore card document."""
    f = doc.get("fields", {})

    # Extract ALL daily sales (date -> {n: count, p: price})
    ds_raw = _val(f.get("dailySales")) or {}
    all_daily_sales = []
    if isinstance(ds_raw, dict):
        for date_str, sale_data in sorted(ds_raw.items(), reverse=True):
            if isinstance(sale_data, dict):
                price = sale_data.get("p", 0)
                if price and price > 0:
                    all_daily_sales.append({
                        "date": date_str,
                        "price": price,
                        "count": sale_data.get("n", 0),
                    })

    recent_sales = all_daily_sales[:20]
    current_value = recent_sales[0]["price"] if recent_sales else None

    return {
        "card_id": _val(f.get("cardId")) or "",
        "label": _val(f.get("label")) or "",
        "player": _val(f.get("player")) or "",
        "category": _val(f.get("category")) or "",
        "year": _val(f.get("year")) or "",
        "set": _val(f.get("set")) or "",
        "variation": _val(f.get("variation")) or "",
        "number": _val(f.get("number")) or "",
        "condition": _val(f.get("condition")) or "",
        "grading_company": _val(f.get("gradingCompany")) or "",
        "pop": _val(f.get("pop")) or 0,
        "num_sales": _val(f.get("numSales")) or 0,
        "image": _val(f.get("image")) or "",
        "slug": _val(f.get("slug")) or "",
        "current_value": current_value,
        "recent_sales": recent_sales[:10],
        "all_sales": all_daily_sales,  # Full sales history for charting
        "total_tracked_sales": len(all_daily_sales),
        "psa_spec_id": _val(f.get("psaSpecId")),
        "source": "Card Ladder",
    }


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

async def get_player_index(player_name: str) -> Optional[dict]:
    """Get Card Ladder player index data by exact name."""
    url = f"{FIRESTORE_BASE}/players/{player_name}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return _parse_player(resp.json())
    except Exception as e:
        print(f"[cardladder] player error: {e}")
    return None


async def search_player(player_name: str) -> Optional[dict]:
    """Try multiple name formats to find a player on Card Ladder."""
    # Build candidate names
    candidates = [player_name]

    # Title case
    titled = player_name.title()
    if titled not in candidates:
        candidates.append(titled)

    # Handle names like "LeBRON JAMES" -> "LeBron James"
    # Split into words, title-case each but preserve known prefixes
    prefixes = {"Mc", "Mac", "Le", "De", "La", "Di", "Van", "Von", "Al", "El", "O'"}
    words = player_name.split()
    smart_titled = []
    for w in words:
        wt = w.title()
        # Check for prefixes (e.g. LeBron, McDonald, DeGrom)
        for pfx in prefixes:
            if w.upper().startswith(pfx.upper()) and len(w) > len(pfx):
                wt = pfx + w[len(pfx):].title()
                break
        smart_titled.append(wt)
    smart = " ".join(smart_titled)
    if smart not in candidates:
        candidates.append(smart)

    # Original upper
    if player_name.upper() not in candidates:
        candidates.append(player_name.upper())

    for name in candidates:
        result = await get_player_index(name)
        if result and result.get("total_cards"):
            return result
    return None


async def search_cards_by_player(player_name: str, limit: int = 10) -> List[dict]:
    """Search Card Ladder for cards by player name."""
    url = f"{FIRESTORE_BASE}:runQuery"
    # Try exact name first, then title case
    for name in [player_name, player_name.title()]:
        query = {
            "structuredQuery": {
                "from": [{"collectionId": "cards"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "player"},
                        "op": "EQUAL",
                        "value": {"stringValue": name},
                    }
                },
                "limit": limit,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=query)
                if resp.status_code == 200:
                    results = resp.json()
                    cards = []
                    for item in results:
                        doc = item.get("document")
                        if doc:
                            cards.append(_parse_card(doc))
                    if cards:
                        return cards
        except Exception as e:
            print(f"[cardladder] card search error: {e}")
    return []


async def match_card(subject: str, year: str = "", brand: str = "",
                     card_number: str = "", grade: str = "",
                     grading_company: str = "psa") -> Optional[dict]:
    """Find the best matching Card Ladder card profile for a graded card."""
    cards = await search_cards_by_player(subject, limit=50)
    if not cards:
        return None

    gc = grading_company.lower()
    best_match = None
    best_score = 0

    for card in cards:
        score = 0
        # Grading company match
        if card.get("grading_company", "").lower() == gc:
            score += 2
        # Year match
        if year and card.get("year") and year[:4] == card["year"][:4]:
            score += 3
        # Grade match
        if grade and card.get("condition") and grade in card["condition"]:
            score += 1
        # Card number match (very important — differentiates cards within same set)
        cn_match = False
        if card_number and card.get("number"):
            cn1 = card_number.lower().strip("#").strip()
            cn2 = card["number"].lower().strip("#").strip()
            if cn1 == cn2:
                score += 5  # Strong signal
                cn_match = True
        # Brand/set match
        if brand and card.get("set"):
            bw = set(brand.lower().split())
            sw = set(card["set"].lower().split())
            overlap = len(bw & sw)
            score += min(overlap, 3)
        # Label contains key words from brand
        label = (card.get("label") or "").lower()
        if brand:
            brand_words = [w for w in brand.lower().split() if len(w) > 3]
            label_hits = sum(1 for w in brand_words if w in label)
            score += min(label_hits, 2)

        if score > best_score:
            best_score = score
            best_match = card
            print(f"[cardladder] New best: score={score} cn_match={cn_match} label={card.get('label','')[:50]}")

    # Require at least year + some other match
    if best_match and best_score >= 5:
        best_match["match_score"] = best_score
        return best_match
    return None
