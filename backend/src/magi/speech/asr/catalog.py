"""Pinned ASR model families and verified download assets."""

from dataclasses import dataclass
from typing import Literal

REPO = "csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09"
REVISION = "906992d326ebf0c5171cde675aa0902be9e5bc6c"
LICENSE_URL = "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8358-tensorflow1/files?Revision=v1.1.9"


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    model_file: str
    files: tuple[ModelFile, ...]
    family: Literal["paraformer", "sense_voice"] = "paraformer"
    repo: str = REPO
    revision: str = REVISION
    license: str = "Apache-2.0 (upstream model card)"
    license_url: str = LICENSE_URL

    @property
    def source_url(self) -> str:
        return f"https://huggingface.co/{self.repo}/tree/{self.revision}"

    def file_url(self, file: ModelFile) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{file.name}"


_TOKENS = ModelFile(
    "tokens.txt", 75354, "6c0e3b35cece259829e6cb5b8d90d13db88f61ea3a2953d11898e4b2bfd7a2e2"
)
CATALOG = {
    model.id: model
    for model in (
        ModelSpec(
            "paraformer-zh-en-int8",
            "Paraformer Chinese / English (int8)",
            "model.int8.onnx",
            (
                ModelFile(
                    "model.int8.onnx",
                    227330205,
                    "90bc03034ae1bef9575f8cc798cd1519c8be8aa9e8b458a033e32017ff4d584c",
                ),
                _TOKENS,
            ),
        ),
        ModelSpec(
            "paraformer-zh-en-fp32",
            "Paraformer Chinese / English (float32)",
            "model.onnx",
            (
                ModelFile(
                    "model.onnx",
                    822641426,
                    "ed302fb061dcb65655b5240f5f8cd18d6d6c2f5c2b5cb63184d413d728bc1ec4",
                ),
                _TOKENS,
            ),
        ),
        ModelSpec(
            "sensevoice-zh-en-ja-ko-yue",
            "SenseVoice",
            "model.int8.onnx",
            (
                ModelFile(
                    "model.int8.onnx",
                    239233841,
                    "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
                ),
                ModelFile(
                    "tokens.txt",
                    315894,
                    "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
                ),
            ),
            family="sense_voice",
            repo="csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
            revision="2365baeacb507f821a0c8120fcee3d484dba7a07",
            license="SenseVoice model license",
            license_url="https://huggingface.co/FunAudioLLM/SenseVoiceSmall/blob/main/LICENSE",
        ),
    )
}
