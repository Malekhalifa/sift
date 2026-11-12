import math

from tp import lazyprices as lp

BODY = " ".join(["Our results could be hurt by competition and regulation of our supplier network."] * 60)


def _doc(real=BODY, cross_ref=True):
    ref = "<p>For more detail see Item 1A. Risk Factors below.</p>" if cross_ref else ""
    return (
        "<html><ix:header>HIDDEN item 1a risk factors</ix:header><body>"
        "<table><tr><td>Item 1A.</td><td>Risk Factors</td><td>12</td></tr><tr><td>Item 1B.</td><td>Unresolved</td><td>20</td></tr></table>"
        f"<p>Item 1. Business</p><p>We sell goods.</p>{ref}"
        f"<p><b>Item 1A.</b> <b>Risk&nbsp;Factors</b></p><p>{real}</p><p>Item 1B. Unresolved Staff Comments</p><p>None</p></body></html>"
    )


def test_stopword_list_is_the_registered_120():
    assert len(lp.STOPWORDS) == 120


def test_item_1a_skips_table_of_contents_and_cross_references():
    section = lp.item_1a(lp.html_to_text(_doc()))
    assert section is not None and "competition" in section
    assert "We sell goods" not in section and "HIDDEN" not in section


def test_short_or_missing_section_is_rejected():
    assert lp.item_1a(lp.html_to_text(_doc(real="Not required for smaller reporting companies."))) is None
    assert lp.item_1a("just some text") is None


def test_counts_drop_stopwords_and_short_words():
    c = lp.word_counts("The supplier and the supplier of an oil rig")
    assert c == {"supplier": 2, "oil": 1, "rig": 1}


def test_cosine_identical_is_one_and_disjoint_is_zero():
    a = {"x": 2, "y": 1}
    assert math.isclose(lp.cosine(a, dict(a)), 1.0)
    assert lp.cosine(a, {"z": 3}) == 0.0
    assert math.isnan(lp.cosine({}, a))
