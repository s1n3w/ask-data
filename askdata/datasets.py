"""Datasets the engine can answer questions about, and everything that differs between them.

The pipeline (prompt skeleton, guard, repairs, refusals, typo recovery, eval) is shared. A dataset
supplies its database, an annotated schema, domain rules for the prompt, the columns whose real
values the model should see, where names live (for typo recovery), and UI text.
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from .config import ROOT


@dataclass(frozen=True)
class Dataset:
    key: str                      # "chinook"
    title: str                    # shown in the UI
    db_path: Path
    schema_file: Path
    subject: str                  # "You write SQLite queries for <subject>."
    missing_examples: str         # examples of data the schema doesn't hold, for the refusal rule
    name_rule: str                # how to treat a name the model doesn't recognize
    domain_rules: str             # extra bullet lines, each ending in a newline
    count_names: str              # example names for count columns
    apostrophe: str               # example of a doubled apostrophe
    time_rule: str                # timestamp handling bullet(s), each ending in a newline
    date_column: str              # column used in the relative-date examples
    known_values: list[tuple[str, str]]   # (table, column) whose distinct values go in the prompt
    name_sources: list[tuple[str, str]]   # (table, SQL expression) holding titles/names
    examples: list[str]           # starter questions in the UI
    ask_label: str                # UI heading
    answer_note: str = ""         # facts the answer writer needs, e.g. units
    as_of: Callable[[sqlite3.Connection], date | None] = field(default=lambda db: None)
    # None = live data ("today" is today). A date = historical data treated as of that day.

    @property
    def schema(self) -> str:
        return self.schema_file.read_text(encoding="utf-8")


def _latest_invoice(db: sqlite3.Connection) -> date:
    return date.fromisoformat(db.execute("SELECT MAX(date(InvoiceDate)) FROM Invoice").fetchone()[0])


CHINOOK = Dataset(
    key="chinook",
    title="Chinook music store",
    db_path=ROOT / "datasets" / "chinook" / "chinook.db",
    schema_file=ROOT / "datasets" / "chinook" / "schema.sql",
    subject="the sales database of Chinook, an online music store",
    missing_examples="costs, marketing, or anything else these\n  tables don't record",
    name_rule=".",
    domain_rules="",
    count_names="customers, invoices, tracks_sold",
    apostrophe="'Guns N'' Roses'",
    time_rule="",
    date_column="InvoiceDate",
    known_values=[("Genre", "Name"), ("MediaType", "Name"), ("Employee", "Title"),
                  ("Customer", "Country"), ("Playlist", "Name")],
    name_sources=[("Artist", "Name"), ("Album", "Title"), ("Track", "Name"), ("Genre", "Name"),
                  ("Playlist", "Name"), ("Customer", "FirstName || ' ' || LastName"),
                  ("Employee", "FirstName || ' ' || LastName"), ("Customer", "Country"), ("Customer", "City")],
    examples=[
        "What was total revenue in each year?",
        "Who are our top 5 customers by total spend?",
        "Which sales support agent brought in the most revenue?",
        "Which genres sell best in the USA?",
        "How many customers does each country have?",
        "Which artists have the most tracks in the catalog?",
    ],
    ask_label="Ask anything about the music store",
    answer_note="Money values are plain US dollars: 138.6 means $138.60.",
    as_of=_latest_invoice,
)

DATASETS = {d.key: d for d in (CHINOOK,)}
