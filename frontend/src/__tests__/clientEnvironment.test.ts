import { afterEach, describe, expect, it, vi } from 'vitest';

import { captureClientEnvironment } from '@/api/client-environment';
import { api } from '@/api/client';
import { messagesApi } from '@/api/modules/messages';

describe('turn client environment', () => {
  afterEach(() => vi.restoreAllMocks());

  it.each([
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'windows'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 'macos'],
    ['Mozilla/5.0 (X11; Linux x86_64)', 'linux'],
    ['Mozilla/5.0 (Linux; Android 14)', 'android'],
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 'ios'],
    ['', 'unknown'],
  ])('reduces %s to an advisory OS family', (agent, os) => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(agent);
    const snapshot = captureClientEnvironment();
    expect(snapshot.os).toBe(os);
    expect(Object.keys(snapshot).sort()).toEqual(['os', 'timezone']);
  });

  it('captures the client timezone without interpreting it as a location', () => {
    const options = Intl.DateTimeFormat().resolvedOptions();
    vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
      ...options, timeZone: 'Pacific/Honolulu',
    });
    expect(captureClientEnvironment().timezone).toBe('Pacific/Honolulu');
  });

  it('keeps message sending available when timezone detection fails', () => {
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => { throw new Error('Unavailable'); });
    expect(captureClientEnvironment().timezone).toBeNull();
  });

  it('attaches context at the transport boundary without mutating the retryable message', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'queued' });
    const request = { message: 'Hello', session_id: 's1', client_turn_id: 'turn-1' };
    await messagesApi.sendMessage(request);
    expect(post).toHaveBeenCalledWith('/messages/send', {
      ...request, client_environment: captureClientEnvironment(),
    });
    expect(request).not.toHaveProperty('client_environment');
  });
});
