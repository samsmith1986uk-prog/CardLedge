"""
Card Resolver v4
----------------
Multi-source card data resolver. Zero Playwright dependency — runs on Render free tier.

Working sources (March 2026):
  Sales:  130point (back.130point.com POST API) — aggregates eBay/Goldin/Fanatics/Heritage
  Images: Collectors tRPC API (PSA certs, via httpx + stored cookies)
"""

import httpx
import re
import json
import asyncio
from typing import List
from urllib.parse import quote_plus

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
}

# ─────────────────────────────────────────────
# CARD IDENTITY
# ─────────────────────────────────────────────

def build_card_identity(psa_cert: dict) -> dict:
    subject = psa_cert.get("subject", "")
    year = psa_cert.get("year", "")
    brand = psa_cert.get("brand", "")
    variety = psa_cert.get("variety", "")
    card_number = psa_cert.get("card_number", "")
    grade = psa_cert.get("grade", "10")
    gc = psa_cert.get("grading_company", "PSA")
    cert_number = psa_cert.get("cert_number", "")
    parallel = _detect_parallel(variety, brand)

    return {
        "subject": subject,
        "year": year,
        "brand": brand,
        "variety": variety,
        "card_number": card_number,
        "grade": grade,
        "grading_company": gc,
        "cert_number": cert_number,
        "parallel": parallel,
        "query_short": f"{subject} {year} {card_number}".strip(),
        "query_full": f"{subject} {year} {brand} #{card_number} {variety}".strip(),
        "query_graded": f"{subject} {year} {brand} {card_number} {gc} {grade}".strip(),
        "query_clean": f"{subject} {year} {brand} {card_number} {gc} {grade}".strip(),
    }

def _detect_parallel(variety: str, brand: str) -> dict:
    v = (variety + " " + brand).upper()
    tiers = [
        (["SUPERFRACTOR", "1/1", "GOLD LABEL"],          "Superfractor",      "#FFD700", 10.0),
        (["PRINTING PLATE", "PRINT PLATE"],               "Printing Plate",    "#C0C0C0", 9.5),
        (["LOGOMAN"],                                     "Logoman",           "#ef4444", 9.5),
        (["AUTO", "AUTOGRAPH", "SIGNED"],                 "Autograph",         "#9333ea", 9.0),
        (["/10 ", "/5 ", "/1 "],                          "Low Numbered",      "#f97316", 9.2),
        (["/25 ", "/50 "],                                "Short Print",       "#f97316", 8.8),
        (["/99 ", "/100 "],                               "Numbered /99",      "#3b82f6", 8.0),
        (["/149", "/199", "/249"],                        "Numbered",          "#3b82f6", 7.5),
        (["MANGA RARE", "LIMITADA", "LIMITADO"],          "Manga Rare",        "#f59e0b", 8.5),
        (["ALTERNATE ART", "ALT ART"],                    "Alternate Art",     "#ec4899", 7.0),
        (["REFRACTOR", "PRIZM", "CHROME"],                "Refractor",         "#06b6d4", 7.0),
        (["GOLD FOIL", "GOLD PARALLEL"],                  "Gold Parallel",     "#d97706", 7.5),
        (["BIS ", "ESPECIAL", "SPECIAL"],                 "Special Variant",   "#f59e0b", 7.5),
        (["ROOKIE", " RC ", "FIRST"],                     "Rookie",            "#10b981", 6.5),
        (["BASE", "COMMON"],                              "Base",              "#6b7280", 4.0),
    ]
    for keywords, tier, color, score in tiers:
        if any(k in v for k in keywords):
            return {"tier": tier, "color": color, "score": score}
    return {"tier": "Base", "color": "#6b7280", "score": 4.0}


# ─────────────────────────────────────────────
# IMAGE RESOLUTION (httpx only — no Playwright)
# ─────────────────────────────────────────────

async def resolve_card_image(identity: dict) -> dict:
    """Get card image via Collectors tRPC API, then 130point image search.
    Returns dict with 'front' and optionally 'back' image URLs."""
    cert = identity.get("cert_number", "")
    gc = identity.get("grading_company", "").upper()

    # Source 1: Collectors tRPC API — real PSA CloudFront images (front + back)
    if gc == "PSA" and cert:
        try:
            from scrapers.collectors_image import fetch_cert_images
            imgs = await fetch_cert_images(cert)
            if imgs.get("front"):
                print(f"[image/collectors] Found: {imgs['front'][:80]}")
                return imgs
        except Exception as e:
            print(f"[image/collectors] Error: {e}")

    # Source 2: 130point image search — find a sold listing image that matches
    # the exact card (subject + year + set + variety + card number)
    img = await _image_from_130point(identity)
    if img:
        return {"front": img, "back": ""}

    return {"front": "", "back": ""}


async def _image_from_130point(identity: dict) -> str:
    """Search 130point for a sold listing image matching the exact card variant."""
    subject = identity.get("subject", "")
    year = identity.get("year", "")
    brand = identity.get("brand", "")
    variety = identity.get("variety", "")
    card_number = identity.get("card_number", "")
    grade = identity.get("grade", "")
    gc = identity.get("grading_company", "PSA")

    if not subject:
        return ""

    # Build a specific query including variety
    query = f"{subject} {year} {brand} {variety} {card_number} {gc} {grade}".strip()
    query = re.sub(r'\s+', ' ', query)
    print(f"[image/130point] Searching: {query}")

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
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
                return ""

            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL)
            cn = card_number.strip("#").strip()
            variety_words = [w.upper() for w in variety.split() if len(w) > 3] if variety else []
            subject_upper = subject.upper()

            for row in rows:
                img_m = re.search(r"src='(https://i\.ebayimg\.com/[^']+)'", row)
                if not img_m:
                    continue
                title_m = re.search(r"id='titleText'[^>]*>(?:<a[^>]*>)?(.*?)(?:</a>)?</span>", row, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip().upper() if title_m else ""
                if not title:
                    continue

                # Must contain subject last name
                name_words = subject_upper.split()
                last_name = name_words[-1] if name_words else ""
                if last_name and last_name not in title:
                    continue

                # Must contain card number
                if cn and f"#{cn}" not in title and f" {cn} " not in title and not title.endswith(f" {cn}"):
                    continue

                # Must contain variety keywords (if any)
                if variety_words and not all(vw in title for vw in variety_words):
                    continue

                img = img_m.group(1)
                img = img.replace("s-l140", "s-l500").replace("s-l150", "s-l500")
                print(f"[image/130point] Match: {title[:70]} -> {img[:60]}")
                return img

            print(f"[image/130point] No exact variant match in {len(rows)} results")
    except Exception as e:
        print(f"[image/130point] Error: {e}")
    return ""


# ─────────────────────────────────────────────
# TITLE RELEVANCE FILTERING
# ─────────────────────────────────────────────

def _compute_title_relevance(title: str, identity: dict) -> float:
    """Score how relevant a sale title is to the card identity (0.0-1.0).
    Requires player name match + bonus for year/number/brand/grade."""
    if not title or not identity.get("subject"):
        return 0.0

    title_upper = title.upper()
    subject = identity.get("subject", "").upper()

    # Check player name: all name words must appear in title
    name_words = [w for w in subject.split() if len(w) > 1]
    if not name_words:
        return 0.0

    # At least the last name (last word OR longest word) must appear in title
    last_word = name_words[-1] if name_words else ""
    longest_word = max(name_words, key=len) if name_words else ""
    if last_word not in title_upper and longest_word not in title_upper:
        return 0.0

    # Score: how many name words match
    name_hits = sum(1 for w in name_words if w in title_upper)
    name_score = name_hits / len(name_words)  # 0.0-1.0

    # If less than half the name matches, reject
    if name_score < 0.5:
        return 0.0

    # Bonus points for other card details matching
    bonus = 0.0
    year = identity.get("year", "")
    if year and year[:4] in title:
        bonus += 0.15

    card_number = identity.get("card_number", "")
    if card_number:
        # Match #123 or just 123 in title
        cn_clean = card_number.strip("#").strip()
        if cn_clean and (f"#{cn_clean}" in title or f"#{cn_clean} " in title or f" {cn_clean} " in title):
            bonus += 0.15

    brand = identity.get("brand", "").upper()
    if brand:
        brand_words = [w for w in brand.split() if len(w) > 2]
        brand_hits = sum(1 for w in brand_words if w in title_upper)
        if brand_words:
            bonus += 0.1 * min(1.0, brand_hits / max(1, len(brand_words)))

    gc = identity.get("grading_company", "").upper()
    if gc and gc in title_upper:
        bonus += 0.1

    grade = identity.get("grade", "")
    if grade and gc:
        # Match "PSA 10" or "BGS 8.5" pattern
        grade_pattern = f"{gc}\\s*{re.escape(grade)}"
        if re.search(grade_pattern, title_upper):
            bonus += 0.1

    return min(1.0, name_score * 0.5 + bonus + 0.3)  # base 0.3 for having name match


def filter_relevant_sales(sales: List[dict], identity: dict, threshold: float = 0.55) -> List[dict]:
    """Filter sales to only include those relevant to the card identity."""
    if not identity.get("subject"):
        return sales

    filtered = []
    for sale in sales:
        title = sale.get("title", "")
        score = _compute_title_relevance(title, identity)
        if score >= threshold:
            sale["relevance_score"] = round(score, 2)
            filtered.append(sale)
        else:
            print(f"[filter] Rejected (score={score:.2f}): {title[:80]}")

    if not filtered and sales:
        # If we filtered everything out, keep the best matches
        scored = [(s, _compute_title_relevance(s.get("title", ""), identity)) for s in sales]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Keep top 5 even if below threshold
        for s, score in scored[:5]:
            s["relevance_score"] = round(score, 2)
            filtered.append(s)
        print(f"[filter] All below threshold, kept top {len(filtered)}")

    print(f"[filter] Kept {len(filtered)}/{len(sales)} sales (threshold={threshold})")
    return filtered


# ─────────────────────────────────────────────
# SALES DATA
# ─────────────────────────────────────────────

def _parse_date_for_sort(date_str: str) -> str:
    """Parse various date formats into ISO format for correct sorting."""
    if not date_str:
        return ""
    from datetime import datetime
    for fmt in [
        "%a %d %b %Y %H:%M:%S %Z",  # "Tue 28 Jan 2025 02:22:00 GMT"
        "%a %d %b %Y",                # "Tue 28 Jan 2025"
        "%b %d, %Y",                  # "Jan 28, 2025"
        "%m/%d/%Y",                    # "01/28/2025"
        "%Y-%m-%d",                    # "2025-01-28"
        "%d %b %Y",                    # "28 Jan 2025"
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    # Try to extract any 4-digit year + month pattern
    m = re.search(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})', date_str, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return date_str  # fallback to original string


async def resolve_sales_data(identity: dict) -> dict:
    # Try multiple sources in parallel — 130point + eBay direct
    tasks = [
        _sales_from_130point(identity),
        _sales_from_ebay(identity),
    ]
    source_names = ["130point", "eBay"]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_sales = []
    sources_hit = []
    for name, result in zip(source_names, results):
        if isinstance(result, Exception):
            print(f"[sales/{name}] exception: {result}")
        elif isinstance(result, list) and result:
            for sale in result:
                sale["source"] = name
            all_sales.extend(result)
            sources_hit.append(name)
            print(f"[sales/{name}] {len(result)} sales found")
        else:
            print(f"[sales/{name}] 0 results")

    # Filter irrelevant sales (wrong player, wrong card)
    all_sales = filter_relevant_sales(all_sales, identity)

    all_sales.sort(key=lambda x: _parse_date_for_sort(x.get("date", "")), reverse=True)

    prices = [s["price"] for s in all_sales if s.get("price") and s["price"] > 5]
    stats = {}
    if prices:
        ps = sorted(prices)
        n = len(ps)
        stats = {
            "avg_price": round(sum(ps) / n, 2),
            "median_price": round(ps[n // 2], 2),
            "high_price": max(ps),
            "low_price": min(ps),
            "last_sale": prices[0],
            "total_sales": n,
            "sources": sources_hit,
        }

    return {"sales": all_sales, "stats": stats, "sources_hit": sources_hit}


async def _sales_from_130point(identity: dict) -> list:
    """130point via back.130point.com POST API."""
    query = identity["query_clean"]
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
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
            if r.status_code != 200 or len(r.text) < 500:
                return []

            html = r.text
            sales = []
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)

            for row in rows:
                # Extract data-price attribute (most reliable)
                price_attr = re.search(r'data-price="([^"]+)"', row)
                if not price_attr:
                    continue

                try:
                    price = float(price_attr.group(1))
                except (ValueError, TypeError):
                    continue
                if price < 5:
                    continue

                # Extract title
                title_m = re.search(r"id='titleText'[^>]*>(?:<a[^>]*>)?(.*?)(?:</a>)?</span>", row, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

                # Extract date
                date_m = re.search(r"id='dateText'[^>]*>(?:<b>Date:</b>)?\s*(.*?)</span>", row, re.DOTALL)
                date_str = re.sub(r'<[^>]+>', '', date_m.group(1)).strip() if date_m else ""

                # Extract URL
                url_m = re.search(r"href='(https://www\.ebay\.com/itm/[^']+)'", row)
                item_url = url_m.group(1) if url_m else ""

                # Extract image
                img_m = re.search(r"src='(https://i\.ebayimg\.com/[^']+)'", row)
                image = img_m.group(1) if img_m else ""
                # Upgrade thumbnail to larger image
                if image and "s-l150" in image:
                    image = image.replace("s-l150", "s-l500")

                # Extract currency
                curr_m = re.search(r'data-currency="([^"]+)"', row)
                currency = curr_m.group(1) if curr_m else "USD"

                # Extract sale type
                sale_type_m = re.search(r'Sale Type:\s*(\w+)', row)
                sale_type = sale_type_m.group(1) if sale_type_m else ""

                # Extract platform (eBay, Goldin, etc)
                platform = "eBay"
                if "Goldin" in row:
                    platform = "Goldin"
                elif "Fanatics" in row:
                    platform = "Fanatics"
                elif "Heritage" in row:
                    platform = "Heritage"
                elif "MySlabs" in row:
                    platform = "MySlabs"

                sales.append({
                    "price": price,
                    "currency": currency,
                    "date": date_str,
                    "title": title,
                    "url": item_url,
                    "image_url": image,
                    "grade": identity["grade"],
                    "platform": f"130point ({platform})",
                    "sale_type": sale_type,
                })

            return sales
    except Exception as e:
        print(f"[130point] {e}")
    return []


async def _sales_from_ebay(identity: dict) -> list:
    """Scrape eBay sold listings via httpx (no Playwright).
    Uses eBay's search results HTML page."""
    query = identity["query_graded"]
    encoded = quote_plus(query)
    # LH_Sold=1&LH_Complete=1 = sold items only
    url = f"https://www.ebay.com/sch/i.html?_nkw={encoded}&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc"
    print(f"[ebay] Searching: {query}")

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers={
                "User-Agent": BROWSER_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
            if r.status_code != 200:
                print(f"[ebay] HTTP {r.status_code}")
                return []

            html = r.text
            sales = []

            # Parse eBay search results — each item is in s-item__wrapper
            items = re.findall(r'<li[^>]*class="s-item[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL)
            if not items:
                # Fallback: try finding items in different format
                items = re.findall(r'<div[^>]*class="s-item__wrapper[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</li>', html, re.DOTALL)
            print(f"[ebay] Found {len(items)} item blocks")

            for item in items:
                # Title
                title_m = re.search(r'<span[^>]*role="heading"[^>]*>(.*?)</span>', item, re.DOTALL)
                if not title_m:
                    title_m = re.search(r'class="s-item__title"[^>]*>(?:<span[^>]*>)?(.*?)(?:</span>)?</(?:div|span|h3)', item, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
                if not title or title.lower().startswith("shop on ebay"):
                    continue

                # Price
                price_m = re.search(r'class="s-item__price"[^>]*>\s*(?:<span[^>]*>)?\s*\$?([\d,]+\.?\d*)', item)
                if not price_m:
                    continue
                try:
                    price = float(price_m.group(1).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                if price < 5:
                    continue

                # Date
                date_m = re.search(r'class="s-item__ended-date[^"]*"[^>]*>(.*?)<', item)
                if not date_m:
                    date_m = re.search(r'class="s-item__endedDate[^"]*"[^>]*>(.*?)<', item)
                if not date_m:
                    date_m = re.search(r'SOLD\s+(\w+\s+\d+,?\s*\d*)', item, re.IGNORECASE)
                date_str = re.sub(r'<[^>]+>', '', date_m.group(1)).strip() if date_m else ""
                # Clean up "Sold  Mar 12, 2026" format
                date_str = re.sub(r'^Sold\s+', '', date_str, flags=re.IGNORECASE).strip()

                # Image
                img_m = re.search(r'<img[^>]*src="(https://i\.ebayimg\.com/[^"]+)"', item)
                image = img_m.group(1) if img_m else ""
                if image:
                    image = re.sub(r's-l\d+', 's-l500', image)

                # URL
                url_m = re.search(r'href="(https://www\.ebay\.com/itm/[^"]+)"', item)
                item_url = url_m.group(1) if url_m else ""

                sales.append({
                    "price": price,
                    "currency": "USD",
                    "date": date_str,
                    "title": title,
                    "url": item_url,
                    "image_url": image,
                    "grade": identity.get("grade", ""),
                    "platform": "eBay (sold)",
                    "sale_type": "auction",
                })

            print(f"[ebay] Parsed {len(sales)} sales")
            return sales
    except Exception as e:
        print(f"[ebay] Error: {e}")
    return []


# ─────────────────────────────────────────────
# MAIN RESOLVER
# ─────────────────────────────────────────────

async def resolve_card(psa_cert: dict) -> dict:
    """Full resolution: image + sales from all sources."""
    if not psa_cert or not psa_cert.get("subject"):
        return {"identity": {}, "image_url": "", "sales": [], "stats": {}, "sources_hit": []}

    identity = build_card_identity(psa_cert)
    print(f"[resolver] Resolving: {identity['query_graded']}")

    image_task = resolve_card_image(identity)
    sales_task = resolve_sales_data(identity)
    image_result, sales_data = await asyncio.gather(image_task, sales_task)

    image_url = image_result.get("front", "") if isinstance(image_result, dict) else (image_result or "")
    back_image_url = image_result.get("back", "") if isinstance(image_result, dict) else ""
    print(f"[resolver] Image: {image_url[:60] if image_url else 'none'}")
    print(f"[resolver] Sales: {sales_data['stats'].get('total_sales', 0)} from {sales_data['sources_hit']}")

    return {
        "identity": identity,
        "image_url": image_url,
        "back_image_url": back_image_url,
        "sales": sales_data["sales"],
        "stats": sales_data["stats"],
        "sources_hit": sales_data["sources_hit"],
        "card_identity": identity,
    }
