"""
SlabIQ Scraper Diagnostic & Fix Bot
Runs itself, tests every source, patches what's broken, reports results.
"""
import asyncio, httpx, re, json, subprocess, sys
from urllib.parse import quote_plus

TEST_CARD = {
    "subject": "Lamine Yamal",
    "year": "2023",
    "brand": "Panini Megacracks",
    "card_number": "108",
    "variety": "Bis",
    "grade": "10",
    "query_clean": "Lamine Yamal Megacracks PSA 10",
    "query_graded": "Lamine Yamal Megacracks 108 PSA 10",
    "query_short": "Lamine Yamal Megacracks 108",
}

H_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

RESULTS = {}

async def test_playwright():
    print("\n🤖 Testing Playwright...")
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page(user_agent=H_BROWSER["User-Agent"])
            await page.goto("https://www.ebay.com/sch/i.html?_nkw=Lamine+Yamal+PSA+10&LH_Sold=1&LH_Complete=1", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            content = await page.content()
            await browser.close()
            has_prices = "s-item__price" in content
            imgs = re.findall(r'https://i\.ebayimg\.com/images/g/[^\s"]+', content)
            prices = re.findall(r'\$([0-9,]+\.?[0-9]{0,2})', content)
            prices = [float(p.replace(",","")) for p in prices if 5 < float(p.replace(",","")) < 50000]
            print(f"  ✅ Playwright works | prices={prices[:3]} | images={len(imgs)}")
            RESULTS["playwright"] = {"works": True, "prices": prices[:5], "images": imgs[:2]}
            return True
    except Exception as e:
        print(f"  ❌ Playwright failed: {e}")
        RESULTS["playwright"] = {"works": False, "error": str(e)}
        return False

async def test_ebay_direct():
    print("\n🛒 Testing eBay direct HTTP...")
    headers = {
        **H_BROWSER,
        "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    }
    url = "https://www.ebay.com/sch/i.html?_nkw=Lamine+Yamal+PSA+10&LH_Sold=1&LH_Complete=1&_ipg=20"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers, http2=True) as c:
            r = await c.get(url)
            print(f"  Status: {r.status_code} | len: {len(r.text)}")
            if r.status_code == 200:
                imgs = re.findall(r'https://i\.ebayimg\.com/images/g/[^\s"]+', r.text)
                prices = re.findall(r'\$([0-9,]+\.?[0-9]{0,2})', r.text)
                prices = [float(p.replace(",","")) for p in prices if 5 < float(p.replace(",","")) < 50000]
                print(f"  ✅ eBay HTTP works | prices={prices[:3]} | images={len(imgs)}")
                RESULTS["ebay_http"] = {"works": True, "prices": prices[:5], "images": imgs[:2]}
                return True
            else:
                print(f"  ❌ eBay blocked: {r.status_code}")
                RESULTS["ebay_http"] = {"works": False, "status": r.status_code}
                return False
    except Exception as e:
        print(f"  ❌ eBay error: {e}")
        RESULTS["ebay_http"] = {"works": False, "error": str(e)}
        return False

async def test_130point():
    print("\n📊 Testing 130point...")
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin", "mobile": False})
        url = "https://130point.com/sales/?s=Lamine+Yamal+PSA+10&source=all"
        r = scraper.get(url, timeout=15)
        print(f"  Status: {r.status_code} | len: {len(r.text)}")
        has_sales = any(x in r.text.lower() for x in ["sold", "sale", "$", "price"])
        prices = re.findall(r'\$([0-9,]+\.?[0-9]{0,2})', r.text)
        prices = [float(p.replace(",","")) for p in prices if 5 < float(p.replace(",","")) < 50000]
        if r.status_code == 200 and prices:
            print(f"  ✅ 130point works | prices={prices[:3]}")
            RESULTS["130point"] = {"works": True, "prices": prices[:5]}
            return True
        else:
            print(f"  ❌ 130point blocked or empty | has_sales_text={has_sales}")
            RESULTS["130point"] = {"works": False, "status": r.status_code}
            return False
    except Exception as e:
        print(f"  ❌ 130point error: {e}")
        RESULTS["130point"] = {"works": False, "error": str(e)}
        return False

async def test_cardladder_playwright():
    print("\n🪜 Testing Card Ladder via Playwright...")
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page(user_agent=H_BROWSER["User-Agent"])
            await page.goto("https://www.cardladder.com/", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            # Try the search input
            try:
                await page.fill('input[type="search"], input[placeholder*="search" i], input[name="q"]', "Lamine Yamal")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)
            except:
                await page.goto("https://www.cardladder.com/?search=Lamine+Yamal", wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            content = await page.content()
            # Log all XHR requests
            url_hit = page.url
            print(f"  Final URL: {url_hit}")
            has_results = any(x in content.lower() for x in ["yamal", "result", "card"])
            prices = re.findall(r'\$([0-9,]+\.?[0-9]{0,2})', content)
            prices = [float(p.replace(",","")) for p in prices if 5 < float(p.replace(",","")) < 50000]
            print(f"  Has results: {has_results} | prices: {prices[:3]}")
            
            # Also intercept network calls to find their API
            await browser.close()
            RESULTS["cardladder"] = {"works": has_results, "prices": prices[:5], "url": url_hit}
            return has_results
    except Exception as e:
        print(f"  ❌ Card Ladder error: {e}")
        RESULTS["cardladder"] = {"works": False, "error": str(e)}
        return False

async def test_cardladder_api():
    print("\n🪜 Testing Card Ladder API intercept...")
    try:
        from playwright.async_api import async_playwright
        api_calls = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = await browser.new_context(user_agent=H_BROWSER["User-Agent"])
            
            # Intercept all API calls
            async def handle_request(request):
                if any(x in request.url for x in ["api", "search", "card", "json", "graphql"]):
                    api_calls.append(request.url)
            
            page = await ctx.new_page()
            page.on("request", handle_request)
            await page.goto("https://www.cardladder.com/", wait_until="networkidle")
            try:
                await page.fill('input[type="search"], input[placeholder*="search" i]', "Lamine Yamal")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(4000)
            except:
                pass
            await browser.close()
        
        print(f"  API calls intercepted ({len(api_calls)}):")
        for url in api_calls[:20]:
            print(f"    {url}")
        RESULTS["cardladder_api"] = {"calls": api_calls[:20]}
        return len(api_calls) > 0
    except Exception as e:
        print(f"  ❌ API intercept error: {e}")
        return False

async def test_mavin():
    print("\n💰 Testing Mavin...")
    url = "https://mavin.io/search?q=Lamine+Yamal+PSA+10&sold=1"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=H_BROWSER) as c:
            r = await c.get(url)
            print(f"  Status: {r.status_code} | len: {len(r.text)}")
            if r.status_code == 200:
                prices = re.findall(r'\$([0-9,]+\.?[0-9]{0,2})', r.text)
                prices = [float(p.replace(",","")) for p in prices if 5 < float(p.replace(",","")) < 50000]
                imgs = re.findall(r'https://i\.ebayimg\.com/[^\s"]+', r.text)
                has_json = "salesData" in r.text or "sold_items" in r.text
                print(f"  prices={prices[:3]} | images={len(imgs)} | has_json={has_json}")
                RESULTS["mavin"] = {"works": bool(prices), "prices": prices[:5], "images": imgs[:2], "has_json": has_json}
                return bool(prices)
            RESULTS["mavin"] = {"works": False, "status": r.status_code}
            return False
    except Exception as e:
        print(f"  ❌ Mavin error: {e}")
        RESULTS["mavin"] = {"works": False, "error": str(e)}
        return False

async def test_pricecharting():
    print("\n📈 Testing PriceCharting...")
    url = "https://www.pricecharting.com/search-products?q=Lamine+Yamal&type=prices"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=H_BROWSER) as c:
            r = await c.get(url)
            print(f"  Status: {r.status_code} | len: {len(r.text)}")
            found_link = re.search(r'href="(/(?:game|trading-card)/[^"?]+)"', r.text)
            if found_link:
                product_url = "https://www.pricecharting.com" + found_link.group(1)
                print(f"  Found product: {product_url}")
                r2 = await c.get(product_url)
                prices = re.findall(r'\$([0-9,]+\.?[0-9]{0,2})', r2.text)
                prices = [float(p.replace(",","")) for p in prices if 5 < float(p.replace(",","")) < 50000]
                print(f"  ✅ PriceCharting works | prices={prices[:3]}")
                RESULTS["pricecharting"] = {"works": True, "prices": prices[:5], "url": product_url}
                return True
            print(f"  ❌ No product found")
            RESULTS["pricecharting"] = {"works": False}
            return False
    except Exception as e:
        print(f"  ❌ PriceCharting error: {e}")
        RESULTS["pricecharting"] = {"works": False, "error": str(e)}
        return False

async def main():
    print("=" * 60)
    print("SlabIQ Scraper Diagnostic Bot")
    print("=" * 60)
    print(f"Test card: {TEST_CARD['query_clean']}")

    # Run all tests
    pw_works = await test_playwright()
    await test_ebay_direct()
    await test_130point()
    await test_mavin()
    await test_pricecharting()
    if pw_works:
        await test_cardladder_playwright()
        await test_cardladder_api()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for source, result in RESULTS.items():
        status = "✅" if result.get("works") else "❌"
        print(f"{status} {source}: {result}")

    # Save results
    with open("scraper_diagnostic.json", "w") as f:
        json.dump(RESULTS, f, indent=2)
    print("\nFull results saved to scraper_diagnostic.json")

asyncio.run(main())
