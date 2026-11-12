"""The manual rebuild scripts keep what the recorder added to the legacy files and never leave a half-written file."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from tp import config, insiders
from tp.collect import datasets, store
from tp.collect.sources import sec

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
INGESTED = pd.Timestamp("2026-11-01", tz="UTC")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_merge_test", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    """An EdgarClient that knows one ticker and serves canned filings; nothing touches the network."""

    def __init__(self, eightk: pd.DataFrame | None = None, earnings: pd.DataFrame | None = None) -> None:
        self._eightk, self._earnings = eightk, earnings

    def ticker_map(self) -> dict[str, int]:
        return {"AAA": 1000} if self._eightk is not None or self._earnings is not None else {}

    def eightk_filings(self, cik: int) -> pd.DataFrame:
        return self._eightk.copy()

    def earnings_filings(self, cik: int) -> pd.DataFrame:
        return self._earnings.copy()


@pytest.fixture(autouse=True)
def universe(monkeypatch):
    monkeypatch.setattr(config, "load_universe", lambda: {"universe": {"traded": ["AAA"], "regime": []}})
    monkeypatch.setattr(config, "events_symbols", lambda: [])
    monkeypatch.setattr(config, "confirm_symbols", lambda: [])


def seed(name: str, frame: pd.DataFrame) -> Path:
    path = datasets.dataset(name).path
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def failing_write(monkeypatch):
    real = pd.DataFrame.to_parquet

    def failing(self, path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            Path(path).write_text("partial")
            raise OSError("disk full")
        return real(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", failing)
    return lambda: monkeypatch.setattr(pd.DataFrame, "to_parquet", real)


def no_tmp(path: Path) -> bool:
    return not list(path.parent.glob("*.tmp"))


# store.merge_rebuilt

def test_merge_rebuilt_without_a_stored_file_returns_the_rebuilt_frame():
    ds = datasets.dataset("eightk")
    rebuilt = pd.DataFrame({"symbol": ["AAA"], "accession": ["a1"], "filed_at": [pd.Timestamp("2024-01-02", tz="UTC")], "items": ["1.01"]})
    assert store.merge_rebuilt(ds, rebuilt).equals(rebuilt)


def test_merge_rebuilt_refuses_an_unreadable_stored_file():
    ds = datasets.dataset("eightk")
    ds.path.parent.mkdir(parents=True, exist_ok=True)
    ds.path.write_bytes(b"not parquet")
    with pytest.raises(store.StoreError):
        store.merge_rebuilt(ds, pd.DataFrame())


# scripts/fetch_shares.py

def shares_frame(symbol: str, accn: str, end: str) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": [symbol], "cik": pd.Series([1000], dtype="int64"), "accn": [accn], "form": ["10-Q"],
        "filed": pd.to_datetime(["2024-05-01"]), "end": pd.to_datetime([end]), "val": [10.0],
    })


@pytest.fixture
def shares(monkeypatch):
    mod = load("fetch_shares")
    monkeypatch.setattr(mod, "EdgarClient", lambda: FakeClient())
    monkeypatch.setattr(sec, "xbrl_symbols", lambda: ["AAA"])
    by_symbol = config.DATA_DIR / "xbrl" / "by_symbol"
    by_symbol.mkdir(parents=True)
    rebuilt = pd.concat([shares_frame("AAA", "a1", "2024-03-31"), shares_frame("AAA", "a2", "2024-06-30")], ignore_index=True)
    rebuilt.to_parquet(by_symbol / "AAA.parquet", index=False)
    stored = pd.concat([shares_frame("AAA", "a1", "2024-03-31"), shares_frame("ZZZ", "z1", "2024-03-31")], ignore_index=True)
    stored["ingested_at"] = INGESTED
    return mod, seed("xbrl_shares", stored), stored


def test_shares_rebuild_keeps_recorder_rows_and_ingested_at(shares):
    mod, path, _ = shares
    assert mod.main() == 0
    out = pd.read_parquet(path)
    assert sorted(out["accn"]) == ["a1", "a2", "z1"]
    got = out.set_index("accn")["ingested_at"]
    assert got["a1"] == INGESTED and got["z1"] == INGESTED and pd.isna(got["a2"])
    assert no_tmp(path)


def test_shares_failure_mid_write_leaves_the_stored_file_intact(shares, monkeypatch):
    mod, path, stored = shares
    restore = failing_write(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        mod.main()
    restore()
    assert pd.read_parquet(path).equals(stored) and no_tmp(path)


# scripts/fetch_insider.py

def trades_frame(trade_id: str, owner: int) -> pd.DataFrame:
    return pd.DataFrame({
        "trade_id": [trade_id], "accession": ["acc"], "filing_date": pd.to_datetime(["2024-02-01"]),
        "issuer_cik": pd.Series([1000], dtype="int64"), "owner_cik": pd.Series([owner], dtype="int64"),
        "trade_date": pd.to_datetime(["2024-01-30"]), "code": ["P"], "shares": [10.0], "price": [5.0], "value": [50.0],
    })


@pytest.fixture
def insider(monkeypatch):
    mod = load("fetch_insider")
    monkeypatch.setattr(sec, "finished_quarters", lambda today: ["2024q1"])
    monkeypatch.setattr(mod, "write_symbol_map", lambda: 0)
    parsed = config.DATA_DIR / "insider" / "parsed"
    parsed.mkdir(parents=True)
    pd.concat([trades_frame("t1", 7), trades_frame("t2", 8)], ignore_index=True).to_parquet(parsed / "2024q1.parquet", index=False)
    stored = pd.concat([trades_frame("t1", 7), trades_frame("t9", 9)], ignore_index=True)
    stored["ingested_at"] = INGESTED
    assert list(stored.columns[:-1]) == insiders.TRADE_COLUMNS
    return mod, seed("form4", stored), stored


def test_insider_rebuild_keeps_recorder_rows_and_ingested_at(insider):
    mod, path, _ = insider
    assert mod.main() == 0
    out = pd.read_parquet(path)
    assert sorted(out["trade_id"]) == ["t1", "t2", "t9"]
    got = out.set_index("trade_id")["ingested_at"]
    assert got["t1"] == INGESTED and got["t9"] == INGESTED and pd.isna(got["t2"])
    assert no_tmp(path)


def test_insider_failure_mid_write_leaves_the_stored_file_intact(insider, monkeypatch):
    mod, path, stored = insider
    restore = failing_write(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        mod.main()
    restore()
    assert pd.read_parquet(path).equals(stored) and no_tmp(path)


# scripts/fetch_eightk.py

def filings(*accessions: str, items: bool = True) -> pd.DataFrame:
    out = pd.DataFrame({"accession": list(accessions), "filed_at": pd.to_datetime(["2024-03-01"] * len(accessions), utc=True)})
    if items:
        out["items"] = "2.02"
    return out


@pytest.fixture
def eightk(monkeypatch):
    mod = load("fetch_eightk")
    rebuilt = filings("a1", "a2")
    monkeypatch.setattr(mod, "EdgarClient", lambda: FakeClient(eightk=rebuilt))
    stored = filings("a1", "z9")
    stored.insert(0, "symbol", ["AAA", "ZZZ"])
    stored["ingested_at"] = INGESTED
    return mod, seed("eightk", stored), stored


def test_eightk_rebuild_keeps_recorder_rows_and_ingested_at(eightk):
    mod, path, _ = eightk
    assert mod.main() == 0
    out = pd.read_parquet(path)
    assert sorted(out["accession"]) == ["a1", "a2", "z9"]
    got = out.set_index("accession")["ingested_at"]
    assert got["a1"] == INGESTED and got["z9"] == INGESTED and pd.isna(got["a2"])
    assert no_tmp(path)


def test_eightk_failure_mid_write_leaves_the_stored_file_intact(eightk, monkeypatch):
    mod, path, stored = eightk
    restore = failing_write(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        mod.main()
    restore()
    assert pd.read_parquet(path).equals(stored) and no_tmp(path)


# scripts/fetch_earnings.py

@pytest.fixture
def earnings(monkeypatch):
    mod = load("fetch_earnings")
    monkeypatch.setattr("sys.argv", ["fetch_earnings"])
    monkeypatch.setattr(mod, "EdgarClient", lambda: FakeClient(earnings=filings("a1", "a2", items=False)))
    stored = filings("a1", "z9", items=False)
    stored.insert(0, "symbol", ["AAA", "ZZZ"])
    stored.insert(1, "cik", pd.Series([1000, 2000], dtype="int64"))
    stored["ingested_at"] = INGESTED
    return mod, seed("earnings", stored), stored


def test_earnings_rebuild_keeps_recorder_rows_and_ingested_at(earnings):
    mod, path, _ = earnings
    assert mod.main() == 0
    out = pd.read_parquet(path)
    assert sorted(out["accession"]) == ["a1", "a2", "z9"]
    got = out.set_index("accession")["ingested_at"]
    assert got["a1"] == INGESTED and got["z9"] == INGESTED and pd.isna(got["a2"])
    assert no_tmp(path)


def test_earnings_failure_mid_write_leaves_the_stored_file_intact(earnings, monkeypatch):
    mod, path, stored = earnings
    restore = failing_write(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        mod.main()
    restore()
    assert pd.read_parquet(path).equals(stored) and no_tmp(path)
