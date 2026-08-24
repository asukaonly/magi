from magi.config.models import AppConfig
from magi.llm.factory import is_llm_selection_pending as _is_llm_selection_pending


def test_is_llm_selection_pending_when_required_selection_blank() -> None:
    config = AppConfig()
    config.llm.selections["core"].provider_id = ""
    config.llm.selections["core"].model = ""

    assert _is_llm_selection_pending(config) is True


def test_is_llm_selection_pending_when_required_selections_ready() -> None:
    # A default AppConfig() ships with a blank required core selection,
    # so the user must pick a provider/model on first run.
    config = AppConfig()
    config.llm.selections["core"].provider_id = "openai"
    config.llm.selections["core"].model = "gpt-4o"

    assert _is_llm_selection_pending(config) is False
