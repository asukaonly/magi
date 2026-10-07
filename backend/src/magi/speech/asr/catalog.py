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
    family: Literal["paraformer", "sense_voice", "qwen3_asr", "whisper"] = "paraformer"
    repo: str = REPO
    revision: str = REVISION
    license: str = "Apache-2.0 (upstream model card)"
    license_url: str = LICENSE_URL
    featured: bool = True
    recommended: bool = False

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
            featured=False,
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
            featured=False,
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
            recommended=True,
        ),
        ModelSpec(
            "qwen3-asr-0.6b-int8",
            "Qwen3-ASR 0.6B",
            "encoder.int8.onnx",
            (
                ModelFile(
                    "conv_frontend.onnx", 44148281,
                    "d22dc4423e0940e49884e903d2ea2f7e5567c14fc1aed97e4e26d6b8f208ef9e",
                ),
                ModelFile(
                    "encoder.int8.onnx", 182491662,
                    "60748d3e6744a57c9c91e1b17424a6c2990567e8adceb0783940c03ed98fa9d9",
                ),
                ModelFile(
                    "decoder.int8.onnx", 755914231,
                    "4f6885be5959ae26af3089d38ee7972c5fafbeeb1cf8d5e76eab6d8b61ca5771",
                ),
                ModelFile(
                    "tokenizer/merges.txt", 1671853,
                    "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
                ),
                ModelFile(
                    "tokenizer/vocab.json", 2776833,
                    "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
                ),
                ModelFile(
                    "tokenizer/tokenizer_config.json", 12487,
                    "4942d005604266809309cabc9f4e9cb89ce855d59b14681fdc0e1cc62ea26c4c",
                ),
            ),
            family="qwen3_asr",
            repo="csukuangfj2/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25",
            revision="68818b2313fe77bd06f6a7c5068ff3ef59d02b8a",
            license="Apache-2.0",
            license_url="https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/LICENSE",
        ),
        ModelSpec(
            "whisper-large-v3-turbo-int8",
            "Whisper large-v3-turbo",
            "turbo-encoder.int8.onnx",
            (
                ModelFile(
                    "turbo-encoder.int8.onnx", 674716297,
                    "b02dcdf54f348741e93fe732b67d933c8dcb6735655f710640143081db38878b",
                ),
                ModelFile(
                    "turbo-decoder.int8.onnx", 361080764,
                    "20accd02388482eb3a46bd615631adfdc85e1eb2c7db9ea3f02a40ffe6b81547",
                ),
                ModelFile(
                    "turbo-tokens.txt", 816730,
                    "b34b360dbb493e781e479794586d661700670d65564001f23024971d1f2fa126",
                ),
            ),
            family="whisper",
            repo="csukuangfj/sherpa-onnx-whisper-turbo",
            revision="2ca6ff69fc878651b770880507669577ac41c2ff",
            license="MIT",
            license_url="https://github.com/openai/whisper/blob/main/LICENSE",
        ),
    )
}
