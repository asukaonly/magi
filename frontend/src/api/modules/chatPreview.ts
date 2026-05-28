/**
 * Streaming client for POST /api/chat/preview.
 *
 * Yields text chunks as they arrive over the response body. Throws if the
 * server returns a non-2xx status. Uses `fetch` directly (instead of the
 * axios-based {@link apiClient}) because axios does not expose streamed
 * response bodies in browser environments.
 */

import { resolveApiBaseUrl } from '../client';

export interface PreviewTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatPreviewRequest {
  seed_slug: string;
  history: PreviewTurn[];
  message: PreviewTurn;
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
