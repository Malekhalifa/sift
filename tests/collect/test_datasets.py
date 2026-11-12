from tp import config, political
from tp.collect.datasets import DATASETS, dataset, load_settings

LEGACY = {"eightk", "earnings", "form4", "finra_shortvol", "dod_awards", "trump_posts", "xbrl_shares"}


def test_registry_has_every_planned_dataset():
    assert set(DATASETS) == {
        "eightk", "earnings", "tenk_index", "form4", "xbrl_shares", "finra_shortvol", "finra_short_interest",
        "dod_awards", "trump_posts", "sp500_changes", "wikipedia_pageviews", "congress_trades",
    }


def test_existing_datasets_keep_their_legacy_paths():
    assert dataset("eightk").path == config.DATA_DIR / "events" / "eightk.parquet"
    assert dataset("earnings").path == config.DATA_DIR / "events" / "earnings.parquet"
    assert dataset("form4").path == config.DATA_DIR / "insider" / "trades.parquet"
    assert dataset("finra_shortvol").path == config.DATA_DIR / "finra" / "shortvol.parquet"
    assert dataset("dod_awards").path == political.awards_path()
    assert dataset("trump_posts").path == political.posts_path()
    assert dataset("xbrl_shares").path == config.DATA_DIR / "xbrl" / "shares.parquet"


def test_new_datasets_live_under_store():
    for name in set(DATASETS) - LEGACY:
        assert dataset(name).path.parent == config.DATA_DIR / "store"


def test_keys_and_timestamp_columns():
    assert dataset("form4").key == ("trade_id", "owner_cik")
    assert dataset("form4").ts_col == "filing_date"
    assert dataset("dod_awards").key == ("award_id", "action_date", "amount")
    assert dataset("congress_trades").key == ("source_id",)
    assert dataset("trump_posts").key == ("source", "id") and dataset("trump_posts").ts_col == "ts"
    assert dataset("sp500_changes").key == ("effective_date", "added", "removed")
    assert dataset("sp500_changes").ts_col == "effective_date"
    assert dataset("wikipedia_pageviews").key == ("date", "symbol", "article")
    assert dataset("wikipedia_pageviews").ts_col == "date"
    assert dataset("eightk").key == ("symbol", "accession")
    assert dataset("earnings").key == ("symbol", "accession")
    assert dataset("tenk_index").key == ("symbol", "accn")
    assert dataset("xbrl_shares").key == ("accn", "symbol", "end")


def test_settings_have_ports_and_cap():
    settings = load_settings()
    assert settings["metrics"]["port"] == 9120
    assert settings["apify"]["monthly_cap_usd"] == 4.0
    assert settings["sources"]["alpaca_bars"]["lag_minutes"] == 20
    assert settings["sources"]["wikipedia_pageviews"]["schedule"] == "daily 06:30 UTC"
    assert len(settings["sources"]) == 11
