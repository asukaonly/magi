"""Small, explicit speech capability catalog shared by validation and settings."""

from urllib.parse import urlsplit

from magi.config.models import AppConfig, LLMProviderSettings

from .contracts import TTSModelChoice, VoiceInfo
from .models import MODEL_NAMES, REMOTE_VOICES, TTSModelStore, local_voices


def endpoint(provider: LLMProviderSettings) -> str:
    service = provider.services.tts
    defaults = {"minimax": "https://api.minimax.io/v1", "dashscope": "https://dashscope.aliyuncs.com/api/v1"}
    return service.base_url or defaults.get(service.protocol) or provider.base_url or (
        "https://api.openai.com/v1" if provider.provider_type == "openai" else "")


def remote_voices(base_url: str, model: str) -> list[str]:
    """A compatible endpoint does not imply OpenAI's model or voice catalog."""
    if urlsplit(base_url).hostname != "api.openai.com":
        return []
    if model == "gpt-4o-mini-tts":
        return list(REMOTE_VOICES)
    if model in {"tts-1", "tts-1-hd"}:
        return [voice for voice in REMOTE_VOICES if voice not in {"ballad", "verse", "marin", "cedar"}]
    return []


def provider_models(provider_id: str, provider: LLMProviderSettings) -> list[TTSModelChoice]:
    common = {"engine": "remote", "provider_id": provider_id, "provider_name": provider.display_name or provider_id}
    protocol = provider.services.tts.protocol
    if protocol == "minimax":
        voices = [VoiceInfo(id="Chinese (Mandarin)_Lyrical_Voice", language="zh", name="Lyrical Voice"),
                  VoiceInfo(id="Chinese (Mandarin)_HK_Flight_Attendant", language="zh", name="HK Flight Attendant"),
                  VoiceInfo(id="English_Graceful_Lady", language="en", name="Graceful Lady")]
        return [TTSModelChoice(**common, model_id=model, name=model, voices=voices,
                              custom_voice=True, speed_min=0.5, speed_max=2,
                              emotions=["happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm"])
                for model in ("speech-2.8-hd", "speech-2.8-turbo")]
    if protocol == "dashscope":
        return [TTSModelChoice(**common, model_id=model, name=model,
                              voices=[VoiceInfo(id="Cherry", language="zh", name="Cherry")],
                              custom_voice=True, instructions=model == "qwen3-tts-instruct-flash")
                for model in ("qwen3-tts-flash", "qwen3-tts-instruct-flash")]
    if urlsplit(endpoint(provider)).hostname == "api.openai.com":
        return [TTSModelChoice(**common, model_id=model, name=model,
                              voices=[VoiceInfo(id=voice, language="multilingual", name=voice.title())
                                      for voice in remote_voices(endpoint(provider), model)],
                              speed_min=0.25, speed_max=4, instructions=model == "gpt-4o-mini-tts")
                for model in ("gpt-4o-mini-tts", "tts-1", "tts-1-hd")]
    # Only the basic WAV protocol is promised for user-supplied compatible endpoints.
    return [TTSModelChoice(**common, model_id="", name="", voices=[], custom_model=True,
                          custom_voice=True, speed_min=0.5, speed_max=2)]


def choices(config: AppConfig, models: TTSModelStore) -> list[TTSModelChoice]:
    result = [TTSModelChoice(engine="local", model_id=model_id, name=name,
                            voices=local_voices(model_id), speed_min=0.5, speed_max=2,
                            download_bytes=sum(item["size"] for item in models.get(model_id).manifest()["files"]),
                            status=models.get(model_id).snapshot())
              for model_id, name in MODEL_NAMES.items()]
    for provider_id, provider in config.llm.providers.items():
        if provider.enabled and provider.services.tts.enabled:
            result.extend(provider_models(provider_id, provider))
    return result
