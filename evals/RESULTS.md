# Eval results

Model: `qwen2.5-coder:32b` via Ollama on an RTX 4090 (24 GB), temperature 0, 8K context.
Scoring: execution match on the question set in `questions/chinook.toml`.
Raw per-question results are in `evals/results/` (gitignored).

## Chinook (2026-10-22)

The engine pointed at [Chinook](https://github.com/lerocha/chinook-database), a sample sales
database for an online music store: customers, employees, invoices and a track catalog. The
44 business questions (`questions/chinook.toml`) were written and committed before any model
run on this dataset.

| Run | Core (44) | What changed |
|---|---|---|
| **v1 (untuned)** | **41 (93.2%)** | Only an annotated schema; the shared prompt, written before this dataset, unchanged |
| v2 | 43 (97.7%) | Two shared rules: return names rather than IDs, and total per item before averaging |

**The generalization result is the untuned v1: 93.2% on a database the engine had never seen,
including 3/3 refusals and 9/9 date questions.** v2's rules came from reading v1's failures, so
v2 is tuned to this question set.

- v1 failures: **m04** and **m16** returned employee IDs (`3, 4, 5`; `2`) instead of names, a
  pattern the prompt had never been tested against. **h05** averaged individual
  invoices ($5.71) instead of each customer's total spend ($39.67), a grain error.
- v2 fixed m04 and m16. **h05 still fails**: the averaging rule didn't take, and it's left as a
  known failure rather than given a question-specific rule.
- Found while testing the UI: the answer *sentence* said Iron Maiden earned "$138.6 million" and
  added a total that wasn't in the result, even though the chart was right. The answer writer
  now states only numbers from the result, adds no units or scale words, and gets a per-dataset
  note on units ("plain US dollars"). Answer sentences aren't scored by the eval; this was caught
  by reading answers in the app.
