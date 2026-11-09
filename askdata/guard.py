"""Run model-written SQL safely: read-only, single statement, time- and row-limited."""
import re
import sqlite3
import time
from pathlib import Path

MAX_ROWS = 500
TIMEOUT_S = 10

# Actions a SELECT legitimately needs; everything else (writes, ATTACH, PRAGMA...) is denied.
_ALLOWED = {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


class UnsafeSQL(Exception):
    pass


def extract_sql(text: str) -> str:
    """Pull the SQL out of a model reply (handles ```sql fences and stray prose)."""
    fenced = re.search(r"```(?:sql|sqlite)?\s*(.*?)```", text, re.S | re.I)
    sql = fenced.group(1) if fenced else text
    return sql.strip().rstrip(";").strip()


def _authorizer(action, *_):
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    db.set_authorizer(_authorizer)
    return db


def run_query(db: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple], bool]:
    """Execute one SELECT. Returns (columns, rows, truncated). Raises on unsafe or invalid SQL."""
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I):
        raise UnsafeSQL("Only SELECT queries are allowed.")
    deadline = time.time() + TIMEOUT_S
    db.set_progress_handler(lambda: time.time() > deadline, 10_000)  # nonzero return aborts the query
    try:
        # execute() rejects multiple statements ("You can only execute one statement at a time").
        cur = db.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.DatabaseError as e:
        if "not authorized" in str(e):
            raise UnsafeSQL(str(e)) from e
        if "interrupted" in str(e):
            raise sqlite3.OperationalError(f"Query took longer than {TIMEOUT_S}s.") from e
        raise
    finally:
        db.set_progress_handler(None, 0)
    columns = [d[0] for d in cur.description or []]
    return columns, rows[:MAX_ROWS], len(rows) > MAX_ROWS
