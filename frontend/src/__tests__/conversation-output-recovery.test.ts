import { describe, expect, it } from 'vitest';
import {
  applyStreamTextDelta,
  applyStreamTextReset,
  applyStreamToolCall,
} from '@/stores/conversation-streaming';

describe('output limit recovery previews', () => {
  it('discards partial text and pending calls while preserving completed calls', () => {
    const turnId = 'turn';
    let messages = applyStreamTextDelta([], { turnId, textDelta: 'partial answer' }).messages;
    messages = applyStreamToolCall(messages, {
      turnId, toolCallId: 'done', toolName: 'read_file', status: 'completed',
      toolArguments: { path: 'file.txt' },
    }).messages;
    messages = applyStreamToolCall(messages, {
      turnId, toolCallId: 'partial', toolName: 'ask_user_question', status: 'running',
      toolArgsDelta: '{"question":',
    }).messages;

    const reset = applyStreamTextReset(messages, { turnId });

    expect(reset.messages[0].content).toBe('');
    expect(reset.messages[0].streaming).toBe(true);
    expect(reset.messages[0].toolCalls).toEqual([expect.objectContaining({
      toolCallId: 'done', toolName: 'read_file', status: 'completed',
      toolArguments: { path: 'file.txt' },
    })]);
    expect(messages[0].toolCalls).toHaveLength(2);
    expect(applyStreamTextReset(messages, { turnId: 'another' }).changed).toBe(false);
  });
});
