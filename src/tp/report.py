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
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS = ROOT / "docs" / "diagrams"
REPORT_DIR = ROOT / "docs" / "report"
DEFAULT_RENDERER = Path(os.environ.get("PRETTY_MERMAID_DIR", Path.home() / ".claude" / "skills" / "pretty-mermaid"))
THEME = "nord-light"
FIGURE_WIDTHS = {"pipeline": "78%", "method": "70%", "verdicts": "100%"}  # share of the text width; anything else is full width

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


def keep_together(text: str) -> str:
    """Raw LaTeX before every heading and table: if too little room is left on the page, start a new one, so a table or a
    section never begins at the foot of a page and leaves its content on the next. A heading that is followed directly by a
    table asks for the room of the whole table, so the two stay together."""
    def table_lines(block: str) -> int:
        """Rendered height in lines: each row is as tall as its most wrapped cell. Columns share the width in proportion to the
        dashes of the separator row (as pandoc sets them), about 105 characters per full-width line at table size."""
        rows = [r for r in block.split("\n") if r.strip()]
        if len(rows) < 3:
            return 8
        dashes = [max(len(c.strip()), 1) for c in rows[1].strip().strip("|").split("|")]
        total, lines = sum(dashes), 0
        for row in [rows[0], *rows[2:]]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            lines += max([-(-len(c) // max(6, int(105 * d / total))) for c, d in zip(cells, dashes)] + [1])
        return min(int(lines * 1.3) + 5, 46)

    def figure_lines(block: str) -> int:
        """Height of an image paragraph in lines, from the PNG's aspect ratio and its share of the 15.8 cm text width."""
        m = re.match(r"!\[[^\]]*\]\(([^)\s]+)\)(?:\{width=(\d+)%\})?", block)
        if not m or not Path(m.group(1)).exists():
            return 9
        with open(m.group(1), "rb") as f:
            f.read(16)
            w, h = struct.unpack(">II", f.read(8))
        height_cm = 15.8 * int(m.group(2) or 100) / 100 * h / w
        return int(height_cm / 0.51) + 4

    blocks = text.split("\n\n")
    out, in_code = [], False
    for i, block in enumerate(blocks):
        if not in_code:
            first = block.lstrip().split("\n", 1)[0]
            following = blocks[i + 1] if i + 1 < len(blocks) else ""
            if block.startswith("|"):
                if not (i and blocks[i - 1].lstrip().startswith(("## ", "### "))):  # else the heading already asked for the room
                    out.append(f"\\Needspace{{{table_lines(block)}\\baselineskip}}")
            elif first.startswith(("## ", "### ")):
                if following.startswith("|"):
                    need = table_lines(following) + 3
                elif following.startswith("!["):
                    need = min(figure_lines(following) + 3, 46)
                elif i + 2 < len(blocks) and blocks[i + 2].startswith("|") and len(following) < 400:
                    need = min(table_lines(blocks[i + 2]) + 3 + len(following) // 80 + 1, 46)  # heading, short intro, table
                else:
                    need = 9
                out.append(f"\\Needspace{{{need}\\baselineskip}}")
        if block.count("```") % 2 == 1:
            in_code = not in_code
        out.append(block)
    return "\n\n".join(out)


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
    text = keep_together(text[head:] if head != -1 else text)
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
    icon = work / "icon.png"
    svg_to_png(ROOT / "assets" / "icon.svg", icon, 512)
    cover = work / "cover.tex"
    cover.write_text((REPORT_DIR / "cover.tex").read_text().replace("@DATE@", date).replace("@ICON@", str(icon)))
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pandoc", str(body), "-f", "markdown+pipe_tables+implicit_figures", "-o", str(out_pdf), "--pdf-engine=xelatex",
         "--toc", "--toc-depth=1", "--shift-heading-level-by=-1", "--highlight-style=tango", f"--include-in-header={REPORT_DIR / 'header.tex'}",
         f"--include-before-body={cover}", "--resource-path", str(work),
         "-V", "documentclass=article", "-V", "classoption=table", "-V", "papersize=a4",
         "-V", "geometry:top=2.3cm,bottom=2.7cm,left=2.6cm,right=2.6cm", "-V", "fontsize=11pt", "-V", "linestretch=1.1",
         "-V", "mainfont=Charter", "-V", "monofont=Menlo", "-V", "colorlinks=true", "-V", "linkcolor=accent",
         "-V", "urlcolor=accent", "-V", "toccolor=ink", "-V", "title-meta=Twelve trading ideas, tested honestly on free data",
         "-V", "subject=Pre-registered negative-results report on short-term US stock strategies"],
        check=True, capture_output=True, text=True,
    )
