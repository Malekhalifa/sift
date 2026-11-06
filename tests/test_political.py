import pandas as pd

from tp import political


def ts(s):
    return pd.Timestamp(s, tz="America/New_York").tz_convert("UTC")


def test_tone_counts_fixed_word_lists():
    assert political.tone("Thank you, a great investment and tremendous jobs!") == 1
    assert political.tone("Terrible, a disaster, they should be fired") == -1
    assert political.tone("Great company but a terrible disgrace") == -1  # 1 positive against 2 negative
    assert political.tone("The meeting is on Tuesday") == 0
    assert political.tone("great terrible") == 0  # tied


def test_mentions_use_whole_words_and_the_frozen_aliases():
    assert "BA" in political.mentioned("Boeing is building a brand new 747")
    assert "AMZN" in political.mentioned("Amazon pays no taxes")
    assert "META" in political.mentioned("Facebook is anti-Trump")
    assert political.mentioned("Hillary was booking rooms; I use ups and downs") == []
    assert "F" not in political.mentioned("Dr. Ford testified")  # bare Ford is people


def test_prime_mapping():
    assert political.prime_of("ELECTRIC BOAT CORPORATION") == "GD"
    assert political.prime_of("SIKORSKY AIRCRAFT CORP") == "LMT"
    assert political.prime_of("RAYTHEON COMPANY") == "RTX"
    assert political.prime_of("ACME WIDGETS INC") is None


def test_post_events_skip_quoted_tweets_and_toneless_posts_and_thin_repeats():
    posts = pd.DataFrame({
        "source": "twitter",
        "ts": [ts("2018-03-05 08:00"), ts("2018-03-05 12:00"), ts("2018-03-06 08:00"), ts("2018-03-07 08:00"), ts("2018-03-20 08:00")],
        "text": ["Boeing is doing great!", "Boeing is a disaster", '"@fan: Boeing is great"', "Boeing is on the news", "Boeing is terrible"],
    })
    ev = political.post_events(posts)
    # first post starts the 5-day window; the second (same day) and the quoted and toneless ones are out; the 20 March one counts
    assert ev["symbol"].tolist() == ["BA", "BA"] and ev["tone"].tolist() == [1, -1]
    assert ev["ts"].tolist() == [ts("2018-03-05 08:00"), ts("2018-03-20 08:00")]


def test_award_events_take_the_largest_per_day_and_thin():
    aw = pd.DataFrame({
        "recipient": ["LOCKHEED MARTIN CORP", "SIKORSKY AIRCRAFT", "LOCKHEED MARTIN CORP", "LOCKHEED MARTIN CORP", "UNKNOWN CO"],
        "action_date": pd.to_datetime(["2019-03-04", "2019-03-04", "2019-03-06", "2019-03-20", "2019-03-04"]),
        "amount": [2e8, 5e8, 3e8, 1e8, 9e9],
    })
    ev = political.award_events(aw)
    assert ev["symbol"].tolist() == ["LMT", "LMT"] and ev["amount"].tolist() == [5e8, 1e8]


def test_entry_sessions():
    sessions = pd.bdate_range("2024-03-04", periods=8)  # Mon 4 Mar .. Wed 13 Mar
    assert political.post_entry_pos(ts("2024-03-05 07:00"), sessions) == 1  # before the open: that day's open (Tue)
    assert political.post_entry_pos(ts("2024-03-05 10:00"), sessions) == 2  # during the session: next open
    assert political.post_entry_pos(ts("2024-03-05 20:00"), sessions) == 2  # after the close: next open
    assert political.post_entry_pos(ts("2024-03-09 09:00"), sessions) == 5  # Saturday: Monday's open
    assert political.award_entry_pos(ts("2024-03-05 00:00"), sessions) == 3  # action Tue: open of Thu, the second session after
    assert political.award_entry_pos(ts("2024-03-09 00:00"), sessions) == 6  # action Sat: second session after is Tue 12 Mar
