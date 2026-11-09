"""Score the pipeline against a dataset's question set (evals/questions/<dataset>.toml).

Run:  python -m evals.run --label v1
      python -m evals.run --label v1 --ids e01,h04      (subset)
Writes evals/results/<date_time>-<dataset>-<label>-<model>[-subset].json (gitignored).
"""
import argparse
import json
import statistics
import sys
import time
import tomllib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from askdata import llm
from askdata.ask import ask
from askdata.datasets import DATASETS
from askdata.launcher import ollama_running, start_ollama
from askdata.guard import connect_readonly, run_query

from .compare import results_match

HERE = Path(__file__).parent
QUESTIONS_DIR = HERE / "questions"
RESULTS_DIR = HERE / "results"


def gold_results(db, q: dict) -> list[list[tuple]]:
    return [run_query(db, sql.strip().rstrip(";"))[1] for sql in [q["sql"]] + q.get("alt_sql", [])]


def score(q: dict, r, golds: list[list[tuple]]) -> str:
    """One of: pass, wrong_result, sql_error, rejected, missed_refusal, false_refusal."""
    if q.get("expect") == "refuse":
        return "pass" if r.refusal else "missed_refusal"
    if r.refusal:
        return "false_refusal"
    if r.error:
        return "rejected" if r.error.startswith("Rejected") else "sql_error"
    ordered = q.get("ordered", False)
    return "pass" if any(results_match(g, r.rows, ordered) for g in golds) else "wrong_result"


def summarize(records: list[dict]) -> None:
    def pct(rows):
        return f"{100 * sum(x['status'] == 'pass' for x in rows) / len(rows):5.1f}%  ({sum(x['status'] == 'pass' for x in rows)}/{len(rows)})"

    by_group = defaultdict(list)
    for rec in records:
        by_group[rec["group"]].append(rec)
    print()
    for name in sorted(by_group, key=lambda g: g != "core"):  # core first
        print(f"{name:15}{pct(by_group[name])}")
    print(f"{'all':15}{pct(records)}")

    core = by_group.get("core", records)
    for key in ("difficulty", "category"):
        groups = defaultdict(list)
        for rec in core:
            groups[rec[key]].append(rec)
        print(f"\nCore by {key}:")
        for name in sorted(groups):
            print(f"  {name:15}{pct(groups[name])}")
    statuses = defaultdict(int)
    for rec in records:
        statuses[rec["status"]] += 1
    print("\nOutcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())))
    secs = sorted(rec["seconds"] for rec in records)
    print(f"Latency: median {statistics.median(secs):.1f}s, p90 {secs[int(0.9 * (len(secs) - 1))]:.1f}s | "
          f"repaired on retry: {sum(rec['attempts'] > 1 for rec in records)} | "
          f"tokens: {sum(rec['tokens'] for rec in records):,}")


def load_questions(dataset, ids: str | None = None) -> list[dict]:
    questions = tomllib.loads((QUESTIONS_DIR / f"{dataset.key}.toml").read_text(encoding="utf-8"))["question"]
    if ids:
        wanted = set(ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    return questions


def run_questions(dataset, model: str, questions: list[dict], verbose: bool = True) -> list[dict]:
    """Ask every question (SQL only, no answer sentence) and score it. Ollama must be running."""
    db = connect_readonly(dataset.db_path)
    records = []
    for q in questions:
        golds = [] if q.get("expect") == "refuse" else gold_results(db, q)
        r = ask(q["question"], model, answer=False, dataset=dataset)
        status = score(q, r, golds)
        records.append({
            "id": q["id"], "group": q.get("group", "core"), "difficulty": q["difficulty"], "category": q["category"], "question": q["question"],
            "status": status, "sql": r.sql, "error": r.error, "refusal": r.refusal,
            "attempts": r.attempts, "failed_attempts": r.failed_attempts,
            "seconds": round(r.seconds, 2), "tokens": r.tokens,
            "output_tokens": sum(c.output_tokens for c in r.llm_calls),
            "gen_seconds": round(sum(c.gen_seconds for c in r.llm_calls), 3),
            "predicted_rows": [list(map(str, row)) for row in r.rows[:10]],
            "gold_rows": [list(map(str, row)) for row in golds[0][:10]] if golds else None,
        })
        if verbose:
            mark = "PASS" if status == "pass" else status.upper()
            print(f"{q['id']:4} {mark:15} {r.seconds:5.1f}s  {q['question']}", flush=True)
    db.close()
    return records


def save(records: list[dict], dataset, label: str, model: str, wall_seconds: float, subset: bool = False, **extra) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}-{dataset.key}-{label}-{model.replace(':', '_')}{'-subset' if subset else ''}.json"
    out.write_text(json.dumps({
        "dataset": dataset.key, "label": label, "model": model, "run_at": datetime.now().isoformat(timespec="seconds"),
        "wall_seconds": round(wall_seconds, 1), **extra, "records": records,
    }, indent=2), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="version label, e.g. v1")
    parser.add_argument("--model", default=llm.DEFAULT_MODEL)
    parser.add_argument("--dataset", default="chinook", choices=sorted(DATASETS))
    parser.add_argument("--ids", help="comma-separated subset of question ids")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    dataset = DATASETS[args.dataset]
    questions = load_questions(dataset, args.ids)
    if not ollama_running():
        _ollama = start_ollama()  # stops when this process exits (kill-on-close job)
    llm.chat([{"role": "user", "content": "Reply OK."}], args.model)  # load the model before timing anything
    started = time.time()
    records = run_questions(dataset, args.model, questions)
    summarize(records)
    out = save(records, dataset, args.label, args.model, time.time() - started, subset=bool(args.ids))
    print(f"\nSaved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
