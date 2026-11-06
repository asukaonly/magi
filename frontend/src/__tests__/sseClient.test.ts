import { afterEach, describe, expect, it, vi } from 'vitest';
const { fetchMock, centerId } = vi.hoisted(() => ({ fetchMock: vi.fn(), centerId: 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0' }));
import { SseClient, SseFrames } from '@/realtime/sse-client';
const epoch = 'a0c4c092-b043-4767-a2a7-041ad6194b8c';
const event = (sequence: number, extra = {}) => ({ contract_version: 1, server_id: centerId, epoch, sequence, event_id: `${epoch}:${sequence}`, event_type: 'state.changed', data: { resource: 'tasks' }, ...extra });
function stream() {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  return { response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }), interrupt: () => controller.error(new TypeError('Connection interrupted')), send: (payload: unknown) => controller.enqueue(new TextEncoder().encode(`event: magi\ndata: ${JSON.stringify(payload)}\n\n`)) };
}
const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });
describe('authenticated center events', () => {
  it('uses direct product payloads and rejects undeclared runtime details', async () => {
    const wire = stream(); fetchMock.mockResolvedValue(wire.response);
    const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock });
    const listener = vi.fn(); client.subscribe(listener); await client.connect();
    wire.send(event(1, { event_type: 'control.ask.requested', data: { session_id: 's', request_id: 'q' } }));
    wire.send(event(2, { event_type: 'control.ask.requested', data: { session_id: 's', tool_arguments: { secret: true } } }));
    await vi.waitFor(() => expect(listener).toHaveBeenCalledTimes(2));
    expect(listener.mock.calls[0][0]).toMatchObject({ event: 'control.ask.requested', data: { request_id: 'q' } });
    expect(listener.mock.calls[1][0]).toEqual({ event: 'resync_required', data: { reason: 'invalid_product_event' } });
    client.disconnect();
  });
  it('parses fragmented frames and bounds incomplete input', () => {
    const frames = new SseFrames(); expect(frames.push('data: {')).toEqual([]);
    expect(frames.push('}\r\n\r\n: heartbeat\n\n')).toEqual(['data: {}', ': heartbeat']);
    expect(() => frames.push('x'.repeat(128 * 1024 + 1))).toThrow('size limit');
  });
  it('deduplicates event IDs and requests reconciliation after a gap', async () => {
    const wire = stream(); fetchMock.mockResolvedValue(wire.response);
    const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock }); const listener = vi.fn(); client.subscribe(listener); await client.connect();
    wire.send(event(1)); wire.send(event(1)); wire.send(event(3)); await vi.waitFor(() => expect(listener).toHaveBeenCalledTimes(3));
    expect(listener.mock.calls.map(([message]) => message.event)).toEqual(['state.changed', 'resync_required', 'state.changed']);
    client.disconnect();
  });
  it('does not dispatch a late initial connection after disconnect', async () => {
    let finish: (value: Response) => void = () => undefined;
    fetchMock.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock }); const listener = vi.fn(); client.subscribe(listener); const pending = client.connect();
    client.disconnect(); const wire = stream(); finish(wire.response); await pending; await settle(); expect(wire.response.body?.locked).toBe(false); expect(listener).not.toHaveBeenCalled();
  });
  it('rejects an HTML response instead of reporting events connected', async () => {
    fetchMock.mockResolvedValue(new Response('<html>', { headers: { 'Content-Type': 'text/html' } }));
    const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock }); await expect(client.connect()).rejects.toThrow('rejected'); client.disconnect();
  });
});

it('automatically retries an initial failure and stops retries on disconnect', async () => {
  vi.useFakeTimers();
  const wire = stream();
  fetchMock.mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(wire.response);
  const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock });
  const status = vi.fn();
  client.subscribeStatus(status);
  await expect(client.connect()).rejects.toThrow('offline');
  await vi.advanceTimersByTimeAsync(1_100);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ connected: true }));
  expect(status.mock.calls.every(([state]) => !state.accessDenied)).toBe(true);
  client.disconnect();
  await vi.advanceTimersByTimeAsync(120_000);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('automatically resumes an interrupted stream and retains its last event cursor', async () => {
  vi.useFakeTimers();
  const first = stream();
  const resumed = stream();
  fetchMock.mockReset().mockResolvedValueOnce(first.response).mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(resumed.response);
  const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock });
  const status = vi.fn();
  client.subscribeStatus(status);
  await client.connect();
  first.send(event(1));
  await settle();
  first.interrupt();
  await vi.advanceTimersByTimeAsync(3_100);
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock.mock.calls[2][1].headers['Last-Event-ID']).toBe(`${epoch}:1`);
  expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ connected: true, accessDenied: false }));
  client.disconnect();
});

it.each([401, 403])('retains an actionable %s rejection until a connection succeeds', async (code) => {
  vi.useFakeTimers();
  fetchMock.mockReset().mockResolvedValueOnce(new Response(null, { status: code }))
    .mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(stream().response);
  const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock });
  const status = vi.fn();
  client.subscribeStatus(status);
  await expect(client.connect()).rejects.toThrow('access was denied');
  expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ accessDenied: true }));
  await vi.advanceTimersByTimeAsync(1_100);
  expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ accessDenied: true }));
  await vi.advanceTimersByTimeAsync(2_000);
  expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ connected: true, accessDenied: false }));
  client.disconnect();
});

it('does not retry a failed initial attempt after its owner is disconnected', async () => {
  vi.useFakeTimers();
  fetchMock.mockRejectedValue(new TypeError('offline'));
  const client = new SseClient({ baseUrl: 'https://center.example/api', serverId: centerId, fetch: fetchMock });
  await expect(client.connect()).rejects.toThrow('offline');
  client.disconnect();
  await vi.advanceTimersByTimeAsync(120_000);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
