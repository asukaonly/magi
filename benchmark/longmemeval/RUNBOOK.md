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

## 4. Shortest Path: Run Everything In One Command

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/run_all.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT"
```

This command:

- uses backend `http://127.0.0.1:8000`
- generates a readable run id from current local time
- runs replay
- runs query
- runs official QA evaluation
- prints a final JSON summary to stdout

If LongMemEval is not checked out at `/Users/asuka/code/LongMemEval`, set:

```bash
export LONGMEMEVAL_ROOT=/absolute/path/to/LongMemEval
```

## 5. Replay LongMemEval History Into Memory

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

## 6. Run Memory Query Evaluation

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

If you want the backend LLM to synthesize final answers from retrieved evidence, add:

```bash
  --answer-with-llm
```

## 7. Inspect the Results

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

## 7.5. Debug One Question At A Time

If you want to inspect one replayed question without rerunning the whole dataset:

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/query_one.py \
  --dataset "$LONGMEM_DATA" \
  --run-id "$LONGMEM_RUN" \
  --question-id "gpt4_2655b836"
```

To debug the retrieval + answer-model path, add:

```bash
  --answer-with-llm
```

If you also want the exact prompt sent to the backend LLM in the debug JSON output, add:

```bash
  --show-prompt
```

This prints:

- the original question
- the expected answer
- the resolved namespace
- retrieved hits
- retrieval trace
- optional `answer` and `answer_trace`

When `--answer-with-llm` is enabled, the backend logs also print:

- `Eval query answer synthesis started`
- `Eval query answer synthesis completed`

If you want the CLI to fail faster instead of waiting quietly for a slow backend response, add:

```bash
  --request-timeout 30
```

## 8. Run Official LongMemEval QA Scoring

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

## 8.5. Rerun Query And Scoring Without Replay

If you changed retrieval or query logic and want to reuse previously replayed memory, run:

```bash
python /Users/asuka/code/magi/benchmark/longmemeval/rerun_query_and_score.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN"
```

This command:

- reuses the existing replayed namespaces for the same `run-id`
- reruns `query_dataset.py`
- reruns official QA evaluation when `OPENAI_API_KEY` is set
- skips official evaluation with a clear status when `OPENAI_API_KEY` is missing

To enable retrieval + answer-model mode on reruns, add:

```bash
  --answer-with-llm
```

## 9. Optional: Run a Small Smoke Sample First

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
