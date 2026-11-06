"""Pinned model resources with staged, checked installation on the service host."""

import asyncio
import hashlib
import importlib.util
import json
import platform
import shutil
from pathlib import Path
from urllib.parse import quote

import httpx

from .contracts import TTSModelStatus, VoiceInfo
from ...utils.model_download import DownloadFile, DownloadTracker, download_files, remove_directory, safe_path

MODEL_ID = "kokoro-multi-lang-v1_0"
MELO_ID = "vits-melo-tts-zh_en"
VOX_ID = "voxcpm2-8bit"
NANO_ID = "moss-tts-nano"
QWEN_ID = "qwen3-tts-customvoice-8bit"
MOSS_ID = "moss-tts-local-1.5-4bit"
MLX_MODELS = {VOX_ID, NANO_ID, QWEN_ID, MOSS_ID}
MODEL_NAMES = {VOX_ID: "VoxCPM2", NANO_ID: "MOSS TTS Nano", QWEN_ID: "Qwen3-TTS CustomVoice",
               MOSS_ID: "MOSS TTS Local 1.5", MELO_ID: "MeloTTS", MODEL_ID: "Kokoro"}
MANIFESTS = {MODEL_ID: "kokoro-manifest.json", MELO_ID: "melo-manifest.json",
             **{model: model + "-manifest.json" for model in MLX_MODELS}}
VOICE_NAMES = ("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
               "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa "
               "bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis "
               "ef_dora em_alex ff_siwis hf_alpha hf_beta hm_omega hm_psi if_sara im_nicola "
               "jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo pf_dora pm_alex pm_santa "
               "zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia zm_yunyang").split()
LOCAL_VOICES = [VoiceInfo(id=name, language="zh" if name.startswith("z") else "en")
                for name in VOICE_NAMES if name[0] in "zab"]
REMOTE_VOICES = "alloy ash ballad coral echo fable nova onyx sage shimmer verse marin cedar".split()


def local_voices(model_id: str) -> list[VoiceInfo]:
    if model_id == MODEL_ID:
        return LOCAL_VOICES
    if model_id == MELO_ID:
        return [VoiceInfo(id="zh_en", language="zh", name="MeloTTS")]
    if model_id == QWEN_ID:
        return [VoiceInfo(id=name, language=language, name=name.replace('_', ' ').title())
                for name, language in [("serena", "zh"), ("vivian", "zh"), ("uncle_fu", "zh"),
                                       ("dylan", "zh"), ("eric", "zh"), ("ryan", "en"),
                                       ("aiden", "en"), ("ono_anna", "ja"), ("sohee", "ko")]]
    if model_id in MLX_MODELS:
        return []
    raise ValueError("invalid_model")


class ModelManager:
    def __init__(self, root: Path, model_id: str = MODEL_ID) -> None:
        self.root = root
        self.model_id = model_id
        self.directory = root / model_id
        self.status = TTSModelStatus(model_id=model_id)
        self.task: asyncio.Task[None] | None = None
        self.in_use = False
        self.cancelling = False
        self.transfer: DownloadTracker | None = None

    def snapshot(self) -> TTSModelStatus:
        result = self.status.model_copy()
        modules = ("onnxruntime", "kaldifst", "espeakng_loader") if self.model_id == MODEL_ID else ("sherpa_onnx",)
        result.runtime_available = all(importlib.util.find_spec(name) is not None for name in modules)
        if self.model_id in MLX_MODELS:
            result.runtime_available = (platform.system() == "Darwin" and platform.machine() == "arm64"
                                        and importlib.util.find_spec("mlx_audio") is not None)
        if (self.directory / "verified.json").is_file():
            result.state = "ready"
        result.download = self.transfer.snapshot() if self.transfer else None
        return result

    def manifest(self) -> dict:
        return json.loads(Path(__file__).with_name(MANIFESTS[self.model_id]).read_text())

    def verify(self, directory: Path | None = None, codec_directory: Path | None = None) -> None:
        root = directory or self.directory
        for item in self.manifest()["files"]:
            name = item["path"]
            path = codec_directory / name.removeprefix("codec/") if codec_directory and name.startswith("codec/") else root / name
            if (directory is None and path.is_symlink()) or not path.is_file() or path.stat().st_size != item["size"]:
                raise ValueError("model_missing")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError("model_checksum_failed")

    def inspect_directory(self, path: str, codec_path: str = "") -> TTSModelStatus:
        directory, codec = external_directories(path, codec_path, self.model_id)
        self.verify(directory, codec)
        return self.snapshot().model_copy(update={"state": "ready", "download": None, "error": None})

    def download(self, proxy_url: str | None = None) -> TTSModelStatus:
        if self.cancelling or (self.task and not self.task.done()):
            return self.snapshot()
        if self.in_use:
            raise ValueError("model_busy")
        if self.snapshot().state == "ready":
            return self.snapshot()
        self.status = TTSModelStatus(model_id=self.model_id, state="downloading")
        self.transfer = DownloadTracker()
        self.task = asyncio.create_task(self._download(proxy_url))
        return self.snapshot()

    async def _download(self, proxy_url: str | None) -> None:
        staging = self.root / (self.model_id + ".partial")
        manifest = self.manifest()
        assert self.transfer is not None
        try:
            safe_path(self.directory, "verified.json")
            await download_files([DownloadFile(
                item["path"],
                f'https://huggingface.co/{item.get("repo", manifest["repo"])}/resolve/{item.get("revision", manifest["revision"])}/{quote(item.get("source_path", item["path"]))}',
                item["size"], item["sha256"],
            ) for item in manifest["files"]], staging, self.transfer, proxy_url)
            (staging / "verified.json").write_text(json.dumps({"revision": manifest["revision"]}))
            if self.directory.exists():
                await remove_directory(self.directory)
            (staging / ".download.json").unlink()
            staging.rename(self.directory)
            self.status.state = "ready"
            self.transfer.phase = "completed"
        except asyncio.CancelledError:
            self.status.state = "cancelled"
            self.transfer.phase = "cancelled"
            raise
        except (OSError, ValueError, asyncio.TimeoutError, httpx.HTTPError):
            self.status.state = "failed"
            self.status.error = "model_download_failed"
            self.transfer.phase = "failed"

    async def cancel(self) -> TTSModelStatus:
        if self.cancelling and self.task:
            await asyncio.shield(asyncio.gather(self.task, return_exceptions=True))
            return self.snapshot()
        if self.task and not self.task.done():
            self.cancelling = True
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self.status.state = "cancelled"
            finally:
                if self.transfer:
                    self.transfer.phase = "cancelled"
                self.cancelling = False
        return self.snapshot()

    def delete(self) -> TTSModelStatus:
        if self.in_use or self.cancelling or (self.task and not self.task.done()):
            raise ValueError("model_busy")
        shutil.rmtree(self.directory, ignore_errors=True)
        staging = self.root / (self.model_id + ".partial")
        safe_path(staging, ".download.json")
        shutil.rmtree(staging, ignore_errors=True)
        self.status = TTSModelStatus(model_id=self.model_id)
        self.transfer = None
        return self.snapshot()


class TTSModelStore:
    def __init__(self, root: Path) -> None:
        self.models = {model_id: ModelManager(root, model_id) for model_id in MODEL_NAMES}

    def get(self, model_id: str) -> ModelManager:
        if model_id not in self.models:
            raise ValueError("invalid_model")
        return self.models[model_id]


def external_directories(path: str, codec_path: str, model_id: str) -> tuple[Path, Path | None]:
    """External packages are read in place, never adopted by the download manager."""
    directory = Path(path).expanduser()
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("model_directory_invalid")
    if codec_path and model_id not in {NANO_ID, MOSS_ID}:
        raise ValueError("unsupported_parameter")
    codec = Path(codec_path).expanduser() if codec_path else None
    if codec and (not codec.is_absolute() or not codec.is_dir()):
        raise ValueError("model_directory_invalid")
    return directory.resolve(), codec.resolve() if codec else None
