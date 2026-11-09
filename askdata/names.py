"""Typo recovery: when a query matches nothing, retry with the closest real title or name.

"albums by iron maidan" -> WHERE Name LIKE '%iron maidan%' -> no rows. The literal is compared
with every title and name in the dataset; a close match ("Iron Maiden") is substituted and the
query re-run. Only literals used in = / LIKE / IN (...) comparisons are considered, so date
modifiers such as 'localtime' are never rewritten.

Where names live differs per dataset, so callers pass `sources`: (table, SQL expression) pairs,
e.g. ("Artist", "Name") or ("Customer", "FirstName || ' ' || LastName").
"""
import difflib
import re
import sqlite3

CUTOFF = 0.8          # SequenceMatcher ratio; "iron maidan" vs "iron maiden" = 0.91
MIN_LENGTH = 4

# A string literal right after =, LIKE, or the opening of IN ( ... ), with optional surrounding % wildcards.
COMPARED_LITERAL = re.compile(r"(?P<op>=|\bLIKE\b|\bIN\s*\()\s*'(?P<lit>(?:[^']|'')*)'", re.I)


def library_names(db: sqlite3.Connection, sources: list[tuple[str, str]]) -> dict[str, str]:
    """lower-cased name -> name as stored."""
    names = {}
    for table, expr in sources:
        for (name,) in db.execute(f"SELECT DISTINCT {expr} FROM {table}"):
            if name:
                names.setdefault(str(name).casefold(), str(name))
    return names


def find_library_name(db: sqlite3.Connection, text: str, sources: list[tuple[str, str]]) -> str | None:
    """The title or name that `text` refers to, allowing for typos (None if it's nothing we have)."""
    names = library_names(db, sources)
    core = text.strip().strip("'\".").casefold()
    if core in names:
        return names[core]
    close = difflib.get_close_matches(core, names.keys(), n=1, cutoff=CUTOFF)
    return names[close[0]] if close else None


def where_is(db: sqlite3.Connection, name: str, sources: list[tuple[str, str]]) -> list[str]:
    """Which tables hold this exact name, e.g. ['Artist']."""
    found = []
    for table, expr in sources:
        if table not in found and db.execute(f"SELECT 1 FROM {table} WHERE {expr} = ? LIMIT 1", (name,)).fetchone():
            found.append(table)
    return found


def wrong_table_hint(db: sqlite3.Connection, sql: str, sources: list[tuple[str, str]]) -> str | None:
    """For an empty result: a searched-for name that exists, but only in tables the query doesn't use.

    "tracks on led zeppelin iv" searched Artist; Led Zeppelin IV is an album. Returns e.g.
    "'Led Zeppelin IV' is in table Album, which the query doesn't use." or None.
    """
    names = library_names(db, sources)
    hints = []
    for match in COMPARED_LITERAL.finditer(sql):
        core = match.group("lit").replace("''", "'").strip("%")
        name = names.get(core.casefold())
        if not name:
            continue
        unused = [t for t in where_is(db, name, sources) if not re.search(rf"\b{re.escape(t)}\b", sql, re.I)]
        if unused:
            hints.append(f"'{name}' is in table {', '.join(unused)}, which the query doesn't use.")
    return " ".join(dict.fromkeys(hints)) or None


def suggest_fix(db: sqlite3.Connection, sql: str, sources: list[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]] | None:
    """Return (corrected_sql, [(typed, matched), ...]) or None when nothing looks misspelled."""
    names = library_names(db, sources)
    corrections = []

    def replace(match: re.Match) -> str:
        raw = match.group("lit")
        text = raw.replace("''", "'")
        core = text.strip("%")
        if len(core) < MIN_LENGTH or not re.search(r"[A-Za-z]", core) or core.casefold() in names:
            return match.group(0)
        close = difflib.get_close_matches(core.casefold(), names.keys(), n=1, cutoff=CUTOFF)
        if not close:
            return match.group(0)
        fixed_name = names[close[0]]
        corrections.append((core, fixed_name))
        prefix, suffix = text[: len(text) - len(text.lstrip("%"))], text[len(text.rstrip("%")):]
        fixed = (prefix + fixed_name + suffix).replace("'", "''")
        return match.group(0).replace(f"'{raw}'", f"'{fixed}'")

    fixed_sql = COMPARED_LITERAL.sub(replace, sql)
    return (fixed_sql, corrections) if corrections else None
