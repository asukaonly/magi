# LongMemEval Backend Runbook

This runbook is the shortest path for running LongMemEval against a real Magi backend runtime.

## 1. Start a Headless Magi Runtime

Build the independent server and create a configuration with dedicated test data:

```text
cargo build -p magi-server
target/debug/magi-server init --config /absolute/path/benchmark-server.json --data-dir /absolute/path/benchmark-data --development-root /absolute/path/magi
```

On Windows use `target/debug/magi-server.exe` and Windows absolute paths. The
repository Python environment must already contain the backend and plugin SDK
dependencies. Configure providers inside this isolated runtime before ingesting.

Generate a fresh random credential of at least 32 characters and set
`MAGI_DESKTOP_SESSION_TOKEN` to that value in both the service-launcher shell and
the benchmark shell. Do not place it in configuration files, URLs or reports.
The helper passes it over the private owner pipe and keeps that pipe open:

```text
python benchmark/run_service.py --config /absolute/path/benchmark-server.json
```

The helper owns the service until it exits. The service starts its own Python
worker, uses loopback HTTP, and prints its `baseUrl`. Set the configuration's
`port` field if the default 19080 is unavailable; 0 requests an ephemeral port.
Pass the printed address without `/api` explicitly as `--backend-url`.
The desktop app's session credential remains private and is not exported to
benchmark processes. Do not separately start a Python worker for this workflow.

## 2. Confirm the Backend Is Reachable

In a new terminal:

```bash
curl http://127.0.0.1:<gateway-port>/api/health
```

Use the port printed by `magi-server`. You should get a JSON response instead of a
connection error.

To verify an authenticated endpoint, export the same temporary credential used
by the benchmark service launcher and run:

```bash
curl \
  -H "X-Magi-Session-Token: $MAGI_DESKTOP_SESSION_TOKEN" \
  http://127.0.0.1:<gateway-port>/api/ready
```

## 3. Prepare the Dataset Path

Example:

```bash
export MAGI_DESKTOP_SESSION_TOKEN="<same-random-token>"
export LONGMEM_DATA=/absolute/path/to/longmemeval_oracle.json
export LONGMEM_OUT=benchmark/outputs
export LONGMEM_RUN=oracle-backend
export LONGMEMEVAL_ROOT=/absolute/path/to/LongMemEval
```

On PowerShell, use `$env:NAME = "value"` for the same variables. The benchmark
fails immediately if `MAGI_DESKTOP_SESSION_TOKEN` is missing or blank.

The scripts auto-discover the headless Magi gateway from
`~/.magi/runtime/gateway.port`. If you need to override it, also set
`MAGI_BACKEND=http://127.0.0.1:<gateway-port>` and pass
`--backend-url "$MAGI_BACKEND"`.

## 4. Shortest Path: Run Everything In One Command

```bash
python benchmark/longmemeval/run_all.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT"
```

This command:

- uses the auto-discovered Magi gateway unless `--backend-url` is provided
- generates a readable run id from current local time
- runs replay
- runs query
- runs official QA evaluation
- prints a final JSON summary to stdout

If LongMemEval is not in the expected local checkout path, set:

```bash
export LONGMEMEVAL_ROOT=/absolute/path/to/LongMemEval
```

## 5. Replay LongMemEval History Into Memory

```bash
python benchmark/longmemeval/replay_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN"

# Optional: fail faster on a stuck gateway, or poll drain state more/less often
#   --request-timeout 900
#   --poll-interval-seconds 2
```

Expected output:

- a `replay_manifest.jsonl` file under `benchmark/outputs/longmemeval/<run-id>/`
- a `post_replay.json` file under `benchmark/outputs/longmemeval/<run-id>/`
- one row per question, with the namespace used for replay
- per-question console progress lines for L1 writes
- console output for current `L2 pipeline stats`

## 6. Run Memory Query Evaluation

```bash
python benchmark/longmemeval/query_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN"
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
python benchmark/longmemeval/query_one.py \
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
python benchmark/longmemeval/evaluate_official.py \
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
python benchmark/longmemeval/rerun_query_and_score.py \
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
python benchmark/longmemeval/replay_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN-smoke" \
  --limit 5

python benchmark/longmemeval/query_dataset.py \
  --dataset "$LONGMEM_DATA" \
  --output-root "$LONGMEM_OUT" \
  --run-id "$LONGMEM_RUN-smoke" \
  --limit 5
```

## Notes

- The replay, query, and one-shot scripts in this runbook always use the running
  Magi gateway. Omitting `--backend-url` only enables port-file discovery; it
  does not switch to an in-process test harness.
- `benchmark/longmemeval/runner.py` is the separate local lightweight harness
  intended mainly for L1-focused testing.
- If results come back as many `"unknown"` predictions, inspect backend logs and `predictions_with_trace.jsonl` first. That usually means retrieval is missing evidence, not that the benchmark scripts failed.
