import { beforeEach, describe, expect, it, vi } from 'vitest';
import examples from '../../../contracts/api/frontend-events-examples.json';
import { parseChatMessage, parseChatSession, parseBackgroundTask, validateRunEvent, executionControlSchema } from '@/api/event-contract';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import { useConversationStore } from '@/stores/conversation-store';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { backgroundTasksApi } from '@/api/modules/backgroundTasks';
import { projectChatRealtimeEffectPlan, createChatRealtimeResponseTracker } from '@/domain/chat/realtime';

const { get } = vi.hoisted(() => ({ get: vi.fn<(path: string) => Promise<unknown>>() }));
vi.mock('@/api/client', () => ({ api: { get }, unwrapGatewayPayload: (value: unknown) => value }));

beforeEach(() => {
  get.mockReset();
  useConversationStore.getState().reset();
  useBackgroundTaskStore.getState().reset();
});

describe('production chat and task serialization contracts', () => {
  it('accepts actual Python serializers and notification builders', () => {
    expect(parseChatMessage(examples.message).content).toBe('Hello');
    expect(parseChatSession(examples.session).history_version).toBe(0);
    expect(parseBackgroundTask(examples.task).status).toBe('suspended_waiting_user');
    expect(validateRunEvent(examples.runEvent)).toBe(true);
    expect(executionControlSchema.safeParse(examples.control).success).toBe(true);
    expect(applyRealtimeStoreProjection({ event: 'chat_message_upserted', data: examples.upsert })).toBe(true);
    expect(useConversationStore.getState().messagesBySession['fixture-session'][0].content).toBe('Hello');
    expect(applyRealtimeStoreProjection({ event: 'chat_message_hidden', data: examples.hidden })).toBe(true);
    expect(useConversationStore.getState().messagesBySession['fixture-session']).toEqual([]);
    expect(applyRealtimeStoreProjection({ event: 'agent_response', data: examples.response })).toBe(true);
    expect(applyRealtimeStoreProjection({ event: 'agent_response_chunk', data: examples.chunk })).toBe(true);
  });

  it.each([
    { ...examples.message, content: 123 },
    { ...examples.message, role: 'system' },
    { ...examples.message, attachments: [{ attachment_id: 'a', kind: 'file', original_name: 1 }] },
    { ...examples.message, run_state: { state: 'running', can_cancel: 'false' } },
  ])('rejects malformed message fields without partially changing the stores', message => {
    expect(() => parseChatMessage(message)).toThrow();
    expect(applyRealtimeStoreProjection({ event: 'chat_message_upserted', data: { ...examples.upsert, message } })).toBe(false);
    expect(useConversationStore.getState().messagesBySession).toEqual({});
  });

  it('rejects mismatched session summaries before writing a message or deleting it', () => {
    const summary = { ...examples.session, session_id: 'other-session' };
    expect(applyRealtimeStoreProjection({ event: 'chat_message_upserted', data: { ...examples.upsert, session_summary: summary } })).toBe(false);
    expect(applyRealtimeStoreProjection({ event: 'chat_message_hidden', data: { ...examples.hidden, session_summary: summary } })).toBe(false);
    expect(useConversationStore.getState().messagesBySession).toEqual({});
  });

  it('rejects incomplete task events and malformed REST data instead of reporting an empty list', async () => {
    expect(applyRealtimeStoreProjection({ event: 'background_task_state_changed', data: { task_id: 't', status: 'running' } })).toBe(false);
    get.mockResolvedValueOnce({ tasks: [{ ...examples.task, status: 'unknown' }], active_count: 1, total: 1 });
    await expect(backgroundTasksApi.list()).rejects.toThrow();
    get.mockResolvedValueOnce({ tasks: [examples.task], active_count: 1, total: 1 });
    await expect(backgroundTasksApi.list()).resolves.toMatchObject({ tasks: [{ status: 'suspended_waiting_user' }] });
  });

  it('bounds invalid rhythm tracking as well as valid tracking', () => {
    const tracker = createChatRealtimeResponseTracker();
    for (let index = 0; index < 33; index += 1) {
      tracker.observeRhythm({ session_id: 's', turn_id: `turn-${index}` });
    }
    expect(tracker.observeRhythm({
      session_id: 's', turn_id: 'turn-0', message_id: 'new-message',
      message_payload: { rhythm: { segment_index: 0, segment_count: 1 } },
    })).toBe(true);
  });

  it('does not clear pending turns with a coerced identity or a malformed final flag', () => {
    for (const data of [
      { session_id: 12, turn_id: 'turn', is_final: true },
      { session_id: '12', turn_id: 'turn', is_final: 'false' },
    ]) {
      expect(projectChatRealtimeEffectPlan({ event: 'agent_response', data }, {
        allowInterjection: false, turnsBySession: { '12': 'turn' },
      }).clearPendingResponseTurn).toBeUndefined();
    }
  });
});
