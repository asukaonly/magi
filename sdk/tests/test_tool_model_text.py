"""Model observations remain separate from canonical values across the wire."""

import io

import pytest
from magi_plugin_sdk.runtime import OperationResult
from magi_plugin_sdk.tools import ToolResult
from magi_plugin_sdk.transport import pack, read_frame
from pydantic import ValidationError


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled", "uncertain"])
def test_operation_observation_round_trip_preserves_status_and_data(status):
    operation = OperationResult(
        status=status, value={"receipt": "id-1", "diagnostics": {"attempts": 3}},
        model_text="Receipt: id-1\nProvider diagnostic details omitted.",
        error_code=None if status == "succeeded" else "PROVIDER_ERROR",
    )
    decoded = read_frame(io.BytesIO(pack({"result": operation})))["result"]
    assert decoded == operation
    tool = ToolResult.from_operation(decoded)
    assert tool.success is (status == "succeeded")
    assert tool.operation_status == status
    assert tool.model_text == operation.model_text
    assert tool.data == operation.value
    assert read_frame(io.BytesIO(pack({"result": tool})))["result"] == tool


@pytest.mark.parametrize("model_text", [42, {"text": "wrong shape"}, ["text"]])
def test_model_observation_requires_text(model_text):
    with pytest.raises(ValidationError):
        ToolResult(success=True, model_text=model_text)
    with pytest.raises(ValidationError):
        OperationResult(status="succeeded", model_text=model_text)


def test_model_observation_is_optional_for_structured_consumers():
    result = ToolResult(success=True, data={"receipt": "id-1"})
    assert result.model_text is None
    assert result.data == {"receipt": "id-1"}
