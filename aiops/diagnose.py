"""Deterministic offline baseline and an optional Claude Agent SDK route."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Config
from .schema import DIAGNOSIS_JSON_SCHEMA, Diagnosis


@dataclass
class AgentOutcome:
    diagnosis: Diagnosis
    run: dict[str, Any]


def _ollama_chat(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{config.ollama_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Ollama returned a non-object response")
    return result


async def ollama_diagnosis(alert: dict[str, Any], config: Config) -> AgentOutcome:
    """Run one constrained local tool call, then request a schema-bound diagnosis."""
    from .observe import collect_snapshot

    tool = {
        "type": "function",
        "function": {
            "name": "inspect_demo",
            "description": "Read current state, service metrics, and Prometheus trend for this local demo",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
    system = (
        "You diagnose only the local Docker demo. You must call inspect_demo exactly once before "
        "deciding and use only its evidence. Never claim an action was executed."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(alert, ensure_ascii=False)},
    ]
    first = _ollama_chat(config, {
        "model": config.ollama_model, "messages": messages, "tools": [tool],
        "stream": False, "think": False, "keep_alive": "5m",
        "options": {"temperature": 0},
    })
    assistant = first.get("message") or {}
    calls = assistant.get("tool_calls") or []
    if len(calls) != 1 or (calls[0].get("function") or {}).get("name") != "inspect_demo":
        raise RuntimeError("Local Agent did not call the read-only inspect_demo tool exactly once")

    snapshot = collect_snapshot(config)
    if "docker" in snapshot:
        snapshot["docker"].pop("labels", None)
    messages.extend([
        assistant,
        {"role": "tool", "tool_name": "inspect_demo",
         "content": json.dumps(snapshot, ensure_ascii=False)},
    ])
    messages.append({
        "role": "user",
        "content": (
            "Return the final diagnosis matching the required JSON schema. A restart is temporary "
            "containment; sustained growth also requires a code fix. If evidence is insufficient, "
            "use info_only with confidence below 0.6. Set proposed_action=restart_instance only when "
            "remediation_type=online_op; otherwise set proposed_action=none."
        ),
    })
    final = _ollama_chat(config, {
        "model": config.ollama_model, "messages": messages, "format": DIAGNOSIS_JSON_SCHEMA,
        "stream": False, "think": False, "keep_alive": "5m",
        "options": {"temperature": 0},
    })
    content = (final.get("message") or {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("Local Agent returned no structured diagnosis")
    try:
        structured = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Local Agent returned invalid JSON") from exc
    return AgentOutcome(
        Diagnosis.parse(structured),
        {
            "provider": "ollama", "model": config.ollama_model, "tool_called": True,
            "num_turns": 2, "total_cost_usd": 0.0,
            "prompt_tokens": first.get("prompt_eval_count", 0) + final.get("prompt_eval_count", 0),
            "completion_tokens": first.get("eval_count", 0) + final.get("eval_count", 0),
            "total_duration_ms": round(
                (first.get("total_duration", 0) + final.get("total_duration", 0)) / 1_000_000, 1
            ),
        },
    )


def heuristic_diagnosis(alert: dict[str, Any], snapshot: dict[str, Any]) -> Diagnosis:
    samples = snapshot.get("seen_products_samples") or []
    state = snapshot.get("docker") or {}
    growing = len(samples) >= 2 and samples[-1] > samples[0] + 100
    service = str(alert.get("service") or "unknown")
    evidence = [f"alertname={alert.get('alertname', 'unknown')}"]
    if samples:
        evidence.append(f"Prometheus seen_products: first={samples[0]}, last={samples[-1]}, samples={len(samples)}")
    if state:
        evidence.append(f"docker running={state.get('running')}, restart_count={state.get('restart_count')}, oom_killed={state.get('oom_killed')}")
    if growing and service == "recommendation" and state.get("running"):
        return Diagnosis(
            kind="deploy_regression", suspect_service=service, remediation_type="online_op",
            confidence=0.8, summary="recommendation retained-product count keeps rising; restart is temporary containment",
            evidence=evidence, also_code_fix=True, proposed_action="restart_instance",
        )
    return Diagnosis(
        kind="unknown", suspect_service=service, remediation_type="info_only", confidence=0.2,
        summary="insufficient observations to establish sustained growth", evidence=evidence,
    )


async def claude_diagnosis(alert: dict[str, Any], config: Config) -> AgentOutcome:
    """Agent chooses when to inspect the local demo via one read-only MCP tool."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set for this demo")
    try:
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolUseBlock,
            create_sdk_mcp_server, query, tool,
        )
    except ImportError as exc:
        raise RuntimeError("Install the Claude extra: pip install -e '.[claude]'") from exc

    from .observe import collect_snapshot

    @tool("inspect_demo", "Read current Docker state, service metrics and Prometheus trend for the local demo", {})
    async def inspect_demo(_args: dict[str, Any]) -> dict[str, Any]:
        data = collect_snapshot(config)
        # Do not expose unrelated container metadata to the model.
        if "docker" in data:
            data["docker"].pop("labels", None)
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    server = create_sdk_mcp_server(name="aiops_demo", version="0.1.0", tools=[inspect_demo])
    options = ClaudeAgentOptions(
        model=config.model,
        tools=[],
        mcp_servers={"aiops_demo": server},
        strict_mcp_config=True,
        allowed_tools=["mcp__aiops_demo__inspect_demo"],
        disallowed_tools=["Bash", "Write", "Edit"],
        setting_sources=[],
        permission_mode="dontAsk",
        max_turns=5,
        max_budget_usd=0.20,
        output_format={"type": "json_schema", "schema": DIAGNOSIS_JSON_SCHEMA},
        system_prompt=(
            "You are diagnosing only the local Docker demo. Call inspect_demo before deciding. "
            "Use only evidence returned by the tool. A restart is temporary containment; "
            "sustained growth also requires a code fix. If evidence is insufficient, use "
            "info_only and confidence below 0.6. Never claim an action was executed."
        ),
    )
    structured = None
    tool_called = False
    run: dict[str, Any] = {}
    async for message in query(prompt=json.dumps(alert, ensure_ascii=False), options=options):
        if isinstance(message, AssistantMessage):
            tool_called |= any(
                isinstance(block, ToolUseBlock) and block.name == "mcp__aiops_demo__inspect_demo"
                for block in message.content
            )
        if isinstance(message, ResultMessage):
            if message.subtype != "success" or message.is_error or message.terminal_reason:
                raise RuntimeError(
                    f"Agent ended with {message.subtype}; reason={message.terminal_reason}"
                )
            structured = message.structured_output
            run = {
                "model": config.model,
                "tool_called": tool_called,
                "num_turns": message.num_turns,
                "total_cost_usd": message.total_cost_usd,
            }
    if not tool_called:
        raise RuntimeError("Agent did not call the read-only inspect_demo tool")
    if not isinstance(structured, dict):
        raise RuntimeError("Agent returned no structured diagnosis")
    return AgentOutcome(Diagnosis.parse(structured), run)
