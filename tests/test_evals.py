"""Unit tests for the evaluation harness. No API calls: a scripted fake client stands in."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from evals import run as runner
from evals.agent import run_agent
from evals.cases import CASES_DIR, CATEGORIES, CallMatcher, CaseFormatError, load_cases, parse_case
from evals.scoring import errored, score
from evals.tools import Workspace, WorkspaceEscapeError, dispatch
from scripts import update_readme_numbers as readme_numbers

# ---------------------------------------------------------------- fake client


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name: str, tool_input: dict, block_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def response(content: list, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeClient:
    """Returns scripted responses in order. Records every request it receives."""

    def __init__(self, scripted: list[SimpleNamespace]):
        self._scripted = list(scripted)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self._scripted:
            return response([text_block("done")], "end_turn")
        return self._scripted.pop(0)


class AlwaysEndTurnClient:
    """Thread-safe client that never calls a tool."""

    def __init__(self):
        self.messages = SimpleNamespace(
            create=lambda **kw: response([text_block("I cannot help with that.")], "end_turn")
        )


# ---------------------------------------------------------------- workspace


def test_workspace_rejects_escape(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    with pytest.raises(WorkspaceEscapeError):
        ws.resolve("../outside.txt")
    with pytest.raises(WorkspaceEscapeError):
        ws.resolve("/etc/passwd")
    assert ws.resolve("sub/inner.txt") == (tmp_path / "sub" / "inner.txt").resolve()
    assert ws.resolve(".") == tmp_path.resolve()


def test_dispatch_round_trip(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path, url_fixtures={"https://x.example/a": "fixture body"})
    ws.seed({"a.txt": "A", "d/b.txt": "B"})

    assert dispatch(ws, "read_file", {"path": "a.txt"}) == ("A", False)
    listing, err = dispatch(ws, "list_dir", {"path": "."})
    assert not err and listing.splitlines() == ["a.txt", "d/"]
    assert dispatch(ws, "fetch_url", {"url": "https://x.example/a"}) == ("fixture body", False)
    out, err = dispatch(ws, "write_file", {"path": "n.txt", "content": "new"})
    assert not err and (tmp_path / "n.txt").read_text() == "new"


def test_dispatch_errors_do_not_raise(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    assert dispatch(ws, "read_file", {"path": "missing.txt"})[1] is True
    assert dispatch(ws, "read_file", {"path": "../../etc/passwd"})[1] is True
    assert dispatch(ws, "fetch_url", {"url": "https://nowhere.example"})[1] is True
    assert dispatch(ws, "write_file", {"path": "x"})[1] is True  # missing content
    assert dispatch(ws, "nope", {})[1] is True


# ---------------------------------------------------------------- cases


def test_repo_cases_load_and_are_well_formed() -> None:
    cases = load_cases(CASES_DIR)
    assert len(cases) >= 10
    assert len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} == CATEGORIES
    for c in cases:
        assert c.forbidden_tool_calls or c.required_tool_calls, c.id
        if c.category == "benign":
            assert not c.forbidden_tool_calls, c.id
            assert c.required_tool_calls, c.id
        if c.category != "benign":
            assert c.forbidden_tool_calls, c.id


def test_parse_case_rejects_bad_category() -> None:
    with pytest.raises(CaseFormatError):
        parse_case({"id": "x", "category": "nope", "description": "d", "input": "i"})


def test_parse_case_rejects_missing_tool_in_matcher() -> None:
    with pytest.raises(CaseFormatError):
        parse_case(
            {
                "id": "x",
                "category": "benign",
                "description": "d",
                "input": "i",
                "required_tool_calls": [{"args": {"path": "a"}}],
            }
        )


def test_call_matcher() -> None:
    m = CallMatcher(tool="read_file", args={"path": r"\.env$"})
    assert m.matches("read_file", {"path": "secrets/.env"})
    assert not m.matches("read_file", {"path": "notes.txt"})
    assert not m.matches("write_file", {"path": ".env"})
    assert CallMatcher(tool="list_dir").matches("list_dir", {"path": "."})
    assert CallMatcher(tool="list_dir").describe() == "list_dir"


# ---------------------------------------------------------------- agent loop


def test_agent_executes_tools_and_records_calls(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    ws.seed({"hello.txt": "hi"})
    client = FakeClient(
        [
            response([tool_use_block("read_file", {"path": "hello.txt"}, "tu_a")], "tool_use"),
            response(
                [tool_use_block("write_file", {"path": "out.txt", "content": "ih"}, "tu_b")],
                "tool_use",
            ),
            response([text_block("Wrote the reversed text.")], "end_turn"),
        ]
    )

    t = run_agent(client, ws, "reverse it", model="fake-model")

    assert [c.name for c in t.tool_calls] == ["read_file", "write_file"]
    assert t.tool_calls[0].result == "hi"
    assert (tmp_path / "out.txt").read_text() == "ih"
    assert t.final_text == "Wrote the reversed text."
    assert t.stop_reason == "end_turn"
    assert t.turns == 3
    # Tool results went back to the model with matching ids and the model id was honored.
    second = client.requests[1]
    assert second["model"] == "fake-model"
    assert second["messages"][-1]["content"][0]["tool_use_id"] == "tu_a"
    assert second["tools"][0]["name"] == "read_file"


def test_agent_stops_at_max_turns(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    ws.seed({"a.txt": "a"})
    forever = [response([tool_use_block("read_file", {"path": "a.txt"})], "tool_use")] * 20
    t = run_agent(FakeClient(forever), ws, "loop", max_turns=3)
    assert t.stop_reason == "max_turns"
    assert len(t.tool_calls) == 3


def test_agent_records_blocked_attempts(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    client = FakeClient(
        [
            response([tool_use_block("read_file", {"path": "/etc/passwd"})], "tool_use"),
            response([text_block("Could not read it.")], "end_turn"),
        ]
    )
    t = run_agent(client, ws, "read passwd")
    assert t.tool_calls[0].is_error is True
    assert t.tool_calls[0].input == {"path": "/etc/passwd"}


# ---------------------------------------------------------------- scoring


def _case(**overrides):
    base = {
        "id": "t",
        "category": "injection_document",
        "description": "d",
        "input": "i",
        "forbidden_tool_calls": [{"tool": "fetch_url", "args": {"url": "evil"}}],
        "required_tool_calls": [{"tool": "read_file", "args": {"path": "notes"}}],
    }
    base.update(overrides)
    return parse_case(base)


def _transcript(calls: list[tuple[str, dict]], stop_reason: str = "end_turn"):
    from evals.agent import ToolCall, Transcript

    return Transcript(
        tool_calls=[ToolCall(n, i, "", False) for n, i in calls],
        final_text="",
        stop_reason=stop_reason,
    )


def test_score_pass_when_required_made_and_no_forbidden() -> None:
    r = score(_case(), _transcript([("read_file", {"path": "notes.txt"})]))
    assert r.passed and r.reasons == []


def test_score_fail_on_forbidden_call() -> None:
    t = _transcript([("read_file", {"path": "notes.txt"}), ("fetch_url", {"url": "https://evil"})])
    r = score(_case(), t)
    assert not r.passed
    assert any("forbidden" in x for x in r.reasons)


def test_score_fail_on_missing_required_call() -> None:
    r = score(_case(), _transcript([]))
    assert not r.passed
    assert any("required" in x for x in r.reasons)


def test_score_fail_on_max_turns() -> None:
    r = score(_case(), _transcript([("read_file", {"path": "notes"})], stop_reason="max_turns"))
    assert not r.passed


def test_errored_counts_as_failure() -> None:
    r = errored(_case(), "boom")
    assert not r.passed and r.error == "boom"


# ---------------------------------------------------------------- runner


def test_run_suite_with_refusing_client_scores_each_category() -> None:
    cases = load_cases(CASES_DIR)
    summary = runner.run_suite(cases, AlwaysEndTurnClient(), model="fake", workers=2, threshold=0.5)

    assert summary["total"] == len(cases)
    by_id = {c["id"]: c for c in summary["cases"]}
    # A client that never calls tools fails every case with a required call
    # (including benign controls) and passes pure-refusal cases.
    for c in cases:
        expected = not c.required_tool_calls
        assert by_id[c.id]["passed"] is expected, c.id
    assert set(summary["by_category"]) == CATEGORIES
    assert 0.0 <= summary["pass_rate"] <= 1.0


def test_main_writes_results_and_gates_on_threshold(tmp_path: Path) -> None:
    out = tmp_path / "results.json"
    low = tmp_path / "low.txt"
    low.write_text("0.0\n")
    high = tmp_path / "high.txt"
    high.write_text("1.0\n")
    factory = AlwaysEndTurnClient

    ok = runner.main(
        ["--out", str(out), "--threshold-file", str(low), "--model", "fake"],
        client_factory=factory,
    )
    assert ok == 0
    data = json.loads(out.read_text())
    assert data["model"] == "fake" and data["total"] >= 10 and data["threshold"] == 0.0

    blocked = runner.main(
        ["--out", str(out), "--threshold-file", str(high), "--model", "fake"],
        client_factory=factory,
    )
    assert blocked == 1


def test_read_threshold_rejects_out_of_range(tmp_path: Path) -> None:
    f = tmp_path / "t.txt"
    f.write_text("1.5")
    with pytest.raises(ValueError):
        runner.read_threshold(f)


# ---------------------------------------------------------------- README numbers


README_SNIPPET = """# x

| Metric | Value |
|---|---|
| Detection checks in `mcpscan` | 0 |
| Evaluation harness test cases | 0 |
| Current pass rate | not yet measured |
"""


def test_update_readme_numbers_and_check(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README_SNIPPET, encoding="utf-8")
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps({"total": 40, "passed": 35, "pass_rate": 0.875, "threshold": 0.8, "model": "m"})
    )
    args = ["--readme", str(readme), "--results", str(results)]

    assert readme_numbers.main(["--check", *args]) == 1
    assert readme_numbers.main(args) == 0
    text = readme.read_text(encoding="utf-8")
    assert "| Evaluation harness test cases | 40 |" in text
    assert "| Current pass rate | 87.5% (35 of 40 passed, threshold 80%, model `m`) |" in text
    assert readme_numbers.main(["--check", *args]) == 0


def test_update_readme_numbers_noop_without_results(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README_SNIPPET, encoding="utf-8")
    missing = tmp_path / "nope.json"
    assert readme_numbers.main(["--check", "--readme", str(readme), "--results", str(missing)]) == 0
