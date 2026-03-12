"""
Collectors Image Resolver
-------------------------
Fetches PSA card images (front + back) via the Collectors app tRPC API.

Two modes:
  1. COLLECTORS_COOKIES env var (httpx, no Playwright) — for production/Render
  2. Playwright login fallback (PSA_EMAIL + PSA_PASSWORD) — for local dev

Cookie refresh: Run locally with PSA_EMAIL/PSA_PASSWORD set, then copy the
printed COLLECTORS_COOKIES value to your Render environment variables.
"""

import os
import json
import asyncio
import httpx

TRPC_URL = "https://app.collectors.com/collection/api/trpc/search.getCertDetails"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Cached Playwright page (local dev only)
_pw_page = None
_pw_lock = asyncio.Lock()


def _get_cookie_header() -> str:
    """Build Cookie header from COLLECTORS_COOKIES env var."""
    raw = os.getenv("COLLECTORS_COOKIES", "")
    if not raw:
        return ""
    try:
        cookies = json.loads(raw)
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    except (json.JSONDecodeError, KeyError, TypeError):
        return ""


async def fetch_cert_images_httpx(cert: str) -> dict:
    """Fetch card images using stored cookies via httpx (no Playwright)."""
    cookie_header = _get_cookie_header()
    if not cookie_header:
        return {}

    hex_input = json.dumps({"certNumber": cert}).encode().hex()
    url = f'{TRPC_URL}?batch=1&input={{"0":"{hex_input}"}}'
    headers = {
        "User-Agent": BROWSER_UA,
        "Cookie": cookie_header,
        "Referer": "https://app.collectors.com/collection",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                print(f"[collectors/httpx] Status {resp.status_code} for cert {cert}")
                return {}
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                info = data[0].get("result", {}).get("data", {}).get("json", {})
                front = info.get("frontImageUrl", "")
                back = info.get("backImageUrl", "")
                if front:
                    front = front.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
                if back:
                    back = back.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
                return {"front": front, "back": back}
    except Exception as e:
        print(f"[collectors/httpx] Error for cert {cert}: {e}")
    return {}


async def _get_pw_page():
    """Login to Collectors via Playwright (local dev fallback)."""
    global _pw_page
    if _pw_page is not None:
        try:
            await _pw_page.evaluate("1+1")
            return _pw_page
        except Exception:
            _pw_page = None

    email = os.getenv("PSA_EMAIL", "")
    password = os.getenv("PSA_PASSWORD", "")
    if not email or not password:
        return None

    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = await browser.new_context(
            user_agent=BROWSER_UA, viewport={"width": 1440, "height": 900}
        )
        page = await ctx.new_page()

        await page.goto("https://app.collectors.com/signin", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        try:
            await page.locator(".osano-cm-dialog__close").click(timeout=3000)
            await page.wait_for_timeout(500)
        except Exception:
            pass

        await page.locator('input[type="email"], input[name="email"]').first.fill(email)
        await page.wait_for_timeout(500)
        await page.locator('button:has-text("Continue")').first.click(timeout=10000)
        await page.wait_for_timeout(3000)
        await page.locator('input[type="password"]').first.fill(password)
        await page.wait_for_timeout(500)
        await page.evaluate(
            "document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='Verify') b.click() })"
        )
        await page.wait_for_timeout(8000)

        if "collection" in page.url:
            print(f"[collectors/pw] Logged in: {page.url}")
            _pw_page = page

            # Print cookies so user can copy to COLLECTORS_COOKIES env var
            cookies = await ctx.cookies()
            essential_names = [
                "accessToken", "refreshToken", "idToken",
                "sessionId", "sessionCookie", "env", "cf_clearance",
            ]
            essential = [
                {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")}
                for c in cookies
                if c["name"] in essential_names and any(d in c.get("domain", "") for d in ["collectors.com"])
            ]
            print(f"[collectors/pw] Copy this to COLLECTORS_COOKIES env var on Render:")
            print(json.dumps(essential))
            return page
        else:
            print(f"[collectors/pw] Login failed, URL: {page.url}")
            await browser.close()
            return None
    except Exception as e:
        print(f"[collectors/pw] Login error: {e}")
        return None


async def fetch_cert_images_playwright(cert: str) -> dict:
    """Fetch card images via Playwright session (local dev fallback)."""
    async with _pw_lock:
        page = await _get_pw_page()
    if not page:
        return {}

    try:
        hex_input = json.dumps({"certNumber": cert}).encode().hex()
        result = await page.evaluate(f"""async () => {{
            try {{
                const resp = await fetch(
                    '/collection/api/trpc/search.getCertDetails?batch=1&input={{"0":"{hex_input}"}}',
                    {{credentials: 'include'}}
                );
                if (!resp.ok) return null;
                return await resp.json();
            }} catch(e) {{ return null; }}
        }}""")

        if result and isinstance(result, list) and len(result) > 0:
            info = result[0].get("result", {}).get("data", {}).get("json", {})
            front = info.get("frontImageUrl", "")
            back = info.get("backImageUrl", "")
            if front:
                front = front.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
            if back:
                back = back.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
            return {"front": front, "back": back}
    except Exception as e:
        print(f"[collectors/pw] API error for cert {cert}: {e}")
        global _pw_page
        _pw_page = None
    return {}


async def fetch_cert_images(cert: str) -> dict:
    """Get PSA card images. Tries httpx with stored cookies first, falls back to Playwright.
    Returns {"front": url, "back": url} or empty dict."""
    # 1. Try httpx with env var cookies (production/Render)
    result = await fetch_cert_images_httpx(cert)
    if result.get("front"):
        print(f"[collectors] httpx OK for cert {cert}")
        return result

    # 2. Fall back to Playwright login (local dev)
    result = await fetch_cert_images_playwright(cert)
    if result.get("front"):
        print(f"[collectors] Playwright OK for cert {cert}")
        return result

    return {"front": "", "back": ""}
