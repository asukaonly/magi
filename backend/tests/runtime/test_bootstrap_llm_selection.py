
import pytest
from magi.config.models import AppConfig
from magi.llm.factory import is_llm_selection_pending as _is_llm_selection_pending


@pytest.mark.parametrize(
    "provider_id_value,model_value,expected_pending",
    [
        pytest.param("", "", True, id="is_llm_selection_pending_when_required_selection_blank"),
        pytest.param(
            "openai", "gpt-4o", False, id="is_llm_selection_pending_when_required_selections_ready"
        ),
    ],
)
def test_llm_selection_readiness_tracks_required_fields(
    provider_id_value, model_value, expected_pending
) -> None:
    config = AppConfig()
    config.llm.selections["core"].provider_id = provider_id_value
    config.llm.selections["core"].model = model_value
    assert _is_llm_selection_pending(config) is expected_pending
