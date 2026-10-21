"""Rewrite the README Numbers table from evals/results.json.

    python scripts/update_readme_numbers.py          # update README.md in place
    python scripts/update_readme_numbers.py --check  # exit 1 if README is out of date

The README is never edited by hand for these rows. CI runs --check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
RESULTS = REPO_ROOT / "evals" / "results.json"

ROW_CASES = "Evaluation harness test cases"
ROW_RATE = "Current pass rate"


def render_rows(results: dict) -> dict[str, str]:
    total = int(results["total"])
    passed = int(results["passed"])
    rate = float(results["pass_rate"]) * 100
    threshold = float(results["threshold"]) * 100
    model = results["model"]
    return {
        ROW_CASES: str(total),
        ROW_RATE: (
            f"{rate:.1f}% ({passed} of {total} passed, threshold {threshold:.0f}%, model `{model}`)"
        ),
    }


def apply(readme_text: str, rows: dict[str, str]) -> str:
    out = readme_text
    for label, value in rows.items():
        pattern = re.compile(rf"^\| {re.escape(label)} \| .* \|$", re.MULTILINE)
        replacement = f"| {label} | {value} |"
        out, n = pattern.subn(replacement, out, count=1)
        if n != 1:
            raise SystemExit(f"README row not found: {label}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--readme", type=Path, default=README)
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args(argv)

    if not args.results.exists():
        print(f"no results file at {args.results}; nothing to do")
        return 0

    results = json.loads(args.results.read_text(encoding="utf-8"))
    current = args.readme.read_text(encoding="utf-8")
    updated = apply(current, render_rows(results))

    if args.check:
        if updated != current:
            print("README Numbers table is out of date. Run scripts/update_readme_numbers.py")
            return 1
        print("README Numbers table matches evals/results.json")
        return 0

    if updated != current:
        args.readme.write_text(updated, encoding="utf-8", newline="\n")
        print("README updated")
    else:
        print("README already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
