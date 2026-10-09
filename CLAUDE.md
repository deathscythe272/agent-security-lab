# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

A public portfolio proving agentic AI security skills with working code. 3 parts:

1. `src/mcpscan/`: a security scanner for Model Context Protocol (MCP) servers.
2. `sandbox/`: a hardware-isolated agent runtime on a Raspberry Pi 5 (k3s, Helm chart), plus an evaluation harness.
3. `policy/`: Open Policy Agent (OPA) policies in Rego. Guardrails for the agent and Conftest checks for Kubernetes manifests. Every policy has `opa test` unit tests.

See `README.md` for architecture and status. See `docs/threat-model.md` (planned) before touching sandbox code.

## Rules

- Every change goes through a pull request. No direct pushes to `main`.
- CI must be green before merge. The eval harness pass rate (once it exists) is a merge gate.
- Every component has a status label in the README status table: done, in progress, or planned. Update it in the same PR that changes the status. Update the Numbers table in the same PR that changes a count.
- Do not write marketing language in docs. State what the code does and what it does not do.
- Spell out acronyms on first use in any document.
- Every detection check in `mcpscan` gets a unit test with a positive and a negative fixture.
- Every sandbox control gets at least 1 evaluation case.
- Guardrail decisions live in Rego, never in Python conditionals. Python asks OPA and acts on the answer.
- Every detection over the audit log gets a triage runbook in `docs/runbooks/` and an eval case that triggers it.
- Supply chain gates (SBOM, image scan, cosign, secret scan) are CI steps. Do not disable one to get a green build; fix the finding.

## Commands

```
python -m pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

## Conventions

- Python 3.12+, `src/` layout, `ruff` for lint and format, `pytest` for tests.
- Findings in `mcpscan` carry an OWASP Top 10 for LLM Applications ID and a MITRE ATLAS technique ID.
- Kubernetes manifests come from the Helm chart only. No hand-written manifests outside `sandbox/chart/`.
- Branch names: `feat/`, `fix/`, `docs/`, `ci/`.
