# Model comparison

Run 2026-10-22 on an RTX 4090 (24 GB) with Ollama, temperature 0, 8K context, the same prompt and pipeline for every model. Accuracy is execution match on the hand-checked question sets; latency is per question (write and run the SQL, including any repairs), with the model already loaded.

| Model | Download | Chinook (44) | Median | p90 | Tokens/s | Memory | On GPU | Cold load |
|---|---|---|---|---|---|---|---|---|
| `qwen2.5-coder:7b` | 4.7 GB | 36/44 (81.8%) | 0.3 s | 0.6 s | 157 | 5.1 GB | 100% | 2 s |
| `qwen2.5-coder:14b` | 9.0 GB | 41/44 (93.2%) | 0.6 s | 1.0 s | 84 | 10.4 GB | 100% | 3 s |
| `qwen2.5-coder:32b` | 19.9 GB | 42/44 (95.5%) | 1.2 s | 2.1 s | 41 | 21.8 GB | 100% | 5 s |
| `qwen3.6:27b` | 17.8 GB | 44/44 (100.0%) | 0.9 s | 1.4 s | 112 | 17.2 GB | 100% | 5 s* |

\* The first load right after downloading took 35 s; re-measured afterwards: 5.0 s and 5.2 s, the same
as the 32B (4.7 s).

## What it shows

- **Size matters for this task.** Within one model family, the 7B gets 82% and the 14B 93%,
  against the 32B's 95%. The smaller models are 2–4× faster but miss more joins and refusals.
- **qwen3.6:27b is the most accurate and faster than the 32B.** It is perfect on Chinook
  (44/44), generates 2.7× more tokens per second and uses 4.6 GB less memory.
- **Runs vary by about one question.** The 32B scored 43/44 in its v2 run and 42/44 here with
  the same prompt: "customers who bought every year" got a different, wrong query (GPU
  arithmetic isn't perfectly deterministic, even at temperature 0). Differences of 1–2 questions
  between models are within that noise.

## Questions each model got wrong

- `qwen2.5-coder:7b` on chinook: m04 (wrong result), m16 (wrong result), h05 (wrong result), h06 (wrong result), h08 (sql error), h09 (wrong result), h12 (wrong result), r03 (missed refusal)
- `qwen2.5-coder:14b` on chinook: h05 (wrong result), h06 (wrong result), r03 (missed refusal)
- `qwen2.5-coder:32b` on chinook: h05 (wrong result), h06 (wrong result)
- `qwen3.6:27b` on chinook: none
