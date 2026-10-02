"""Bounded audio values and the optional one-way channel contract.

Synthesis owns the content; an output channel owns the destination and playback.
Audio is deliberately a complete, bounded WAV file. This is not a byte-stream
protocol, a speech engine, or a promise of durable/exactly-once playback.
"""

from __future__ import annotations

import io
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_AUDIO_SECONDS = 60


@dataclass(frozen=True, slots=True)
class WavInfo:
    """Format derived from the file, never supplied by a caller."""

    sample_rate_hz: int
    channels: int
    frames: int

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate_hz


def inspect_wav(data: bytes) -> WavInfo:
    """Validate a complete PCM16 WAV without trusting headers or MIME labels."""
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_AUDIO_BYTES:
        raise ValueError("Audio must be a WAV file of at most 2 MiB")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Audio must use the RIFF WAVE container")
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise ValueError("WAV container length does not match the file")
    offset = 12
    seen: set[bytes] = set()
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("WAV chunk header is incomplete")
        kind = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "little")
        end = offset + 8 + size + (size % 2)
        if end > len(data):
            raise ValueError("WAV chunk data is incomplete")
        if kind == b"fmt ":
            header = data[offset + 8:offset + 24]
            if size < 16 or int.from_bytes(header[:2], "little") != 1:
                raise ValueError("Audio must use the PCM WAV format")
            channels = int.from_bytes(header[2:4], "little")
            rate = int.from_bytes(header[4:8], "little")
            byte_rate = int.from_bytes(header[8:12], "little")
            alignment = int.from_bytes(header[12:14], "little")
            bits = int.from_bytes(header[14:16], "little")
            if bits != 16 or alignment != channels * 2 or byte_rate != rate * alignment:
                raise ValueError("WAV format rates and alignment must match PCM16 samples")
        if kind in (b"fmt ", b"data"):
            if kind in seen:
                raise ValueError("WAV contains duplicate format or sample chunks")
            seen.add(kind)
        offset = end
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            rate, channels, frames = (
                reader.getframerate(), reader.getnchannels(), reader.getnframes()
            )
            if reader.getsampwidth() != 2 or reader.getcomptype() != "NONE":
                raise ValueError("Audio must use uncompressed 16-bit PCM")
            if channels not in (1, 2) or not 8000 <= rate <= 96000:
                raise ValueError("Audio must have one or two channels at 8 to 96 kHz")
            if not 0 < frames <= rate * MAX_AUDIO_SECONDS:
                raise ValueError("Audio duration must be greater than zero and at most 60 seconds")
            if len(reader.readframes(frames + 1)) != frames * channels * 2:
                raise ValueError("WAV sample data is incomplete or misaligned")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Audio contains an invalid WAV header") from exc
    return WavInfo(sample_rate_hz=rate, channels=channels, frames=frames)


@dataclass(frozen=True, slots=True)
class AudioClip:
    """A complete PCM16 WAV that fits the plugin IPC frame after base64 encoding."""

    data: bytes

    def __post_init__(self) -> None:
        inspect_wav(self.data)


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be a nonempty identifier of at most 512 characters")


@dataclass(frozen=True, slots=True)
class AudioOutputTarget:
    """An explicitly selected endpoint; target_id belongs to the channel."""

    channel_type: str
    target_id: str

    def __post_init__(self) -> None:
        _identifier(self.channel_type, "channel_type")
        _identifier(self.target_id, "target_id")


class AudioPlaybackState(str, Enum):
    ACCEPTED = "accepted"
    PLAYING = "playing"
    COMPLETED = "completed"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AudioPlaybackReceipt:
    """Playback evidence; acceptance alone does not prove that sound was played."""

    target: AudioOutputTarget
    request_id: str
    playback_id: str
    state: AudioPlaybackState

    def __post_init__(self) -> None:
        if not isinstance(self.target, AudioOutputTarget):
            raise TypeError("Playback target must be an AudioOutputTarget")
        _identifier(self.request_id, "request_id")
        _identifier(self.playback_id, "playback_id")
        if not isinstance(self.state, AudioPlaybackState):
            raise TypeError("Playback state must be an AudioPlaybackState")


class AudioOutputChannel(ABC):
    """Optional output-only contribution returned by Plugin.get_channel().

    No chat identity, inbound clear strategy or typing indicator is required.
    The host invokes play once for an explicitly selected target. Adapters
    correlate request_id with their provider; they must not claim completion
    without evidence or retry an uncertain side effect automatically.
    """

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Return this channel's registry identifier."""

    @abstractmethod
    async def start(self) -> None:
        """Prepare the output connection."""

    @abstractmethod
    async def stop(self) -> None:
        """Release the connection and all local audio resources."""

    @abstractmethod
    async def play_audio(
        self, target: AudioOutputTarget, clip: AudioClip, request_id: str,
    ) -> AudioPlaybackReceipt:
        """Submit one complete clip; validate that the target is authorized."""

    @abstractmethod
    async def get_playback(self, receipt: AudioPlaybackReceipt) -> AudioPlaybackReceipt:
        """Return evidence for this exact playback, or UNKNOWN if unavailable."""

    @abstractmethod
    async def stop_playback(self, receipt: AudioPlaybackReceipt) -> AudioPlaybackReceipt:
        """Stop this playback; report UNKNOWN when stopping cannot be confirmed."""

    @abstractmethod
    async def clear_audio(self) -> None:
        """Invalidate local playback state without waiting for a remote device.

        Stop local buffers, forget retained content and reject in-flight late
        results. A subsequent start/play must not replay pre-clear audio. This
        is local content cleanup, not proof that remote sound was stopped.
        """
