/**
 * Timed preview client for POST /api/chat/preview.
 *
 * The desktop gateway buffers proxied HTTP responses, so the server returns
 * validated bubbles together with their intended reveal delays. This client
 * applies those delays locally and yields bubbles one at a time.
 */

import { authenticatedFetch, resolveApiBaseUrl } from '../client';
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

interface PreviewDeliverySegment {
  content: string;
  delay_ms: number;
}

interface ChatPreviewResponse {
  segments: PreviewDeliverySegment[];
}

function waitForPreviewDelay(delayMs: number): Promise<void> {
  if (delayMs <= 0) return Promise.resolve();
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
}

export async function* streamChatPreview(
  request: ChatPreviewRequest,
  init?: { signal?: AbortSignal },
): AsyncGenerator<string, void, unknown> {
  const baseUrl = resolveApiBaseUrl();
  const response = await authenticatedFetch(`${baseUrl}/chat/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: init?.signal,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`chat preview failed (${response.status}): ${detail}`);
  }

  const payload = (await response.json()) as ChatPreviewResponse;
  if (!Array.isArray(payload.segments)) {
    throw new Error('chat preview response had no segments');
  }

  for (const [index, segment] of payload.segments.entries()) {
    await waitForPreviewDelay(segment.delay_ms);
    const prefix = index === 0 ? '' : '‖';
    yield `${prefix}${segment.content}`;
  }
}
