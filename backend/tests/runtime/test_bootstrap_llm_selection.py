from magi.config.models import AppConfig
from magi.runtime.bootstrap import _is_llm_selection_pending


def test_is_llm_selection_pending_when_required_selection_blank() -> None:
    config = AppConfig()
    config.llm.selections["context_decider"].provider_id = ""
    config.llm.selections["context_decider"].model = ""

    assert _is_llm_selection_pending(config) is True


def test_is_llm_selection_pending_when_required_selections_ready() -> None:
    config = AppConfig()

    assert _is_llm_selection_pending(config) is False
