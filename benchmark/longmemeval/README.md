# LongMemEval

This directory contains the Magi-specific adapter and runner code for LongMemEval.

Quick ops guide:

- See [RUNBOOK.md](./RUNBOOK.md) for the backend-service workflow from startup to replay/query commands.

One-shot runner:

```bash
python benchmark/longmemeval/run_all.py \
  --dataset /absolute/path/to/longmemeval_oracle.json \
  --output-root benchmark/outputs
```

This fixed-flow runner uses:

- backend URL: auto-discovered from `~/.magi/runtime/gateway.port` when the headless gateway CLI is running, or set explicitly with `--backend-url`
- gateway credential: the non-empty `MAGI_DESKTOP_SESSION_TOKEN` value shared with the headless gateway CLI
- run id: local time formatted as `YYYY-MM-DD HH:MM:SS`
- LongMemEval root: set `LONGMEMEVAL_ROOT` to your local LongMemEval checkout for portable runs

The desktop app keeps its session credential private, so its port file alone is
not enough for an external benchmark process. Follow
[RUNBOOK.md](./RUNBOOK.md) to start the authenticated headless runtime.

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
It also writes `post_replay.json`, triggers temporal L3 summaries for `hour/day/week/month`, and prints current L2 pipeline stats to the console.
During replay it prints per-question L1 write progress in the form `[L1 replay] current/total ...`.
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

During query replay it prints per-question query progress in the form `[Query replay] current/total ...`.

Backend-service flow:

```bash
python benchmark/longmemeval/replay_dataset.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-backend \
  --backend-url http://127.0.0.1:19080

python benchmark/longmemeval/query_dataset.py \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-backend \
  --backend-url http://127.0.0.1:19080
```

This mode reuses the memory runtime already initialized by the backend service, including its provider and LLM configuration.
The `--backend-url` value should point at the Magi gateway HTTP address. In the current architecture `backend/run_server.py`
starts an IPC worker only; it is not the benchmark HTTP entrypoint.
Set `MAGI_DESKTOP_SESSION_TOKEN` to the same temporary value used when starting
`gateway-cli`; all benchmark GET and POST requests send it in the gateway
authentication header.

Official QA scoring wrapper:

```bash
python benchmark/longmemeval/evaluate_official.py \
  --longmemeval-root /absolute/path/to/LongMemEval \
  --dataset data/longmemeval_oracle.json \
  --output-root benchmark/outputs \
  --run-id oracle-backend \
  --judge-model gpt-4o
```

This reads the current run's `predictions.jsonl`, calls LongMemEval's official `evaluate_qa.py`, and writes `official_eval_summary.json` next to the benchmark outputs.

Wrong-answer analysis:

```bash
python benchmark/longmemeval/error_report.py \
  --dataset /absolute/path/to/longmemeval_s_cleaned.json \
  --output-root /absolute/path/to/LongMemEval/outputs \
  --run-id 0402-15-16-test \
  --judge-model zen-gpt-4o
```

This reads the run's `predictions_with_trace.jsonl` and official `predictions.jsonl.eval-results-<judge-model>`,
then writes:

- `error_report.csv`
- `error_report.jsonl`
- `error_report_summary.json`

The report buckets wrong answers into retrieval misses, same-session bundle misses, and synthesis/judge misses using
the same local bundle-window heuristic as the current evaluation query path.
