/**
 * System suggestions API client.
 *
 * Wraps `POST /system-suggestions/check` and `POST /system-suggestions/dismiss`,
 * which surface the backend's view of which plugins the user might want to
 * enable based on recent message text (and which suggestions they've dismissed).
 */
import { api, unwrapGatewayPayload } from '../client';

/**
 * How long a dismissed suggestion stays suppressed.
 *
 * - `transient`: a short cooldown (minutes/hours) before re-surfacing.
 * - `explicit`: a long cooldown (days) — user actively said "not now".
 * - `never`: permanent — user said "stop suggesting this".
 */
export type DismissalKind = 'transient' | 'explicit' | 'never';

export interface SuggestionProposal {
  dedupe_key: string;
  category: string;
  plugin_ids: string[];
  confidence: number;
  rationale: { zh: string; en: string };
}

interface CheckResponse {
  suggestions: SuggestionProposal[];
}

interface DismissResponse {
  dedupe_key: string;
  dismissed: boolean;
}

/**
 * Ask the backend which (if any) system suggestions are appropriate for the
 * given user text. The backend deduplicates against the dismissal repository,
 * so the returned list already excludes anything the user has snoozed.
 */
export async function checkSystemSuggestions(args: {
  text: string;
  locale: 'zh' | 'en';
}): Promise<SuggestionProposal[]> {
  const response = await api.post<CheckResponse>(
    '/system-suggestions/check',
    args,
  );
  return unwrapGatewayPayload(response).suggestions;
}

/**
 * Record that the user dismissed a suggestion. The `kind` controls how long
 * the dismissal lasts (see {@link DismissalKind}).
 */
export async function dismissSystemSuggestion(args: {
  dedupe_key: string;
  kind: DismissalKind;
}): Promise<DismissResponse> {
  const response = await api.post<DismissResponse>(
    '/system-suggestions/dismiss',
    args,
  );
  return unwrapGatewayPayload(response);
}
