"""Constrained local code-repair demo with red/green and Docker build gates."""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
import time
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .diagnose import _ollama_chat


REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_file": {"type": "string", "enum": ["recommendation_server.py"]},
        "old_text": {"type": "string", "minLength": 1},
        "new_text": {"type": "string", "minLength": 1},
        "rationale": {"type": "string", "minLength": 1},
    },
    "required": ["target_file", "old_text", "new_text", "rationale"],
}


@dataclass
class RepairPlan:
    target_file: str
    old_text: str
    new_text: str
    rationale: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "RepairPlan":
        if set(value) != set(cls.__dataclass_fields__):
            raise ValueError("repair plan fields do not match the contract")
        plan = cls(**value)
        if plan.target_file != "recommendation_server.py":
            raise ValueError("only recommendation_server.py may be changed")
        if not all(isinstance(item, str) and item for item in asdict(plan).values()):
            raise ValueError("repair plan fields must be nonempty strings")
        return plan


def _run(command: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }


def _docker_runtime_gate(cwd: Path) -> dict[str, Any]:
    name = f"aiops-repair-check-{int(time.time())}"
    started = _run([
        "docker", "run", "-d", "--rm", "--name", name,
        "-e", "LEAK_ENABLED=1", "-e", "LEAK_BATCH=200",
        "-e", "LEAK_INTERVAL_SECONDS=0.1", "aiops-recommendation-repaired:demo",
    ], cwd)
    checks: list[dict[str, Any]] = []
    try:
        if started["exit_code"] != 0:
            return {"exit_code": 1, "start": started, "checks": checks}
        health = None
        for _attempt in range(20):
            check = _run([
                "docker", "exec", name, "python", "-c",
                "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/healthz').read().decode().strip())",
            ], cwd, timeout=10)
            checks.append(check)
            if check["exit_code"] == 0 and check["stdout"].strip() == "ok":
                health = "ok"
                break
            time.sleep(0.25)
        time.sleep(1)
        metrics = _run([
            "docker", "exec", name, "python", "-c",
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/metrics').read().decode())",
        ], cwd, timeout=10)
        match = re.search(r"^recommendation_seen_products (\d+)$", metrics["stdout"], re.MULTILINE)
        seen = int(match.group(1)) if match else None
        passed = health == "ok" and metrics["exit_code"] == 0 and seen is not None and seen <= 500
        return {
            "exit_code": 0 if passed else 1, "health": health,
            "seen_products": seen, "expected_max": 500,
            "start": started, "metrics": metrics, "health_attempts": len(checks),
        }
    finally:
        _run(["docker", "rm", "-f", name], cwd, timeout=30)


def _validate_and_apply(source: str, plan: RepairPlan) -> str:
    append_line = "_seen_product_ids.extend(product_ids)"
    trim_line = "del _seen_product_ids[:-500]"
    if source.count(append_line) != 1:
        raise ValueError("planted append must exist exactly once")
    if plan.old_text.strip() != append_line:
        raise ValueError("repair must target the planted unbounded append")
    if len(plan.old_text) > 500 or len(plan.new_text) > 1000:
        raise ValueError("repair replacement is too broad")
    if "_seen_product_ids" not in plan.new_text:
        raise ValueError("replacement must retain explicit bounded-state handling")
    forbidden = ("subprocess", "os.system", "eval(", "exec(", "__import__", "open(")
    if any(token in plan.new_text for token in forbidden):
        raise ValueError("replacement contains a forbidden capability")
    if "_seen_product_ids =" in plan.new_text:
        raise ValueError("replacement must not rebind the shared list")
    if trim_line not in plan.new_text:
        raise ValueError("replacement must trim the shared list in place")
    proposed_lines = [line.strip() for line in plan.new_text.splitlines() if line.strip()]
    if proposed_lines != [append_line, trim_line]:
        raise ValueError("replacement may contain only the approved append and in-place trim")
    index = source.index(append_line)
    line_start = source.rfind("\n", 0, index) + 1
    indent = source[line_start:index]
    if indent.strip():
        raise ValueError("could not establish source indentation")
    replacement = append_line + "\n" + indent + trim_line
    return source.replace(append_line, replacement, 1)


def _request_repair(source: str, test_source: str, config: Config) -> tuple[RepairPlan, dict[str, Any]]:
    tool = {
        "type": "function",
        "function": {
            "name": "inspect_repair_fixture",
            "description": "Read the only editable source file and its immutable regression test",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a constrained repair agent. Your first response must contain only "
                "inspect_repair_fixture tool call. Do not analyze or propose a repair before its result. "
                "Fix only the planted unbounded _seen_product_ids list growth. Preserve behavior, "
                "use the existing list and lock, add no imports, and propose one small exact text replacement."
            ),
        },
        {"role": "user", "content": "Call inspect_repair_fixture now."},
    ]
    first = _ollama_chat(config, {
        "model": config.ollama_model, "messages": messages, "tools": [tool],
        "stream": False, "think": False, "keep_alive": "5m", "options": {"temperature": 0},
    })
    assistant = first.get("message") or {}
    calls = assistant.get("tool_calls") or []
    if not 1 <= len(calls) <= 3 or any(
        (call.get("function") or {}).get("name") != "inspect_repair_fixture" for call in calls
    ):
        raise RuntimeError(
            "Repair Agent made an invalid read-tool request; response="
            + json.dumps(assistant, ensure_ascii=False)[:2000]
        )
    messages.append(assistant)
    tool_result = json.dumps({
        "editable_file": "recommendation_server.py", "source": source,
        "immutable_test": "test_recommendation.py", "test_source": test_source,
    })
    messages.extend(
        {
            "role": "tool", "tool_name": "inspect_repair_fixture",
            "content": tool_result,
        }
        for _call in calls
    )
    messages.append(
        {
            "role": "user",
            "content": (
                "Return the repair plan. old_text must match exactly and include the existing extend line. "
                "new_text must keep the extend line and add exactly `del _seen_product_ids[:-500]` "
                "on the next line with the same indentation. Do not assign to _seen_product_ids."
            ),
        }
    )
    final = _ollama_chat(config, {
        "model": config.ollama_model, "messages": messages, "format": REPAIR_SCHEMA,
        "stream": False, "think": False, "keep_alive": "5m", "options": {"temperature": 0},
    })
    content = (final.get("message") or {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("Repair Agent returned no structured plan")
    try:
        plan = RepairPlan.parse(json.loads(content))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Repair Agent returned invalid JSON") from exc
    run = {
        "provider": "ollama", "model": config.ollama_model,
        "tool_called": True, "tool_call_count": len(calls),
        "num_turns": 2, "total_cost_usd": 0.0,
        "prompt_tokens": first.get("prompt_eval_count", 0) + final.get("prompt_eval_count", 0),
        "completion_tokens": first.get("eval_count", 0) + final.get("eval_count", 0),
        "total_duration_ms": round(
            (first.get("total_duration", 0) + final.get("total_duration", 0)) / 1_000_000, 1
        ),
    }
    return plan, run


def run_repair(project_root: Path, report_dir: Path, config: Config) -> dict[str, Any]:
    fixture = project_root / "fixtures" / "recommendation"
    workspace = report_dir / "workspace"
    report_dir.mkdir(parents=True, exist_ok=False)
    shutil.copytree(fixture, workspace)
    source_path = workspace / "recommendation_server.py"
    test_path = workspace / "test_recommendation.py"
    original = source_path.read_text(encoding="utf-8")
    test_source = test_path.read_text(encoding="utf-8")

    test_command = [sys.executable, "-m", "unittest", "-v", "test_recommendation"]
    red = _run(test_command, workspace)
    if red["exit_code"] == 0:
        raise RuntimeError("red gate failed: regression test unexpectedly passed before repair")

    plan, agent_run = _request_repair(original, test_source, config)
    repaired = _validate_and_apply(original, plan)
    source_path.write_text(repaired, encoding="utf-8")
    patch = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), repaired.splitlines(keepends=True),
        fromfile="a/recommendation_server.py", tofile="b/recommendation_server.py",
    ))
    (report_dir / "repair.patch").write_text(patch, encoding="utf-8")

    green = _run(test_command, workspace)
    compile_gate = _run([sys.executable, "-m", "compileall", "-q", "."], workspace)
    docker_gate = _run([
        "docker", "build", "--tag", "aiops-recommendation-repaired:demo", ".",
    ], workspace, timeout=300)
    runtime_gate = (
        _docker_runtime_gate(workspace) if docker_gate["exit_code"] == 0
        else {"exit_code": 1, "reason": "docker build failed"}
    )
    gates_passed = all(
        gate["exit_code"] == 0 for gate in (green, compile_gate, docker_gate, runtime_gate)
    )
    report = {
        "status": "passed" if gates_passed else "failed",
        "isolation": {"workspace": str(workspace), "canonical_fixture_modified": False},
        "changed_files": ["recommendation_server.py"],
        "immutable_test": "test_recommendation.py",
        "plan": asdict(plan),
        "agent_run": agent_run,
        "gates": {"red_before_repair": red, "green_after_repair": green,
                  "compile": compile_gate, "docker_build": docker_gate,
                  "docker_runtime": runtime_gate},
        "patch_file": str(report_dir / "repair.patch"),
    }
    (report_dir / "repair.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not gates_passed:
        raise RuntimeError(f"one or more repair gates failed; inspect {report_dir / 'repair.json'}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated local code-repair Agent")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    report_dir = args.report_dir or project_root / "reports" / time.strftime("repair-%Y%m%d-%H%M%S")
    report = run_repair(project_root, report_dir.resolve(), Config.from_env())
    print(json.dumps({
        "status": report["status"], "patch_file": report["patch_file"],
        "tool_called": report["agent_run"]["tool_called"],
        "total_duration_ms": report["agent_run"]["total_duration_ms"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
