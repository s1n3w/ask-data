"""Compare models on accuracy, speed and memory across the question sets.

Run:  python -m evals.compare_models qwen2.5-coder:32b qwen3.6:27b --repeat 2
Each model starts cold (everything unloaded), so load times and memory are comparable. With
--repeat, every question set runs several times and accuracy is reported as a range, because
the same model and prompt can differ by a question or so between runs.
Writes evals/models/<date>-<label>.md and one results file per model, dataset and run in evals/results/.
"""
import argparse
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import requests

from askdata import llm
from askdata.datasets import DATASETS
from askdata.launcher import ollama_running, start_ollama

from .run import HERE, load_questions, run_questions, save

REPORTS = HERE / "models"


def download_sizes() -> dict[str, float]:
    r = requests.get(f"{llm.OLLAMA_URL}/api/tags", timeout=30)
    r.raise_for_status()
    return {m["name"]: m["size"] / 1e9 for m in r.json()["models"]}


def unload_all() -> None:
    for name in llm.loaded_models():
        llm.unload(name)
    deadline = time.time() + 60
    while llm.loaded_models() and time.time() < deadline:
        time.sleep(0.5)


def passed(records: list[dict], group: str | None = "core") -> tuple[int, int]:
    rows = [r for r in records if group is None or r["group"] == group]
    return sum(r["status"] == "pass" for r in rows), len(rows)


def measure(model: str, label: str, repeat: int) -> dict:
    unload_all()
    started = time.time()
    llm.chat([{"role": "user", "content": "Reply OK."}], model)
    load_seconds = time.time() - started
    memory = llm.loaded_models().get(model, {"size_gb": 0, "vram_gb": 0})

    result = {"model": model, "load_seconds": load_seconds, **memory, "runs": {}}
    all_records = []
    for dataset in DATASETS.values():
        if not dataset.db_path.exists():
            continue
        questions = load_questions(dataset)
        result["runs"][dataset.key] = []
        for n in range(repeat):
            t = time.time()
            records = run_questions(dataset, model, questions, verbose=False)
            save(records, dataset, f"{label}-run{n + 1}", model, time.time() - t, load_seconds=load_seconds, **memory)
            result["runs"][dataset.key].append(records)
            all_records += records
            core = passed(records)
            print(f"  {dataset.key:8} run {n + 1}: core {core[0]}/{core[1]}  ({time.time() - t:.0f}s)", flush=True)

    secs = sorted(r["seconds"] for r in all_records)
    result["median_s"] = statistics.median(secs)
    result["p90_s"] = secs[int(0.9 * (len(secs) - 1))]
    gen = sum(r["gen_seconds"] for r in all_records)
    result["tokens_per_s"] = sum(r["output_tokens"] for r in all_records) / gen if gen else 0
    llm.unload(model)
    return result


def score_range(runs: list[list[dict]], group: str | None = "core") -> str:
    if not runs:
        return "—"
    scores = [passed(records, group) for records in runs]
    low, high, n = min(p for p, _ in scores), max(p for p, _ in scores), scores[0][1]
    pct = f"{100 * low / n:.1f}%" if low == high else f"{100 * low / n:.0f}–{100 * high / n:.0f}%"
    return f"{low}/{n} ({pct})" if low == high else f"{low}–{high}/{n} ({pct})"


def write_report(results: list[dict], sizes: dict[str, float], repeat: int, label: str) -> Path:
    lines = [
        "# Model comparison",
        "",
        f"Run {date.today().isoformat()} on an RTX 4090 (24 GB) with Ollama, temperature 0, 8K context, the same "
        f"prompt and pipeline for every model. Each question set ran {repeat} time(s) per model; a range means the "
        "runs differed. Accuracy is execution match on the hand-checked question sets; latency is per question "
        "(write and run the SQL, including any repairs), with the model already loaded.",
        "",
        "| Model | Download | Chinook (44) | Median | p90 | Tokens/s | Memory | On GPU | Cold load |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for res in results:
        on_gpu = 100 * res["vram_gb"] / res["size_gb"] if res["size_gb"] else 0
        lines.append(
            f"| `{res['model']}` | {sizes.get(res['model'], 0):.1f} GB | {score_range(res['runs'].get('chinook', []))} | "
            f"{res['median_s']:.1f} s | {res['p90_s']:.1f} s | {res['tokens_per_s']:.0f} | "
            f"{res['size_gb']:.1f} GB | {on_gpu:.0f}% | {res['load_seconds']:.0f} s |")
    lines += ["", "## Questions each model got wrong", "", "(n/m = wrong in n of m runs)", ""]
    for res in results:
        for key, runs in res["runs"].items():
            misses = Counter(r["id"] for records in runs for r in records if r["status"] != "pass")
            listed = ", ".join(f"{qid} ({n}/{len(runs)})" for qid, n in sorted(misses.items()))
            lines.append(f"- `{res['model']}` on {key}: {listed or 'none'}")
    REPORTS.mkdir(exist_ok=True)
    report = REPORTS / f"{date.today().isoformat()}-{label}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+")
    parser.add_argument("--label", default="compare")
    parser.add_argument("--repeat", type=int, default=1, help="runs per question set")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not ollama_running():
        _ollama = start_ollama()  # stops when this process exits (kill-on-close job)
    sizes = download_sizes()
    missing = [m for m in args.models if m not in sizes]
    if missing:
        raise SystemExit(f"Not downloaded: {', '.join(missing)} (run: ollama pull <model>)")
    results = []
    for model in args.models:
        print(f"{model}", flush=True)
        results.append(measure(model, args.label, args.repeat))
    report = write_report(results, sizes, args.repeat, args.label)
    print(f"\nWrote {report.relative_to(HERE.parent)}")
    print(report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
