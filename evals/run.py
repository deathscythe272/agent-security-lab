"""Evaluation runner.

    python -m evals.run [--cases evals/cases] [--out evals/results.json] [--model ID]
                        [--threshold-file evals/threshold.txt] [--workers 4] [--only ID ...]

Prints 1 line per case and a summary, writes results JSON, and exits non-zero when the
pass rate is below the threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.agent import DEFAULT_MODEL, run_agent
from evals.cases import CASES_DIR, Case, load_cases
from evals.scoring import CaseResult, errored, score
from evals.tools import Workspace

EVALS_DIR = Path(__file__).parent
DEFAULT_OUT = EVALS_DIR / "results.json"
DEFAULT_THRESHOLD_FILE = EVALS_DIR / "threshold.txt"


def read_threshold(path: Path) -> float:
    value = float(path.read_text(encoding="utf-8").strip())
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {value}")
    return value


def run_case(case: Case, client: Any, model: str) -> CaseResult:
    with tempfile.TemporaryDirectory(prefix=f"eval-{case.id}-") as tmp:
        ws = Workspace(root=Path(tmp), url_fixtures=dict(case.url_fixtures))
        ws.seed(case.workspace_files)
        try:
            transcript = run_agent(client, ws, case.input, model=model)
        except Exception as exc:  # noqa: BLE001 - any failure is recorded, never hidden
            return errored(case, f"{type(exc).__name__}: {exc}")
    return score(case, transcript)


def run_suite(
    cases: Sequence[Case],
    client: Any,
    *,
    model: str = DEFAULT_MODEL,
    workers: int = 4,
    threshold: float = 0.0,
) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda c: run_case(c, client, model), cases))

    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        by_category[r.category]["total"] += 1
        by_category[r.category]["passed"] += int(r.passed)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return {
        "model": model,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "threshold": threshold,
        "by_category": dict(sorted(by_category.items())),
        "cases": [r.to_dict() for r in results],
    }


def meets_threshold(summary: dict[str, Any]) -> bool:
    return summary["total"] > 0 and summary["pass_rate"] >= summary["threshold"]


def print_report(summary: dict[str, Any], out: Any = sys.stdout) -> None:
    for r in summary["cases"]:
        mark = "PASS" if r["passed"] else "FAIL"
        detail = "" if r["passed"] else "  <- " + "; ".join(r["reasons"])
        print(f"{mark}  {r['id']:<28} {r['category']:<24}{detail}", file=out)
    print(file=out)
    for cat, c in summary["by_category"].items():
        print(f"{cat:<24} {c['passed']:>3} / {c['total']:<3}", file=out)
    print(file=out)
    pct = summary["pass_rate"] * 100
    print(
        f"passed {summary['passed']} / {summary['total']}  pass rate {pct:.1f}%  "
        f"threshold {summary['threshold'] * 100:.1f}%  model {summary['model']}",
        file=out,
    )


def default_client_factory() -> Any:
    import anthropic

    return anthropic.Anthropic()


def main(argv: Sequence[str] | None = None, client_factory: Callable[[], Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent evaluation harness.")
    parser.add_argument("--cases", type=Path, default=CASES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", default=os.environ.get("EVAL_MODEL", DEFAULT_MODEL))
    parser.add_argument("--threshold-file", type=Path, default=DEFAULT_THRESHOLD_FILE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", nargs="*", default=None, help="Run only these case ids.")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.only:
        wanted = set(args.only)
        cases = [c for c in cases if c.id in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    threshold = read_threshold(args.threshold_file)
    client = (client_factory or default_client_factory)()
    summary = run_suite(cases, client, model=args.model, workers=args.workers, threshold=threshold)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print_report(summary)
    print(f"wrote {args.out}")

    if not meets_threshold(summary):
        print("FAIL: pass rate is below threshold", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
