from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    container: str = "aiops-recommendation"
    service_url: str = "http://127.0.0.1:8088"
    prometheus_url: str = "http://127.0.0.1:9090"
    docker_project: str = "aiopsagent"
    allowed_targets: frozenset[str] = frozenset({"recommendation"})
    confidence_threshold: float = 0.6
    model: str = "sonnet"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"

    @classmethod
    def from_env(cls) -> Config:
        raw_targets = os.getenv("AIOPS_ALLOWED_TARGETS", "recommendation")
        return cls(
            container=os.getenv("AIOPS_CONTAINER", "aiops-recommendation"),
            service_url=os.getenv("AIOPS_SERVICE_URL", "http://127.0.0.1:8088"),
            prometheus_url=os.getenv("AIOPS_PROMETHEUS_URL", "http://127.0.0.1:9090"),
            docker_project=os.getenv("AIOPS_DOCKER_PROJECT", "aiopsagent"),
            allowed_targets=frozenset(x.strip() for x in raw_targets.split(",") if x.strip()),
            confidence_threshold=float(os.getenv("AIOPS_CONFIDENCE_THRESHOLD", "0.6")),
            model=os.getenv("AIOPS_MODEL", "sonnet"),
            ollama_url=os.getenv("AIOPS_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("AIOPS_OLLAMA_MODEL", "qwen3:4b"),
        )
