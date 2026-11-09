import sqlite3

import pytest

from askdata.datasets import CHINOOK
from askdata.names import suggest_fix as _suggest_fix


def suggest_fix(db, sql):
    return _suggest_fix(db, sql, CHINOOK.name_sources)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    for table in ("Artist", "Track", "Genre", "Playlist"):
        conn.execute(f"CREATE TABLE {table} (Name TEXT)")
    conn.execute("CREATE TABLE Album (Title TEXT)")
    conn.execute("CREATE TABLE Customer (FirstName TEXT, LastName TEXT, Country TEXT, City TEXT)")
    conn.execute("CREATE TABLE Employee (FirstName TEXT, LastName TEXT)")
    conn.executemany("INSERT INTO Artist VALUES (?)", [("Iron Maiden",), ("Guns N' Roses",), ("Led Zeppelin",)])
    conn.execute("INSERT INTO Album VALUES ('Led Zeppelin IV')")
    conn.execute("INSERT INTO Employee VALUES ('Margaret', 'Park')")
    return conn


def test_fixes_typo_inside_like_wildcards(db):
    sql, fixes = suggest_fix(db, "SELECT * FROM Artist WHERE Name LIKE '%iron maidan%'")
    assert sql == "SELECT * FROM Artist WHERE Name LIKE '%Iron Maiden%'"
    assert fixes == [("iron maidan", "Iron Maiden")]


def test_fixes_equality_and_keeps_quotes_escaped(db):
    sql, _ = suggest_fix(db, "SELECT * FROM Artist WHERE Name = 'Guns N Roses'")
    assert sql == "SELECT * FROM Artist WHERE Name = 'Guns N'' Roses'"


def test_fixes_person_names(db):
    sql, _ = suggest_fix(db, "SELECT * FROM Employee WHERE FirstName || ' ' || LastName = 'Margret Park'")
    assert "'Margaret Park'" in sql


def test_leaves_correct_names_and_non_comparisons_alone(db):
    assert suggest_fix(db, "SELECT * FROM Artist WHERE Name = 'Iron Maiden'") is None
    # Function arguments (date modifiers) are not comparisons, so they're never rewritten.
    assert suggest_fix(db, "SELECT date('now', 'localtime') FROM Artist") is None
    # Too far from any real name: no guess.
    assert suggest_fix(db, "SELECT * FROM Artist WHERE Name LIKE '%metallica%'") is None


def test_wrong_table_hint(db):
    from askdata.names import wrong_table_hint
    hint = wrong_table_hint(db, "SELECT * FROM Artist WHERE Name LIKE '%led zeppelin iv%'", CHINOOK.name_sources)
    assert hint == "'Led Zeppelin IV' is in table Album, which the query doesn't use."
    # Already querying the right table, or a name we don't have: no hint.
    assert wrong_table_hint(db, "SELECT * FROM Album WHERE Title = 'Led Zeppelin IV'", CHINOOK.name_sources) is None
    assert wrong_table_hint(db, "SELECT * FROM Artist WHERE Name = 'Metallica'", CHINOOK.name_sources) is None
