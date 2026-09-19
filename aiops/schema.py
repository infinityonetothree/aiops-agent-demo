from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

KINDS = frozenset({"dependency", "resource", "deploy_regression", "config", "unknown"})
REMEDIATIONS = frozenset({"online_op", "code_fix", "info_only"})
ACTIONS = frozenset({"restart_instance", "none"})


@dataclass
class Diagnosis:
    kind: str
    suspect_service: str
    remediation_type: str
    confidence: float
    summary: str
    evidence: list[str]
    also_code_fix: bool = False
    proposed_action: str = "none"

    @classmethod
    def parse(cls, value: dict[str, Any]) -> Diagnosis:
        result = cls(**{key: value[key] for key in cls.__dataclass_fields__ if key in value})
        if result.kind not in KINDS:
            raise ValueError("invalid kind")
        if result.remediation_type not in REMEDIATIONS:
            raise ValueError("invalid remediation_type")
        if result.proposed_action not in ACTIONS:
            raise ValueError("invalid proposed_action")
        if not isinstance(result.confidence, (int, float)) or not 0 <= result.confidence <= 1:
            raise ValueError("confidence must be 0..1")
        if not isinstance(result.suspect_service, str) or not result.suspect_service:
            raise ValueError("suspect_service required")
        if not isinstance(result.summary, str) or not result.summary:
            raise ValueError("summary required")
        if not isinstance(result.evidence, list) or not result.evidence or not all(
            isinstance(x, str) and x for x in result.evidence
        ):
            raise ValueError("nonempty evidence required")
        if not isinstance(result.also_code_fix, bool):
            raise ValueError("also_code_fix must be boolean")
        if result.proposed_action == "restart_instance" and result.remediation_type != "online_op":
            raise ValueError("restart_instance requires remediation_type=online_op")
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    alert: dict[str, Any]
    diagnosis: Diagnosis
    route: str
    snapshot: dict[str, Any]
    executed_actions: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    agent_run: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DIAGNOSIS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": sorted(KINDS)},
        "suspect_service": {"type": "string"},
        "remediation_type": {"type": "string", "enum": sorted(REMEDIATIONS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "also_code_fix": {"type": "boolean"},
        "proposed_action": {"type": "string", "enum": sorted(ACTIONS)},
    },
    "required": [
        "kind", "suspect_service", "remediation_type", "confidence", "summary",
        "evidence", "also_code_fix", "proposed_action",
    ],
}
