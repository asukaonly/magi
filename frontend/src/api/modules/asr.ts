import { apiClient } from '../client';
import { ApiContractError } from '../config-contract';
import type { components } from '../generated/asr-types';
import { validateASRJob, validateASRModel, validateASRModels, validateASRStatus } from '../generated/asr-validators';
import { getRuntimeConfig, getRuntimeGeneration } from '@/runtime/config';

export type ASRStatus = components['schemas']['ASRStatus'];
export type ASRJob = components['schemas']['ASRJob'];
export type ASRModel = components['schemas']['ASRModel'];
export type ASRScope = { generation: number; dataEpoch: string | undefined; contentEpoch: string | undefined };
export type ASROperation = ASRScope & { requestId: string; runtimeId: string; configRevision: string };

export function asrScope(): ASRScope {
  const runtime = getRuntimeConfig();
  return { generation: getRuntimeGeneration(), dataEpoch: runtime.dataEpoch, contentEpoch: runtime.contentEpoch };
}
export function ownsASRScope(scope: ASRScope): boolean {
  const current = asrScope();
  return scope.generation === current.generation && scope.dataEpoch === current.dataEpoch && scope.contentEpoch === current.contentEpoch;
}
function scoped(scope: ASRScope, signal?: AbortSignal) {
  if (!ownsASRScope(scope)) throw new DOMException('ASR connection changed', 'AbortError');
  return { signal, headers: { 'X-Magi-Data-Epoch': scope.dataEpoch } };
}
function operationConfig(operation: ASROperation, signal?: AbortSignal) {
  const config = scoped(operation, signal);
  return { ...config, headers: { ...config.headers, 'X-Magi-ASR-Runtime': operation.runtimeId, 'X-Magi-ASR-Config': operation.configRevision } };
}
function job(value: unknown, operation: ASROperation): ASRJob {
  if (!ownsASRScope(operation) || !validateASRJob(value) || value.request_id !== operation.requestId
    || value.runtime_id !== operation.runtimeId) throw new ApiContractError('ASR job');
  return value;
}
const base = '/speech/asr';
const path = (operation: ASROperation) => `${base}/transcriptions/${encodeURIComponent(operation.requestId)}`;
export function createASROperation(runtimeId: string, configRevision: string): ASROperation {
  return { ...asrScope(), runtimeId, configRevision, requestId: `${Date.now()}-${crypto.randomUUID()}` };
}
export const asrApi = {
  async status(signal?: AbortSignal): Promise<ASRStatus> {
    const scope = asrScope();
    const response = await apiClient.get<unknown>(`${base}/status`, scoped(scope, signal));
    if (!ownsASRScope(scope) || !validateASRStatus(response.data)) throw new ApiContractError('ASR status');
    return response.data;
  },
  async submit(operation: ASROperation, audio: ArrayBuffer, signal?: AbortSignal): Promise<ASRJob> {
    const config = operationConfig(operation, signal);
    const response = await apiClient.post<unknown>(path(operation), audio, {
      ...config, timeout: 15000, headers: { ...config.headers, 'Content-Type': 'audio/wav' },
    });
    return job(response.data, operation);
  },
  async get(operation: ASROperation, signal?: AbortSignal): Promise<ASRJob> {
    return job((await apiClient.get<unknown>(path(operation), operationConfig(operation, signal))).data, operation);
  },
  async cancel(operation: ASROperation): Promise<void> {
    if (!ownsASRScope(operation)) return;
    await apiClient.post<unknown>(`${path(operation)}/cancel`, undefined, operationConfig(operation));
  },
  async models(signal?: AbortSignal): Promise<ASRModel[]> {
    const scope = asrScope();
    const response = await apiClient.get<unknown>(`${base}/models`, scoped(scope, signal));
    if (!ownsASRScope(scope) || !validateASRModels(response.data)) throw new ApiContractError('ASR models');
    return response.data.models;
  },
  async modelAction(id: string, action: 'download' | 'cancel' | 'delete'): Promise<ASRModel> {
    const scope = asrScope();
    const url = `${base}/models/${encodeURIComponent(id)}`;
    const response = action === 'delete'
      ? await apiClient.delete<unknown>(url, scoped(scope))
      : await apiClient.post<unknown>(`${url}/download${action === 'cancel' ? '/cancel' : ''}`, undefined, scoped(scope));
    if (!ownsASRScope(scope) || !validateASRModel(response.data)) throw new ApiContractError('ASR model');
    return response.data;
  },
};

export function asrErrorCode(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'code' in error && typeof error.code === 'string') return error.code;
  return 'request_failed';
}

function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Cancelled', 'AbortError')); return; }
    const aborted = () => { window.clearTimeout(timer); reject(new DOMException('Cancelled', 'AbortError')); };
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', aborted); resolve(); }, 500);
    signal.addEventListener('abort', aborted, { once: true });
  });
}

/** Reconcile an uncertain upload with reads; never replay paid transcription. */
export async function transcribeRecording(operation: ASROperation, audio: ArrayBuffer, signal: AbortSignal): Promise<ASRJob> {
  let snapshot: ASRJob | null = null;
  try { snapshot = await asrApi.submit(operation, audio, signal); }
  catch (error) {
    if (signal.aborted || !ownsASRScope(operation)) throw error;
    if (typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number') throw error;
  }
  const deadline = Date.now() + 210000;
  while (!signal.aborted && ownsASRScope(operation)) {
    if (snapshot && !['queued', 'running'].includes(snapshot.state)) return snapshot;
    if (Date.now() > deadline) throw new Error('ASR reconciliation timed out');
    await pause(signal);
    snapshot = await asrApi.get(operation, signal);
  }
  throw new DOMException('ASR cancelled', 'AbortError');
}
