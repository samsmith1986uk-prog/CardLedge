"""
Collectors Image Resolver
-------------------------
Fetches PSA card images (front + back) via the Collectors app tRPC API.

Authentication: Direct Okta API login (httpx, no browser/Playwright needed).
  1. POST /api/v1/authn → sessionToken
  2. GET /oauth2/default/v1/authorize (PKCE) → auth code
  3. POST /oauth2/default/v1/token → access_token + refresh_token

Auto-refreshes tokens. Works on Render free tier (zero browser deps).
"""

import os
import json
import asyncio
import time
import hashlib
import base64
import secrets
import httpx
from urllib.parse import urlparse, parse_qs

TRPC_URL = "https://app.collectors.com/collection/api/trpc/search.getCertDetails"
AUTHN_URL = "https://login.collectors.com/api/v1/authn"
AUTHORIZE_URL = "https://login.collectors.com/oauth2/default/v1/authorize"
TOKEN_URL = "https://login.collectors.com/oauth2/default/v1/token"
REDIRECT_URI = "https://app.collectors.com/handleloginredirect"
CLIENT_ID = "0oa1gegcbllaryzA1697"
SCOPES = "customer offline_access openid"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Credentials (from env vars)
_EMAIL = os.getenv("PSA_EMAIL", "sam.smith.1986.uk@icloud.com")
_PASSWORD = os.getenv("PSA_PASSWORD", "England123!!!")

# In-memory token state
_access_token = None
_refresh_token = None
_token_expiry = 0
_lock = asyncio.Lock()
_login_attempts = 0


async def _okta_login() -> bool:
    """Login via Okta API (pure httpx, no browser). Returns True on success."""
    global _access_token, _refresh_token, _token_expiry, _login_attempts
    _login_attempts += 1
    print(f"[collectors] Okta login attempt #{_login_attempts}...")

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            # Step 1: Primary authentication
            auth_resp = await client.post(
                AUTHN_URL,
                json={"username": _EMAIL, "password": _PASSWORD},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            if auth_resp.status_code != 200:
                print(f"[collectors] Okta authn failed: {auth_resp.status_code} {auth_resp.text[:200]}")
                return False

            auth_data = auth_resp.json()
            if auth_data.get("status") != "SUCCESS":
                print(f"[collectors] Okta authn status: {auth_data.get('status')}")
                return False

            session_token = auth_data["sessionToken"]
            print(f"[collectors] Got session token")

            # Step 2: PKCE authorize
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).rstrip(b"=").decode()

            authz_resp = await client.get(
                AUTHORIZE_URL,
                params={
                    "client_id": CLIENT_ID,
                    "response_type": "code",
                    "scope": SCOPES,
                    "redirect_uri": REDIRECT_URI,
                    "sessionToken": session_token,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "state": "slabiq",
                    "nonce": secrets.token_urlsafe(32),
                },
            )
            location = authz_resp.headers.get("location", "")
            if "code=" not in location:
                print(f"[collectors] No auth code in redirect: {location[:120]}")
                return False

            code = parse_qs(urlparse(location).query)["code"][0]
            print(f"[collectors] Got auth code")

            # Step 3: Exchange code for tokens
            token_resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                print(f"[collectors] Token exchange failed: {token_resp.status_code} {token_resp.text[:200]}")
                return False

            tokens = token_resp.json()
            _access_token = tokens.get("access_token", "")
            _refresh_token = tokens.get("refresh_token", "")
            expires_in = tokens.get("expires_in", 86400)
            _token_expiry = time.time() + expires_in - 300  # 5 min buffer

            if _access_token:
                print(f"[collectors] Login successful! Token expires in {expires_in}s")
                return True

            print(f"[collectors] No access token in response")
            return False

    except Exception as e:
        print(f"[collectors] Okta login error: {e}")
        return False


async def _refresh_access_token() -> bool:
    """Use refresh token to get new access token. Returns True on success."""
    global _access_token, _refresh_token, _token_expiry

    if not _refresh_token:
        print("[collectors] No refresh token, need full login")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": _refresh_token,
                    "client_id": CLIENT_ID,
                    "scope": SCOPES,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                data = resp.json()
                _access_token = data.get("access_token", _access_token)
                _refresh_token = data.get("refresh_token", _refresh_token)
                expires_in = data.get("expires_in", 86400)
                _token_expiry = time.time() + expires_in - 300
                print(f"[collectors] Token refreshed, expires in {expires_in}s")
                return True
            print(f"[collectors] Refresh failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[collectors] Refresh error: {e}")
    return False


async def _ensure_token() -> str:
    """Ensure we have a valid access token. Login or refresh as needed."""
    global _access_token, _token_expiry

    async with _lock:
        # Token still valid
        if _access_token and time.time() < _token_expiry:
            return _access_token

        # Try refresh first (faster than full login)
        if _refresh_token:
            print("[collectors] Token expired, refreshing...")
            if await _refresh_access_token():
                return _access_token

        # Full login
        print("[collectors] Full login required...")
        for attempt in range(3):
            if await _okta_login():
                return _access_token
            if attempt < 2:
                wait = (attempt + 1) * 5
                print(f"[collectors] Login failed, retrying in {wait}s...")
                await asyncio.sleep(wait)

        print("[collectors] All login attempts failed")
        return ""


def _parse_trpc_response(data, expected_cert: str = "") -> dict:
    """Extract front/back image URLs from tRPC response.
    Validates returned cert matches expected cert to prevent wrong-card images."""
    if data and isinstance(data, list) and len(data) > 0:
        info = data[0].get("result", {}).get("data", {}).get("json", {})
        # Verify cert number matches exactly
        returned_cert = str(info.get("certNumber", ""))
        if expected_cert and returned_cert != expected_cert:
            print(f"[collectors] CERT MISMATCH: asked for {expected_cert}, got {returned_cert} — rejecting")
            return {}
        front = info.get("frontImageUrl") or ""
        back = info.get("backImageUrl") or ""
        if front:
            front = front.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
        if back:
            back = back.replace("/small/", "/medium/").replace("/thumbnail/", "/medium/")
        return {"front": front, "back": back}
    return {}


async def fetch_cert_images(cert: str) -> dict:
    """Get PSA card images via Collectors tRPC API.
    Auto-authenticates via Okta. Returns {"front": url, "back": url}."""
    access_token = await _ensure_token()
    if not access_token:
        return {"front": "", "back": ""}

    hex_input = json.dumps({"certNumber": cert}).encode().hex()
    url = f'{TRPC_URL}?batch=1&input={{"0":"{hex_input}"}}'
    headers = {
        "User-Agent": BROWSER_UA,
        "Cookie": f"accessToken={access_token};env=prod",
        "Referer": "https://app.collectors.com/collection",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                result = _parse_trpc_response(resp.json(), cert)
                if result.get("front"):
                    return result

            # If 401/403, refresh and retry once
            if resp.status_code in (401, 403):
                print(f"[collectors] Got {resp.status_code}, re-authenticating...")
                async with _lock:
                    refreshed = await _refresh_access_token()
                    if not refreshed:
                        await _okta_login()
                new_token = _access_token
                if new_token:
                    headers["Cookie"] = f"accessToken={new_token};env=prod"
                    resp2 = await client.get(url, headers=headers)
                    if resp2.status_code == 200:
                        return _parse_trpc_response(resp2.json())

            print(f"[collectors] Status {resp.status_code} for cert {cert}")
    except Exception as e:
        print(f"[collectors] Error for cert {cert}: {e}")

    return {"front": "", "back": ""}
