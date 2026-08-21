#!/usr/bin/env python3
"""
serve.py — stdlib HTTP server for the PRD Reviewer.

Browsers block fetch() on file:// URLs, so the reviewer must be served over HTTP.
This serves the REPOSITORY ROOT (so the app can fetch the PRD docs and the source
they reference via relative paths back to the root) and opens this reviewer's URL.

The reviewer can live at any depth (e.g. docs/JIRA/JIRA-1855/review/), so the repo
root is found by walking up to the nearest .git rather than assuming a fixed depth.

Usage:
    python serve.py            # serve on :8848, open it
    python serve.py 9000       # custom port
    python serve.py --no-open  # don't launch a browser
"""

import http.server
import os
import socketserver
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def find_repo_root(start):
    p = start
    for _ in range(40):
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return os.path.abspath(os.path.join(start, "..", ".."))


REPO_ROOT = find_repo_root(HERE)
# Path of this reviewer relative to the repo root (e.g. "docs/JIRA/JIRA-1855/review").
URL_PATH = "/" + os.path.relpath(HERE, REPO_ROOT).replace(os.sep, "/") + "/"


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
        url = f"http://127.0.0.1:{port}{URL_PATH}"
        print(f"Serving repo root {REPO_ROOT}")
        print(f"PRD Reviewer:  {url}")
        print("Ctrl-C to stop.")
        if open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
