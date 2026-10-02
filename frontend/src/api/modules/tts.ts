import { api } from '../client';
import { ApiContractError } from '../config-contract';
import type { components } from '../generated/tts-types';
import { validateSynthesisJob, validateTTSConfiguration, validateTTSModelStatus } from '../generated/tts-validators';

type Wire = components['schemas'];
export type TTSJob = Wire['SynthesisJob'];
export type TTSSource = Wire['SynthesisRequest']['source'];
export type TTSConfiguration = Wire['TTSConfiguration'];
export type TTSSettings = Wire['TTSSettings'];
export type TTSModelStatus = Wire['TTSModelStatus'];

function job(value: unknown): TTSJob {
  if (!validateSynthesisJob(value)) throw new ApiContractError('TTS job');
  if (value.ready_segments < 0 || value.ready_segments > value.total_segments) throw new ApiContractError('TTS sequence');
  return value;
}
function settings(value: unknown): TTSConfiguration {
  if (!validateTTSConfiguration(value)) throw new ApiContractError('TTS configuration');
  return value;
}
function model(value: unknown): TTSModelStatus {
  if (!validateTTSModelStatus(value)) throw new ApiContractError('TTS model');
  return value;
}
const base = '/speech/tts';
export const ttsApi = {
  settings: async () => settings(await api.get<unknown>(`${base}/settings`)),
  save: async (value: TTSSettings, revision: string) => settings(await api.put<unknown>(`${base}/settings`, { settings: value, revision })),
  model: async () => model(await api.get<unknown>(`${base}/models`)),
  download: async () => model(await api.post<unknown>(`${base}/models/download`, {})),
  cancelDownload: async () => model(await api.post<unknown>(`${base}/models/download/cancel`, {})),
  deleteModel: async () => model(await api.delete<unknown>(`${base}/models`)),
  create: async (requestId: string, source: TTSSource, signal: AbortSignal) => job(await api.post<unknown>(`${base}/syntheses`, { request_id: requestId, source }, { signal })),
  byRequest: async (requestId: string, signal: AbortSignal) => job(await api.get<unknown>(`${base}/syntheses/by-request/${requestId}`, { signal })),
  get: async (id: string, signal: AbortSignal) => job(await api.get<unknown>(`${base}/syntheses/${id}`, { signal })),
  advance: async (id: string, seq: number, signal: AbortSignal) => job(await api.post<unknown>(`${base}/syntheses/${id}/segments/${seq}`, {}, { signal })),
  cancel: async (requestId: string) => job(await api.post<unknown>(`${base}/syntheses/by-request/${requestId}/cancel`, {})),
  audio: async (id: string, seq: number, signal: AbortSignal): Promise<ArrayBuffer> => {
    const value: unknown = await api.get<unknown>(`${base}/syntheses/${id}/segments/${seq}`, { responseType: 'arraybuffer', signal });
    if (!(value instanceof ArrayBuffer)) throw new ApiContractError('TTS WAV');
    return value;
  },
};
