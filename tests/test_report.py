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


def test_pdf_markdown_drops_the_title_block_and_attaches_captions(tmp_path, monkeypatch):
    drawn = []
    monkeypatch.setattr(report, "render_mermaid", lambda code, png, renderer=None, width=1500: drawn.append(png.name))
    text = ("# Title\n\nReport date: 1 January 2026.\n\n## Abstract\n\nBody.\n\n<!-- diagram:method -->\n```mermaid\n"
            + report.diagram_source("method") + "\n```\n<!-- /diagram -->\n\n*Figure 2. The method,\nover two lines.*\n\nTail.\n")
    out = report.pdf_markdown(text, tmp_path, tmp_path / "work")
    assert out.startswith("## Abstract") and "# Title" not in out
    assert drawn == ["method.png"]
    assert "![Figure 2. The method, over two lines.](" in out and "{width=80%}" in out and "*Figure 2" not in out


def test_pdf_markdown_uses_real_plus_minus_and_minus_signs(tmp_path):
    out = report.pdf_markdown("## Abstract\n\nGain +0.028R +-0.078, drop -0.079R, years 2019-2024, a 5-min bar, in `--flag-1`.\n", tmp_path, tmp_path / "w")
    assert "+0.028R \u00b10.078" in out and "+-" not in out
    assert "\u22120.079R" in out
    assert "2019-2024" in out and "5-min" in out and "--flag-1" in out
