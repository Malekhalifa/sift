"""Build the research report: keep the Mermaid diagrams identical in every markdown file, render them, and typeset the PDF.

The diagram sources live in docs/diagrams/*.mmd. Markdown files embed them between marker comments

    <!-- diagram:pipeline -->
    ```mermaid
    ...
    ```
    <!-- /diagram -->

so GitHub renders them natively. `sync_diagrams` rewrites those blocks from the source files, a test checks nothing has
drifted, and `build_pdf` renders each block to PNG (local Node renderer, no browser) and runs pandoc with XeLaTeX.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS = ROOT / "docs" / "diagrams"
REPORT_DIR = ROOT / "docs" / "report"
DEFAULT_RENDERER = Path(os.environ.get("PRETTY_MERMAID_DIR", Path.home() / ".claude" / "skills" / "pretty-mermaid"))
THEME = "nord-light"
FIGURE_WIDTHS = {"pipeline": "86%", "method": "80%", "verdicts": "100%"}  # share of the text width; anything else is full width

MARKED = re.compile(r"(<!-- diagram:(?P<name>[\w-]+) -->\n)```mermaid\n.*?\n```\n(<!-- /diagram -->)", re.S)
FENCE = re.compile(r"```mermaid\n(?P<code>.*?)\n```\n", re.S)
# An image paragraph followed by an italic "*Figure N. ...*" paragraph: the caption moves into the image alt text.
CAPTIONED = re.compile(r"(?P<img>!\[[^\]]*\]\((?P<src>[^)\s]+)\)(?:\{[^}]*\})?)\n\n\*(?P<cap>Figure \d+\..*?)\*\n", re.S)


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


def svg_to_png(svg: Path, png: Path, width: int = 1920) -> None:
    subprocess.run(["rsvg-convert", "-w", str(width), str(svg), "-o", str(png)], check=True, capture_output=True, text=True)


def name_of(code: str) -> str | None:
    for path in DIAGRAMS.glob("*.mmd"):
        if path.read_text().rstrip("\n") == code.rstrip("\n"):
            return path.stem
    return None


def pdf_markdown(text: str, source_dir: Path, work: Path, renderer: Path = DEFAULT_RENDERER) -> str:
    """Markdown ready for pandoc: mermaid blocks and SVGs become PNG figures (with their captions); the title block above
    the Abstract is dropped (the cover page carries it)."""
    work.mkdir(parents=True, exist_ok=True)
    widths: dict[str, str] = {}

    def draw(m: re.Match) -> str:
        code = m.group("code")
        stem = name_of(code) or hashlib.sha1(code.encode()).hexdigest()[:8]
        png = work / f"{stem}.png"
        render_mermaid(code, png, renderer)
        widths[str(png)] = FIGURE_WIDTHS.get(stem, "100%")
        return f"![]({png})\n"

    text = FENCE.sub(draw, text)
    text = re.sub(r"<!-- /?diagram[^>]*-->\n?", "", text)

    def vector(m: re.Match) -> str:
        src = (source_dir / m.group(2)).resolve()
        png = work / (src.stem + ".png")
        svg_to_png(src, png)
        return f"![{m.group(1)}]({png})"

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+\.svg)\)", vector, text)

    def caption(m: re.Match) -> str:
        cap = " ".join(m.group("cap").split()).replace("[", "(").replace("]", ")")
        width = widths.get(m.group("src"), "100%")
        return f"![{cap}]({m.group('src')}){{width={width}}}\n"

    text = CAPTIONED.sub(caption, text)
    head = text.find("## Abstract")
    text = text[head:] if head != -1 else text
    # typography: +-0.1 becomes a plus-minus sign, and a leading hyphen before a digit becomes a true minus sign
    text = re.sub(r"\+-(?=\s?\d)", "\u00b1", text)
    return re.sub(r"(?<![\w\-/.])-(?=\d)", "\u2212", text)


def build_pdf(markdown: Path, out_pdf: Path, renderer: Path = DEFAULT_RENDERER) -> None:
    for tool in ("pandoc", "xelatex", "rsvg-convert", "node"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found on PATH")
    raw = markdown.read_text()
    date = (re.search(r"Report date: ([^.]+)\.", raw) or [None, ""])[1]
    work = ROOT / "data" / "report_build"
    shutil.rmtree(work, ignore_errors=True)
    body = work / "report.md"
    work.mkdir(parents=True)
    body.write_text(pdf_markdown(sync_diagrams(raw), markdown.parent, work, renderer))
    cover = work / "cover.tex"
    cover.write_text((REPORT_DIR / "cover.tex").read_text().replace("@DATE@", date))
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pandoc", str(body), "-f", "markdown+pipe_tables+implicit_figures", "-o", str(out_pdf), "--pdf-engine=xelatex",
         "--toc", "--toc-depth=2", "--highlight-style=tango", f"--include-in-header={REPORT_DIR / 'header.tex'}",
         f"--include-before-body={cover}", "--resource-path", str(work),
         "-V", "documentclass=article", "-V", "geometry:margin=2.3cm", "-V", "fontsize=10.5pt", "-V", "linestretch=1.12",
         "-V", "mainfont=Avenir Next", "-V", "monofont=Menlo", "-V", "colorlinks=true", "-V", "linkcolor=accent",
         "-V", "urlcolor=accent", "-V", "toccolor=ink", "-V", "title-meta=Twelve trading ideas, tested honestly on free data",
         "-V", "subject=Pre-registered negative-results report on short-term US stock strategies"],
        check=True, capture_output=True, text=True,
    )
