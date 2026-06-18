# Benchmark Workspace

`benchmark/` contains dataset-specific adapters, runners, and reporting code for evaluation work.

This directory is intentionally separate from `backend/src/magi/`:

- runtime code stays benchmark-agnostic
- dataset parsing stays outside the product runtime
- benchmark outputs and helper scripts live here

Current benchmark targets:

- `longmemeval/`
- `locomo/`

Conventions:

- benchmark-specific parsing, replay policy, and reporting stay here
- product/runtime code stays under `backend/src/magi/`
- outputs are written under `benchmark/outputs/` or a caller-provided output root
- Phase 1 benchmarks should prefer subsystem evaluation over full chat rendering when the goal is to isolate one capability
