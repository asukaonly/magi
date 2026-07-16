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
import type { PersonalityConfig } from './personas';

export interface PreviewTurn {
  role: 'user' | 'assistant';
  content: string;
}

/** Complete inline persona config for an unsaved onboarding draft. */
export type PreviewPersonaOverride = PersonalityConfig;

export interface ChatPreviewRequest {
  /** A known persona seed. Omit when sending `persona_override` instead. */
  seed_slug?: string;
  /**
   * Seed locale folder ("zh" / "en") — selects which bundled preset the
   * `seed_slug` resolves against (must match the locale the previews were
   * loaded with). Ignored when `persona_override` is set.
   */
  locale?: string;
  history: PreviewTurn[];
  message: PreviewTurn;
  /**
   * Optional unsaved LLM configuration. During onboarding the user has not yet
   * persisted their provider/model selections, so we pass the in-progress
   * config here and the backend resolves a throwaway core adapter from it
   * (falling back to the persisted config when omitted).
   */
  llm_override?: LLMConfig;
  /**
   * Optional complete inline persona config. Used to preview an onboarding-generated
   * (unsaved) persona; exactly one of `seed_slug` / `persona_override` must be
   * provided.
   */
  persona_override?: PreviewPersonaOverride;
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
