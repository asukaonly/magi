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

Replay-only flow:

```bash
python benchmark/longmemeval/replay_dataset.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-replay \
  --limit 10
```

This writes `replay_manifest.jsonl` under `benchmark/outputs/longmemeval/<run-id>/`.
By default this local mode is an L1-focused harness. For full backend-configured memory runtime, pass `--backend-url`.

Query-only flow:

```bash
python benchmark/longmemeval/query_dataset.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-replay \
  --limit 10
```

This reopens the same persisted memory state under `benchmark/outputs/longmemeval/<run-id>/state/` and writes:

- `predictions.jsonl`
- `predictions_with_trace.jsonl`
- `summary.json`

Backend-service flow:

```bash
python benchmark/longmemeval/replay_dataset.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-backend \
  --backend-url http://127.0.0.1:8000

python benchmark/longmemeval/query_dataset.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-backend \
  --backend-url http://127.0.0.1:8000
```

This mode reuses the memory runtime already initialized by the backend service, including its provider and LLM configuration.
