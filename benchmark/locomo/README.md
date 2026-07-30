# LoCoMo

This directory contains the Magi-specific adapter and runner code for LoCoMo.

Expected external checkout:

```bash
git clone https://github.com/snap-research/locomo ~/code/locomo
```

The scripts default to `~/code/locomo/data/locomo10.json`. You can also set
`LOCOMO_ROOT` or pass `--dataset`.

LoCoMo uses the same authenticated Magi gateway client as LongMemEval. Before
running it, start the Python IPC worker and headless `gateway-cli` by following
the [LongMemEval runbook](../longmemeval/RUNBOOK.md), then set
`MAGI_DESKTOP_SESSION_TOKEN` to the same non-empty temporary value used by the
gateway. The desktop app's port file alone is not sufficient because its
session credential remains private to the app.

One-shot runner:

```bash
python benchmark/locomo/run_all.py \
  --output-root benchmark/outputs \
  --limit 1 \
  --qa-limit 10 \
  --skip-finalize \
  --skip-background-wait
```

The one-shot runner also attempts LoCoMo LLM-as-judge scoring through the
running Magi backend, using the same Core LLM configuration as the app. Use
`--skip-llm-judge` to disable it explicitly.

Before query, the replay step actively drains benchmark memory work: it flushes
L2 extraction batches, waits for L2 extraction/reconcile/snapshot work, drains
pending L2 edge embeddings, generates L3 summaries, then waits for embedding
queues to become idle.

To reuse an already imported run and rerun only query/scoring:

```bash
python benchmark/locomo/run_all.py \
  --output-root benchmark/outputs \
  --run-id <existing-run-id> \
  --query-only \
  --qa-limit 10
```

Standalone judge scoring for an existing run:

```bash
python benchmark/locomo/llm_judge.py \
  --output-root benchmark/outputs \
  --run-id <run-id>
```

Replay/query split:

```bash
python benchmark/locomo/replay_dataset.py \
  --output-root benchmark/outputs \
  --run-id locomo-smoke \
  --limit 1 \
  --qa-limit 10 \
  --skip-finalize \
  --skip-background-wait

python benchmark/locomo/query_dataset.py \
  --output-root benchmark/outputs \
  --run-id locomo-smoke \
  --limit 1 \
  --qa-limit 10 \
  --answer-with-llm
```

Outputs are written under `benchmark/outputs/locomo/<run-id>/`:

- `replay_manifest.jsonl`
- `predictions.jsonl`
- `predictions_with_trace.jsonl`
- `predictions_with_judge.jsonl`
- `locomo_predictions.json`
- `summary.json`
- `llm_judge_results.jsonl`
- `llm_judge_summary.json`
- `error_report.jsonl`
- `error_report.csv`
- `error_report_summary.json`

`summary.json` contains the local official-style F1 score. When judge scoring
runs successfully, it also contains `llm_judge_score`, a binary LLM judge score
over categories 1-4. Category 5 adversarial questions are excluded by default,
matching common LoCoMo J-score reporting. Pass `--include-adversarial` to the
standalone judge script only when you intentionally want to inspect that extra
category.

Phase 1 scope:

- QA only
- one memory namespace per LoCoMo conversation
- both LoCoMo speakers are replayed as memory-bearing dialogue, with speaker names kept in the text
- images represented by the released BLIP captions plus image search queries
- image-bearing turns carry a small two-turn neighbor context window
- local official-style F1 scoring
