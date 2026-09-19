from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from .config import Config
from .diagnose import claude_diagnosis, heuristic_diagnosis, ollama_diagnosis
from .observe import collect_snapshot
from .remediate import restart_demo_target
from .schema import Diagnosis, Report


def _fallback(alert: dict[str, Any], reason: str) -> Diagnosis:
    return Diagnosis(
        kind="unknown", suspect_service=str(alert.get("service") or "unknown"),
        remediation_type="info_only", confidence=0.0,
        summary="diagnosis unavailable", evidence=[reason],
    )


async def run_alert(
    alert: dict[str, Any], config: Config, *, mode: str = "heuristic", apply_low_risk: bool = False,
) -> Report:
    snapshot = collect_snapshot(config)
    note = ""
    agent_run: dict[str, Any] = {}
    try:
        if mode == "heuristic":
            diagnosis = heuristic_diagnosis(alert, snapshot)
        elif mode == "ollama":
            outcome = await ollama_diagnosis(alert, config)
            diagnosis, agent_run = outcome.diagnosis, outcome.run
        elif mode == "claude":
            outcome = await claude_diagnosis(alert, config)
            diagnosis, agent_run = outcome.diagnosis, outcome.run
        else:
            raise ValueError(f"unknown mode {mode}")
    except Exception as exc:
        diagnosis = _fallback(alert, f"{type(exc).__name__}: {exc}")
        note = "diagnosis degraded; review manually"

    actions: list[dict[str, Any]] = []
    if diagnosis.confidence < config.confidence_threshold:
        route = "human_review_low_confidence"
    elif diagnosis.remediation_type == "online_op":
        route = "human_review_online_op"
        if diagnosis.proposed_action == "restart_instance" and apply_low_risk:
            try:
                action = restart_demo_target(diagnosis.suspect_service, config)
                actions.append(action)
                route = "auto_remediated" if action["health_verified"] else "human_review_failed_recovery"
            except (OSError, subprocess.SubprocessError, ValueError, IndexError, PermissionError) as exc:
                note = f"automatic restart rejected or failed: {type(exc).__name__}: {exc}"
        if diagnosis.also_code_fix:
            route += "_code_fix_pending"
    elif diagnosis.remediation_type == "code_fix":
        route = "code_fix_pending"
    else:
        route = "info_only"
    return Report(alert=alert, diagnosis=diagnosis, route=route, snapshot=snapshot,
                  executed_actions=actions, note=note, agent_run=agent_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Docker AIOps demo")
    parser.add_argument("alert", type=Path, help="JSON alert file")
    parser.add_argument("--mode", choices=["heuristic", "ollama", "claude"], default="heuristic")
    parser.add_argument("--apply-low-risk", action="store_true", help="permit an authorized local demo restart")
    parser.add_argument("--report", type=Path, help="write JSON report to this file")
    args = parser.parse_args()
    with args.alert.open("r", encoding="utf-8") as stream:
        alert = json.load(stream)
    if not isinstance(alert, dict):
        parser.error("alert JSON must be an object")
    report = asyncio.run(run_alert(alert, Config.from_env(), mode=args.mode,
                                   apply_low_risk=args.apply_low_risk))
    result = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(result + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
