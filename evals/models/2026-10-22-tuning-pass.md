# Model comparison

Run 2026-10-22 on an RTX 4090 (24 GB) with Ollama, temperature 0, 8K context, the same prompt and pipeline for every model. Each question set ran 2 time(s) per model; a range means the runs differed. Accuracy is execution match on the hand-checked question sets; latency is per question (write and run the SQL, including any repairs), with the model already loaded.

| Model | Download | Chinook (44) | Median | p90 | Tokens/s | Memory | On GPU | Cold load |
|---|---|---|---|---|---|---|---|---|
| `qwen2.5-coder:32b` | 19.9 GB | 40/44 (90.9%) | 1.1 s | 2.0 s | 41 | 21.8 GB | 100% | 5 s |
| `qwen3.6:27b` | 17.8 GB | 42–43/44 (95–98%) | 0.9 s | 1.3 s | 110 | 17.2 GB | 100% | 6 s |

## Questions each model got wrong

(n/m = wrong in n of m runs)

- `qwen2.5-coder:32b` on chinook: h03 (2/2), h05 (2/2), h12 (2/2), m04 (2/2)
- `qwen3.6:27b` on chinook: h02 (1/2), h08 (2/2)

## What changed and what it shows

The tuning pass made general changes after the first comparison (`2026-10-22-model-sizes.md`),
applied to both models:

- Shared rules: return values one per column (no glued display strings); count rows that meet a
  per-item condition with an outer `SELECT COUNT(*) FROM (... GROUP BY ... HAVING ...)`; do date
  math with `julianday()` and never subtract date text.
- Pipeline: when a query returns nothing but a name it searched for exists in a table it didn't
  use, the model is told where the name is and retries (`names.wrong_table_hint`).

**Decision rule, set before the runs:** switch the app to qwen3.6 if its average accuracy over both
runs is at least the 32B's (the original rule also counted a second, private question set, which
pointed the same way). Result on Chinook: qwen3.6 42.5 of 44, the 32B 40, so the app now uses qwen3.6.

Side effects, reported rather than tuned away:

- **The 32B got worse** (42 → 40). Its new misses are mostly ordinary: it listed all employees
  including managers with no customers and cross-joined a total. Rules refined for one model can
  cost another.
- **The counting rule over-applied once:** qwen3.6 answered "How many tracks are on our biggest
  playlist?" with 1, wrapping a single group in an outer COUNT. It passed before the rule.
