"""M18 parse-rate gate (docs/m18-lazyprices-protocol.md): data checks only, no returns.

    uv run python scripts/lazyprices_gate.py
"""

from __future__ import annotations

import pandas as pd

from tp import config, lazyprices

GATE = 0.70


def with_similarity(filings: pd.DataFrame) -> pd.DataFrame:
    """Per symbol: for each ok filing, the cosine to its previous-year ok filing (300-430 days earlier, nearest 365), else NaN."""
    ok = filings[filings["status"] == "ok"].sort_values("filed_at").reset_index(drop=True)
    counts = [__import__("json").loads(c) for c in ok["counts"]]
    sims = []
    for i, f in enumerate(ok.itertuples()):
        gap = (f.filed_at - ok["filed_at"]).dt.days.to_numpy()
        cand = [j for j in range(len(ok)) if 300 <= gap[j] <= 430]
        sims.append(lazyprices.cosine(counts[i], counts[min(cand, key=lambda j: abs(gap[j] - 365))]) if cand else float("nan"))
    return ok[["symbol", "accn", "filed_at"]].assign(similarity=sims)


def main() -> None:
    rf = pd.read_parquet(config.DATA_DIR / "riskfactors" / "riskfactors.parquet")
    rf["year"] = rf["filed_at"].dt.year
    print("Filings by year (parsed ok / all):")
    for y, g in rf.groupby("year"):
        print(f"  {y}: {int((g['status'] == 'ok').sum())} / {len(g)}  ({(g['status'] == 'ok').mean():.0%})")
    overall = (rf["status"] == "ok").mean()
    window = rf[(rf["year"] >= 2016) & (rf["year"] <= 2024)]
    sims = pd.concat([with_similarity(g) for _, g in rf.groupby("symbol")], ignore_index=True)
    sims = sims[(sims["filed_at"].dt.year >= 2016)]
    paired = sims["similarity"].notna().sum() / len(window)
    print(f"\nParse rate, all 10-Ks 2015-2024: {overall:.1%}  (gate {GATE:.0%})")
    print(f"2016-2024 10-Ks with a valid section AND a valid previous-year section: {paired:.1%}  (gate {GATE:.0%})")
    print("GATE " + ("PASSED" if overall >= GATE and paired >= GATE else "FAILED: inconclusive for data reasons; fix the parser and re-register"))
    print(f"similarity quartiles: {sims['similarity'].describe()[['25%', '50%', '75%']].round(3).to_dict()}")


if __name__ == "__main__":
    main()
