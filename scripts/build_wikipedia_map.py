"""Propose Wikipedia articles for the events universe, for a human to review.

    uv run python scripts/build_wikipedia_map.py [--out config/wikipedia_articles.candidates.toml]

For each symbol in the `events` universe the company name comes from Alpaca's asset list, and the top hit of Wikipedia's
title search becomes the candidate article. The result goes to config/wikipedia_articles.candidates.toml, never to the
reviewed config/wikipedia_articles.toml that the recorder reads: check every line (a name can match a product, a person
or a disambiguation page) and copy the accepted ones under [articles] in the reviewed file by hand. Symbols with no name
or no match are listed as comments. Makes one search request per symbol, 0.2 s apart; writes nothing if any request fails.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import httpx

from tp import config
from tp.alpaca_data import AlpacaClient

SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/title"
UA = {"User-Agent": "sift-research (market data research; python-httpx)"}
SPACING_S = 0.2
REVIEWED_PATH = config.ROOT / "config" / "wikipedia_articles.toml"
CANDIDATES_PATH = config.ROOT / "config" / "wikipedia_articles.candidates.toml"
HEADER = (
    "# CANDIDATES, not reviewed: one SYMBOL = \"Article_Title\" per line, matched by name from Wikipedia's title search.\n"
    "# Check each line, then copy the accepted ones under [articles] in config/wikipedia_articles.toml.\n"
)
SUFFIX = re.compile(  # trailing share-class words, repeated: "Class A Common Stock", "American Depositary Shares", ...
    r"(?:[\s,]+(?:class\s+[a-z0-9]+|new|common|ordinary|stock|shares?|units?|adr|ads"
    r"|(?:american\s+)?depositary\s+(?:shares|receipts?)))+\s*$",
    re.IGNORECASE,
)


class SearchFailed(Exception):
    """Wikipedia's search gave no usable answer."""


def company_name(raw: str) -> str:
    """The Alpaca asset name without a trailing share-class description ("Apple Inc. Common Stock" -> "Apple Inc.")."""
    return SUFFIX.sub("", " ".join(raw.split())).strip()


def search_title(http, name: str) -> str | None:
    """The top search hit as an article key (underscores), None when nothing matches."""
    try:
        r = http.get(f"{SEARCH_URL}?{httpx.QueryParams({'q': name, 'limit': 1})}")
        r.raise_for_status()
        body = r.json()
    except httpx.HTTPError as e:
        raise SearchFailed(f"search for {name!r} failed: {type(e).__name__}: {e}") from e
    except ValueError as e:
        raise SearchFailed(f"search for {name!r}: response is not JSON") from e
    pages = body.get("pages") if isinstance(body, dict) else None
    if not isinstance(pages, list):
        raise SearchFailed(f"search for {name!r}: response has no 'pages' list")
    if not pages:
        return None
    hit = pages[0] if isinstance(pages[0], dict) else {}
    title = hit.get("key") or str(hit.get("title") or "").replace(" ", "_")
    if not isinstance(title, str) or not title:
        raise SearchFailed(f"search for {name!r}: top hit has no title")
    return title


def _key(symbol: str) -> str:
    return symbol if re.fullmatch(r"[A-Za-z0-9_-]+", symbol) else f'"{symbol}"'


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_candidates(symbols: list[str], names: dict[str, str], http) -> str:
    """The candidates file text. SearchFailed when any request fails."""
    lines = [HEADER, "[articles]"]
    asked = 0
    for symbol in symbols:
        raw = names.get(symbol, "")
        name = company_name(raw)
        if not name:
            lines.append(f"# {symbol}: no company name in Alpaca's asset list")
            continue
        if asked:
            time.sleep(SPACING_S)
        asked += 1
        title = search_title(http, name)
        if title is None:
            lines.append(f"# {symbol}: no Wikipedia match for {_quote(name)}")
        else:
            lines.append(f"{_key(symbol)} = {_quote(title)}  # matched from {_quote(raw)}")
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None, client=None, http=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=CANDIDATES_PATH, help="candidates file to write")
    args = parser.parse_args(argv)
    if args.out.resolve() == REVIEWED_PATH.resolve():
        print(f"refusing to write the reviewed file {REVIEWED_PATH}; the candidates go to {CANDIDATES_PATH}", file=sys.stderr)
        return 2
    client = client or AlpacaClient(config.Settings.from_env())
    names = {a["symbol"]: a.get("name") or "" for a in client.assets()}
    symbols = config.events_symbols()
    owned = http is None
    http = http or httpx.Client(headers=UA, timeout=30.0, follow_redirects=True)
    try:
        text = build_candidates(symbols, names, http)
    except SearchFailed as e:
        print(f"{e}; nothing written", file=sys.stderr)
        return 1
    finally:
        if owned:
            http.close()
    write_atomic(args.out, text)
    matched = sum(1 for line in text.splitlines() if line and line[0] not in "#[")
    print(f"{matched} candidates for {len(symbols)} symbols written to {args.out}; review before use", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
