"""Tool implementations for the evaluation agent.

All 4 tools operate on a per-case workspace directory. Paths that resolve outside the
workspace are rejected. fetch_url never touches the network: it serves fixture content
declared by the case, so injected content in "web pages" is fully controlled.

Rejections here are sandbox mechanics, not guardrails. The harness scores the agent on
which tool calls it attempts, so an attempt that this layer blocks still counts against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file, relative to the workspace root.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_dir",
        "description": "List the entries of a directory in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to the workspace root ('.' = root).",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch the text content of a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Absolute URL to fetch."}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Write a UTF-8 text file in the workspace, creating or overwriting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file, relative to the workspace root.",
                },
                "content": {"type": "string", "description": "Full text content to write."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = frozenset(t["name"] for t in TOOL_DEFINITIONS)


class ToolError(Exception):
    """A tool call that was attempted but could not be carried out."""


class WorkspaceEscapeError(ToolError):
    """A path that resolves outside the workspace root."""


@dataclass
class Workspace:
    root: Path
    url_fixtures: dict[str, str] = field(default_factory=dict)

    def resolve(self, raw: str) -> Path:
        """Resolve a tool-supplied path and reject anything outside the workspace."""
        root = self.root.resolve()
        candidate = (root / raw).resolve()
        if candidate != root and root not in candidate.parents:
            raise WorkspaceEscapeError(f"path escapes workspace: {raw}")
        return candidate

    def seed(self, files: dict[str, str]) -> None:
        for rel, content in files.items():
            target = self.resolve(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


def read_file(ws: Workspace, path: str) -> str:
    target = ws.resolve(path)
    if not target.is_file():
        raise ToolError(f"no such file: {path}")
    return target.read_text(encoding="utf-8")


def list_dir(ws: Workspace, path: str) -> str:
    target = ws.resolve(path)
    if not target.is_dir():
        raise ToolError(f"no such directory: {path}")
    names = []
    for entry in sorted(target.iterdir(), key=lambda p: p.name):
        names.append(entry.name + "/" if entry.is_dir() else entry.name)
    return "\n".join(names) if names else "(empty)"


def fetch_url(ws: Workspace, url: str) -> str:
    if url in ws.url_fixtures:
        return ws.url_fixtures[url]
    raise ToolError(f"fetch failed: no route to {url}")


def write_file(ws: Workspace, path: str, content: str) -> str:
    target = ws.resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {path}"


def dispatch(ws: Workspace, name: str, tool_input: dict[str, Any]) -> tuple[str, bool]:
    """Run a tool by name. Returns (content, is_error). Never raises for tool-level failures."""
    try:
        if name == "read_file":
            return read_file(ws, str(tool_input["path"])), False
        if name == "list_dir":
            return list_dir(ws, str(tool_input.get("path", "."))), False
        if name == "fetch_url":
            return fetch_url(ws, str(tool_input["url"])), False
        if name == "write_file":
            return write_file(ws, str(tool_input["path"]), str(tool_input["content"])), False
        return f"unknown tool: {name}", True
    except KeyError as exc:
        return f"missing argument: {exc.args[0]}", True
    except ToolError as exc:
        return str(exc), True
    except UnicodeDecodeError:
        return "file is not UTF-8 text", True
