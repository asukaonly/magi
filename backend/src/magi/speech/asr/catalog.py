"""Pinned conversion of ModelScope Paraformer revision v1.1.9.

The upstream model card declares Apache License 2.0. Keep this candidate
experimental until packaged macOS and Windows quality gates are exercised.
"""

from dataclasses import dataclass

REPO = "csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09"
REVISION = "906992d326ebf0c5171cde675aa0902be9e5bc6c"
SOURCE_URL = f"https://huggingface.co/{REPO}/tree/{REVISION}"
LICENSE_URL = "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8358-tensorflow1/files?Revision=v1.1.9"


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{REPO}/resolve/{REVISION}/{self.name}"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    model_file: str
    files: tuple[ModelFile, ...]


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
    )
}
