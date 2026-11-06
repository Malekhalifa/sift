"""Sync the Mermaid diagrams into the markdown files and build the research whitepaper (LaTeX).

    uv run python scripts/build_report.py            # sync diagrams, then typeset docs/whitepaper/sift-whitepaper.tex into
                                                     # docs/Trading-Research-Findings.pdf
    uv run python scripts/build_report.py --sync     # only rewrite the diagram blocks in the markdown files
    uv run python scripts/build_report.py --check    # exit 1 if any markdown file's diagrams differ from docs/diagrams/*.mmd

Needs XeLaTeX, rsvg-convert and Node, plus the Pretty Mermaid renderer (see src/tp/report.py).
"""

from __future__ import annotations

import argparse

from tp import report

MARKDOWN = [report.ROOT / "README.md", report.ROOT / "docs" / "findings.md"]
PDF = report.ROOT / "docs" / "Trading-Research-Findings.pdf"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        drift = report.out_of_sync(MARKDOWN)
        for path in drift:
            print(f"diagrams out of sync: {path}")
        return 1 if drift else 0
    for path in MARKDOWN:
        path.write_text(report.sync_diagrams(path.read_text()))
    if args.sync:
        return 0
    report.build_whitepaper(PDF)
    print(f"wrote {PDF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
