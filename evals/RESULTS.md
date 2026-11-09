# Eval results

Model: `qwen2.5-coder:32b` via Ollama on an RTX 4090 (24 GB), temperature 0, 8K context.
Scoring: execution match on the question set in `questions/chinook.toml`.
Raw per-question results are in `evals/results/` (gitignored).

## Chinook, November 2026 (`qwen3.6:27b`)

The October sections below used `qwen2.5-coder:32b`; the app now defaults to `qwen3.6:27b`.

| Run | Core (44) | Holdout (26) |
|---|---|---|
| Before the fix, 3 runs (holdout 2 runs) | 43, 43, 43 | 25, 25 |
| **After the fix, 3 runs** | **44, 44, 44** | **26, 26, 26** |

- Before: the only core miss was **h08** ("How many tracks are on our biggest playlist?"): the
  October counting rule was over-applied, wrapping the `LIMIT 1` result in an outer `COUNT(*)` (= 1).
- The 26 holdout questions (x01-x26) were written and scored on the unchanged version before the
  fix. Their one miss, **x02** ("How many albums do we sell?"), was ambiguous wording; both
  readings (catalog 347, sold 304) now count.
- Fix: the counting rule now says it is only for counting qualifying groups, and never to wrap a
  `LIMIT 1` query in an outer `COUNT`.
- Caveats: the holdout set has the same author, and x23/x24 share h08's pattern (both passed
  before the fix). Temperature 0 made repeat runs identical.
- h05, the October grain error, passes on `qwen3.6:27b`.

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
