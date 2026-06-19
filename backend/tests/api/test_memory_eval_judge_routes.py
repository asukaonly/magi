from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory import memory_router


def test_memory_eval_judge_answer_uses_core_llm(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    calls: list[dict] = []

    class _FakeLLMAdapter:
        model_name = "core-test-model"

        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            calls.append(
                {
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "kwargs": kwargs,
                }
            )
            assert "Gold answer: 2022" in messages[-1]["content"]
            return '{"label":"CORRECT","reasoning":"same year"}'

    class _FakeLLMPool:
        def get(self, scenario):
            assert str(scenario.value) == "core"
            return _FakeLLMAdapter()

    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/judge-answer",
        json={
            "system_prompt": "Return JSON only.",
            "prompt": "Question: When?\nGold answer: 2022\nGenerated answer: last year",
            "max_tokens": 256,
            "temperature": 0.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == '{"label":"CORRECT","reasoning":"same year"}'
    assert body["llm_scenario"] == "core"
    assert body["model"] == "core-test-model"
    assert calls[0]["max_tokens"] == 256
    assert calls[0]["temperature"] == 0.0
