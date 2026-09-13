import { z } from 'zod';
import { api } from './client';
import { getRuntimeConfig, getRuntimeGeneration } from '@/runtime/config';

const receiptSchema = z.object({
  operation_id: z.string(), state: z.enum(['running', 'completed', 'uncertain']),
  http_status: z.number().int().min(200).max(599).nullable(), result: z.unknown(),
}).strict().refine((receipt) => receipt.state === 'completed' ? receipt.http_status !== null : receipt.http_status === null);
const identitySchema = z.string().regex(/^\d{13}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);

export class PluginRequestRejectedError extends Error {
  constructor() {
    super('Plugin request was rejected');
    this.name = 'PluginRequestRejectedError';
  }
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
  }
  return value;
}

/** Retain only request identity, never credentials or a queued write, on this device. */
export async function confirmedPluginPost<T>(path: string, body: unknown, parseResult: (value: unknown) => T): Promise<T> {
  const scope = getRuntimeConfig();
  const generation = getRuntimeGeneration();
  if (!scope.serverId || !scope.profileId || !scope.dataEpoch) throw new Error('Center connection is not ready');
  const current = () => {
    if (getRuntimeGeneration() !== generation || getRuntimeConfig().dataEpoch !== scope.dataEpoch) {
      throw new Error('Center connection changed');
    }
  };
  const encoded = new TextEncoder().encode(JSON.stringify([scope.serverId, scope.profileId, scope.dataEpoch, path, canonical(body)]));
  const digest = await crypto.subtle.digest('SHA-256', encoded);
  current();
  const key = `magi.plugin-request.${Array.from(new Uint8Array(digest), (v) => v.toString(16).padStart(2, '0')).join('')}`;
  const retained = localStorage.getItem(key);
  const operationId = retained === null ? `${Date.now()}-${crypto.randomUUID()}` : identitySchema.parse(retained);
  // Persist before sending. Storage failure must not leave an untraceable mutation.
  localStorage.setItem(key, operationId);
  const config = { headers: { 'X-Magi-Request-Id': operationId, 'X-Magi-Data-Epoch': scope.dataEpoch } };
  const read = async () => receiptSchema.parse(await api.get<unknown>(`/plugins/requests/${operationId}`, config));
  const accept = (value: unknown): { done: boolean; value: unknown } => {
    const receipt = receiptSchema.safeParse(value);
    if (!receipt.success) return { done: true, value };
    if (receipt.data.operation_id !== operationId) throw new Error('Plugin response belongs to another request');
    if (receipt.data.state === 'uncertain') throw new Error('Plugin request outcome is uncertain; confirm its effects before starting again');
    if (receipt.data.state !== 'completed') return { done: false, value: undefined };
    if (receipt.data.http_status === null || receipt.data.http_status >= 400) {
      localStorage.removeItem(key);
      throw new PluginRequestRejectedError();
    }
    return { done: true, value: receipt.data.result };
  };
  let attempted = false;
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    current();
    let value: unknown;
    if (!attempted && retained === null) {
      attempted = true;
      try { value = await api.post<unknown>(path, body, config); }
      catch { current(); value = await read(); }
    } else {
      try { value = await read(); }
      catch (error) {
        current();
        // The same identity is safe to resubmit only after an explicit not-admitted response.
        if (!attempted && z.object({ status: z.literal(404) }).safeParse(error).success) {
          attempted = true;
          value = await api.post<unknown>(path, body, config);
        } else { throw error; }
      }
    }
    current();
    const result = accept(value);
    if (result.done) {
      const parsed = parseResult(result.value);
      localStorage.removeItem(key);
      return parsed;
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error('Plugin request is still running; confirm the same request later');
}
