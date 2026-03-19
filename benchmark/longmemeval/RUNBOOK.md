# LongMemEval Backend Runbook

This runbook is the shortest path for running LongMemEval against a real Magi backend runtime.

## 1. Start the Backend

From the repository root:

```bash
cd /Users/asuka/code/magi/backend
pip install -r requirements.txt
python run_server.py
```

If you also want the frontend during development, you can start both from the repository root:

```bash
cd /Users/asuka/code/magi
./scripts/dev-hot.sh
```

## 2. Confirm the Backend Is Reachable

In a new terminal:

```bash
curl http://127.0.0.1:8000/api/metrics/health
```

You should get a JSON response instead of a connection error.

## 3. Prepare the Dataset Path

Example:

```bash
export LONGMEM_DATA=/absolute/path/to/longmemeval_oracle.json
export LONGMEM_OUT=/Users/asuka/code/magi/benchmark/outputs
export LONGMEM_RUN=oracle-backend
export MAGI_BACKEND=http://127.0.0.1:8000
```

## 4. Replay LongMemEval History Into Memory

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/replay_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN" \
  --backend-url "$MAGI_BACKEND"
```

Expected output:

- a `replay_manifest.jsonl` file under `benchmark/outputs/longmemeval/<run-id>/`
- a `post_replay.json` file under `benchmark/outputs/longmemeval/<run-id>/`
- one row per question, with the namespace used for replay
- per-question console progress lines for L1 writes
- console output for current `L2 pipeline stats`

## 5. Run Memory Query Evaluation

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/query_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN" \
  --backend-url "$MAGI_BACKEND"
```

Expected output files under `benchmark/outputs/longmemeval/<run-id>/`:

- `predictions.jsonl`
- `predictions_with_trace.jsonl`
- `summary.json`
- per-question console progress lines for query execution

## 6. Inspect the Results

Quick summary:

```bash
cat "$LONGMEM_OUT/longmemeval/$LONGMEM_RUN/summary.json"
```

First few predictions:

```bash
head "$LONGMEM_OUT/longmemeval/$LONGMEM_RUN/predictions.jsonl"
```

First few traces:

```bash
head "$LONGMEM_OUT/longmemeval/$LONGMEM_RUN/predictions_with_trace.jsonl"
```

## 7. Run Official LongMemEval QA Scoring

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/evaluate_official.py \
  --longmemeval-root /absolute/path/to/LongMemEval \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN" \
  --judge-model gpt-4o
```

Expected output files under `benchmark/outputs/longmemeval/<run-id>/`:

- `predictions.jsonl.eval-results-gpt-4o`
- `official_eval_summary.json`

## 8. Optional: Run a Small Smoke Sample First

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/replay_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN-smoke" \
  --limit 5 \
  --backend-url "$MAGI_BACKEND"

python /Users/asuka/code/magi/benchmark/longmemeval/query_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN-smoke" \
  --limit 5 \
  --backend-url "$MAGI_BACKEND"
```

## Notes

- `--backend-url` is the recommended mode when you want the real backend memory runtime, provider config, and LLM-backed layers.
- If you omit `--backend-url`, the benchmark scripts fall back to a local lightweight harness intended mainly for L1-focused testing.
- If results come back as many `"unknown"` predictions, inspect backend logs and `predictions_with_trace.jsonl` first. That usually means retrieval is missing evidence, not that the benchmark scripts failed.
