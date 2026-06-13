# LongMemEval results — Magi v0.1.2

Raw outputs backing the **87.2%** LongMemEval figure quoted in the project README.

## Setup

| Item | Value |
| ---- | ----- |
| Benchmark | LongMemEval **`_s`** (500 questions, full-haystack retrieval, ≈115K-token haystack per question) |
| System under test | Magi long-term memory + retrieval pipeline (backend `eval_support`), run via `benchmark/longmemeval/run_all.py` |
| Run id | `0514-22-16-test` (2026-05-14) |
| Judge | LLM-as-judge, **`glm-5`** (per-question correct/incorrect) |
| Predictions | deterministic from top retrieval hits; falls back to `"unknown"` (abstention) when no hit is available |

A second independent judge (`bailian`) scored the **same** `predictions.jsonl` at **438/500 = 0.8760**, i.e. the headline number is stable across judges. Only the `glm-5` scoring is published here, as requested.

## Score

| LongMemEval category | Accuracy | Correct | Count |
| -------------------- | -------: | ------: | ----: |
| **Overall** | **0.8720** | **436** | **500** |
| Multi-session | 0.8271 | 110 | 133 |
| Single-session assistant | 0.9286 | 52 | 56 |
| Temporal reasoning | 0.8647 | 115 | 133 |
| Knowledge update | 0.9231 | 72 | 78 |
| Single-session preference | 0.6000 | 18 | 30 |
| Single-session user | 0.9857 | 69 | 70 |

Retrieval stats (`summary.json`): session recall@1 = 0.804, mean retrieval compression ratio ≈ 0.021 (system answers from ~2% of the haystack), 30 abstentions, 0 zero-retrieval questions.

## Files

| File | Contents |
| ---- | -------- |
| `predictions.jsonl` | 500 records, `{question_id, hypothesis}` — the model's answer per question. No dataset text. |
| `predictions.jsonl.eval-results-glm-5` | 500 records, `{question_id, hypothesis, autoeval_label}` — the `glm-5` judge verdict per question. |
| `summary.json` | Aggregate retrieval/abstention statistics for the run. |

Not included by design: `predictions_with_trace.jsonl` and the raw dataset. Those carry LongMemEval gold answers / haystack content, which is the dataset authors' to distribute — see the [LongMemEval repository](https://github.com/xiaowu0162/LongMemEval) for the questions and answers.

## Recompute the headline number

From this directory, against the published `glm-5` verdicts:

```bash
python3 - predictions.jsonl.eval-results-glm-5 <<'PY'
import json
n=c=0
for line in open(__import__('sys').argv[1]):
    e=json.loads(line); n+=1
    lab=e["autoeval_label"]
    lab=lab["label"] if isinstance(lab,dict) else lab
    c+=1 if (lab is True or str(lab).lower() in ("yes","true","1","correct")) else 0
print(f"{c}/{n} = {c/n:.4f}")
PY
# -> 436/500 = 0.8720
```

To regenerate predictions end-to-end from the dataset, see [`../../README.md`](../../README.md) and [`../../RUNBOOK.md`](../../RUNBOOK.md).
