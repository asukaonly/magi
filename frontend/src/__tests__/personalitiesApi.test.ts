import { beforeEach, describe, expect, it } from 'vitest';

import { personalitiesApi } from '@/api/modules/personalities';
import type { RuntimeConfig } from '@/runtime/config';

describe('personalitiesApi.getAvatarUrl', () => {
  beforeEach(() => {
    window.__MAGI_RUNTIME__ = {
      isDesktop: true,
      apiBaseUrl: 'http://127.0.0.1:8123/api',
      wsBaseUrl: 'ws://127.0.0.1:8123',
    } satisfies RuntimeConfig;
  });

  it('resolves backend static paths against the backend origin', () => {
    expect(personalitiesApi.getAvatarUrl('/static/avatars/system-melchior.jpg')).toBe(
      'http://127.0.0.1:8123/static/avatars/system-melchior.jpg'
    );
  });

  it('keeps absolute URLs unchanged', () => {
    expect(personalitiesApi.getAvatarUrl('https://example.com/avatar.png')).toBe(
      'https://example.com/avatar.png'
    );
  });
});
