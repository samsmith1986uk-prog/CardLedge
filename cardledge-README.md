# CARDLEDGE — Sports Card Investment Intelligence
## Full Stack: Python Scraping Backend + React Frontend

---

## Architecture

```
cardledge/
├── backend/
│   ├── main.py              ← FastAPI server, main /lookup endpoint
│   ├── requirements.txt
│   ├── .env.example
│   └── scrapers/
│       ├── psa.py           ← PSA Public API + page scrape fallback
│       ├── beckett.py       ← BGS cert lookup + subgrades
│       ├── ebay.py          ← eBay Finding API + page scrape fallback
│       ├── goldin.py        ← Goldin Next.js API + page scrape
│       ├── 130point.py      ← 130point comp search (cloudscraper)
│       └── heritage.py      ← Heritage Auctions (static HTML)
└── frontend/
    └── cardledge-app.jsx    ← React app (runs on Claude.ai or Vite)
```

---

## Quick Start

### 1. Backend Setup

```bash
cd backend

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers (for JS-heavy sites)
playwright install chromium

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys

# Start the API server
uvicorn main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
# Option A: Use the React artifact directly in Claude.ai
# Just paste cardledge-app.jsx into a Claude artifact

# Option B: Run locally with Vite
npm create vite@latest cardledge-frontend -- --template react
cd cardledge-frontend
# Replace src/App.jsx with cardledge-app.jsx content
npm install && npm run dev
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/lookup/{grading_co}/{cert}` | Main lookup — fetches card + all sales |
| GET | `/psa/population/{set_id}` | PSA population report for a set |
| GET | `/health` | Health check |

### Example Request
```bash
# PSA cert lookup
curl http://localhost:8000/lookup/PSA/85028490

# BGS cert lookup  
curl http://localhost:8000/lookup/BGS/0012345678

# Include sales data
curl "http://localhost:8000/lookup/PSA/85028490?include_sales=true"
```

### Example Response
```json
{
  "cert_number": "85028490",
  "grading_company": "PSA",
  "card_details": {
    "subject": "LeBron James",
    "year": "2003",
    "brand": "Topps Chrome",
    "grade": "10",
    "pop": 312,
    "image_url": "https://d1htnxwo4o0jhw.cloudfront.net/..."
  },
  "sales_data": [
    {
      "source": "eBay",
      "title": "2003 Topps Chrome LeBron PSA 10",
      "price": 4800,
      "date": "2025-02-18",
      "url": "https://ebay.com/itm/..."
    }
  ],
  "market_summary": {
    "avg_price": 4906,
    "median_price": 4800,
    "low_price": 4200,
    "high_price": 5800,
    "total_sales_found": 8,
    "sources_checked": 4
  }
}
```

---

## API Keys & Accounts Needed

| Source | Cost | Get It At |
|--------|------|-----------|
| eBay API (Finding + Browse) | Free | developer.ebay.com |
| PSA Public API | Free (PSA account) | psacard.com/publicapi |
| PriceCharting / SportCardsPro | ~$10/mo | sportscardspro.com |
| CardLadder Enterprise | Contact them | cardladder.com |

**No API key needed for:**
- eBay page scraping (fallback)
- 130point (page scrape with cloudscraper)
- Goldin (Next.js data API)
- Heritage Auctions (static HTML)

---

## Scraping Method by Source

| Source | Method | Library | Difficulty |
|--------|--------|---------|------------|
| PSA | Public API | `httpx` | Easy |
| BGS/Beckett | Page scrape | `playwright` | Hard |
| eBay | Finding API + page scrape | `httpx` | Easy |
| Goldin | Next.js data API | `httpx` | Medium |
| 130point | Page scrape | `cloudscraper` | Medium |
| Heritage | Static HTML | `beautifulsoup4` | Easy |
| Fanatics Collect | Playwright | `playwright` | Hard |
| MySlabs | Page scrape | `playwright` | Easy |
| VCP | Page scrape | `httpx` | Medium |

---

## Production Recommendations

### Anti-Bot Measures
```python
# Use rotating proxies for high-volume scraping
# Recommended: Bright Data, Oxylabs, or Smartproxy

# Add to scrapers:
PROXY = "http://user:pass@proxy.example.com:8080"
async with httpx.AsyncClient(proxies=PROXY) as client:
    ...

# Add random delays between requests
import random, asyncio
await asyncio.sleep(random.uniform(1.0, 3.0))
```

### Playwright for JS-heavy sites
```python
# For Beckett, Fanatics, Market Movers:
from playwright.async_api import async_playwright

async def scrape_with_playwright(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")
        content = await page.content()
        await browser.close()
        return content
```

### Rate Limiting
```python
# Add to main.py to prevent abuse
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/lookup/{grading_company}/{cert_number}")
@limiter.limit("10/minute")
async def lookup_card(...):
    ...
```

### Caching
```python
# Cache responses to avoid re-scraping same cert repeatedly
import redis
from functools import wraps

# Cache cert lookups for 1 hour
# Cache price data for 30 minutes
```

---

## Legal Note

Web scraping should be done responsibly:
- Respect robots.txt
- Add delays between requests  
- Don't overload servers
- Consider official APIs where available
- Review each site's Terms of Service for commercial use
