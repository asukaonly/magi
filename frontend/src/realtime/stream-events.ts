export type RealtimeStreamEventKind =
  | 'text_delta'
  | 'reasoning_delta'
  | 'status_update'
  | 'text_flush'
  | 'text_reset'
  | 'tool_call_start'
  | 'tool_call_args'
  | 'tool_call_end'
  | 'usage'
  | 'error'
  | 'done';

export interface RealtimeStreamEvent {
  kind: RealtimeStreamEventKind;
  text?: string;
  toolCallId?: string | null;
  toolName?: string | null;
  toolArgsDelta?: string;
  toolArguments?: Record<string, unknown> | null;
  usage?: Record<string, number> | null;
  errorKind?: string | null;
  errorMessage?: string | null;
  source?: string | null;
  stepLabel?: string | null;
}

const STREAM_EVENT_KINDS = new Set<RealtimeStreamEventKind>([
  'text_delta',
  'reasoning_delta',
  'status_update',
  'text_flush',
  'text_reset',
  'tool_call_start',
  'tool_call_args',
  'tool_call_end',
  'usage',
  'error',
  'done',
]);

const asRecord = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
};

const asTrimmedString = (value: unknown): string | null => {
  const normalized = String(value || '').trim();
  return normalized ? normalized : null;
};

const normalizeUsage = (value: unknown): Record<string, number> | null => {
  const usage = asRecord(value);
  if (!usage) {
    return null;
  }

  const normalized = Object.entries(usage).reduce<Record<string, number>>((acc, [key, entryValue]) => {
    if (typeof entryValue === 'number' && Number.isFinite(entryValue)) {
      acc[key] = entryValue;
    }
    return acc;
  }, {});

  return Object.keys(normalized).length > 0 ? normalized : null;
};

export const normalizeRealtimeStreamEvent = (
  payload: Record<string, unknown>,
): RealtimeStreamEvent | null => {
  const rawEvent = asRecord(payload.event);
  const kind = asTrimmedString(rawEvent?.kind);
  if (!kind || !STREAM_EVENT_KINDS.has(kind as RealtimeStreamEventKind)) {
    return null;
  }

  return {
    kind: kind as RealtimeStreamEventKind,
    text: typeof rawEvent?.text === 'string' ? rawEvent.text : undefined,
    toolCallId: asTrimmedString(rawEvent?.tool_call_id),
    toolName: asTrimmedString(rawEvent?.tool_name),
    toolArgsDelta: typeof rawEvent?.tool_args_delta === 'string' ? rawEvent.tool_args_delta : undefined,
    toolArguments: asRecord(rawEvent?.tool_arguments),
    usage: normalizeUsage(rawEvent?.usage),
    errorKind: asTrimmedString(rawEvent?.error_kind),
    errorMessage: asTrimmedString(rawEvent?.error_message),
    source: asTrimmedString(rawEvent?.source),
    stepLabel: asTrimmedString(rawEvent?.step_label),
  };
};
