import { describe, expect, it } from 'vitest';

import { buildWsBaseUrl, normalizeApiBaseUrl, normalizeConnectableUrl } from '@/runtime/config';

describe('runtime config URL normalization', () => {
  it('replaces restricted bind hosts with a connectable host for API URLs', () => {
    expect(normalizeApiBaseUrl('http://0.0.0.0:8000/api', '127.0.0.1')).toBe('http://127.0.0.1:8000/api');
  });

  it('preserves explicit connectable hosts', () => {
    expect(normalizeConnectableUrl('http://localhost:8000/api', '127.0.0.1')).toBe('http://localhost:8000/api');
  });

  it('derives websocket URLs from the sanitized API origin', () => {
    expect(buildWsBaseUrl(normalizeApiBaseUrl('http://0.0.0.0:8000/api', 'localhost'))).toBe('ws://localhost:8000');
  });
});