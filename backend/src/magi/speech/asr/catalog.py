"""Pinned conversion of ModelScope Paraformer revision v1.1.9.

The upstream model card declares Apache License 2.0. Keep this candidate
experimental until packaged macOS and Windows quality gates are exercised.
"""

from dataclasses import dataclass

MODEL_ID = "paraformer-zh-en-int8"
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


FILES = (
    ModelFile(
        "model.int8.onnx",
        227330205,
        "90bc03034ae1bef9575f8cc798cd1519c8be8aa9e8b458a033e32017ff4d584c",
    ),
    ModelFile(
        "tokens.txt", 75354, "6c0e3b35cece259829e6cb5b8d90d13db88f61ea3a2953d11898e4b2bfd7a2e2"
    ),
)
