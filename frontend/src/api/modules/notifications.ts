/**
 * Notification center API client.
 *
 * Wraps the durable notification endpoints:
 * - `GET /notifications` — list the user's notifications + unread count.
 * - `POST /notifications/mark-read` — mark specific ids (or `{ all: true }`) read.
 * - `POST /notifications/{id}/dismiss` — dismiss a single notification.
 * - `POST /notifications/{id}/action` — record that the user acted on it.
 *
 * Mirrors {@link ../modules/systemSuggestions} — `api.*` + `unwrapGatewayPayload`,
 * with hand-written local TS interfaces (not the generated API types).
 */
import { api, unwrapGatewayPayload } from '../client';
import type { SuggestionPlugin } from './systemSuggestions';

export type NotificationKind = 'suggestion';
export type NotificationStatus = 'unread' | 'read' | 'actioned' | 'dismissed';

export interface NotificationItem {
  id: number;
  kind: NotificationKind;
  dedupe_key: string;
  title: string;
  body: string;
  payload: {
    category?: string;
    plugins?: SuggestionPlugin[];
    conflict_type?: 'profile_conflict';
    shadow_id?: string;
    authoritative_id?: string;
    authoritative_value?: string;
    inferred_value?: string;
    trait_name?: string;
    entity_id?: string;
  };
  status: NotificationStatus;
  created_at_ms: number;
  read_at_ms: number | null;
}

export async function listNotifications(): Promise<{ items: NotificationItem[]; unread_count: number }> {
  const r = await api.get<{ items: NotificationItem[]; unread_count: number }>('/notifications');
  return unwrapGatewayPayload(r);
}
export async function markRead(ids: number[]): Promise<void> {
  await api.post('/notifications/mark-read', { ids });
}
export async function markAllRead(): Promise<void> {
  await api.post('/notifications/mark-read', { all: true });
}
export async function dismissNotification(id: number): Promise<void> {
  await api.post(`/notifications/${id}/dismiss`, {});
}
export async function dismissAllNotifications(): Promise<void> {
  await api.post('/notifications/dismiss-all', {});
}
export async function actionNotification(id: number): Promise<void> {
  await api.post(`/notifications/${id}/action`, {});
}
export async function resolveConflict(id: number, action: 'confirm' | 'reject'): Promise<void> {
  await api.post(`/notifications/${id}/resolve-conflict`, { action });
}
