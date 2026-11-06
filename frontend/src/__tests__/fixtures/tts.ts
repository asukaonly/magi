import type { TTSConfiguration, TTSModelStatus } from '@/api/modules/tts';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';

export function ttsConfiguration(state: TTSModelStatus['state'] = 'ready', runtime = true): TTSConfiguration {
  return {
    settings: { ...structuredClone(DEFAULT_SYSTEM_CONFIG.speech.tts), local_model: 'kokoro-multi-lang-v1_0', local_voice: 'zf_xiaobei' }, revision: 'rev', reference_audio: [],
    models: ['kokoro-multi-lang-v1_0', 'vits-melo-tts-zh_en'].map((model_id, index) => ({
      engine: 'local', model_id, name: index ? 'MeloTTS' : 'Kokoro', provider_id: null, provider_name: '',
      recommended: false, experimental: false, runtime: 'onnx', reference_audio: 'none', voice_description: false, seed: false, companion_model: false,
      voices: index ? [{ id: 'zh_en', language: 'zh', name: 'MeloTTS' }] : [
        { id: 'zf_xiaobei', language: 'zh', name: '' }, { id: 'af_heart', language: 'en', name: '' },
      ], custom_voice: false, custom_model: false, speed_min: 0.5, speed_max: 2, instructions: false, emotions: [],
      download_bytes: index ? 177481452 : 401238752,
      status: { model_id, state, download: null, error: null, runtime_available: runtime, recommended: false },
    })),
  };
}

export function modernTTSConfiguration(): TTSConfiguration {
  const config = ttsConfiguration();
  const base = config.models[0];
  config.settings = structuredClone(DEFAULT_SYSTEM_CONFIG.speech.tts);
  config.models.unshift({ ...base, model_id: 'voxcpm2-8bit', name: 'VoxCPM2', voices: [], recommended: true,
    runtime: 'mlx', reference_audio: 'optional', voice_description: true, seed: true, speed_min: null, speed_max: null,
    status: { ...base.status!, model_id: 'voxcpm2-8bit' } },
    { ...base, model_id: 'moss-tts-nano', name: 'MOSS Nano', voices: [], recommended: true, experimental: true,
      runtime: 'mlx', reference_audio: 'required', companion_model: true, seed: true, speed_min: null, speed_max: null,
      status: { ...base.status!, model_id: 'moss-tts-nano' } });
  return config;
}
