#!/usr/bin/env python3
"""
serve.py — stdlib HTTP server for the Skills & Prompts Explorer.

Browsers block fetch() on file:// URLs, so the Explorer must be served over HTTP.
This serves the REPOSITORY ROOT (so the app can fetch source files via relative
paths back to the root) and opens /docs/explorer/ in your browser.

Usage:
    python3 docs/explorer/serve.py            # serve on :8848, open the explorer
    python3 docs/explorer/serve.py 9000       # custom port
    python3 docs/explorer/serve.py --no-open  # don't launch a browser
"""

import http.server
import os
import socketserver
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def end_headers(self):
        # Explorer fetches with {cache:'no-cache'} — make that effective.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main():
    port = 8848
    open_browser = True
    for arg in sys.argv[1:]:
        if arg == "--no-open":
            open_browser = False
        elif arg.isdigit():
            port = int(arg)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}/docs/explorer/"
        print(f"Serving repo root {REPO_ROOT}")
        print(f"Explorer:  {url}")
        print("Ctrl-C to stop.")
        if open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
