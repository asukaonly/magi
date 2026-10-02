"""Pinned model resources with staged, checked installation on the service host."""

import asyncio
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from urllib.parse import quote

import httpx

from .contracts import TTSModelStatus, VoiceInfo

MODEL_ID = "kokoro-multi-lang-v1_0"
VOICE_NAMES = ("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
               "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa "
               "bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis "
               "ef_dora em_alex ff_siwis hf_alpha hf_beta hm_omega hm_psi if_sara im_nicola "
               "jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo pf_dora pm_alex pm_santa "
               "zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia zm_yunyang").split()
LOCAL_VOICES = [VoiceInfo(id=name, language="zh" if name.startswith("z") else "en")
                for name in VOICE_NAMES if name[0] in "zab"]
REMOTE_VOICES = "alloy ash ballad coral echo fable nova onyx sage shimmer verse marin cedar".split()


class ModelManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / MODEL_ID
        self.status = TTSModelStatus()
        self.task: asyncio.Task[None] | None = None
        self.in_use = False

    def snapshot(self) -> TTSModelStatus:
        result = self.status.model_copy()
        result.runtime_available = importlib.util.find_spec("sherpa_onnx") is not None
        if (self.directory / "verified.json").is_file():
            result.state = "ready"
            result.progress = 1
        return result

    def manifest(self) -> dict:
        return json.loads(Path(__file__).with_name("kokoro-manifest.json").read_text())

    def verify(self) -> None:
        for item in self.manifest()["files"]:
            path = self.directory / item["path"]
            if path.is_symlink() or not path.is_file() or path.stat().st_size != item["size"]:
                raise ValueError("model_missing")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError("model_checksum_failed")

    def download(self, proxy_url: str | None = None) -> TTSModelStatus:
        if self.task and not self.task.done():
            return self.snapshot()
        if self.in_use:
            raise ValueError("model_busy")
        if self.snapshot().state == "ready":
            return self.snapshot()
        self.status = TTSModelStatus(state="downloading")
        self.task = asyncio.create_task(self._download(proxy_url))
        return self.snapshot()

    async def _download(self, proxy_url: str | None) -> None:
        staging = self.root / (MODEL_ID + ".partial")
        manifest = self.manifest()
        try:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, mode=0o700)
            total = sum(item["size"] for item in manifest["files"])
            received = 0
            async with httpx.AsyncClient(follow_redirects=True, timeout=90, proxy=proxy_url, trust_env=False) as client:
                for item in manifest["files"]:
                    path = staging / item["path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    url = f'https://huggingface.co/{manifest["repo"]}/resolve/{manifest["revision"]}/{quote(item["path"])}'
                    size = 0
                    digest = hashlib.sha256()
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        with path.open("wb") as output:
                            async for chunk in response.aiter_bytes(256 * 1024):
                                size += len(chunk)
                                if size > item["size"]:
                                    raise ValueError("model_checksum_failed")
                                output.write(chunk)
                                digest.update(chunk)
                                received += len(chunk)
                                self.status.progress = received / total
                    if size != item["size"] or digest.hexdigest() != item["sha256"]:
                        raise ValueError("model_checksum_failed")
            (staging / "verified.json").write_text(json.dumps({"revision": manifest["revision"]}))
            staging.rename(self.directory)
            self.status.state = "ready"
        except asyncio.CancelledError:
            self.status.state = "cancelled"
        except (OSError, ValueError, httpx.HTTPError):
            self.status.state = "failed"
            self.status.error = "model_download_failed"
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    async def cancel(self) -> TTSModelStatus:
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self.status.state = "cancelled"
        return self.snapshot()

    def delete(self) -> TTSModelStatus:
        if self.in_use or (self.task and not self.task.done()):
            raise ValueError("model_busy")
        shutil.rmtree(self.directory, ignore_errors=True)
        self.status = TTSModelStatus()
        return self.snapshot()
