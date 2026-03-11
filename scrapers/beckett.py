"""
Beckett BGS/BVG Cert Scraper
-----------------------------
Uses Playwright for reliable JS-rendered page scraping.
Falls back to httpx with multiple endpoint patterns.

Beckett cert verification: https://www.beckett.com/grading/card-lookup
"""

import httpx
import re
import json
import asyncio
from typing import Optional


BECKETT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.beckett.com/",
}


async def scrape_beckett_cert(cert_number: str) -> dict:
    """Fetch BGS cert details from Beckett using multiple methods."""
    cert_clean = cert_number.strip()

    # Method 1: Try Playwright (most reliable for JS-rendered pages)
    result = await _try_playwright_beckett(cert_clean)
    if result and result.get("grade") and result["grade"] != "Unknown":
        return result

    # Method 2: Try httpx with multiple endpoints
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        result = await _try_beckett_endpoints(client, cert_clean)
        if result and result.get("grade") and result["grade"] != "Unknown":
            return result

    # Method 3: Try Beckett grading page with Playwright
    result = await _try_beckett_grading_page(cert_clean)
    if result and result.get("grade") and result["grade"] != "Unknown":
        return result

    return _error_result(cert_clean, "Could not fetch BGS cert data. Beckett may require direct verification.")


async def _try_playwright_beckett(cert_number: str) -> Optional[dict]:
    """Use Playwright to render Beckett cert page and extract data."""
    try:
        from playwright.async_api import async_playwright
        urls = [
            f"https://www.beckett.com/grading/card-lookup/cert-{cert_number}",
            f"https://www.beckett.com/grading/submission/grade/{cert_number}",
        ]

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                user_agent=BECKETT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
            )

            for url in urls:
                try:
                    page = await ctx.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=25000)
                    await asyncio.sleep(2)

                    # Try to extract data via JS evaluation
                    data = await page.evaluate("""() => {
                        const result = {};

                        // Try extracting from React state
                        const stateScript = document.querySelector('script:not([src])');
                        if (stateScript) {
                            const match = stateScript.textContent.match(/__INITIAL_STATE__\\s*=\\s*({.*?});/s);
                            if (match) {
                                try {
                                    const state = JSON.parse(match[1]);
                                    const cert = state?.grading?.certificate?.data || state?.certificate || {};
                                    if (cert.overallGrade || cert.grade) {
                                        result.grade = cert.overallGrade || cert.grade;
                                        result.subject = cert.playerName || cert.subject || '';
                                        result.year = cert.year || '';
                                        result.brand = cert.manufacturer || cert.brand || cert.set || '';
                                        result.card_number = cert.cardNumber || '';
                                        result.centering = cert.centeringGrade || cert.centering || '';
                                        result.corners = cert.cornersGrade || cert.corners || '';
                                        result.edges = cert.edgesGrade || cert.edges || '';
                                        result.surface = cert.surfaceGrade || cert.surface || '';
                                        result.image_url = cert.frontImageUrl || cert.imageUrl || '';
                                        return result;
                                    }
                                } catch(e) {}
                            }
                        }

                        // Try extracting from page content
                        const getText = (sel) => {
                            const el = document.querySelector(sel);
                            return el ? el.textContent.trim() : '';
                        };

                        // Try common Beckett page selectors
                        const gradeSelectors = [
                            '.overall-grade', '.grade-result', '.card-grade',
                            '[class*="grade"]', '[class*="Grade"]',
                            '.cert-grade', '#overallGrade'
                        ];
                        for (const sel of gradeSelectors) {
                            const el = document.querySelector(sel);
                            if (el) {
                                const gradeText = el.textContent.trim();
                                const gradeMatch = gradeText.match(/(\\d+\\.?\\d*)/);
                                if (gradeMatch) {
                                    result.grade = gradeMatch[1];
                                    break;
                                }
                            }
                        }

                        // Get player name
                        const nameSelectors = [
                            '.player-name', '.card-name', '.cert-player',
                            '[class*="player"]', '[class*="Player"]',
                            'h1', 'h2'
                        ];
                        for (const sel of nameSelectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim().length > 2) {
                                result.subject = el.textContent.trim();
                                break;
                            }
                        }

                        // Get card image
                        const imgSelectors = [
                            '.card-image img', '.cert-image img',
                            '[class*="card"] img', 'img[src*="beckett"]',
                            'img[src*="card"]'
                        ];
                        for (const sel of imgSelectors) {
                            const el = document.querySelector(sel);
                            if (el && el.src) {
                                result.image_url = el.src;
                                break;
                            }
                        }

                        // Get subgrades
                        const subgradeLabels = ['centering', 'corners', 'edges', 'surface'];
                        for (const label of subgradeLabels) {
                            const els = document.querySelectorAll(`[class*="${label}" i], td, span, div`);
                            for (const el of els) {
                                if (el.textContent.toLowerCase().includes(label)) {
                                    const next = el.nextElementSibling || el.parentElement?.querySelector('[class*="grade"], [class*="score"]');
                                    if (next) {
                                        const m = next.textContent.match(/(\\d+\\.?\\d*)/);
                                        if (m) result[label] = m[1];
                                    }
                                }
                            }
                        }

                        // Try meta tags as last resort
                        if (!result.subject) {
                            const ogTitle = document.querySelector('meta[property="og:title"]');
                            if (ogTitle) result.subject = ogTitle.content;
                        }
                        if (!result.image_url) {
                            const ogImage = document.querySelector('meta[property="og:image"]');
                            if (ogImage) result.image_url = ogImage.content;
                        }

                        // Get page title for parsing
                        result.page_title = document.title;
                        result.body_text = document.body?.innerText?.substring(0, 3000) || '';

                        return result;
                    }""")

                    await page.close()

                    if data and (data.get("grade") or data.get("subject")):
                        result = _build_bgs_result(data, cert_number)
                        if result.get("grade"):
                            await browser.close()
                            return result

                    # Try parsing from body text
                    if data and data.get("body_text"):
                        result = _parse_from_text(data["body_text"], data.get("page_title", ""), cert_number)
                        if result and result.get("grade"):
                            await browser.close()
                            return result

                except Exception as e:
                    print(f"[beckett/playwright] {url}: {e}")
                    continue

            await browser.close()

    except ImportError:
        print("[beckett] Playwright not installed, skipping browser method")
    except Exception as e:
        print(f"[beckett/playwright] error: {e}")

    return None


async def _try_beckett_endpoints(client: httpx.AsyncClient, cert_number: str) -> Optional[dict]:
    """Try multiple Beckett API/page endpoints via httpx."""
    endpoints = [
        f"https://www.beckett.com/grading/certificate/{cert_number}/json",
        f"https://www.beckett.com/grading/submission/grade/{cert_number}",
        f"https://www.beckett.com/grading/card-lookup/cert-{cert_number}",
        f"https://www.beckett.com/grading/card/{cert_number}",
    ]

    for url in endpoints:
        try:
            resp = await client.get(url, headers=BECKETT_HEADERS)
            if resp.status_code != 200:
                continue

            ct = resp.headers.get("content-type", "")

            # JSON response
            if "application/json" in ct:
                try:
                    data = resp.json()
                    return _parse_beckett_data(data, cert_number)
                except Exception:
                    pass

            # HTML response - parse it
            html = resp.text
            if len(html) < 500:
                continue

            # Try embedded JSON
            json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
            if json_match:
                try:
                    state = json.loads(json_match.group(1))
                    cert_data = (state.get("grading", {})
                                      .get("certificate", {})
                                      .get("data", {}))
                    if cert_data:
                        return _parse_beckett_data(cert_data, cert_number)
                except Exception:
                    pass

            # Try Next.js data
            next_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if next_match:
                try:
                    next_data = json.loads(next_match.group(1))
                    props = next_data.get("props", {}).get("pageProps", {})
                    if props.get("grade") or props.get("overallGrade"):
                        return _parse_beckett_data(props, cert_number)
                except Exception:
                    pass

            # Regex extraction from HTML
            result = _parse_beckett_html(html, cert_number)
            if result and result.get("grade"):
                return result

        except Exception as e:
            print(f"[beckett] {url}: {e}")
            continue

    return None


async def _try_beckett_grading_page(cert_number: str) -> Optional[dict]:
    """Try Beckett grading lookup page with form submission via Playwright."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()
            await page.goto("https://www.beckett.com/grading/card-lookup", timeout=20000)
            await asyncio.sleep(1)

            # Try to find and fill cert input
            input_selectors = [
                'input[name="cert"]', 'input[name="certNumber"]',
                'input[name="serial"]', 'input[type="text"]',
                'input[placeholder*="cert" i]', 'input[placeholder*="number" i]',
            ]

            filled = False
            for sel in input_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(cert_number)
                        filled = True
                        break
                except Exception:
                    continue

            if filled:
                # Try to submit
                submit_selectors = [
                    'button[type="submit"]', 'button:has-text("Search")',
                    'button:has-text("Lookup")', 'button:has-text("Verify")',
                    'input[type="submit"]',
                ]
                for sel in submit_selectors:
                    try:
                        btn = await page.query_selector(sel)
                        if btn:
                            await btn.click()
                            await page.wait_for_load_state("networkidle", timeout=15000)
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        continue

                # Extract data from resulting page
                text = await page.inner_text("body")
                title = await page.title()
                result = _parse_from_text(text[:3000], title, cert_number)
                await browser.close()
                return result

            await browser.close()
    except Exception as e:
        print(f"[beckett/form] {e}")

    return None


def _parse_beckett_data(data: dict, cert_number: str) -> dict:
    """Parse Beckett API response."""
    grade = data.get("grade", data.get("overallGrade", ""))
    subgrades = {
        "centering": str(data.get("centering", data.get("centeringGrade", ""))),
        "corners": str(data.get("corners", data.get("cornersGrade", ""))),
        "edges": str(data.get("edges", data.get("edgesGrade", ""))),
        "surface": str(data.get("surface", data.get("surfaceGrade", ""))),
    }

    is_black_label = all(str(v) == "10" for v in subgrades.values() if v)

    return {
        "cert_number": cert_number,
        "grading_company": "BGS",
        "grade": str(grade),
        "subgrades": subgrades,
        "is_black_label": is_black_label,
        "subject": data.get("playerName", data.get("subject", "")),
        "year": str(data.get("year", "")),
        "brand": data.get("manufacturer", data.get("brand", data.get("set", ""))),
        "series": data.get("set", data.get("series", "")),
        "card_number": str(data.get("cardNumber", data.get("card_number", ""))),
        "variety": data.get("variety", data.get("subset", "")),
        "category": data.get("category", data.get("sport", "Sports")),
        "image_url": data.get("imageUrl", data.get("frontImageUrl", "")),
        "source": "Beckett API",
    }


def _parse_beckett_html(html: str, cert_number: str) -> Optional[dict]:
    """Parse Beckett HTML page for cert data."""
    def extract(pattern, default=""):
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else default

    grade = extract(r'(?:overall|card)[\s-]*grade["\s:]*(?:</[^>]+>)*\s*([\d.]+)')
    if not grade:
        grade = extract(r'class="[^"]*grade[^"]*"[^>]*>.*?([\d.]+)', '')
    if not grade:
        grade = extract(r'>\s*([\d.]+)\s*</.*?(?:grade|score)', '')

    subject = extract(r'(?:player|subject|name)["\s:]*(?:</[^>]+>)?\s*([^<]+)')
    year = extract(r'(\d{4})\s*(?:Topps|Panini|Upper Deck|Bowman|Donruss|Prizm|Select|Fleer|Score)', '')
    if not year:
        year = extract(r'(?:year)["\s:]*(?:</[^>]+>)?\s*(\d{4})')

    brand = extract(r'(?:set|brand|manufacturer)["\s:]*(?:</[^>]+>)?\s*([^<]+)')
    centering = extract(r'[Cc]entering[^<]*?(?:</[^>]+>)*\s*([\d.]+)')
    corners = extract(r'[Cc]orners[^<]*?(?:</[^>]+>)*\s*([\d.]+)')
    edges = extract(r'[Ee]dges[^<]*?(?:</[^>]+>)*\s*([\d.]+)')
    surface = extract(r'[Ss]urface[^<]*?(?:</[^>]+>)*\s*([\d.]+)')
    image = extract(r'<img[^>]*src="(https://[^"]*(?:beckett|bgs)[^"]*\.(jpg|png|webp))"')
    card_number = extract(r'(?:card\s*#|number)["\s:]*(?:</[^>]+>)?\s*#?(\w+)')

    if not grade and not subject:
        # Try meta tags
        og_title = extract(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"')
        if og_title:
            result = _parse_from_title(og_title, cert_number)
            if result:
                return result

    if grade or subject:
        subgrades = {
            "centering": centering,
            "corners": corners,
            "edges": edges,
            "surface": surface,
        }
        return {
            "cert_number": cert_number,
            "grading_company": "BGS",
            "grade": grade,
            "subgrades": subgrades,
            "is_black_label": all(v == "10" for v in subgrades.values() if v),
            "subject": subject,
            "year": year,
            "brand": brand,
            "card_number": card_number,
            "variety": "",
            "category": "Sports",
            "image_url": image,
            "source": "Beckett page scrape",
        }

    return None


def _build_bgs_result(data: dict, cert_number: str) -> dict:
    """Build BGS result from Playwright-extracted data."""
    subgrades = {
        "centering": str(data.get("centering", "")),
        "corners": str(data.get("corners", "")),
        "edges": str(data.get("edges", "")),
        "surface": str(data.get("surface", "")),
    }

    grade = str(data.get("grade", ""))

    # Try to parse from page title if no grade found
    if not grade and data.get("page_title"):
        result = _parse_from_title(data["page_title"], cert_number)
        if result:
            return result

    return {
        "cert_number": cert_number,
        "grading_company": "BGS",
        "grade": grade,
        "subgrades": subgrades,
        "is_black_label": all(v == "10" for v in subgrades.values() if v and v != "None"),
        "subject": data.get("subject", ""),
        "year": data.get("year", ""),
        "brand": data.get("brand", ""),
        "card_number": data.get("card_number", ""),
        "variety": "",
        "category": "Sports",
        "image_url": data.get("image_url", ""),
        "source": "Beckett Playwright",
    }


def _parse_from_title(title: str, cert_number: str) -> Optional[dict]:
    """Parse card info from a title string like '2023 Topps #100 Player BGS 9.5'."""
    patterns = [
        r'(\d{4})\s+(.+?)\s+#(\S+)\s+(.+?)\s+(?:BGS|BVG|BCCG)\s+([\d.]+)',
        r'(.+?)\s+(?:BGS|BVG|BCCG)\s+([\d.]+)',
    ]

    m = re.match(patterns[0], title)
    if m:
        return {
            "cert_number": cert_number,
            "grading_company": "BGS",
            "grade": m.group(5),
            "subgrades": {},
            "is_black_label": False,
            "subject": m.group(4),
            "year": m.group(1),
            "brand": m.group(2),
            "card_number": m.group(3),
            "variety": "",
            "category": "Sports",
            "image_url": "",
            "source": "Beckett title parse",
        }

    m = re.match(patterns[1], title)
    if m:
        return {
            "cert_number": cert_number,
            "grading_company": "BGS",
            "grade": m.group(2),
            "subgrades": {},
            "is_black_label": False,
            "subject": m.group(1),
            "year": "",
            "brand": "",
            "card_number": "",
            "variety": "",
            "category": "Sports",
            "image_url": "",
            "source": "Beckett title parse",
        }

    return None


def _parse_from_text(text: str, title: str, cert_number: str) -> Optional[dict]:
    """Parse card data from page body text."""
    # Try title first
    result = _parse_from_title(title, cert_number)
    if result and result.get("grade"):
        return result

    # Extract from body text
    grade_m = re.search(r'(?:Overall|BGS|Grade)[:\s]*([\d.]+)', text)
    grade = grade_m.group(1) if grade_m else ""

    subject = ""
    # Look for player name patterns
    name_m = re.search(r'(?:Player|Name|Subject)[:\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', text)
    if name_m:
        subject = name_m.group(1)

    year_m = re.search(r'(\d{4})\s*(?:Topps|Panini|Upper|Bowman|Donruss)', text)
    year = year_m.group(1) if year_m else ""

    centering_m = re.search(r'[Cc]entering[:\s]*([\d.]+)', text)
    corners_m = re.search(r'[Cc]orners[:\s]*([\d.]+)', text)
    edges_m = re.search(r'[Ee]dges[:\s]*([\d.]+)', text)
    surface_m = re.search(r'[Ss]urface[:\s]*([\d.]+)', text)

    if grade:
        subgrades = {
            "centering": centering_m.group(1) if centering_m else "",
            "corners": corners_m.group(1) if corners_m else "",
            "edges": edges_m.group(1) if edges_m else "",
            "surface": surface_m.group(1) if surface_m else "",
        }
        return {
            "cert_number": cert_number,
            "grading_company": "BGS",
            "grade": grade,
            "subgrades": subgrades,
            "is_black_label": all(v == "10" for v in subgrades.values() if v),
            "subject": subject,
            "year": year,
            "brand": "",
            "card_number": "",
            "variety": "",
            "category": "Sports",
            "image_url": "",
            "source": "Beckett text parse",
        }

    return None


def _error_result(cert_number: str, error: str) -> dict:
    return {
        "cert_number": cert_number,
        "grading_company": "BGS",
        "error": error,
        "grade": "",
        "subject": "",
        "subgrades": {},
        "source": "Beckett (failed)",
    }
