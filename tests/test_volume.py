import pandas as pd
import pytest

from conftest import dbars
from tp.strategies import REGISTRY, VolumeReversal, VolumeSpike

FLAT = (100, 101, 99, 100)


def with_volume(bars, volumes):
    bars = bars.copy()
    bars["volume"] = volumes
    return bars


def stock(closes, volumes):
    rows = [FLAT] * 40 + [(c + 1, c + 2, c - 1, c) for c in closes]
    n = len(rows)
    return with_volume(dbars(rows, start="2024-01-02"), [1000] * 40 + list(volumes) + [1000] * (n - 40 - len(volumes)))


def spy(n):
    return dbars([FLAT] * n, start="2024-01-02")


DROP = [98, 96, 94, 92, 90, 90]
RISE = [102, 104, 106, 108, 110, 110]


def test_volrev_buys_a_quiet_decline_against_the_market():
    bars = stock(DROP, [500] * 6)
    sigs = VolumeReversal(vol_max=1.0, mult=2.0).generate("X", bars, None, spy(len(bars)))
    assert sigs and {s.side for s in sigs} == {"long"} and all(s.tag == "volrev" for s in sigs)
    first = sigs[0]
    assert first.stop < first.entry_ref < first.target
    assert first.ts.tz_convert("America/New_York").hour == 16  # decided at a session close


def test_volrev_volume_condition_blocks_a_loud_decline_but_off_allows_it():
    bars = stock(DROP, [3000] * 6)
    assert VolumeReversal(vol_max=1.0).generate("X", bars, None, spy(len(bars))) == []
    assert VolumeReversal(vol_max=0.0).generate("X", bars, None, spy(len(bars)))


def test_volrev_sells_a_quiet_rise_and_ignores_moves_the_market_made():
    bars = stock(RISE, [500] * 6)
    assert {s.side for s in VolumeReversal(vol_max=1.0).generate("X", bars, None, spy(len(bars)))} == {"short"}
    market_fell = dbars([FLAT] * 40 + [(c + 1, c + 2, c - 1, c) for c in DROP], start="2024-01-02")  # SPY drops the same way
    assert VolumeReversal(vol_max=0.0).generate("X", stock(DROP, [500] * 6), None, market_fell) == []


def test_volrev_needs_spy():
    with pytest.raises(ValueError):
        VolumeReversal().generate("X", stock(DROP, [500] * 6), None, None)


def spike_stock():
    closes = [100] * 15 + [100.2] + [100] * 3 + [110]  # day 56: a quiet spike; day 60: a spike with a 10% move
    rows = [FLAT] * 40 + [(c, c + 1, c - 1, c) for c in closes]
    vol = [1000] * 40 + [1000] * 15 + [5000] + [1000] * 3 + [9000]
    return with_volume(dbars(rows, start="2024-01-02"), vol)


def test_volspike_fires_on_the_highest_volume_day_long_only():
    bars = spike_stock()
    days = lambda sigs: [s.ts.tz_convert("America/New_York").date().isoformat() for s in sigs]  # noqa: E731
    both = VolumeSpike(window=20, ret_max=0.0).generate("X", bars)
    assert {s.side for s in both} == {"long"} and len(both) == 2
    capped = VolumeSpike(window=20, ret_max=1.0).generate("X", bars)
    assert len(capped) == 1 and days(capped)[0] == bars.index[55].tz_convert("America/New_York").date().isoformat()
    assert len(VolumeSpike(window=50, ret_max=0.0).generate("X", bars)) == 2  # a 50-session window still sees both


def test_registry_and_validation():
    assert REGISTRY["volrev"] is VolumeReversal and REGISTRY["volspike"] is VolumeSpike
    with pytest.raises(ValueError):
        VolumeSpike(window=1)
    with pytest.raises(ValueError):
        VolumeReversal(mult=0.0)
