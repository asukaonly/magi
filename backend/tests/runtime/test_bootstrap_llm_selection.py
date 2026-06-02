from magi.config.models import AppConfig
from magi.llm.factory import is_llm_selection_pending as _is_llm_selection_pending


def test_is_llm_selection_pending_when_required_selection_blank() -> None:
    config = AppConfig()
    config.llm.selections["context_decider"].provider_id = ""
    config.llm.selections["context_decider"].model = ""

    assert _is_llm_selection_pending(config) is True


def test_is_llm_selection_pending_when_required_selections_ready() -> None:
    # A default AppConfig() ships with blank required selections
    # (context_decider/core provider_id+model default to ""), so the
    # user must pick a provider/model on first run. Populate them to
    # exercise the "ready" path.
    config = AppConfig()
    for scenario in ("context_decider", "core"):
        config.llm.selections[scenario].provider_id = "openai"
        config.llm.selections[scenario].model = "gpt-4o"

    assert _is_llm_selection_pending(config) is False
