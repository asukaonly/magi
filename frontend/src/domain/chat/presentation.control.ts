import type { ChatTimelineMessage } from './state';
import type {
  ChatPresentationSurface,
  ControlStatusTone,
  ProjectedControlStatusCardPresentation,
  ProjectedControlTodoItem,
} from './presentation.types';

const CONTROL_STATUS_MESSAGE_KINDS = new Set([
  'background_task_completion',
  'background_task_pending',
  'plan_state',
  'todo_state',
  'ask_request',
  'permission_request',
]);

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' ? value as Record<string, unknown> : {}
);

const getBackgroundTaskTone = (status: string): ControlStatusTone => {
  switch (status) {
    case 'succeeded':
      return 'success';
    case 'failed':
      return 'danger';
    case 'cancelled':
      return 'warning';
    default:
      return 'neutral';
  }
};

const getRiskTone = (riskLevel: string): ControlStatusTone => {
  switch (riskLevel) {
    case 'high':
    case 'destructive':
    case 'critical':
      return 'danger';
    case 'medium':
      return 'warning';
    default:
      return 'neutral';
  }
};

const stringifyPreviewValue = (value: unknown): string | null => {
  if (value == null) {
    return null;
  }

  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || null;
  }

  try {
    const serialized = JSON.stringify(value, null, 2);
    return serialized?.trim() || null;
  } catch {
    const fallback = String(value).trim();
    return fallback || null;
  }
};

const numberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

const normalizeTodoStatus = (value: unknown): ProjectedControlTodoItem['status'] => {
  switch (String(value || '').trim().toLowerCase()) {
    case 'completed':
    case 'done':
      return 'completed';
    case 'blocked':
      return 'blocked';
    case 'skipped':
      return 'skipped';
    case 'cancelled':
    case 'canceled':
      return 'cancelled';
    case 'in_progress':
    case 'in-progress':
    case 'running':
    case 'active':
      return 'in_progress';
    default:
      return 'pending';
  }
};

export const isControlStatusMessageKind = (messageKind: string | null | undefined): boolean => (
  CONTROL_STATUS_MESSAGE_KINDS.has(String(messageKind || '').trim())
);

export const getChatPresentationSurface = (
  message: ChatTimelineMessage,
): ChatPresentationSurface => {
  if (message.kind !== 'status') {
    return 'transcript';
  }

  if (isControlStatusMessageKind(message.messageKind)) {
    return 'control_status';
  }

  return 'runtime_status';
};

export const isControlStatusMessage = (message: ChatTimelineMessage): boolean => (
  getChatPresentationSurface(message) === 'control_status'
);

export const isTranscriptMessage = (message: ChatTimelineMessage): boolean => (
  getChatPresentationSurface(message) === 'transcript'
);

export const projectControlStatusCardPresentation = (
  message: ChatTimelineMessage,
): ProjectedControlStatusCardPresentation | null => {
  if (!isControlStatusMessage(message)) {
    return null;
  }

  const payload = asRecord(message.payload);

  switch (message.messageKind) {
    case 'background_task_completion': {
      const content = String(message.content || '');
      const firstNewline = content.indexOf('\n');
      const bodyText = (firstNewline >= 0 ? content.slice(firstNewline + 1) : content).trim();
      const status = String(payload.background_task_status || '').trim().toLowerCase();

      return {
        kind: 'background_task_completion',
        taskId: String(payload.background_task_id || '').trim() || null,
        status,
        statusTone: getBackgroundTaskTone(status),
        title: String(payload.background_task_title || '').trim() || null,
        bodyText: bodyText || null,
      };
    }
    case 'background_task_pending': {
      return {
        kind: 'background_task_pending',
        taskId: String(payload.background_task_id || '').trim() || null,
        title: String(payload.background_task_title || '').trim() || null,
        invocationText: String(payload.invocation_text || '').trim() || null,
        skillName: String(payload.skill_name || '').trim() || null,
      };
    }
    case 'permission_request': {
      const riskLevel = String(payload.risk_level || '').trim().toLowerCase();

      return {
        kind: 'permission_request',
        requestId: String(payload.permission_request_id || '').trim() || null,
        sessionId: String(payload.session_id || '').trim() || null,
        tool: String(payload.tool || message.content || '').trim(),
        riskLevel,
        riskTone: getRiskTone(riskLevel),
        origin: String(payload.origin || '').trim() || null,
        argsPreview: stringifyPreviewValue(payload.tool_args || {}),
        expiresAtMs: numberOrNull(payload.expires_at_ms),
      };
    }
    case 'ask_request': {
      return {
        kind: 'ask_request',
        requestId: String(payload.ask_request_id || '').trim() || null,
        sessionId: String(payload.session_id || '').trim() || null,
        question: String(payload.question || message.content || '').trim(),
        options: Array.isArray(payload.options)
          ? payload.options.map((item) => String(item || '').trim()).filter(Boolean)
          : [],
        allowFreeText: Boolean(payload.allow_free_text),
        isBackground: Boolean(payload.background),
        expiresAtMs: numberOrNull(payload.expires_at_ms),
      };
    }
    case 'plan_state': {
      return {
        kind: 'plan_state',
        active: Boolean(payload.active),
        planText: String(payload.plan_text || message.content || '').trim() || null,
      };
    }
    case 'todo_state': {
      const items = Array.isArray(payload.items)
        ? payload.items
          .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
          .map((item, index) => {
            const rawId = String(item.id || item.content || '').trim();

            return {
              id: rawId || `todo-${index}`,
              content: String(item.content || '').trim(),
              status: normalizeTodoStatus(item.status),
            };
          })
        : [];

      return {
        kind: 'todo_state',
        items,
      };
    }
    default:
      return null;
  }
};
