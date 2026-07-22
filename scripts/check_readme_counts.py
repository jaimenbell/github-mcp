#!/usr/bin/env python3
"""CI count-verification gate.

Fails the build if README.md's claimed pytest counts drift from what the
suite actually reported (via a --junitxml report). Generalizes the
proof-manifest pattern -- a claimed number in a public doc must be provable
against the real artifact it describes, every run, or the build goes red.

Stdlib-only by design (no new test/CI dependency).

README phrasing this anchors to (see README.md's shields.io Tests badge):

    [![tests](https://img.shields.io/badge/tests-86%20passing%20%2F%201%20skipped-brightgreen)](#testing)

The badge label is a URL-encoded "tests-<P> passing / <S> skipped" string,
i.e. "tests-<P>%20passing%20%2F%20<S>%20skipped". If that phrasing ever
changes, update CLAIM_RE below in the same commit that changes the README
badge -- that coupling is the point of this script.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Anchored to the exact shields.io badge phrasing above. Update alongside
# the README badge if the wording ever changes.
CLAIM_RE = re.compile(
    r"tests-(?P<passed>\d+)%20passing%20%2F%20(?P<skipped>\d+)%20skipped"
)


@dataclass(frozen=True)
class Counts:
    total: int
    passed: int
    skipped: int


def parse_claimed_counts(readme_text: str) -> Optional[Counts]:
    """Extract the claimed (total, passed, skipped) triple from README text.
    Returns None if the anchored phrasing isn't found -- a missing/renamed
    claim is a gate failure, not a silent pass. The badge doesn't state an
    explicit total, so total = passed + skipped (this repo's suite has no
    failure/error tolerance baked into the badge -- see compare())."""
    match = CLAIM_RE.search(readme_text)
    if not match:
        return None
    passed = int(match.group("passed"))
    skipped = int(match.group("skipped"))
    return Counts(total=passed + skipped, passed=passed, skipped=skipped)


def parse_actual_counts(junit_xml_path: Path) -> Counts:
    """Extract (total, passed, skipped) from a pytest --junitxml report.
    passed = tests - failures - errors - skipped."""
    tree = ET.parse(junit_xml_path)
    root = tree.getroot()
    # pytest's junit_family=xunit2 (the default) wraps <testsuite> in
    # <testsuites>; handle both shapes.
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise ValueError(f"no <testsuite> element found in {junit_xml_path}")

    total = int(suite.get("tests", 0))
    skipped = int(suite.get("skipped", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    passed = total - skipped - failures - errors
    return Counts(total=total, passed=passed, skipped=skipped)


def compare(claimed: Optional[Counts], actual: Counts) -> tuple[bool, str]:
    """Decide pass/fail and produce a clear human-readable message."""
    if claimed is None:
        return False, (
            "COULD NOT FIND a claimed test count in README.md matching the "
            "expected shields.io badge phrasing 'tests-<P>%20passing%20%2F%20"
            "<S>%20skipped'. Either the README badge wording changed (update "
            "CLAIM_RE in scripts/check_readme_counts.py to match) or the "
            "badge was removed by accident."
        )
    if claimed == actual:
        return True, (
            f"README claim matches actual suite results: "
            f"{actual.passed} passing / {actual.skipped} skipped "
            f"({actual.total} total)."
        )
    return False, (
        "README test-count claim has DRIFTED from the actual suite:\n"
        f"  README claims : {claimed.passed} passing / {claimed.skipped} skipped "
        f"({claimed.total} total)\n"
        f"  actual suite  : {actual.passed} passing / {actual.skipped} skipped "
        f"({actual.total} total)\n"
        "Update README.md's Tests badge to match reality."
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default="README.md", help="path to README.md")
    parser.add_argument(
        "--junit-xml", default="junit.xml", help="path to a pytest --junitxml report"
    )
    args = parser.parse_args(argv)

    readme_path = Path(args.readme)
    junit_path = Path(args.junit_xml)

    if not readme_path.exists():
        print(f"ERROR: README not found at {readme_path}", file=sys.stderr)
        return 2
    if not junit_path.exists():
        print(f"ERROR: junitxml report not found at {junit_path}", file=sys.stderr)
        return 2

    readme_text = readme_path.read_text(encoding="utf-8")
    claimed = parse_claimed_counts(readme_text)
    actual = parse_actual_counts(junit_path)

    ok, message = compare(claimed, actual)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
