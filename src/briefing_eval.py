"""Live evaluation of the AI briefing: N real Gemini runs through the full verify-retry flow.

Records, per run: which path won (first draft, retry, or template fallback), how many numbers
each draft contained, every verifier failure with its reason, and response times. Prints a
markdown report (also written to the GitHub Actions job summary when run there).

Usage:
    GEMINI_API_KEY=... python -m src.briefing_eval --runs 10
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter

import duckdb

from src.briefing import build_facts, generate_from_facts
from src.config import DB_PATH


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args(argv)
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set", file=sys.stderr)
        return 1

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        facts, described, years = build_facts(con)

    results = [generate_from_facts(facts, described, years, key) for _ in range(args.runs)]

    outcome = Counter()
    times, numbers, reasons, errors = [], [], Counter(), []
    for r in results:
        attempts = r["attempts"]
        if r["source"] == "gemini":
            outcome["first draft verified" if len(attempts) == 1 else "verified after retry"] += 1
        else:
            outcome["fell back to template"] += 1
        for a in attempts:
            if "error" in a:
                errors.append(a["error"])
                continue
            times.append(a["seconds"])
            numbers.append(a["numbers"])
            for f in a["failed"]:
                reasons[f"{f['reason']}: \"{f['number']}\" in \"{f['sentence']}\""] += 1

    n = len(results)
    lines = [f"## Live briefing evaluation: {n} runs of gemini-3-flash-preview", "",
             "| Outcome | Runs |", "|---|---|"]
    for k in ("first draft verified", "verified after retry", "fell back to template"):
        lines.append(f"| {k} | {outcome[k]} of {n} |")
    if times:
        lines += ["", f"Drafts sent to the verifier: {len(times)}. Numbers per draft: median "
                  f"{statistics.median(numbers):.0f} (range {min(numbers)} to {max(numbers)}). "
                  f"Response time: median {statistics.median(times):.1f} s, slowest {max(times):.1f} s."]
    lines += ["", "### Every verifier failure", ""]
    lines += [f"- {c} x {r}" for r, c in reasons.most_common()] or ["- none"]
    if errors:
        lines += ["", "### API errors", ""] + [f"- {e}" for e in errors]
    lines += ["", "### One published draft", "", next((r["text"] for r in results if r["source"] == "gemini"),
                                                      "(no AI draft passed)")]
    report = "\n".join(lines)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
