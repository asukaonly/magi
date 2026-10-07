import type { TTSConfiguration, TTSModelStatus } from '@/api/modules/tts';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';

export function ttsConfiguration(state: TTSModelStatus['state'] = 'ready', runtime = true): TTSConfiguration {
  return {
    settings: structuredClone(DEFAULT_SYSTEM_CONFIG.speech.tts), revision: 'rev',
    models: ['kokoro-multi-lang-v1_0', 'vits-melo-tts-zh_en'].map((model_id, index) => ({
      engine: 'local', model_id, name: index ? 'MeloTTS' : 'Kokoro', provider_id: null, provider_name: '',
      voices: index ? [{ id: 'zh_en', language: 'zh', name: 'MeloTTS' }] : [
        { id: 'zf_xiaobei', language: 'zh', name: '' }, { id: 'af_heart', language: 'en', name: '' },
      ], custom_voice: false, custom_model: false, speed_min: 0.5, speed_max: 2, instructions: false, emotions: [],
      download_bytes: index ? 177481452 : 401238752,
      status: { model_id, state, download: null, error: null, runtime_available: runtime, recommended: false },
    })),
  };
}
