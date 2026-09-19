"""Read-only observation of the single Docker demo workload."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from .config import Config


def _get_json(url: str, timeout: float = 3) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def collect_snapshot(config: Config) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"container": config.container, "observed_at": time.time(), "errors": []}
    query_start = int(time.time()) - 120
    try:
        result = subprocess.run(
            ["docker", "inspect", config.container], capture_output=True, text=True,
            timeout=8, check=True,
        )
        obj = json.loads(result.stdout)[0]
        state = obj.get("State") or {}
        started_at = state.get("StartedAt")
        if isinstance(started_at, str) and started_at:
            started_epoch = int(datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp())
            query_start = max(query_start, started_epoch + 1)
        snapshot["docker"] = {
            "name": obj.get("Name", "").lstrip("/"),
            "running": bool(state.get("Running")),
            "oom_killed": bool(state.get("OOMKilled")),
            "restart_count": int(obj.get("RestartCount", 0)),
            "memory_limit_bytes": int((obj.get("HostConfig") or {}).get("Memory") or 0),
            "started_at": started_at,
            "labels": (obj.get("Config") or {}).get("Labels") or {},
        }
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as exc:
        snapshot["errors"].append(f"docker inspect: {type(exc).__name__}: {exc}")

    try:
        with urllib.request.urlopen(config.service_url.rstrip("/") + "/metrics", timeout=3) as response:
            metrics = response.read(100_000).decode("utf-8")
        snapshot["metrics"] = metrics
    except (OSError, ValueError) as exc:
        snapshot["errors"].append(f"service metrics: {type(exc).__name__}: {exc}")

    try:
        query = urllib.parse.quote("recommendation_seen_products[120s]", safe="")
        end = int(time.time())
        url = config.prometheus_url.rstrip("/") + "/api/v1/query?query=" + query + f"&time={end}"
        payload = _get_json(url)
        series = (payload.get("data") or {}).get("result") or []
        values = [
            float(pair[1]) for pair in series[0].get("values", [])
            if float(pair[0]) >= query_start
        ] if series else []
        snapshot["seen_products_samples"] = values
    except (OSError, ValueError, TypeError, IndexError, KeyError) as exc:
        snapshot["errors"].append(f"prometheus: {type(exc).__name__}: {exc}")
    return snapshot
