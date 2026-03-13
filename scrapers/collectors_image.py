"""
Collectors Image Resolver
-------------------------
Fetches PSA card images (front + back) via the Collectors app tRPC API.
Uses COLLECTORS_COOKIES env var with httpx — no Playwright, no Chromium.

Auto-refreshes expired access tokens using the OAuth refresh token.
If refresh fails, falls back to Playwright login (local dev only).
"""

import os
import json
import asyncio
import time
import httpx

TRPC_URL = "https://app.collectors.com/collection/api/trpc/search.getCertDetails"
TOKEN_URL = "https://login.collectors.com/oauth2/default/v1/token"
CLIENT_ID = "0oa1gegcbllaryzA1697"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# In-memory cookie state (loaded from env on first use, refreshed as needed)
_cookies = None
_lock = asyncio.Lock()


def _load_cookies() -> list:
    """Load cookies from COLLECTORS_COOKIES env var."""
    raw = os.getenv("COLLECTORS_COOKIES", "")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _get_cookie_value(cookies: list, name: str) -> str:
    """Get a specific cookie value by name."""
    for c in cookies:
        if c.get("name") == name:
            return c.get("value", "")
    return ""


def _set_cookie_value(cookies: list, name: str, value: str, domain: str = "app.collectors.com"):
    """Update or add a cookie in the list."""
    for c in cookies:
        if c.get("name") == name:
            c["value"] = value
            return
    cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})


def _build_cookie_header(cookies: list) -> str:
    """Build Cookie header string from cookie list."""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def _is_token_expired(cookies: list) -> bool:
    """Check if the access token is expired or about to expire (5 min buffer)."""
    token = _get_cookie_value(cookies, "accessToken")
    if not token:
        return True
    try:
        import base64
        parts = token.split(".")
        if len(parts) < 2:
            return True
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        exp = payload.get("exp", 0)
        return time.time() > (exp - 300)  # 5 minute buffer
    except Exception:
        return True


async def _refresh_token(cookies: list) -> bool:
    """Use OAuth refresh token to get a new access token. Returns True on success."""
    refresh_token = _get_cookie_value(cookies, "refreshToken")
    if not refresh_token:
        print("[collectors] No refresh token available")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "scope": "customer offline_access openid",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                data = resp.json()
                new_access = data.get("access_token", "")
                new_refresh = data.get("refresh_token", refresh_token)
                new_id = data.get("id_token", "")
                if new_access:
                    _set_cookie_value(cookies, "accessToken", new_access)
                    _set_cookie_value(cookies, "refreshToken", new_refresh)
                    if new_id:
                        _set_cookie_value(cookies, "idToken", new_id)
                    print(f"[collectors] Token refreshed, expires in {data.get('expires_in', '?')}s")
                    return True
            print(f"[collectors] Token refresh failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[collectors] Token refresh error: {e}")
    return False


async def _get_cookies() -> list:
    """Get valid cookies, refreshing token if needed."""
    global _cookies
    async with _lock:
        if _cookies is None:
            _cookies = _load_cookies()

        if not _cookies:
            return []

        if _is_token_expired(_cookies):
            print("[collectors] Access token expired, refreshing...")
            refreshed = await _refresh_token(_cookies)
            if not refreshed:
                # Try Playwright login as last resort (local dev only)
                new_cookies = await _playwright_login()
                if new_cookies:
                    _cookies = new_cookies
                else:
                    return []

        return _cookies


async def _playwright_login() -> list:
    """Login via Playwright and return cookies. Only works locally with Chromium installed."""
    email = os.getenv("PSA_EMAIL", "")
    password = os.getenv("PSA_PASSWORD", "")
    if not email or not password:
        print("[collectors] No PSA_EMAIL/PSA_PASSWORD for Playwright fallback")
        return []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[collectors] Playwright not installed (expected on Render)")
        return []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = await browser.new_context(user_agent=BROWSER_UA, viewport={"width": 1440, "height": 900})
            page = await ctx.new_page()

            await page.goto("https://app.collectors.com/signin", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            try:
                await page.locator(".osano-cm-dialog__close").click(timeout=3000)
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

            if "collection" not in page.url:
                print(f"[collectors/pw] Login failed: {page.url}")
                await browser.close()
                return []

            cookies = await ctx.cookies()
            essential_names = ["accessToken", "refreshToken", "idToken", "sessionId", "sessionCookie", "env", "cf_clearance"]
            essential = [
                {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")}
                for c in cookies
                if c["name"] in essential_names and "collectors.com" in c.get("domain", "")
            ]
            print(f"[collectors/pw] Logged in. Update COLLECTORS_COOKIES on Render with:")
            print(json.dumps(essential))
            await browser.close()
            return essential
    except Exception as e:
        print(f"[collectors/pw] Error: {e}")
        return []


def _parse_trpc_response(data) -> dict:
    """Extract front/back image URLs from tRPC response."""
    if data and isinstance(data, list) and len(data) > 0:
        info = data[0].get("result", {}).get("data", {}).get("json", {})
        front = info.get("frontImageUrl", "")
        back = info.get("backImageUrl", "")
        if front:
            front = front.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
        if back:
            back = back.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
        return {"front": front, "back": back}
    return {}


async def fetch_cert_images(cert: str) -> dict:
    """Get PSA card images via Collectors tRPC API (httpx, no Playwright).
    Auto-refreshes expired tokens. Returns {"front": url, "back": url}."""
    cookies = await _get_cookies()
    if not cookies:
        return {"front": "", "back": ""}

    hex_input = json.dumps({"certNumber": cert}).encode().hex()
    url = f'{TRPC_URL}?batch=1&input={{"0":"{hex_input}"}}'
    headers = {
        "User-Agent": BROWSER_UA,
        "Cookie": _build_cookie_header(cookies),
        "Referer": "https://app.collectors.com/collection",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                result = _parse_trpc_response(resp.json())
                if result.get("front"):
                    return result

            # If 401/403, try refreshing token once
            if resp.status_code in (401, 403):
                print(f"[collectors] Got {resp.status_code}, attempting token refresh...")
                async with _lock:
                    if await _refresh_token(cookies):
                        headers["Cookie"] = _build_cookie_header(cookies)
                resp2 = await client.get(url, headers=headers)
                if resp2.status_code == 200:
                    return _parse_trpc_response(resp2.json())

            print(f"[collectors] Status {resp.status_code} for cert {cert}")
    except Exception as e:
        print(f"[collectors] Error for cert {cert}: {e}")

    return {"front": "", "back": ""}
