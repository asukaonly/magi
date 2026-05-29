/**
 * Streaming client for POST /api/chat/preview.
 *
 * Yields text chunks as they arrive over the response body. Throws if the
 * server returns a non-2xx status. Uses `fetch` directly (instead of the
 * axios-based {@link apiClient}) because axios does not expose streamed
 * response bodies in browser environments.
 */

import { resolveApiBaseUrl } from '../client';
import type { LLMConfig } from './config';

export interface PreviewTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatPreviewRequest {
  seed_slug: string;
  history: PreviewTurn[];
  message: PreviewTurn;
  /**
   * Optional unsaved LLM configuration. During onboarding the user has not yet
   * persisted their provider/model selections, so we pass the in-progress
   * config here and the backend resolves a throwaway core adapter from it
   * (falling back to the persisted config when omitted).
   */
  llm_override?: LLMConfig;
}

export async function* streamChatPreview(
  request: ChatPreviewRequest,
  init?: { signal?: AbortSignal },
): AsyncGenerator<string, void, unknown> {
  const baseUrl = resolveApiBaseUrl();
  const response = await fetch(`${baseUrl}/chat/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: init?.signal,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`chat preview failed (${response.status}): ${detail}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('chat preview response had no body');
  }
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (value && value.byteLength > 0) {
      yield decoder.decode(value, { stream: true });
    }
  }
  // Flush any trailing bytes from the decoder.
  const tail = decoder.decode();
  if (tail) yield tail;
}
