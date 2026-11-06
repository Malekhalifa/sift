"""Draw docs/img/forest.svg for docs/findings.md: out-of-sample expectancy per idea with 95% intervals.

    uv run python scripts/make_findings_chart.py

The numbers are copied from the recorded results (docs/m*-results.md); nothing is recomputed here. Market-adjusted values
exist only from M7 on, when that check was added.
"""

from __future__ import annotations

from pathlib import Path

# label, raw (mean, +-95%), market-adjusted (mean, +-95%) or None
ROWS = [
    ("Opening-range breakout, 10 stocks (M4)", (0.065, 0.114), None),
    ("Failed-breakout fade, 10 stocks (M4)", (-0.000, 0.042), None),
    ("Opening-range breakout, 50 stocks (M4b)", (-0.046, 0.028), None),
    ("RSI(2) mean reversion (M6)", (-0.026, 0.021), None),
    ("20/200-day pullback (M6)", (-0.032, 0.028), None),
    ("Earnings drift, 149 stocks (M7)", (0.156, 0.099), (0.090, 0.094)),
    ("Same setting, 250 unseen stocks (M8)", (0.025, 0.077), (0.023, 0.072)),
    ("UT Bot + Schaff Trend Cycle (M9)", (-0.038, 0.006), None),
    ("Supertrend + Waddah Attar (M9)", (-0.042, 0.005), None),
    ("Insider buying, Form 4 (M10)", (0.028, 0.078), (-0.079, 0.065)),
    ("Volume-dry-up reversal (M11)", (-0.008, 0.010), (-0.010, 0.009)),
    ("High-volume continuation (M11)", (0.100, 0.019), (-0.039, 0.018)),
]
BLUE, ORANGE, GREY, INK = "#3a3a3a", "#8c1c33", "#cfcfcf", "#1a1a1a"
LEFT, RIGHT, TOP, ROW_H = 395, 40, 84, 42
LO, HI, WIDTH = -0.20, 0.30, 1040


def main() -> None:
    plot_w = WIDTH - LEFT - RIGHT
    x = lambda v: LEFT + (v - LO) / (HI - LO) * plot_w  # noqa: E731
    height = TOP + len(ROWS) * ROW_H + 70
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" '
        f'font-family="Latin Modern Roman, CMU Serif, Georgia, serif" role="img" aria-label="Out-of-sample expectancy per trading idea">',
        f'<rect width="{WIDTH}" height="{height}" fill="white"/>',
        f'<text x="20" y="32" font-size="22" font-weight="600" fill="{INK}">Out-of-sample expectancy per trade, twelve ideas (R, after costs)</text>',
        f'<text x="20" y="56" font-size="14.5" fill="#5b6672">Dot = result, line = 95% confidence interval. Zero means no edge. Red = after subtracting what simply holding the market earned.</text>',
    ]
    for tick in (-0.2, -0.1, 0.0, 0.1, 0.2, 0.3):
        zero = tick == 0.0
        dash = "" if zero else ' stroke-dasharray="3 4"'
        out.append(f'<line x1="{x(tick):.1f}" y1="{TOP - 8}" x2="{x(tick):.1f}" y2="{TOP + len(ROWS) * ROW_H}" '
                   f'stroke="{INK if zero else GREY}" stroke-width="{1.6 if zero else 1}"{dash}/>')
        name = "0R" if zero else f"{tick:+.1f}R"
        out.append(f'<text x="{x(tick):.1f}" y="{TOP + len(ROWS) * ROW_H + 20}" font-size="14" text-anchor="middle" fill="#5b6672">{name}</text>')
    for i, (label, raw, adj) in enumerate(ROWS):
        cy = TOP + i * ROW_H + ROW_H / 2
        if i % 2 == 0:
            out.insert(2, f'<rect x="10" y="{cy - ROW_H / 2:.1f}" width="{WIDTH - 20}" height="{ROW_H}" fill="#f6f5f4"/>')
        out.append(f'<text x="{LEFT - 14}" y="{cy + 4:.1f}" font-size="15" text-anchor="end" fill="{INK}">{label}</text>')
        for value, color, dy, shape in ((raw, BLUE, -6 if adj else 0, "circle"), (adj, ORANGE, 7, "diamond")):
            if value is None:
                continue
            mean, half = value
            y = cy + dy
            lo, hi = max(mean - half, LO), min(mean + half, HI)
            out.append(f'<line x1="{x(lo):.1f}" y1="{y:.1f}" x2="{x(hi):.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="2.2"/>')
            if shape == "circle":
                out.append(f'<circle cx="{x(mean):.1f}" cy="{y:.1f}" r="4.6" fill="{color}"/>')
            else:
                cx = x(mean)
                out.append(f'<polygon points="{cx:.1f},{y - 5.5:.1f} {cx + 5.5:.1f},{y:.1f} {cx:.1f},{y + 5.5:.1f} {cx - 5.5:.1f},{y:.1f}" fill="{color}"/>')
    ly = height - 22
    out += [
        f'<circle cx="{LEFT}" cy="{ly - 4}" r="4.6" fill="{BLUE}"/><text x="{LEFT + 12}" y="{ly}" font-size="14" fill="{INK}">result as tested</text>',
        f'<polygon points="{LEFT + 190},{ly - 9.5} {LEFT + 195.5},{ly - 4} {LEFT + 190},{ly + 1.5} {LEFT + 184.5},{ly - 4}" fill="{ORANGE}"/>'
        f'<text x="{LEFT + 204}" y="{ly}" font-size="14" fill="{INK}">after subtracting the market (checked from M7 on)</text>',
        "</svg>",
    ]
    path = Path(__file__).resolve().parents[1] / "docs" / "img" / "forest.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
