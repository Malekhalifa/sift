import re
from pathlib import Path

from tp import report

ROOT = Path(__file__).resolve().parents[1]


def test_marked_blocks_are_replaced_from_the_source_files():
    stale = "intro\n<!-- diagram:pipeline -->\n```mermaid\nflowchart LR\n  A --> B\n```\n<!-- /diagram -->\noutro\n"
    fresh = report.sync_diagrams(stale)
    assert report.diagram_source("pipeline") in fresh and "A --> B" not in fresh
    assert fresh.startswith("intro\n") and fresh.endswith("outro\n")
    assert report.sync_diagrams(fresh) == fresh  # idempotent


def test_repository_markdown_diagrams_match_the_sources():
    drift = report.out_of_sync([ROOT / "README.md", ROOT / "docs" / "findings.md"])
    assert drift == [], f"run `uv run python scripts/build_report.py --sync`: {drift}"


def test_every_diagram_source_is_valid_text_for_the_renderer():
    for path in report.DIAGRAMS.glob("*.mmd"):
        first = path.read_text().split("\n", 1)[0]
        assert first.split()[0] in {"flowchart", "graph", "sequenceDiagram", "stateDiagram-v2", "classDiagram", "erDiagram", "xychart-beta"}, path


def test_whitepaper_references_citations_and_figures_resolve():
    tex = report.WHITEPAPER_TEX.read_text()
    labels = set(re.findall(r"\\label\{([^}]+)\}", tex))
    refs = set(re.findall(r"\\(?:page)?ref\{([^}]+)\}", tex)) - {"LastPage"}
    assert refs <= labels, f"undefined references: {sorted(refs - labels)}"
    cites = {k for group in re.findall(r"\\cite\{([^}]+)\}", tex) for k in group.split(",")}
    assert cites <= set(re.findall(r"\\bibitem\{([^}]+)\}", tex))
    for name in re.findall(r"\\includegraphics\[[^\]]*\]\{([^}]+)\}", tex):
        assert (report.WHITEPAPER / name).exists(), name
