# LongMemEval

This directory contains the Magi-specific adapter and runner code for LongMemEval.

Responsibilities:

- load LongMemEval dataset rows
- convert them into benchmark-agnostic replay records and memory queries
- run those records through `backend/src/magi/memory/eval_support/`
- export predictions and retrieval traces

Phase 1 scope:

- replay LongMemEval history into isolated benchmark namespaces
- query memory directly without chat/personality integration
- write `predictions.jsonl` and `predictions_with_trace.jsonl`
- compute local retrieval metrics with `report.py`

Current answer synthesis:

- `predictions.jsonl` is produced deterministically from top retrieval hits
- it does not use `ChatTaskAgent` or persona prompts
- if no retrieval hit is available, the runner falls back to `"unknown"`

Out of scope for this directory:

- changes to Magi runtime memory behavior
- chat-integrated evaluation

Example:

```bash
python benchmark/longmemeval/runner.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-smoke \
  --limit 5
```
