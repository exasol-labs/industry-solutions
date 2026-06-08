#!/usr/bin/env python3
"""Generate the solutions index table in the root README.

Scans each immediate subfolder that contains a README.md, extracts a title,
a one-line description, and optional metadata, then rewrites the table between
the SOLUTIONS:START and SOLUTIONS:END markers in the root README.

Per-solution metadata is optional. To set it, add a leading HTML comment to the
top of a solution's README.md:

    <!--
    industry: Banking & Financial Services
    status: stable
    -->

Usage:
    python scripts/generate_solutions_index.py          # rewrite README.md in place
    python scripts/generate_solutions_index.py --check   # exit 1 if README is stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
START = "<!-- SOLUTIONS:START -->"
END = "<!-- SOLUTIONS:END -->"

# Folders that are never solutions.
IGNORE = {".git", ".github", "scripts", "docs", "assets", "node_modules"}


def parse_metadata(text: str) -> dict[str, str]:
    """Read key: value pairs from a leading HTML comment, if present."""
    match = re.match(r"\s*<!--(.*?)-->", text, re.DOTALL)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    return meta


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def extract_description(text: str) -> str:
    """First non-empty paragraph after the H1 that is not a heading/image/badge."""
    lines = text.splitlines()
    seen_h1 = False
    for line in lines:
        stripped = line.strip()
        if not seen_h1:
            if stripped.startswith("# "):
                seen_h1 = True
            continue
        if not stripped:
            continue
        if stripped.startswith(("#", "!", "<", "[!", "|", "-", "*", ">", "```")):
            continue
        # Collapse inline links to their text and strip stray markdown.
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        return clean
    return ""


def collect_solutions() -> list[dict[str, str]]:
    solutions = []
    for path in sorted(REPO_ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith(".") or path.name in IGNORE:
            continue
        readme = path / "README.md"
        if not readme.exists():
            continue
        text = readme.read_text(encoding="utf-8")
        meta = parse_metadata(text)
        solutions.append(
            {
                "folder": path.name,
                "title": extract_title(text, path.name),
                "description": extract_description(text),
                "industry": meta.get("industry", ""),
                "status": meta.get("status", ""),
            }
        )
    return solutions


def render_table(solutions: list[dict[str, str]]) -> str:
    if not solutions:
        return f"{START}\n\n_No solutions published yet._\n\n{END}"

    rows = ["| Solution | Industry | Description |", "| --- | --- | --- |"]
    for s in solutions:
        title = f"[{s['title']}]({s['folder']}/)"
        industry = s["industry"] or "General"
        description = s["description"] or ""
        rows.append(f"| {title} | {industry} | {description} |")
    table = "\n".join(rows)
    return f"{START}\n\n{table}\n\n{END}"


def rewrite(content: str, block: str) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(content):
        raise SystemExit(
            f"Markers {START} / {END} not found in README.md. Add them where the "
            "solutions table should appear."
        )
    return pattern.sub(block, content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if README.md is out of date instead of rewriting it.",
    )
    args = parser.parse_args()

    content = README.read_text(encoding="utf-8")
    block = render_table(collect_solutions())
    updated = rewrite(content, block)

    if args.check:
        if updated != content:
            print("README.md solutions index is out of date. Run: "
                  "python scripts/generate_solutions_index.py")
            return 1
        print("README.md solutions index is up to date.")
        return 0

    if updated != content:
        README.write_text(updated, encoding="utf-8")
        print("Updated solutions index in README.md.")
    else:
        print("Solutions index already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
