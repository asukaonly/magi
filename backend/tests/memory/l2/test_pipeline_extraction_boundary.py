from __future__ import annotations

import inspect
from pathlib import Path

import magi.memory.l2.pipeline.extraction as extraction
from magi.memory.l2.pipeline.extraction import L2PipelineExtractionMixin
from magi.memory.l2.pipeline.phase2_flow import L2Phase2FlowMixin


def test_phase2_flow_lives_in_dedicated_mixin() -> None:
    assert issubclass(L2PipelineExtractionMixin, L2Phase2FlowMixin)
    assert (
        L2PipelineExtractionMixin._run_phase2_flow
        is L2Phase2FlowMixin._run_phase2_flow
    )

    extraction_source_path = Path(str(inspect.getsourcefile(extraction)))
    extraction_source = extraction_source_path.read_text()

    assert "async def _run_phase2_integration" not in extraction_source
    assert "def _ground_phase2_result" not in extraction_source
    assert "async def _persist_phase2_result" not in extraction_source
    assert "def _phase2_result_payload" not in extraction_source
