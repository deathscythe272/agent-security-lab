# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

A public portfolio proving agentic AI security skills with working code. 2 systems:

1. `src/mcpscan/`: a security scanner for Model Context Protocol (MCP) servers.
2. `sandbox/`: a hardware-isolated agent runtime on a Raspberry Pi 5, plus an evaluation harness.

See `README.md` for architecture and status. See `docs/threat-model.md` (planned) before touching sandbox code.

## Rules

- Every change goes through a pull request. No direct pushes to `main`.
- CI must be green before merge. The eval harness pass rate (once it exists) is a merge gate.
- Every component has a status label in the README status table: done, in progress, or planned. Update it in the same PR that changes the status.
- Do not write marketing language in docs. State what the code does and what it does not do.
- Spell out acronyms on first use in any document.
- Every detection check in `mcpscan` gets a unit test with a positive and a negative fixture.
- Every sandbox control gets at least 1 evaluation case.

## Commands

```
python -m pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

## Conventions

- Python 3.12+, `src/` layout, `ruff` for lint and format, `pytest` for tests.
- Findings in `mcpscan` carry an OWASP Top 10 for LLM Applications ID and a MITRE ATLAS technique ID.
- Branch names: `feat/`, `fix/`, `docs/`, `ci/`.
