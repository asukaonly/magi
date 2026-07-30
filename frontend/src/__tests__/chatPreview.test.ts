import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configureApiClient } from '../api/client';
import { streamChatPreview, type PreviewTurn } from '../api/modules/chatPreview';

describe('chatPreview client', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    configureApiClient({
      baseUrl: 'http://127.0.0.1:43123/api',
      sessionToken: 'preview-session-token',
    });
  });

  afterEach(() => {
    configureApiClient({ sessionToken: undefined });
  });

  it('paces bubbles even when the desktop transport returns one buffered body', async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          segments: [
            { content: 'first reply', delay_ms: 0 },
            { content: 'second reply', delay_ms: 1200 },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const preview = streamChatPreview({
      seed_slug: 'nova',
      history: [],
      message: { role: 'user', content: 'hi' },
    });

    await expect(preview.next()).resolves.toEqual({ value: 'first reply', done: false });

    const second = preview.next();
    let secondResolved = false;
    void second.then(() => {
      secondResolved = true;
    });
    await vi.advanceTimersByTimeAsync(1199);
    expect(secondResolved).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(second).resolves.toEqual({ value: '‖second reply', done: false });
    await expect(preview.next()).resolves.toEqual({ value: undefined, done: true });
  });

  it('throws when the server returns non-200', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('unknown seed: ghost', { status: 400 }),
    );
    const gen = streamChatPreview({
      seed_slug: 'ghost',
      history: [],
      message: { role: 'user', content: 'hi' },
    });
    await expect(async () => {
      for await (const _ of gen) {
        /* drain */
      }
    }).rejects.toThrow(/unknown seed/);
  });

  it('serializes history in order', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ segments: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const history: PreviewTurn[] = [
      { role: 'user', content: 'msg1' },
      { role: 'assistant', content: 'reply1' },
    ];
    for await (const _ of streamChatPreview({
      seed_slug: 'nova',
      history,
      message: { role: 'user', content: 'msg2' },
    })) {
      /* drain */
    }
    expect(fetchSpy).toHaveBeenCalledOnce();
    const body = JSON.parse(fetchSpy.mock.calls[0][1]!.body as string);
    const headers = new Headers(fetchSpy.mock.calls[0][1]!.headers);
    expect(body.history).toEqual(history);
    expect(body.message.content).toBe('msg2');
    expect(headers.get('X-Magi-Session-Token')).toBe('preview-session-token');
  });
});
