from __future__ import annotations

from magi.context.summary_generation import (
    SummaryChunkRequest,
    generate_cumulative_summary,
    resolve_cumulative_summary_output_tokens,
)
from magi.context.window_budget import estimate_context_tokens


async def test_cumulative_summary_chunks_multilingual_text_by_full_prompt_capacity() -> None:
    source = ("这是需要完整保留的中文上下文。" * 2_000).strip()
    requests: list[SummaryChunkRequest] = []
    system_prompt = "Summarize faithfully."
    input_capacity = 3_000

    async def call_chunk(request: SummaryChunkRequest) -> str:
        requests.append(request)
        return "阶段摘要" * 120

    summary = await generate_cumulative_summary(
        source_text=source,
        system_prompt=system_prompt,
        input_capacity=input_capacity,
        build_prompt=lambda previous, chunk: (
            f"Previous:\n{previous}\n\nNext:\n{chunk}" if previous else f"Next:\n{chunk}"
        ),
        call_chunk=call_chunk,
    )

    assert summary == "阶段摘要" * 120
    assert len(requests) > 1
    assert "".join(request.source_chunk for request in requests) == source
    assert all(
        estimate_context_tokens(
            {
                "system_prompt": system_prompt,
                "messages": [{"role": "user", "content": request.prompt}],
            }
        )
        <= int(input_capacity * 0.90)
        for request in requests
    )
    assert requests[-1].is_final is True


def test_cumulative_summary_output_leaves_room_for_merge_input() -> None:
    assert resolve_cumulative_summary_output_tokens(8_000, input_capacity=8_000) == 3_200
    assert resolve_cumulative_summary_output_tokens(1_000, input_capacity=8_000) == 1_000
