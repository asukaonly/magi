import { beforeEach, describe, expect, it, vi } from 'vitest';
import { dispatchAppEvent } from '@/constants/events';

const {
  isPermissionGrantedMock,
  requestPermissionMock,
  sendNotificationMock,
  requestUserAttentionMock,
  setBadgeCountMock,
} = vi.hoisted(() => ({
  isPermissionGrantedMock: vi.fn(),
  requestPermissionMock: vi.fn(),
  sendNotificationMock: vi.fn(),
  requestUserAttentionMock: vi.fn(),
  setBadgeCountMock: vi.fn(),
}));

vi.mock('@tauri-apps/plugin-notification', () => ({
  isPermissionGranted: isPermissionGrantedMock,
  requestPermission: requestPermissionMock,
  sendNotification: sendNotificationMock,
}));

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({
    requestUserAttention: requestUserAttentionMock,
    setBadgeCount: setBadgeCountMock,
  }),
  UserAttentionType: {
    Informational: 2,
  },
}));

describe('desktop chat notifications', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    isPermissionGrantedMock.mockResolvedValue(true);
    requestPermissionMock.mockResolvedValue('granted');
  });

  it('does not notify when desktop notifications are disabled', async () => {
    const { notifyForUnreadChatMessage } = await import('@/runtime/desktop-notifications');

    const sent = await notifyForUnreadChatMessage({
      sessionId: 'session-b',
      currentSessionId: 'session-a',
      title: 'Session B',
      body: 'done',
      desktopNotificationsEnabled: false,
      desktopNotificationPreviewsEnabled: true,
    });

    expect(sent).toBe(false);
    expect(sendNotificationMock).not.toHaveBeenCalled();
  });

  it('does not notify for the active chat session', async () => {
    const { notifyForUnreadChatMessage } = await import('@/runtime/desktop-notifications');

    const sent = await notifyForUnreadChatMessage({
      sessionId: 'session-a',
      currentSessionId: 'session-a',
      title: 'Session A',
      body: 'visible',
      desktopNotificationsEnabled: true,
      desktopNotificationPreviewsEnabled: true,
    });

    expect(sent).toBe(false);
    expect(sendNotificationMock).not.toHaveBeenCalled();
  });

  it('requests notification permission before the first notification is needed', async () => {
    isPermissionGrantedMock.mockResolvedValueOnce(false);
    const { requestDesktopNotificationPermission } = await import('@/runtime/desktop-notifications');

    const granted = await requestDesktopNotificationPermission();

    expect(granted).toBe(true);
    expect(requestPermissionMock).toHaveBeenCalledTimes(1);
  });

  it('sends a notification for unread content in another chat session', async () => {
    const { notifyForUnreadChatMessage } = await import('@/runtime/desktop-notifications');

    const sent = await notifyForUnreadChatMessage({
      sessionId: 'session-b',
      currentSessionId: 'session-a',
      title: 'Session B',
      body: 'the report is ready',
      desktopNotificationsEnabled: true,
      desktopNotificationPreviewsEnabled: true,
    });

    expect(sent).toBe(true);
    expect(sendNotificationMock).toHaveBeenCalledWith({
      title: 'Session B',
      body: 'the report is ready',
    });
    expect(requestUserAttentionMock).toHaveBeenCalledWith(2);
  });

  it('hides message body when notification previews are disabled', async () => {
    const { notifyForUnreadChatMessage } = await import('@/runtime/desktop-notifications');

    await notifyForUnreadChatMessage({
      sessionId: 'session-b',
      currentSessionId: 'session-a',
      title: 'Session B',
      body: 'secret details',
      desktopNotificationsEnabled: true,
      desktopNotificationPreviewsEnabled: false,
    });

    expect(sendNotificationMock).toHaveBeenCalledWith({
      title: 'Session B',
      body: 'Magi 有一条新消息',
    });
  });

  it('syncs app badge count and clears it at zero', async () => {
    const { syncUnreadBadgeCount } = await import('@/runtime/desktop-notifications');

    await syncUnreadBadgeCount(5);
    await syncUnreadBadgeCount(0);

    expect(setBadgeCountMock).toHaveBeenNthCalledWith(1, 5);
    expect(setBadgeCountMock).toHaveBeenNthCalledWith(2, undefined);
  });

  it('clears notification content dedupe while preserving preferences', async () => {
    const {
      clearDesktopNotificationContentState,
      notifyForUnreadChatMessage,
      syncDesktopNotificationPreferences,
    } = await import('@/runtime/desktop-notifications');
    syncDesktopNotificationPreferences({
      desktop_notifications_enabled: true,
      desktop_notification_previews_enabled: false,
    });
    await notifyForUnreadChatMessage({
      sessionId: 'session-b',
      currentSessionId: 'session-a',
      title: 'Session B',
      body: 'private body',
      dedupeId: 'private-message-id',
      desktopNotificationsEnabled: true,
      desktopNotificationPreviewsEnabled: false,
    });

    expect(clearDesktopNotificationContentState()).toBe(true);

    expect(window.localStorage.getItem('magi.desktopNotifications.sent.v1')).toBeNull();
    expect(window.localStorage.getItem('magi.desktopNotifications.preferences.v1')).not.toBeNull();
  });

  it('drops a notification that finishes permission checks after a full clear', async () => {
    let resolvePermission: ((value: string) => void) | undefined;
    isPermissionGrantedMock.mockResolvedValueOnce(false);
    requestPermissionMock.mockImplementationOnce(() => new Promise((resolve) => {
      resolvePermission = resolve;
    }));
    const {
      clearDesktopNotificationContentState,
      notifyForUnreadChatMessage,
    } = await import('@/runtime/desktop-notifications');

    const pending = notifyForUnreadChatMessage({
      sessionId: 'session-before-clear',
      currentSessionId: 'session-a',
      title: 'Old session',
      body: 'old private body',
      dedupeId: 'old-private-message-id',
      desktopNotificationsEnabled: true,
      desktopNotificationPreviewsEnabled: true,
    });
    await vi.waitFor(() => {
      expect(requestPermissionMock).toHaveBeenCalledTimes(1);
    });

    dispatchAppEvent.memoryClearStarted();
    expect(clearDesktopNotificationContentState()).toBe(true);
    resolvePermission?.('granted');

    await expect(pending).resolves.toBe(false);
    expect(sendNotificationMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('magi.desktopNotifications.sent.v1')).toBeNull();
  });
});
