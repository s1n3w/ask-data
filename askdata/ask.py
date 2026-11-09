"""Natural-language question -> SQL -> answer over a dataset (Chinook by default).

Run:  python -m askdata.ask "Who are our top 5 customers?"
      python -m askdata.ask            (interactive)
"""
import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import llm
from .datasets import CHINOOK, DATASETS, Dataset
from .guard import UnsafeSQL, connect_readonly, extract_sql, run_query
from .names import find_library_name, suggest_fix, where_is, wrong_table_hint

MAX_ATTEMPTS = 3          # first try + 2 repairs after an SQL error
ANSWER_ROW_LIMIT = 50     # rows shown to the model when it writes the final answer

REFUSAL_MARKER = "CANNOT_ANSWER:"

# Shared prompt skeleton; the {placeholders} come from the dataset (see datasets.py).
SQL_RULES = """You write SQLite queries for {subject}.
{as_of_line}

Rules:
- Reply with exactly one SQLite SELECT statement in a ```sql block, nothing else.
- Use only the tables and columns in the schema below.
- When the answer is a person or thing (a customer, employee, artist, show...), return its name,
  joining to get it; never only an ID.
- To average a per-item total (e.g. average spend per customer), total each item first, then
  average those totals.
- To count how many items meet a per-item condition (GROUP BY ... HAVING), count the groups in an
  outer query: SELECT COUNT(*) FROM (SELECT ... GROUP BY ... HAVING ...).
- Return values as stored, one per column (e.g. title and show_title as separate columns); don't
  join columns into display strings.
- If the schema has no data for what is asked (for example {missing_examples}), reply with one line: CANNOT_ANSWER: <what is missing>.
  Never substitute a different column and present it as the requested one.
  Refuse only when the KIND of information isn't stored, never because a name isn't recognized{name_rule}
{domain_rules}- Name count columns for what they count, e.g. {count_names}.
- Write an apostrophe inside a SQL string by doubling it: {apostrophe}.
{time_rule}- When finding the oldest/newest/longest/highest etc., exclude rows where the sorted column IS NULL.
- Match titles and names case-insensitively (LIKE or COLLATE NOCASE) unless an exact match is clearly intended.
- Give columns readable aliases and round decimals to 1-2 places.

SQLite date reference (weekday 0 = Sunday ... 6 = Saturday). Date values are text, so never subtract
or add them directly: days between = julianday(a) - julianday(b); shift = date(d, '+N days').
- Yesterday: date({now},'-1 day')
- Last N days: {col} >= datetime({now},'-N days')
- This month so far: {col} >= date({now},'start of month')
- Last calendar month: {col} >= date({now},'start of month','-1 month')
  AND {col} < date({now},'start of month')
- 'weekday N' moves FORWARD to the next day N (or stays put if today is N). So the most recent
  past day N, e.g. "last Saturday", is date({now},'weekday 6','-7 days')."""


def sql_rules(dataset: Dataset = CHINOOK, today: date | None = None, as_of: date | None = None) -> str:
    """The system prompt's rules for a dataset. `as_of` fixes "today" for historical data."""
    if as_of:
        as_of_line = (f"The data is historical: treat {as_of.isoformat()} ({as_of.strftime('%A')}), the latest date in "
                      f"it, as today. A month named without a year means the most recent one up to then.")
        now = f"'{as_of.isoformat()}'"
    else:
        today = today or date.today()
        as_of_line = (f"Today is {today.isoformat()} ({today.strftime('%A')}). A month or day named without a year "
                      f"means the most recent one up to today.")
        now = "'now','localtime'"
    return SQL_RULES.format(
        subject=dataset.subject, as_of_line=as_of_line, missing_examples=dataset.missing_examples,
        name_rule=dataset.name_rule, domain_rules=dataset.domain_rules, count_names=dataset.count_names,
        apostrophe=dataset.apostrophe, time_rule=dataset.time_rule, now=now, col=dataset.date_column)


@dataclass
class Result:
    question: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    answer: str | None = None
    refusal: str | None = None     # set when the question can't be answered from this data
    error: str | None = None
    attempts: int = 0
    failed_attempts: list[str] = field(default_factory=list)  # "sql -> error" for each repaired try
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (typed, matched) misspelled names
    refusal_overridden: bool = False  # refused over a name that is actually in the library, then retried
    empty_hint_used: bool = False     # an empty result was retried with "that name is in table X"
    llm_calls: list[llm.Reply] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def tokens(self) -> int:
        return sum(c.prompt_tokens + c.output_tokens for c in self.llm_calls)


def describe_values(db: sqlite3.Connection, dataset: Dataset) -> str:
    """Actual values of low-cardinality columns, so the model doesn't guess e.g. '4K' vs '4k'."""
    lines = []
    for table, column in dataset.known_values:
        values = [v for (v,) in db.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY 1")]
        lines.append(f"- {table}.{column}: {', '.join(map(str, values))}")
    return "Known values:\n" + "\n".join(lines)


def system_prompt(db: sqlite3.Connection, dataset: Dataset) -> str:
    rules = sql_rules(dataset, as_of=dataset.as_of(db))
    return f"{rules}\n\nSchema:\n{dataset.schema}\n{describe_values(db, dataset)}"


def generate_sql(question: str, db: sqlite3.Connection, model: str, result: Result, dataset: Dataset) -> None:
    sources = dataset.name_sources
    messages = [
        {"role": "system", "content": system_prompt(db, dataset)},
        {"role": "user", "content": question},
    ]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result.attempts = attempt
        reply = llm.chat(messages, model)
        result.llm_calls.append(reply)
        refusal = re.search(re.escape(REFUSAL_MARKER) + r"\s*(.*)", reply.text)
        if refusal and "```" not in reply.text:
            reason = refusal.group(1).strip()
            known = find_library_name(db, reason, sources) if reason else None
            if known and not result.refusal_overridden:
                # It "couldn't find" something that is in the data: say where it is and try again.
                result.refusal_overridden = True
                tables = ", ".join(where_is(db, known, sources)) or "the database"
                messages += [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": f"'{known}' is in the database (table: {tables}). "
                                                f"Answer the original question with a query."},
                ]
                if known.casefold() != reason.strip("'\".").casefold():
                    result.corrections.append((reason, known))
                continue
            result.refusal = reason or "The data needed isn't in the database."
            result.sql, result.error = None, None
            return
        result.sql = extract_sql(reply.text)
        try:
            result.columns, result.rows, result.truncated = run_query(db, result.sql)
            result.error = None
            # An aggregate over nothing still returns one row of NULLs, e.g. ROUND(... / COUNT(*)).
            if all(v is None for row in result.rows for v in row):
                retry_with_corrected_names(db, result, sources)
            empty = all(v is None for row in result.rows for v in row)
            hint = wrong_table_hint(db, result.sql, sources) if empty and attempt < MAX_ATTEMPTS else None
            if hint and not result.empty_hint_used:
                # Found nothing, but the name it searched for lives in a table it didn't query.
                result.empty_hint_used = True
                messages += [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": f"That query returned no rows. {hint} Fix the query."},
                ]
                continue
            return
        except UnsafeSQL as e:
            result.error = f"Rejected: {e}"
            return  # never retry around the safety check
        except sqlite3.Error as e:
            result.error = f"SQL error: {e}"
            result.failed_attempts.append(f"{result.sql}\n-> {e}")
            messages += [
                {"role": "assistant", "content": reply.text},
                # Don't offer a refusal here: v2 testing showed it makes the model give up on fixable joins.
                {"role": "user", "content": f"That query failed with: {e}\nFix it and reply with the corrected query only."},
            ]


def retry_with_corrected_names(db: sqlite3.Connection, result: Result, sources: list[tuple[str, str]]) -> None:
    """An empty result may just be a misspelled title; retry once with the closest real names."""
    fix = suggest_fix(db, result.sql, sources)
    if not fix:
        return
    fixed_sql, corrections = fix
    try:
        columns, rows, truncated = run_query(db, fixed_sql)
    except (UnsafeSQL, sqlite3.Error):
        return
    if any(v is not None for row in rows for v in row):
        result.sql, result.columns, result.rows, result.truncated = fixed_sql, columns, rows, truncated
        result.corrections = corrections


def explain(result: Result, model: str, dataset: Dataset) -> None:
    table = "\n".join([" | ".join(result.columns)] + [" | ".join(map(str, r)) for r in result.rows[:ANSWER_ROW_LIMIT]])
    note = f"\n(Showing {ANSWER_ROW_LIMIT} of {len(result.rows)}+ rows.)" if len(result.rows) > ANSWER_ROW_LIMIT or result.truncated else ""
    reply = llm.chat([
        {"role": "system", "content": "Answer the user's question in plain sentences using only the query result. "
                                      "If the result has several rows, the user also sees the full table, so summarize all "
                                      "of it in one or two sentences instead of listing every row: for a ranking, name the "
                                      "top item and its value; for a list, give how many items there are and what they "
                                      "have in common (e.g. 'You watched 8 episodes: 6 of Show A and 2 of Show B'). "
                                      "Never describe only the first row as if it were the whole result. "
                                      "If the result includes a summary or tagline and the user asked what something is "
                                      "about, retell that description in two to four sentences. "
                                      "If the result is empty, say nothing matched. Don't mention SQL. "
                                      "Only state numbers that appear in the result, exactly as given: don't add them up "
                                      "or compute new ones, and never add units or scale words (thousand, million) "
                                      "that the result doesn't show." + (f" {dataset.answer_note}" if dataset.answer_note else "")},
        {"role": "user", "content": f"Question: {result.question}\n\nQuery result:\n{table or '(no rows)'}{note}"},
    ], model)
    result.llm_calls.append(reply)
    result.answer = reply.text.strip()


def ask(question: str, model: str = llm.DEFAULT_MODEL, answer: bool = True,
        dataset: Dataset = CHINOOK, db_path: Path | None = None) -> Result:
    started = time.time()
    result = Result(question)
    db = connect_readonly(db_path or dataset.db_path)
    try:
        generate_sql(question, db, model, result, dataset)
        if answer and result.error is None and result.refusal is None:
            explain(result, model, dataset)
    finally:
        db.close()
    result.seconds = time.time() - started
    return result


def print_result(r: Result) -> None:
    if r.refusal:
        print(f"\nCan't answer that from this data: {r.refusal}")
        print(f"\n[{r.seconds:.1f}s, {r.attempts} attempt(s), {r.tokens:,} tokens]")
        return
    print(f"\nSQL:\n{r.sql}\n")
    if r.error:
        print(r.error)
    else:
        for row in [r.columns] + r.rows[:10]:
            print("  " + " | ".join(map(str, row)))
        if len(r.rows) > 10:
            print(f"  ... {len(r.rows) - 10} more rows")
        print(f"\n{r.answer}")
    for typed, matched in r.corrections:
        print(f'(Matched "{typed}" to "{matched}".)')
    print(f"\n[{r.seconds:.1f}s, {r.attempts} attempt(s), {r.tokens:,} tokens]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="*")
    parser.add_argument("--model", default=llm.DEFAULT_MODEL)
    parser.add_argument("--dataset", default="chinook", choices=sorted(DATASETS))
    args = parser.parse_args()
    dataset = DATASETS[args.dataset]
    sys.stdout.reconfigure(encoding="utf-8")  # non-ASCII names crash the default Windows console codec
    if args.question:
        print_result(ask(" ".join(args.question), args.model, dataset=dataset))
        return
    while True:
        try:
            question = input(f"\nAsk about the {dataset.title} (blank to quit): ").strip()
        except EOFError:
            break
        if not question:
            break
        print_result(ask(question, args.model, dataset=dataset))


if __name__ == "__main__":
    main()
