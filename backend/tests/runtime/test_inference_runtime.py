"""Required inference dependencies must fail closed before packaging."""

from types import SimpleNamespace

import pytest

from magi.utils import inference_runtime
from magi.utils.sidecar_build import build_pyinstaller_command


@pytest.mark.parametrize("module_name", ["onnxruntime", "tokenizers", "sherpa_onnx"])
@pytest.mark.parametrize("failure", ["missing", "native_library", "missing_api", "invalid_api"])
def test_build_rejects_incomplete_inference_runtime(monkeypatch, module_name, failure):
    original_import = inference_runtime.importlib.import_module

    def import_module(name, package=None):
        if name != module_name:
            return original_import(name, package)
        if failure == "missing":
            raise ModuleNotFoundError(name)
        if failure == "native_library":
            raise OSError("Native library could not be loaded")
        if failure == "missing_api":
            return SimpleNamespace()
        return SimpleNamespace(InferenceSession=None, Tokenizer=None, OfflineRecognizer=None)

    monkeypatch.setattr(inference_runtime.importlib, "import_module", import_module)
    with pytest.raises(RuntimeError, match=f"Required inference runtime {module_name}") as error:
        build_pyinstaller_command()
    assert error.value.__cause__ is not None


@pytest.mark.parametrize("missing_api", ["OfflineRecognizer", "OfflineTts"])
def test_both_speech_apis_are_required(monkeypatch, missing_api):
    original_import = inference_runtime.importlib.import_module
    speech = SimpleNamespace(OfflineRecognizer=lambda: None, OfflineTts=lambda: None)
    delattr(speech, missing_api)
    monkeypatch.setattr(
        inference_runtime.importlib,
        "import_module",
        lambda name: speech if name == "sherpa_onnx" else original_import(name),
    )
    with pytest.raises(RuntimeError, match="Required inference runtime sherpa_onnx"):
        inference_runtime.validate_inference_runtime()


def test_required_inference_apis_load_without_models():
    inference_runtime.validate_inference_runtime()


@pytest.mark.parametrize("method", ["from_sense_voice", "from_qwen3_asr", "from_whisper"])
def test_catalog_recognizer_apis_are_required(monkeypatch, method):
    import sherpa_onnx

    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, method, None)
    with pytest.raises(RuntimeError, match="Required inference runtime sherpa_onnx"):
        inference_runtime.validate_inference_runtime()
