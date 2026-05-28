import { describe, expect, it, vi, beforeEach } from 'vitest';
import { streamChatPreview, type PreviewTurn } from '../api/modules/chatPreview';

describe('chatPreview client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('streams chunks from the response body', async () => {
    const chunks = ['hello', ' ', 'world'];
    const encoder = new TextEncoder();
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(responseBody, { status: 200, headers: { 'Content-Type': 'text/plain' } }),
    );

    const received: string[] = [];
    for await (const chunk of streamChatPreview({
      seed_slug: 'nova',
      history: [],
      message: { role: 'user', content: 'hi' },
    })) {
      received.push(chunk);
    }
    expect(received.join('')).toBe('hello world');
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
      new Response('ok', { status: 200 }),
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
    expect(body.history).toEqual(history);
    expect(body.message.content).toBe('msg2');
  });
});
