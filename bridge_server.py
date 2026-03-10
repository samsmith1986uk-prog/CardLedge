#!/usr/bin/env python3
"""
SlabIQ Bridge Server
Runs on your Mac, exposes a secure endpoint.
Claude sends commands to it, reads results, iterates.

Usage: python3 bridge_server.py
"""
import subprocess, json, os, hashlib, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# Simple shared secret so only Claude can send commands
SECRET = hashlib.sha256(b"slabiq-bridge-2026").hexdigest()[:16]
PORT = 9999

class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == "/ping":
            self._respond(200, {"status": "online", "secret_hint": SECRET[:4] + "..."})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            self._respond(404, {"error": "not found"})
            return

        # Auth check
        auth = self.headers.get("X-Secret", "")
        if auth != SECRET:
            self._respond(403, {"error": "forbidden"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        command = body.get("command", "")
        timeout = body.get("timeout", 30)
        cwd = body.get("cwd", os.path.expanduser("~/Downloads/cardledge-backend"))

        print(f"\n▶ {command[:100]}")

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, timeout=timeout,
                executable="/bin/zsh", cwd=cwd
            )
            output = result.stdout
            if result.stderr:
                output += "\nSTDERR: " + result.stderr
            if result.returncode != 0:
                output += f"\nEXIT: {result.returncode}"
            print(f"✓ {output[:80].strip()}")
            self._respond(200, {"output": output.strip(), "exit_code": result.returncode})
        except subprocess.TimeoutExpired:
            self._respond(200, {"output": f"TIMEOUT after {timeout}s", "exit_code": -1})
        except Exception as e:
            self._respond(500, {"output": str(e), "exit_code": -1})

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

def main():
    print("=" * 50)
    print("  SlabIQ Bridge Server")
    print(f"  Port: {PORT}")
    print(f"  Secret: {SECRET}")
    print("=" * 50)
    print("\nStarting ngrok tunnel...")

    # Start ngrok in background
    ngrok = subprocess.Popen(
        ["ngrok", "http", str(PORT), "--log=stdout"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    import time, urllib.request
    time.sleep(2)

    # Get public URL from ngrok API
    try:
        resp = urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=5)
        tunnels = json.loads(resp.read())
        public_url = tunnels["tunnels"][0]["public_url"]
        print(f"\n✅ Public URL: {public_url}")
        print(f"✅ Secret: {SECRET}")
        print(f"\n📋 Give Claude this info:")
        print(f"   URL: {public_url}")
        print(f"   SECRET: {SECRET}")
        print("\nBridge is live. Talk to Claude in the other window.\n")
    except Exception as e:
        print(f"⚠️  ngrok tunnel info unavailable: {e}")
        print(f"Install ngrok: brew install ngrok")
        print(f"Server still running on localhost:{PORT}")
        print(f"Secret: {SECRET}\n")

    server = HTTPServer(("0.0.0.0", PORT), BridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBridge stopped.")
        ngrok.terminate()

if __name__ == "__main__":
    main()
