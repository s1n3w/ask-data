"""Check the relative-date idioms the prompt teaches against SQLite itself, for every weekday."""
import sqlite3
from datetime import date, timedelta

import pytest

from askdata.ask import sql_rules


def sqlite_date(today: date, *modifiers: str) -> str:
    args = ", ".join(["?"] + ["?"] * len(modifiers))
    return sqlite3.connect(":memory:").execute(f"SELECT date({args})", (today.isoformat(), *modifiers)).fetchone()[0]


@pytest.mark.parametrize("offset", range(7))
def test_last_saturday_idiom(offset):
    today = date(2026, 10, 18) + timedelta(days=offset)  # 2026-10-18 is a Sunday
    expected = today - timedelta(days=(today.weekday() - 5) % 7 or 7)  # most recent past Saturday
    assert sqlite_date(today, "weekday 6", "-7 days") == expected.isoformat()


def test_rules_include_today():
    rules = sql_rules(today=date(2026, 10, 22))
    assert "Today is 2026-10-22 (Thursday)" in rules


def test_historical_dataset_uses_its_as_of_date():
    from askdata.datasets import CHINOOK
    rules = sql_rules(CHINOOK, as_of=date(2013, 12, 22))
    assert "treat 2013-12-22 (Sunday)" in rules
    assert "'now'" not in rules and "date('2013-12-22','-1 day')" in rules
