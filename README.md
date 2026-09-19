# Local Docker AIOps Agent demo

This is a fresh implementation inspired by the supplied project description. It is **not** the original project's source code. The current milestone covers a deliberately leaky recommendation service, Prometheus metrics, local structured Agent diagnosis, a tightly scoped Docker restart, and an isolated local code-repair Agent with test and image gates. GitHub PR creation, Milvus, Jaeger traces and kind are later milestones.

## What the demo does now

1. Docker Compose runs `recommendation` with a 128 MiB memory limit. A background thread continuously appends product IDs to an unbounded list.
2. `/metrics` exposes the list size. Prometheus scrapes it every five seconds.
3. `python -m aiops.run alerts/s4.json` collects Docker and Prometheus observations and produces a JSON diagnosis. The default `heuristic` mode needs no API key.
4. `--mode ollama` uses a local Qwen3 model in Docker. It must call one read-only observation tool before returning a schema-bound diagnosis. `--mode claude` remains an optional adapter.
5. `--apply-low-risk` permits only `docker restart` of the exact Compose `recommendation` container after a fresh project/service label check. Without this flag, diagnosis is read-only.

The planted regression test at `fixtures/recommendation/test_recommendation.py` is intentionally red in the canonical fixture. The repair Agent copies the fixture to `reports/repair-*/workspace`, proves the test is red, applies one constrained model proposal, and requires green tests, compilation, Docker build, container health, and a runtime bound of 500 entries. The canonical fixture remains unchanged so the demo is repeatable.

## Prerequisites

- Windows: Docker Desktop with its WSL 2 Linux backend. A separate Ubuntu WSL distribution is optional for this Python-based milestone. Linux is also supported.
- Python 3.10+ and Git. The default diagnosis uses Python's standard library only.
- For local Agent mode: Docker GPU support and the `qwen3:4b` Ollama model. `scripts/demo_agent.ps1` provisions both automatically.
- Optional Claude mode requires an Anthropic API key and `pip install -e '.[claude]'`.

## First run

On Linux or in an optional WSL Ubuntu distribution:

```bash
cd aiops-agent
python3 -m venv .venv
source .venv/bin/activate
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8088/healthz
curl http://127.0.0.1:8088/metrics
```

On Windows PowerShell, after installing a user-accessible Python 3.10+:

```powershell
cd aiops-agent
py -m venv .venv
.\.venv\Scripts\Activate.ps1
docker compose up --build -d
curl.exe http://127.0.0.1:8088/healthz
```

Wait at least 20 seconds for Prometheus to collect several samples, then run:

```bash
python -m aiops.run alerts/s4.json --report reports/s4-readonly.json
```

Inspect `route`, `diagnosis.evidence`, `snapshot.seen_products_samples`, and `executed_actions`. To perform one authorized restart in **this local demo only**:

```bash
python -m aiops.run alerts/s4.json --apply-low-risk --report reports/s4-restart.json
```

For local model-led diagnosis on Windows PowerShell, run:

```powershell
.\scripts\demo_agent.ps1
```

The first run downloads the Ollama image and the approximately 2.5 GB model. Later runs reuse the Docker volume. The `agent_run` field records provider, model, required tool call, token counts, duration, and zero API cost. A structured answer without the tool call or with an inconsistent action is rejected. The script stops all demo containers by default.

## Isolated repair demo

```powershell
.\scripts\demo_repair.ps1
```

The resulting `reports/repair-*/repair.json` captures the failed pre-repair test, successful post-repair test, compile gate, Docker build, and runtime health/bounded-state check. `repair.patch` is the review artifact. The model cannot choose arbitrary paths or commands: only `recommendation_server.py` is editable, the regression test is immutable, and the executor accepts only the approved in-place list trim.

Do not put actual API keys in `.env.example` or Git. This implementation does not load `.env` automatically.

## Offline checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q aiops fixtures/recommendation
```

The regression test in `fixtures/recommendation` is excluded from the normal test suite because it is deliberately failing until the repair stage.

## Current safeguards and limitations

- No model-generated shell command is executed. Restart is selected by an action ID and performed by code using an argument array.
- A restart is recorded only after `docker restart` exits successfully. `health_verified` reports whether `/healthz` recovered; a successful restart is not treated as a permanent fix.
- The heuristic requires at least two Prometheus samples showing growth. Without evidence, it routes to human review.
- The demo currently observes and repairs one fixture only. It does not yet trace requests through Jaeger or create GitHub PRs.
- A container OOM and automatic restart can reset its current `OOMKilled` flag; the observed list-size trend and restart count should be read together.

Stop the demo with `docker compose down` when finished.
