"""Deliberately leaky fixture for an isolated Docker AIOps demo."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_seen_product_ids: list[str] = []
_lock = threading.Lock()
_requests = 0
_started = time.time()


def get_recommendations(product_ids: list[str], max_results: int = 5) -> list[str]:
    """The append is the planted bug; a later PR should make storage bounded."""
    global _requests
    with _lock:
        _seen_product_ids.extend(product_ids)
        del _seen_product_ids[:-500]
        _requests += 1
    catalog = [f"PRODUCT-{i}" for i in range(20)]
    chosen = set(product_ids)
    return [item for item in catalog if item not in chosen][:max_results]


def seen_count() -> int:
    with _lock:
        return len(_seen_product_ids)


def request_count() -> int:
    with _lock:
        return _requests


def _background_load() -> None:
    batch = max(1, int(os.getenv("LEAK_BATCH", "200")))
    interval = max(0.1, float(os.getenv("LEAK_INTERVAL_SECONDS", "1")))
    while True:
        # Unique 1 KiB strings make memory growth visible within a short demo.
        stamp = str(time.time_ns())
        get_recommendations([f"{stamp}-{i}-" + ("X" * 1024) for i in range(batch)])
        time.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path)
        if path.path == "/healthz":
            self._send(200, "ok\n", "text/plain")
        elif path.path == "/metrics":
            body = (
                "# TYPE recommendation_seen_products gauge\n"
                f"recommendation_seen_products {seen_count()}\n"
                "# TYPE recommendation_requests_total counter\n"
                f"recommendation_requests_total {request_count()}\n"
                "# TYPE recommendation_uptime_seconds gauge\n"
                f"recommendation_uptime_seconds {time.time() - _started:.1f}\n"
            )
            self._send(200, body, "text/plain; version=0.0.4")
        elif path.path == "/recommend":
            ids = parse_qs(path.query).get("product_id", ["PRODUCT-1"])
            self._send(200, json.dumps({"products": get_recommendations(ids)}), "application/json")
        else:
            self._send(404, "not found\n", "text/plain")

    def log_message(self, format: str, *args: object) -> None:
        print(format % args, flush=True)

    def _send(self, code: int, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    if os.getenv("LEAK_ENABLED", "0") == "1":
        threading.Thread(target=_background_load, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    signal.signal(
        signal.SIGTERM,
        lambda _signum, _frame: threading.Thread(target=server.shutdown, daemon=True).start(),
    )
    server.serve_forever()
    server.server_close()
