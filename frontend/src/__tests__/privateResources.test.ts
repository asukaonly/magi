import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const clientMocks = vi.hoisted(() => ({
  post: vi.fn(),
  resolveApiBaseUrl: vi.fn(() => 'http://127.0.0.1:43123/api'),
}));

vi.mock('@/api/client', () => ({
  api: {
    post: clientMocks.post,
  },
  resolveApiBaseUrl: clientMocks.resolveApiBaseUrl,
}));

import {
  clearPrivateResourceAccessCache,
  getCachedPrivateResourceUrl,
  parsePrivateResourceSource,
  resolvePrivateResourceUrl,
  type PrivateResourceDescriptor,
} from '@/api/modules/privateResources';
import { dispatchAppEvent } from '@/constants/events';

const CHAT_DESCRIPTOR: PrivateResourceDescriptor = {
  kind: 'chat_attachment',
  user_id: 'local_user',
  session_id: 'session-1',
  attachment_id: 'attachment-1',
};
const CHAT_ACCESS_PATH =
  '/api/messages/session/session-1/attachments/attachment-1/content?user_id=local_user';
const TIMELINE_ACCESS_PATH =
  '/api/timeline/asset/photo-library%3A%2F%2Fday%2Fphoto.jpg';

describe('privateResources', () => {
  beforeEach(() => {
    vi.useRealTimers();
    clientMocks.post.mockReset();
    clientMocks.resolveApiBaseUrl.mockReturnValue('http://127.0.0.1:43123/api');
    clearPrivateResourceAccessCache();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearPrivateResourceAccessCache();
  });

  it('parses private gateway URLs and preserves the chat user identity', () => {
    expect(parsePrivateResourceSource(
      'http://127.0.0.1:43123/api/messages/session/session-1/attachments/attachment-1/content?user_id=local_user',
    )).toEqual(CHAT_DESCRIPTOR);
    expect(parsePrivateResourceSource(
      'http://127.0.0.1:43123/api/messages/session/session-1/attachments/attachment-1/content',
    )).toBeNull();
    expect(parsePrivateResourceSource(
      'http://127.0.0.1:43123/api/timeline/asset/photo-library%3A%2F%2Fday%2Fphoto.jpg',
    )).toEqual({
      kind: 'timeline_asset',
      asset_ref: 'photo-library://day/photo.jpg',
    });
    expect(parsePrivateResourceSource(
      'http://127.0.0.1:43123/static/user-avatars/custom.png',
    )).toEqual({
      kind: 'user_avatar',
      filename: 'custom.png',
    });
  });

  it('ignores external, built-in, data, and blob image sources', () => {
    expect(parsePrivateResourceSource('https://images.example/avatar.png')).toBeNull();
    expect(parsePrivateResourceSource(
      'http://127.0.0.1:43123/static/avatars/builtin.png',
    )).toBeNull();
    expect(parsePrivateResourceSource('data:image/png;base64,AAAA')).toBeNull();
    expect(parsePrivateResourceSource('blob:http://localhost/local-preview')).toBeNull();
  });

  it('returns an absolute gateway URL for a relative access grant', async () => {
    clientMocks.post.mockResolvedValue({
      data: {
        access_url: `${CHAT_ACCESS_PATH}&resource_ticket=grant-1`,
        expires_at_ms: Date.now() + 60_000,
      },
    });

    await expect(resolvePrivateResourceUrl(CHAT_DESCRIPTOR)).resolves.toBe(
      `http://127.0.0.1:43123${CHAT_ACCESS_PATH}&resource_ticket=grant-1`,
    );
    expect(clientMocks.post).toHaveBeenCalledWith(
      '/private-resource-tickets',
      CHAT_DESCRIPTOR,
    );
  });

  it.each([
    ['absolute', 'https://evil.example/private/photo'],
    ['protocol-relative', '//evil.example/private/photo'],
    ['wrong-resource', '/api/timeline/asset/other?resource_ticket=grant-1'],
    ['missing-ticket', CHAT_ACCESS_PATH],
    ['unexpected-query', `${CHAT_ACCESS_PATH}&resource_ticket=grant-1&extra=value`],
  ])('rejects a malicious %s access grant', async (_kind, accessUrl) => {
    clientMocks.post.mockResolvedValue({
      data: {
        access_url: accessUrl,
        expires_at_ms: Date.now() + 60_000,
      },
    });

    await expect(resolvePrivateResourceUrl(CHAT_DESCRIPTOR)).rejects.toThrow(
      'Private resource access response is invalid',
    );
  });

  it('rejects an access grant that is already expired', async () => {
    clientMocks.post.mockResolvedValue({
      data: {
        access_url: `${CHAT_ACCESS_PATH}&resource_ticket=expired`,
        expires_at_ms: Date.now(),
      },
    });

    await expect(resolvePrivateResourceUrl(CHAT_DESCRIPTOR)).rejects.toThrow(
      'Private resource access response is invalid',
    );
  });

  it('deduplicates concurrent ticket requests for the same resource', async () => {
    let completeRequest!: (value: {
      data: { access_url: string; expires_at_ms: number };
    }) => void;
    clientMocks.post.mockReturnValue(new Promise((resolve) => {
      completeRequest = resolve;
    }));

    const first = resolvePrivateResourceUrl(CHAT_DESCRIPTOR);
    const second = resolvePrivateResourceUrl(CHAT_DESCRIPTOR);

    expect(clientMocks.post).toHaveBeenCalledTimes(1);
    completeRequest({
      data: {
        access_url: `${CHAT_ACCESS_PATH}&resource_ticket=shared`,
        expires_at_ms: Date.now() + 60_000,
      },
    });

    await expect(Promise.all([first, second])).resolves.toEqual([
      `http://127.0.0.1:43123${CHAT_ACCESS_PATH}&resource_ticket=shared`,
      `http://127.0.0.1:43123${CHAT_ACCESS_PATH}&resource_ticket=shared`,
    ]);
  });

  it('retires an unfinished grant request when content is cleared', async () => {
    let completeRequest!: (value: {
      data: { access_url: string; expires_at_ms: number };
    }) => void;
    clientMocks.post.mockReturnValue(new Promise((resolve) => {
      completeRequest = resolve;
    }));

    const pending = resolvePrivateResourceUrl(CHAT_DESCRIPTOR);
    expect(clearPrivateResourceAccessCache()).toBe(true);
    completeRequest({
      data: {
        access_url: `${CHAT_ACCESS_PATH}&resource_ticket=retired`,
        expires_at_ms: Date.now() + 60_000,
      },
    });

    await expect(pending).rejects.toThrow('retired');
    expect(getCachedPrivateResourceUrl(CHAT_DESCRIPTOR)).toBeNull();
  });

  it('retires an unfinished grant request as soon as a full clear starts', async () => {
    let completeRequest!: (value: {
      data: { access_url: string; expires_at_ms: number };
    }) => void;
    clientMocks.post.mockReturnValue(new Promise((resolve) => {
      completeRequest = resolve;
    }));

    const pending = resolvePrivateResourceUrl(CHAT_DESCRIPTOR);
    dispatchAppEvent.memoryClearStarted();
    completeRequest({
      data: {
        access_url: `${CHAT_ACCESS_PATH}&resource_ticket=retired-at-start`,
        expires_at_ms: Date.now() + 60_000,
      },
    });

    await expect(pending).rejects.toThrow('retired');
    expect(getCachedPrivateResourceUrl(CHAT_DESCRIPTOR)).toBeNull();
  });

  it('requests a new grant when the cached one is close to expiry', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-30T08:00:00.000Z'));
    clientMocks.post
      .mockResolvedValueOnce({
        data: {
          access_url: `${TIMELINE_ACCESS_PATH}?resource_ticket=old`,
          expires_at_ms: Date.now() + 10_000,
        },
      })
      .mockResolvedValueOnce({
        data: {
          access_url: `${TIMELINE_ACCESS_PATH}?resource_ticket=fresh`,
          expires_at_ms: Date.now() + 60_000,
        },
      });
    const descriptor: PrivateResourceDescriptor = {
      kind: 'timeline_asset',
      asset_ref: 'photo-library://day/photo.jpg',
    };

    await expect(resolvePrivateResourceUrl(descriptor)).resolves.toContain(
      'resource_ticket=old',
    );
    vi.advanceTimersByTime(6_000);
    await expect(resolvePrivateResourceUrl(descriptor)).resolves.toContain(
      'resource_ticket=fresh',
    );
    expect(clientMocks.post).toHaveBeenCalledTimes(2);
  });
});
