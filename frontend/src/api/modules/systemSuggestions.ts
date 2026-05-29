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
 * An active dismissal record, as returned by
 * `GET /system-suggestions/dismissals`. Only currently-active dismissals are
 * listed; expired transient/explicit cooldowns are omitted by the backend.
 */
export interface DismissalItem {
  dedupe_key: string;
  dismissed_at: string;
  kind: DismissalKind;
}

/**
 * Ask the backend which (if any) system suggestions are appropriate for the
 * given user text. The backend deduplicates against the dismissal repository,
 * so the returned list already excludes anything the user has snoozed.
 */
export async function checkSystemSuggestions(args: {
  text: string;
  locale: 'zh' | 'en';
  sessionId?: string;
}): Promise<SuggestionProposal[]> {
  const response = await api.post<CheckResponse>('/system-suggestions/check', {
    text: args.text,
    locale: args.locale,
    session_id: args.sessionId ?? 'default',
  });
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

/**
 * List the user's currently-active suggestion dismissals. Powers the Settings
 * "dismissed suggestions" section and the sidebar badge count.
 */
export async function listDismissals(): Promise<DismissalItem[]> {
  const response = await api.get<{ dismissals: DismissalItem[] }>(
    '/system-suggestions/dismissals',
  );
  return unwrapGatewayPayload(response).dismissals;
}

/**
 * Clear a single dismissal so its suggestion can surface again.
 */
export async function clearDismissal(dedupeKey: string): Promise<void> {
  await api.delete(
    `/system-suggestions/dismissals/${encodeURIComponent(dedupeKey)}`,
  );
}
