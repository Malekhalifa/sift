"""Build the research whitepaper: keep the Mermaid diagrams identical in every markdown file, render them, typeset the PDF.

The diagram sources live in docs/diagrams/*.mmd. Markdown files embed them between marker comments

    <!-- diagram:pipeline -->
    ```mermaid
    ...
    ```
    <!-- /diagram -->

so GitHub renders them natively. `sync_diagrams` rewrites those blocks from the source files, a test checks nothing has
drifted. The PDF is the LaTeX whitepaper (docs/whitepaper/sift-whitepaper.tex); `build_whitepaper` renders its figures
(Mermaid through a local Node renderer, no browser) and typesets it with XeLaTeX.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS = ROOT / "docs" / "diagrams"
DEFAULT_RENDERER = Path(os.environ.get("PRETTY_MERMAID_DIR", Path.home() / ".claude" / "skills" / "pretty-mermaid"))
THEME = "nord-light"

MARKED = re.compile(r"(<!-- diagram:(?P<name>[\w-]+) -->\n)```mermaid\n.*?\n```\n(<!-- /diagram -->)", re.S)


def diagram_source(name: str) -> str:
    return (DIAGRAMS / f"{name}.mmd").read_text().rstrip("\n")


def sync_diagrams(text: str) -> str:
    """Replace every marked mermaid block in `text` with the current contents of its .mmd source."""
    def swap(m: re.Match) -> str:
        return f"{m.group(1)}```mermaid\n{diagram_source(m.group('name'))}\n```\n{m.group(3)}"
    return MARKED.sub(swap, text)


def out_of_sync(paths: list[Path]) -> list[Path]:
    return [p for p in paths if sync_diagrams(p.read_text()) != p.read_text()]


def render_mermaid(source: str, png: Path, renderer: Path = DEFAULT_RENDERER, width: int = 1500) -> None:
    """Mermaid text -> PNG with the Pretty Mermaid CLI (Node, no browser)."""
    if not (renderer / "scripts" / "render.mjs").exists() or not (renderer / "node_modules").exists():
        raise SystemExit(f"Pretty Mermaid renderer not installed at {renderer} (set PRETTY_MERMAID_DIR); run npm ci --ignore-scripts there.")
    mmd = png.with_suffix(".mmd")
    mmd.write_text(source)
    subprocess.run(
        ["node", str(renderer / "scripts" / "render.mjs"), "--input", str(mmd), "--output", str(png), "--format", "png",
         "--width", str(width), "--theme", THEME, "--transparent", "--layer-spacing", "22", "--node-spacing", "18", "--padding", "24",
         "--fg", "#1d2733", "--line", "#4a5b73", "--border", "#8493a9", "--accent", "#1f4e79", "--surface", "#e9eef5"],
        check=True, capture_output=True, text=True,
    )


WHITEPAPER = ROOT / "docs" / "whitepaper"
WHITEPAPER_TEX = WHITEPAPER / "sift-whitepaper.tex"


def build_whitepaper(out_pdf: Path, renderer: Path = DEFAULT_RENDERER) -> None:
    """Render the figures the whitepaper uses into docs/whitepaper/figures and typeset sift-whitepaper.tex with XeLaTeX
    (three passes, for the contents, cross-references and page count)."""
    for tool in ("xelatex", "rsvg-convert", "node"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found on PATH")
    figures = WHITEPAPER / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for name in ("pipeline", "method", "verdicts"):
        png = figures / f"{name}.png"
        render_mermaid(diagram_source(name), png, renderer, width=2400)
        png.with_suffix(".mmd").unlink(missing_ok=True)
    for svg, pdf in ((ROOT / "docs" / "img" / "forest.svg", figures / "forest.pdf"), (ROOT / "assets" / "icon.svg", figures / "icon.pdf")):
        subprocess.run(["rsvg-convert", "-f", "pdf", str(svg), "-o", str(pdf)], check=True, capture_output=True, text=True)
    build = ROOT / "data" / "whitepaper_build"
    build.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        run = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={build}", WHITEPAPER_TEX.name],
                             cwd=WHITEPAPER, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"xelatex failed; see {build / 'sift-whitepaper.log'}")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(build / "sift-whitepaper.pdf", out_pdf)
