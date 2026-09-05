import { z } from 'zod';
import { ApiContractError } from './config-contract';
import type { ChatHistoryMessage, ChatSessionListItem, ChatAttachment } from './modules/messages';
import type { BackgroundTaskDTO } from './modules/backgroundTasks';
import {
  validateChatDisplayMessage, validateChatSessionSummary,
  validateBackgroundTask, validateRunEvent,
} from './generated/events-validators';

const record = z.record(z.string(), z.unknown());
const text = z.string().trim().min(1);
const nullableText = z.string().nullable().optional();
export const attachmentSchema = z.object({
  attachment_id: text, kind: text, original_name: z.string(),
  mime_type: z.string().optional(), size_bytes: z.number().finite().nonnegative().optional(),
  storage_path: z.string().optional(), sha256: z.string().optional(),
  parse_status: z.string().optional(), derived_text_excerpt: z.string().optional(), derived_text_path: z.string().optional(),
}).passthrough();

const historyFields = z.object({
  message_id: nullableText, message_kind: nullableText, persona_id: nullableText,
  role: z.enum(['user', 'assistant']), content: z.string(), timestamp: z.number().finite(),
  turn_id: nullableText, kind: z.enum(['user', 'assistant', 'status']).nullish(),
  trace_display_mode: nullableText, allow_trace_collapse: z.boolean().optional(),
  trace_summary: record.nullish(), trace_available: z.boolean().optional(),
  attachments: z.array(attachmentSchema),
  run_state: z.object({
    state: text, run_id: nullableText, run_revision: z.number().int().optional(),
    run_disposition: nullableText, can_cancel: z.boolean().optional(), can_detach: z.boolean().optional(),
    error_text: nullableText, completed_at_ms: z.number().finite().nullish(),
  }).nullish(),
  reply_to: z.object({ message_id: text, role: z.enum(['user', 'assistant']), message_kind: nullableText, content_excerpt: z.string() }).nullish(),
  label: z.object({ kind: text, text: z.string(), applied_by: text, source: text, created_at_ms: z.number().finite() }).nullish(),
  payload: record.nullish(),
});

export function parseChatMessage(value: unknown): ChatHistoryMessage {
  if (!validateChatDisplayMessage(value)) throw new ApiContractError('Invalid chat message response');
  const parsed = historyFields.safeParse(value);
  if (!parsed.success) throw new ApiContractError('Invalid chat message fields');
  return parsed.data;
}

export function parseChatSession(value: unknown): ChatSessionListItem {
  if (!validateChatSessionSummary(value)) throw new ApiContractError('Invalid chat session response');
  return value;
}

export function parseBackgroundTask(value: unknown): BackgroundTaskDTO {
  if (!validateBackgroundTask(value)) throw new ApiContractError('Invalid background task response');
  return value;
}

export function parseAttachments(value: unknown): ChatAttachment[] {
  const parsed = z.array(attachmentSchema).safeParse(value);
  if (!parsed.success) throw new ApiContractError('Invalid chat attachments');
  return parsed.data;
}

export { validateRunEvent };
export const delegationStateSchema = z.enum(['started', 'running', 'finished', 'failed', 'cancelled', 'discarded', 'applied']);
export const executionControlSchema = z.object({
  session_id: text, turn_id: text, state: text, label: nullableText,
  can_cancel: z.boolean().optional(), run_id: nullableText,
}).passthrough();
export type ExecutionControlPayload = z.infer<typeof executionControlSchema>;

export const agentResponseSchema = z.object({
  session_id: text, turn_id: text, content: z.string(), is_final: z.boolean().optional(),
  message_id: nullableText, message_kind: nullableText, persona_id: nullableText,
  timestamp: z.number().finite().optional(), attachments: z.array(attachmentSchema).optional(),
  trace_summary: record.nullish(), trace_available: z.boolean().optional(),
  ux_plan: record.nullish(), message_payload: record.nullish(),
}).passthrough();

export const contextUsageSchema = z.object({
  session_id: text, turn_id: nullableText,
  used_tokens: z.number().finite().nonnegative(), window_size: z.number().finite().nonnegative(),
  input_capacity: z.number().finite().nonnegative().optional(), threshold: z.number().finite().nonnegative(),
  measurement: z.enum(['actual', 'estimated']), model_provider: nullableText, model_id: nullableText,
  updated_at_ms: z.number().finite().nullish(), timestamp: z.number().finite().optional(),
});
