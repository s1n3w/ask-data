import sqlite3

import pytest

from askdata.guard import UnsafeSQL, connect_readonly, extract_sql, run_query


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    setup = sqlite3.connect(path)
    setup.executescript("CREATE TABLE movies (title TEXT, year INT);"
                        "INSERT INTO movies VALUES ('Alien', 1979), ('Heat', 1995);")
    setup.commit()
    setup.close()
    conn = connect_readonly(path)
    yield conn
    conn.close()


def test_extract_sql_from_fence_and_prose():
    assert extract_sql("Here you go:\n```sql\nSELECT 1;\n```\nHope that helps") == "SELECT 1"
    assert extract_sql("SELECT 1;") == "SELECT 1"


def test_select_and_cte_allowed(db):
    assert run_query(db, "SELECT title FROM movies ORDER BY year")[1] == [("Alien",), ("Heat",)]
    assert run_query(db, "WITH m AS (SELECT * FROM movies) SELECT COUNT(*) FROM m")[1] == [(2,)]


@pytest.mark.parametrize("sql", [
    "DELETE FROM movies",
    "UPDATE movies SET year = 0",
    "DROP TABLE movies",
    "ATTACH DATABASE 'x.db' AS x",
    "PRAGMA writable_schema = 1",
])
def test_non_select_rejected(db, sql):
    with pytest.raises(UnsafeSQL):
        run_query(db, sql)


def test_write_hidden_in_cte_rejected(db):
    with pytest.raises((UnsafeSQL, sqlite3.Error)):
        run_query(db, "WITH x AS (SELECT 1) DELETE FROM movies")
    assert run_query(db, "SELECT COUNT(*) FROM movies")[1] == [(2,)]


def test_multiple_statements_rejected(db):
    with pytest.raises(sqlite3.Error):
        run_query(db, "SELECT 1; DELETE FROM movies")
    assert run_query(db, "SELECT COUNT(*) FROM movies")[1] == [(2,)]


def test_runaway_query_times_out(db, monkeypatch):
    monkeypatch.setattr("askdata.guard.TIMEOUT_S", 0.2)
    with pytest.raises(sqlite3.OperationalError, match="longer than"):
        run_query(db, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n")


def test_row_cap(db, monkeypatch):
    monkeypatch.setattr("askdata.guard.MAX_ROWS", 1)
    _, rows, truncated = run_query(db, "SELECT * FROM movies")
    assert len(rows) == 1 and truncated
