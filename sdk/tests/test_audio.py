import io
import wave

import pytest
from magi_plugin_sdk.audio import (
    MAX_AUDIO_BYTES,
    AudioClip,
    AudioOutputTarget,
    AudioPlaybackReceipt,
    AudioPlaybackState,
    inspect_wav,
)
from magi_plugin_sdk.transport import MAX_FRAME_BYTES, decode, encode, pack


def wav(samples=b"\0\0" * 160, rate=16000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        writer.writeframes(samples)
    return output.getvalue()


def test_wav_metadata_is_derived_from_samples():
    info = inspect_wav(wav(b"\0\0" * 48000, 48000))
    assert (info.sample_rate_hz, info.channels, info.duration_seconds) == (48000, 1, 1)


@pytest.mark.parametrize("data", [
    b"not audio", wav(b""), wav(width=1), wav(channels=3), wav(rate=1000),
    wav()[:-2], wav() + b"trailer", wav(b"\0\0" * (16000 * 61)),
    wav(b"\0\0" * (MAX_AUDIO_BYTES // 2)),
])
def test_rejects_invalid_unsupported_or_unbounded_audio(data):
    with pytest.raises(ValueError):
        AudioClip(data)


def test_rejects_truncated_data_even_if_riff_length_was_rewritten():
    original = wav()
    truncated = original[:4] + (len(original) - 10).to_bytes(4, "little") + original[8:-2]
    with pytest.raises(ValueError, match="incomplete"):
        inspect_wav(truncated)


@pytest.mark.parametrize("offset,value,width", [(20, 3, 2), (28, 1, 4), (32, 4, 2)])
def test_rejects_inconsistent_pcm_headers(offset, value, width):
    data = bytearray(wav())
    data[offset:offset + width] = value.to_bytes(width, "little")
    with pytest.raises(ValueError):
        inspect_wav(bytes(data))


def test_audio_values_round_trip_and_fit_worker_frame():
    clip = AudioClip(wav(b"\0\0" * 960000))
    assert decode(encode(clip)) == clip
    assert len(pack({"clip": clip})) < MAX_FRAME_BYTES
    receipt = AudioPlaybackReceipt(
        AudioOutputTarget("speaker", "living-room"), "request-1", "play-1",
        AudioPlaybackState.ACCEPTED,
    )
    assert decode(encode(receipt)) == receipt
    assert receipt.state is not AudioPlaybackState.COMPLETED


def test_codec_revalidates_audio_and_receipts():
    encoded = encode(AudioClip(wav()))
    encoded["value"]["value"]["data"] = encode(b"invalid")
    with pytest.raises(ValueError):
        decode(encoded)
    with pytest.raises(ValueError):
        AudioPlaybackReceipt(AudioOutputTarget("speaker", "room"), "", "p", AudioPlaybackState.UNKNOWN)
