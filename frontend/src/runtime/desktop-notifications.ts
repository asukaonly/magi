import { getCurrentWindow, UserAttentionType } from '@tauri-apps/api/window';
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from '@tauri-apps/plugin-notification';

type DesktopNotificationPreferences = {
  desktopNotificationsEnabled: boolean;
  desktopNotificationPreviewsEnabled: boolean;
};

export type UnreadChatNotificationRequest = DesktopNotificationPreferences & {
  sessionId: string;
  currentSessionId: string | null;
  title: string;
  body: string;
  dedupeId?: string | null;
};

type RealtimeLikeMessage = {
  event?: string;
  type?: string;
  data?: unknown;
};

const PREFERENCES_STORAGE_KEY = 'magi.desktopNotifications.preferences.v1';
const DEDUPE_STORAGE_KEY = 'magi.desktopNotifications.sent.v1';
const MAX_DEDUPE_IDS = 80;
let notificationContentGeneration = 0;

const DEFAULT_PREFERENCES: DesktopNotificationPreferences = {
  desktopNotificationsEnabled: false,
  desktopNotificationPreviewsEnabled: true,
};

const canUseLocalStorage = (): boolean => (
  typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
);

const normalizeString = (value: unknown): string => String(value || '').trim();

const readJsonObject = (key: string): Record<string, unknown> => {
  if (!canUseLocalStorage()) {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
};

export function syncDesktopNotificationPreferences(preferences: Partial<{
  desktop_notifications_enabled: boolean;
  desktop_notification_previews_enabled: boolean;
}> | null | undefined): void {
  if (!canUseLocalStorage()) {
    return;
  }
  const next: DesktopNotificationPreferences = {
    desktopNotificationsEnabled: Boolean(preferences?.desktop_notifications_enabled),
    desktopNotificationPreviewsEnabled: preferences?.desktop_notification_previews_enabled !== false,
  };
  try {
    window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Notification preferences are mirrored locally for realtime gating only.
  }
}

export function getDesktopNotificationPreferences(): DesktopNotificationPreferences {
  const raw = readJsonObject(PREFERENCES_STORAGE_KEY);
  return {
    desktopNotificationsEnabled: typeof raw.desktopNotificationsEnabled === 'boolean'
      ? raw.desktopNotificationsEnabled
      : DEFAULT_PREFERENCES.desktopNotificationsEnabled,
    desktopNotificationPreviewsEnabled: typeof raw.desktopNotificationPreviewsEnabled === 'boolean'
      ? raw.desktopNotificationPreviewsEnabled
      : DEFAULT_PREFERENCES.desktopNotificationPreviewsEnabled,
  };
}

const loadDedupeIds = (): string[] => {
  const raw = readJsonObject(DEDUPE_STORAGE_KEY);
  const ids = raw.ids;
  return Array.isArray(ids)
    ? ids.map((id) => normalizeString(id)).filter(Boolean)
    : [];
};

const hasNotificationBeenSent = (dedupeId: string | null | undefined): boolean => {
  const normalized = normalizeString(dedupeId);
  if (!normalized) {
    return false;
  }
  return loadDedupeIds().includes(normalized);
};

const rememberNotificationSent = (dedupeId: string | null | undefined): void => {
  const normalized = normalizeString(dedupeId);
  if (!normalized || !canUseLocalStorage()) {
    return;
  }
  const ids = loadDedupeIds().filter((id) => id !== normalized);
  ids.unshift(normalized);
  try {
    window.localStorage.setItem(
      DEDUPE_STORAGE_KEY,
      JSON.stringify({ ids: ids.slice(0, MAX_DEDUPE_IDS) }),
    );
  } catch {
    // Best-effort duplicate suppression.
  }
};

export function clearDesktopNotificationContentState(): boolean {
  notificationContentGeneration += 1;
  if (!canUseLocalStorage()) {
    return typeof window === 'undefined';
  }
  try {
    window.localStorage.removeItem(DEDUPE_STORAGE_KEY);
    return window.localStorage.getItem(DEDUPE_STORAGE_KEY) === null;
  } catch {
    return false;
  }
}

const ensureNotificationPermission = async (): Promise<boolean> => {
  try {
    if (await isPermissionGranted()) {
      return true;
    }
    return await requestPermission() === 'granted';
  } catch {
    return false;
  }
};

export async function requestDesktopNotificationPermission(): Promise<boolean> {
  return ensureNotificationPermission();
}

const notificationBody = (body: string, previewsEnabled: boolean): string => {
  if (!previewsEnabled) {
    return 'Magi 有一条新消息';
  }
  const normalized = normalizeString(body).replace(/\s+/g, ' ');
  if (!normalized) {
    return 'Magi 有一条新消息';
  }
  return normalized.length > 160 ? `${normalized.slice(0, 157)}...` : normalized;
};

export async function notifyForUnreadChatMessage(request: UnreadChatNotificationRequest): Promise<boolean> {
  const sessionId = normalizeString(request.sessionId);
  if (
    !request.desktopNotificationsEnabled
    || !sessionId
    || sessionId === normalizeString(request.currentSessionId)
    || hasNotificationBeenSent(request.dedupeId)
  ) {
    return false;
  }
  const contentGeneration = notificationContentGeneration;
  if (!await ensureNotificationPermission()) {
    return false;
  }
  if (contentGeneration !== notificationContentGeneration) {
    return false;
  }

  try {
    sendNotification({
      title: normalizeString(request.title) || 'Magi',
      body: notificationBody(request.body, request.desktopNotificationPreviewsEnabled),
    });
    rememberNotificationSent(request.dedupeId);
    try {
      await getCurrentWindow().requestUserAttention(UserAttentionType.Informational);
    } catch {
      // Attention hints are platform dependent.
    }
    return true;
  } catch {
    return false;
  }
}

export async function syncUnreadBadgeCount(count: number): Promise<void> {
  const normalizedCount = Number.isFinite(count) && count > 0 ? Math.trunc(count) : undefined;
  try {
    await getCurrentWindow().setBadgeCount(normalizedCount);
  } catch {
    // Unsupported on Windows; macOS handles the dock badge here.
  }
}

export function buildUnreadChatNotificationRequest(
  message: RealtimeLikeMessage,
  currentSessionId: string | null,
): Omit<UnreadChatNotificationRequest, keyof DesktopNotificationPreferences> | null {
  const eventName = normalizeString(message.event || message.type);
  const data = message.data && typeof message.data === 'object'
    ? message.data as Record<string, unknown>
    : null;
  if (!data) {
    return null;
  }

  if (eventName === 'agent_response') {
    const sessionId = normalizeString(data.session_id);
    if (!sessionId || sessionId === normalizeString(currentSessionId)) {
      return null;
    }
    return {
      sessionId,
      currentSessionId,
      title: 'Magi',
      body: normalizeString(data.content),
      dedupeId: normalizeString(data.message_id) || normalizeString(data.turn_id) || null,
    };
  }

  if (eventName !== 'chat_message_upserted') {
    return null;
  }

  const sessionId = normalizeString(data.session_id);
  if (!sessionId || sessionId === normalizeString(currentSessionId)) {
    return null;
  }
  const rawMessage = data.message && typeof data.message === 'object'
    ? data.message as Record<string, unknown>
    : null;
  if (!rawMessage) {
    return null;
  }
  if (normalizeString(rawMessage.role) === 'user' || normalizeString(rawMessage.kind) === 'status') {
    return null;
  }
  const rawSummary = data.session_summary && typeof data.session_summary === 'object'
    ? data.session_summary as Record<string, unknown>
    : null;
  return {
    sessionId,
    currentSessionId,
    title: normalizeString(rawSummary?.title) || 'Magi',
    body: normalizeString(rawMessage.content),
    dedupeId: normalizeString(rawMessage.message_id) || null,
  };
}
