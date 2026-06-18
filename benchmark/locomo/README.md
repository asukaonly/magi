# LoCoMo

This directory contains the Magi-specific adapter and runner code for LoCoMo.

Expected external checkout:

```bash
git clone https://github.com/snap-research/locomo ~/code/locomo
```

The scripts default to `~/code/locomo/data/locomo10.json`. You can also set
`LOCOMO_ROOT` or pass `--dataset`.

One-shot runner:

```bash
python benchmark/locomo/run_all.py \
  --output-root benchmark/outputs \
  --limit 1 \
  --qa-limit 10 \
  --skip-finalize \
  --skip-background-wait
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
- `locomo_predictions.json`
- `summary.json`

Phase 1 scope:

- QA only
- one memory namespace per LoCoMo conversation
- images represented by the released BLIP captions
- local official-style F1 scoring
