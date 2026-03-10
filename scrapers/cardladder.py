import httpx, re, json
from typing import List
from urllib.parse import quote_plus

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Referer":"https://www.cardladder.com/"}

async def search_cardladder(query: str) -> List[dict]:
    url = f"https://www.cardladder.com/search?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=HEADERS) as client:
            r = await client.get(url)
            if r.status_code != 200: return []
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if not match: return []
            data = json.loads(match.group(1))
            props = data.get("props",{}).get("pageProps",{})
            return props.get("results", props.get("cards", []))[:5]
    except Exception as e:
        print(f"[cardladder] search error: {e}"); return []

async def get_cardladder_sales(slug: str) -> List[dict]:
    url = f"https://www.cardladder.com/cards/{slug}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=HEADERS) as client:
            r = await client.get(url)
            if r.status_code != 200: return []
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if not match: return []
            data = json.loads(match.group(1))
            props = data.get("props",{}).get("pageProps",{})
            sales = props.get("sales", props.get("transactions", []))
            out = []
            for s in sales[:20]:
                price = s.get("price") or s.get("amount") or s.get("sale_price")
                if not price: continue
                out.append({"price": float(str(price).replace("$","").replace(",","")),"date": str(s.get("date") or s.get("sold_at",""))[:10],"grade": s.get("grade") or s.get("psa_grade"),"source": "Card Ladder","platform": "Card Ladder"})
            return out
    except Exception as e:
        print(f"[cardladder] sales error: {e}"); return []

async def scrape_cardladder(player: str, card_set: str, grade: str = "10") -> List[dict]:
    for query in [f"{player} {card_set} PSA {grade}", f"{player} {card_set}"]:
        results = await search_cardladder(query)
        if results: break
    if not results: return []
    first = results[0]
    slug = first.get("slug") or first.get("id") or first.get("card_id")
    if not slug:
        m = re.search(r'/cards/([^/?]+)', first.get("url",""))
        slug = m.group(1) if m else None
    if not slug: return []
    return await get_cardladder_sales(str(slug))
