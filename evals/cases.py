"""Case format and loader.

Each case is 1 YAML file in evals/cases/. Scoring is behavioral: a case passes when none
of its forbidden tool calls were attempted and all of its required tool calls were made.
Refusal is measured by what the agent does with its tools, not by the wording of its reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = frozenset(
    {
        "injection_document",
        "injection_tool_output",
        "tool_misuse",
        "exfiltration",
        "benign",
    }
)

INJECTION_VECTORS = frozenset({"document", "tool_output", "user", "none"})

CASES_DIR = Path(__file__).parent / "cases"


class CaseFormatError(ValueError):
    """A case file that does not match the expected format."""


@dataclass(frozen=True)
class CallMatcher:
    """Matches a tool call by tool name and, optionally, regexes over argument values."""

    tool: str
    args: dict[str, str] = field(default_factory=dict)

    def matches(self, name: str, tool_input: dict[str, Any]) -> bool:
        if name != self.tool:
            return False
        for key, pattern in self.args.items():
            value = tool_input.get(key)
            if value is None or re.search(pattern, str(value)) is None:
                return False
        return True

    def describe(self) -> str:
        if not self.args:
            return self.tool
        inner = ", ".join(f"{k}~/{v}/" for k, v in self.args.items())
        return f"{self.tool}({inner})"


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    description: str
    input: str
    injection_vector: str = "none"
    expect_refusal: bool = False
    workspace_files: dict[str, str] = field(default_factory=dict)
    url_fixtures: dict[str, str] = field(default_factory=dict)
    forbidden_tool_calls: tuple[CallMatcher, ...] = ()
    required_tool_calls: tuple[CallMatcher, ...] = ()


def _matchers(raw: Any, case_id: str, key: str) -> tuple[CallMatcher, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise CaseFormatError(f"{case_id}: {key} must be a list")
    out = []
    for item in raw:
        if not isinstance(item, dict) or "tool" not in item:
            raise CaseFormatError(f"{case_id}: each {key} entry needs a 'tool' key")
        args = item.get("args") or {}
        if not isinstance(args, dict):
            raise CaseFormatError(f"{case_id}: {key} args must be a mapping")
        for pattern in args.values():
            re.compile(str(pattern))
        out.append(CallMatcher(tool=str(item["tool"]), args={k: str(v) for k, v in args.items()}))
    return tuple(out)


def parse_case(data: dict[str, Any], source: str = "<memory>") -> Case:
    for key in ("id", "category", "description", "input"):
        if key not in data:
            raise CaseFormatError(f"{source}: missing required key '{key}'")
    case_id = str(data["id"])
    category = str(data["category"])
    if category not in CATEGORIES:
        raise CaseFormatError(f"{case_id}: unknown category '{category}'")
    vector = str(data.get("injection_vector", "none"))
    if vector not in INJECTION_VECTORS:
        raise CaseFormatError(f"{case_id}: unknown injection_vector '{vector}'")
    files = data.get("workspace_files") or {}
    urls = data.get("url_fixtures") or {}
    if not isinstance(files, dict) or not isinstance(urls, dict):
        raise CaseFormatError(f"{case_id}: workspace_files and url_fixtures must be mappings")
    return Case(
        id=case_id,
        category=category,
        description=str(data["description"]).strip(),
        input=str(data["input"]).strip(),
        injection_vector=vector,
        expect_refusal=bool(data.get("expect_refusal", False)),
        workspace_files={str(k): str(v) for k, v in files.items()},
        url_fixtures={str(k): str(v) for k, v in urls.items()},
        forbidden_tool_calls=_matchers(data.get("forbidden_tool_calls"), case_id, "forbidden"),
        required_tool_calls=_matchers(data.get("required_tool_calls"), case_id, "required"),
    )


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise CaseFormatError(f"{path.name}: top level must be a mapping")
        case = parse_case(data, source=path.name)
        if case.id in seen:
            raise CaseFormatError(f"duplicate case id: {case.id}")
        seen.add(case.id)
        cases.append(case)
    return cases
