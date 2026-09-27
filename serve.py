#!/usr/bin/env python3
import http.server
import socketserver
import subprocess
import threading
import time
import re
import os
import shutil

PORT = 8999
# Serve only the public/ subdirectory — never the project root (exposes .py source and data/ JSON)
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

def start_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Local server running on port {PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    # Warn if public/ is empty or missing index.html — build must run first
    import sys
    if not os.path.isfile(os.path.join(DIRECTORY, "index.html")):
        print("WARNING: public/ is empty. Run build_calendar.py first to populate it.", file=sys.stderr)

    # Start local HTTP server in background thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(1)

    # Launch cloudflared quick tunnel
    # Find cloudflared binary
    cloudflared_bin = shutil.which("cloudflared") or ("/tmp/cloudflared" if os.path.exists("/tmp/cloudflared") else None)
    if not cloudflared_bin:
        print(f"NOTICE: cloudflared not found. Server running in local-only mode at http://localhost:{PORT}")
        print("   (To enable public sharing via Cloudflare tunnel, install cloudflared.)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping local server.")
            raise SystemExit(0)
    cmd = [cloudflared_bin, "tunnel", "--url", f"http://localhost:{PORT}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    tunnel_url = None
    for line in iter(proc.stdout.readline, ''):
        print(line, end='', flush=True)
        m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
        if m and not tunnel_url:
            tunnel_url = m.group(0)
            url_file = os.path.join(DIRECTORY, "public_url.txt")
            with open(url_file, "w") as f:
                f.write(tunnel_url + "\n")
            print(f"\n============================================\nPUBLIC URL READY: {tunnel_url}\n============================================\n", flush=True)
            print("🟢 Server & Cloudflare Tunnel are actively running in the foreground.", flush=True)
            print("   (This process intentionally stays open to keep your site online. Press Ctrl+C to stop.)\n", flush=True)

    proc.wait()
