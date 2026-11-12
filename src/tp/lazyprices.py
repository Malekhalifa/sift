"""M18: Lazy Prices, year-over-year change in the 10-K risk-factor text (docs/m18-lazyprices-protocol.md)."""

from __future__ import annotations

import html
import json
import math
import re
from collections import Counter

# The fixed list of 120 common English words dropped before counting (frozen in the M18 protocol).
STOPWORDS = frozenset(
    """
    the and for that with this are our from have not but which may could would such than any can other these
    their its has was will been were also more into over under between those there when where while who whom what
    why how all some most each both either neither about above after again against before below during further
    here once only own same then too very out off down you your yours they them his her hers she him himself
    itself ourselves themselves being having does did doing should because until upon within without among
    through whether however therefore thereby thereof herein hereby shall must might many much including certain
    per via etc thus hence whose just
    """.split()
)
MIN_SECTION_CHARS = 3000
_ITEM_1A = re.compile(r"^[ \t]*item\s*1a\.?\s*[-\u2013\u2014:.]?\s*risk\s*factors", re.I | re.M)
_END = re.compile(r"^[ \t]*(?:item\s*1b\b|item\s*2\.?\s*[-\u2013\u2014:.]?\s*(?:description\s+of\s+)?propert)", re.I | re.M)
_HIDDEN = re.compile(r"<ix:header>.*?</ix:header>|<script.*?</script>|<style.*?</style>", re.I | re.S)
_BLOCK = re.compile(r"</?(?:p|div|br|tr|li|h[1-6]|table|section)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z]{3,}")


def html_to_text(raw: str) -> str:
    """Tags stripped, block tags turned into line breaks, entities decoded, whitespace squeezed inside lines."""
    text = _BLOCK.sub("\n", _HIDDEN.sub(" ", raw))
    text = html.unescape(_TAG.sub(" ", text)).replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n") if ln.strip())


def item_1a(text: str) -> str | None:
    """The longest section from an 'Item 1A Risk Factors' heading to the next 'Item 1B' / 'Item 2 Properties' heading
    (the longest skips the table of contents). None if there is none of at least MIN_SECTION_CHARS."""
    best = ""
    for start in _ITEM_1A.finditer(text):
        end = _END.search(text, start.end())
        section = text[start.end() : end.start() if end else len(text)]
        if end and len(section) > len(best):
            best = section
    return best if len(best) >= MIN_SECTION_CHARS else None


def word_counts(section: str) -> dict[str, int]:
    return dict(Counter(w for w in _WORD.findall(section.lower()) if w not in STOPWORDS))


def cosine(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return float("nan")
    dot = sum(v * b[k] for k, v in a.items() if k in b)
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def counts_to_json(counts: dict[str, int]) -> str:
    return json.dumps(counts, separators=(",", ":"), sort_keys=True)
