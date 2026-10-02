"""Exercise the audio SDK through an actual external worker process."""

import io
import wave

import pytest

from magi_plugin_sdk.audio import (
    AudioClip, AudioOutputChannel, AudioOutputTarget, AudioPlaybackState,
)
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.contracts import PluginManifest
from magi_plugin_sdk.runtime import PluginConnection
from magi.plugins.process_runtime import ProcessPluginProxy


PLUGIN = '''
from dataclasses import replace
from magi_plugin_sdk import Plugin
from magi_plugin_sdk.audio import AudioOutputChannel, AudioPlaybackReceipt, AudioPlaybackState, inspect_wav

class Output(AudioOutputChannel):
    channel_type = "speaker"
    def __init__(self):
        self.cleared = False
    async def start(self):
        pass
    async def stop(self):
        await self.clear_audio()
    async def clear_audio(self):
        self.cleared = True
    async def play_audio(self, target, clip, request_id):
        assert target.channel_type == "speaker"
        frames = inspect_wav(clip.data).frames
        return AudioPlaybackReceipt(target, request_id, str(frames), AudioPlaybackState.ACCEPTED)
    async def get_playback(self, receipt):
        return replace(receipt, state=AudioPlaybackState.UNKNOWN if self.cleared else AudioPlaybackState.PLAYING)
    async def stop_playback(self, receipt):
        return replace(receipt, state=AudioPlaybackState.STOP_REQUESTED)

class TestPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.output = Output()
    def get_channel(self):
        return self.output
'''


class Credentials:
    def get(self, key):
        return None

    def set(self, key, value):
        raise AssertionError("Audio fixture must not access credentials")

    def delete(self, key):
        raise AssertionError("Audio fixture must not access credentials")


@pytest.mark.asyncio
async def test_real_worker_audio_delivery_and_connection_isolation(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "plugin.py").write_text(PLUGIN)
    manifest = PluginManifest(
        id="audio-test", name="Audio test", version="0.1.0", entry_class="TestPlugin",
        plugin_dir=str(package), manifest_path=str(package / "plugin.toml"),
        execution_mode="trusted_process",
    )
    connection = PluginConnection(
        connection_id="audio-connection", plugin_id="audio-test", display_name="Audio", enabled=True,
    )
    context = PluginContext(connection, tmp_path / "state", tmp_path / "resources", Credentials())
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(b"\0\0" * 16000)
    clip = AudioClip(output.getvalue())
    proxy = ProcessPluginProxy(manifest, connection, context)
    try:
        channel = proxy.get_channel()
        assert isinstance(channel, AudioOutputChannel)
        assert not hasattr(channel, "inbound_clear_strategy")
        await channel.start()
        target = AudioOutputTarget(channel.channel_type, "living-room")
        receipt = await channel.play_audio(target, clip, "request-1")
        assert receipt.playback_id == "16000"
        assert receipt.target == target
        assert receipt.state == AudioPlaybackState.ACCEPTED
        assert (await channel.get_playback(receipt)).state == AudioPlaybackState.PLAYING
        assert (await channel.stop_playback(receipt)).state == AudioPlaybackState.STOP_REQUESTED
        with pytest.raises(PermissionError, match="another connection"):
            await channel.play_audio(AudioOutputTarget("foreign:speaker", "room"), clip, "request-2")
        await channel.clear_audio()
        assert (await channel.get_playback(receipt)).state == AudioPlaybackState.UNKNOWN
        await channel.stop()
    finally:
        await proxy.shutdown()
