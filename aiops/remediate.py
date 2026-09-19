"""Small, explicit authority for one local Docker demo container."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from typing import Any

from .config import Config


def restart_demo_target(target: str, config: Config) -> dict[str, Any]:
    if target not in config.allowed_targets or target != "recommendation":
        raise PermissionError(f"target {target!r} is not authorized")
    inspected = subprocess.run(
        ["docker", "inspect", config.container], capture_output=True, text=True,
        timeout=8, check=True,
    )
    obj = json.loads(inspected.stdout)[0]
    labels = (obj.get("Config") or {}).get("Labels") or {}
    if labels.get("com.docker.compose.project") != config.docker_project:
        raise PermissionError("container is outside the configured Docker Compose project")
    if labels.get("com.docker.compose.service") != target:
        raise PermissionError("container service label does not match target")
    if obj.get("Name", "").lstrip("/") != config.container:
        raise PermissionError("container name mismatch")

    result = subprocess.run(
        ["docker", "restart", "--time", "10", config.container],
        capture_output=True, text=True, timeout=30, check=True,
    )
    # A successful Docker command alone does not prove that the service recovered.
    healthy = False
    for _ in range(12):
        try:
            with urllib.request.urlopen(config.service_url.rstrip("/") + "/healthz", timeout=2) as response:
                healthy = response.status == 200
            if healthy:
                break
        except OSError:
            pass
        time.sleep(1)
    return {
        "action": "restart_instance", "target": target,
        "command": ["docker", "restart", "--time", "10", config.container],
        "command_succeeded": result.returncode == 0,
        "health_verified": healthy,
        "executed_at": time.time(),
    }

