import { afterEach, describe, expect, it, vi } from 'vitest';
const { fetchMock, centerId } = vi.hoisted(() => ({ fetchMock: vi.fn(), centerId: 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0' }));
vi.mock('@/api/client', () => ({ authenticatedFetch: fetchMock, resolveApiBaseUrl: () => 'https://center.example/api' }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => ({ serverId: centerId }) }));
import { SseClient, SseFrames } from '@/realtime/sse-client';
const epoch = 'a0c4c092-b043-4767-a2a7-041ad6194b8c';
const event = (sequence: number, extra = {}) => ({ server_id: centerId, epoch, sequence, event_id: `${epoch}:${sequence}`, event_type: 'state.changed', data: { resource: 'tasks' }, ...extra });
function stream() {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  return { response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }), send: (payload: unknown) => controller.enqueue(new TextEncoder().encode(`event: magi\ndata: ${JSON.stringify(payload)}\n\n`)) };
}
const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });
describe('authenticated center events', () => {
  it('parses fragmented frames and bounds incomplete input', () => {
    const frames = new SseFrames(); expect(frames.push('data: {')).toEqual([]);
    expect(frames.push('}\r\n\r\n: heartbeat\n\n')).toEqual(['data: {}', ': heartbeat']);
    expect(() => frames.push('x'.repeat(128 * 1024 + 1))).toThrow('size limit');
  });
  it('deduplicates event IDs and requests reconciliation after a gap', async () => {
    const wire = stream(); fetchMock.mockResolvedValue(wire.response);
    const client = new SseClient(); const listener = vi.fn(); client.subscribe(listener); await client.connect();
    wire.send(event(1)); wire.send(event(1)); wire.send(event(3)); await vi.waitFor(() => expect(listener).toHaveBeenCalledTimes(3));
    expect(listener.mock.calls.map(([message]) => message.event)).toEqual(['state.changed', 'resync_required', 'state.changed']);
    client.disconnect();
  });
  it('does not dispatch a late initial connection after disconnect', async () => {
    let finish: (value: Response) => void = () => undefined;
    fetchMock.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const client = new SseClient(); const listener = vi.fn(); client.subscribe(listener); const pending = client.connect();
    client.disconnect(); const wire = stream(); finish(wire.response); await pending; await settle(); expect(wire.response.body?.locked).toBe(false); expect(listener).not.toHaveBeenCalled();
  });
  it('rejects an HTML response instead of reporting events connected', async () => {
    fetchMock.mockResolvedValue(new Response('<html>', { headers: { 'Content-Type': 'text/html' } }));
    const client = new SseClient(); await expect(client.connect()).rejects.toThrow('rejected'); client.disconnect();
  });
});
