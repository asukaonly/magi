import type { ChatTimelineMessage } from '@/domain/chat/state';
import { readCodeAgentDelegations } from '@/domain/chat/delegations';

const CHAT_CONTENT_EVENTS = new Set([
  'agent_response',
  'agent_response_chunk',
  'chat_message_hidden',
  'chat_message_upserted',
  'turn_ux_plan',
  'execution_trace_update',
  'context_usage',
  'code_agent_delegation_event',
  'code_agent_delegation_state',
]);

const retiredSessionIds = new Set<string>();
const retiredMessageIdsBySession = new Map<string, Set<string>>();
const retiredTurnIdsBySession = new Map<string, Set<string>>();
const retiredDelegationIdsBySession = new Map<string, Set<string>>();
const activatedSessionIdsAfterGlobalClear = new Set<string>();
let globalClearActive = false;

const normalizeIdentity = (value: unknown): string => String(value || '').trim();
const normalizeSessionIdentity = (value: unknown): string => (
  normalizeIdentity(value).toLowerCase()
);
const normalizeMessageIdentity = (value: unknown): string => (
  normalizeIdentity(value).toLowerCase()
);

const retireScopedIdentity = (
  registry: Map<string, Set<string>>,
  sessionId: string,
  value: unknown,
  normalizeValue: (input: unknown) => string = normalizeIdentity,
): void => {
  const normalized = normalizeValue(value);
  if (!normalized) {
    return;
  }
  const current = registry.get(sessionId) ?? new Set<string>();
  current.add(normalized);
  registry.set(sessionId, current);
};

export const isRealtimeChatContentEvent = (eventName: unknown): boolean => (
  CHAT_CONTENT_EVENTS.has(normalizeIdentity(eventName))
);

export const retireRealtimeChatSession = (sessionId: unknown): void => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (normalizedSessionId) {
    retiredSessionIds.add(normalizedSessionId);
    activatedSessionIdsAfterGlobalClear.delete(normalizedSessionId);
  }
};

export const retireRealtimeChatSessions = (
  sessionIds: Iterable<unknown>,
): void => {
  for (const sessionId of sessionIds) {
    retireRealtimeChatSession(sessionId);
  }
};

export const isRealtimeChatSessionRetired = (sessionId: unknown): boolean => (
  retiredSessionIds.has(normalizeSessionIdentity(sessionId))
);

export const isRealtimeChatSessionProjectionAllowed = (
  sessionId: unknown,
): boolean => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  return Boolean(
    normalizedSessionId
    && !retiredSessionIds.has(normalizedSessionId)
    && (
      !globalClearActive
      || activatedSessionIdsAfterGlobalClear.has(normalizedSessionId)
    ),
  );
};

export const retireAllRealtimeChatProjections = (): void => {
  globalClearActive = true;
  activatedSessionIdsAfterGlobalClear.clear();
};

export const activateRealtimeChatSession = (sessionId: unknown): void => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  retiredSessionIds.delete(normalizedSessionId);
  if (globalClearActive) {
    activatedSessionIdsAfterGlobalClear.add(normalizedSessionId);
  }
};

export const activateRealtimeChatSessions = (
  sessionIds: Iterable<unknown>,
): void => {
  for (const sessionId of sessionIds) {
    activateRealtimeChatSession(sessionId);
  }
};

export const retireRealtimeChatMessage = (
  sessionId: unknown,
  message: Pick<ChatTimelineMessage, 'messageId' | 'id' | 'turnId' | 'payload'>,
): void => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  retireScopedIdentity(
    retiredMessageIdsBySession,
    normalizedSessionId,
    message.messageId || message.id,
    normalizeMessageIdentity,
  );
  retireScopedIdentity(
    retiredTurnIdsBySession,
    normalizedSessionId,
    message.turnId,
  );
  for (const { delegationId } of readCodeAgentDelegations(message.payload)) {
    retireScopedIdentity(
      retiredDelegationIdsBySession,
      normalizedSessionId,
      delegationId,
    );
  }
};

export const retireRealtimeChatMessageIds = (
  sessionId: unknown,
  messageIds: Iterable<unknown>,
): void => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  for (const messageId of messageIds) {
    retireScopedIdentity(
      retiredMessageIdsBySession,
      normalizedSessionId,
      messageId,
      normalizeMessageIdentity,
    );
  }
};

export const retireRealtimeChatDelegation = (
  sessionId: unknown,
  delegationId: unknown,
): void => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  retireScopedIdentity(
    retiredDelegationIdsBySession,
    normalizedSessionId,
    delegationId,
  );
};

export const retireRealtimeChatDelegations = (
  sessionId: unknown,
  delegationIds: Iterable<unknown>,
): void => {
  for (const delegationId of delegationIds) {
    retireRealtimeChatDelegation(sessionId, delegationId);
  }
};

export const retireRealtimeChatTurn = (
  sessionId: unknown,
  turnId: unknown,
): void => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  retireScopedIdentity(retiredTurnIdsBySession, normalizedSessionId, turnId);
};

export const retireRealtimeChatTurns = (
  sessionId: unknown,
  turnIds: Iterable<unknown>,
): void => {
  for (const turnId of turnIds) {
    retireRealtimeChatTurn(sessionId, turnId);
  }
};

export const retireRealtimeChatHistory = (
  sessionId: unknown,
  messages: ChatTimelineMessage[],
): void => {
  for (const message of messages) {
    retireRealtimeChatMessage(sessionId, message);
  }
};

export const canApplyRealtimeChatProjection = (
  eventName: unknown,
  data: unknown,
): boolean => {
  if (!isRealtimeChatContentEvent(eventName)) {
    return true;
  }
  if (!data || typeof data !== 'object') {
    return false;
  }

  const payload = data as Record<string, unknown>;
  const nestedMessage = (
    payload.message && typeof payload.message === 'object'
      ? payload.message as Record<string, unknown>
      : {}
  );
  const nestedPayload = (
    nestedMessage.payload && typeof nestedMessage.payload === 'object'
      ? nestedMessage.payload as Record<string, unknown>
      : {}
  );
  const sessionId = normalizeSessionIdentity(
    payload.session_id || nestedMessage.session_id,
  );
  if (!isRealtimeChatSessionProjectionAllowed(sessionId)) {
    return false;
  }

  const messageId = normalizeMessageIdentity(
    payload.message_id || nestedMessage.message_id || nestedMessage.id,
  );
  if (messageId && retiredMessageIdsBySession.get(sessionId)?.has(messageId)) {
    return false;
  }

  const turnId = normalizeIdentity(
    payload.turn_id || nestedMessage.turn_id,
  );
  if (turnId && retiredTurnIdsBySession.get(sessionId)?.has(turnId)) {
    return false;
  }
  const delegationIds = [
    normalizeIdentity(payload.delegation_id),
    ...readCodeAgentDelegations(payload).map(({ delegationId }) => delegationId),
    ...readCodeAgentDelegations(nestedPayload).map(({ delegationId }) => delegationId),
  ].filter(Boolean);
  if (delegationIds.some((delegationId) => (
    retiredDelegationIdsBySession.get(sessionId)?.has(delegationId)
  ))) {
    return false;
  }
  return true;
};

export const canApplyRealtimeChatDelegationProjection = (
  sessionId: unknown,
  delegationId: unknown,
  turnId?: unknown,
): boolean => {
  const normalizedSessionId = normalizeSessionIdentity(sessionId);
  if (!isRealtimeChatSessionProjectionAllowed(normalizedSessionId)) {
    return false;
  }
  const normalizedDelegationId = normalizeIdentity(delegationId);
  if (
    normalizedDelegationId
    && retiredDelegationIdsBySession
      .get(normalizedSessionId)
      ?.has(normalizedDelegationId)
  ) {
    return false;
  }
  const normalizedTurnId = normalizeIdentity(turnId);
  return !(
    normalizedTurnId
    && retiredTurnIdsBySession.get(normalizedSessionId)?.has(normalizedTurnId)
  );
};

export const resetRealtimeChatProjectionRetirementForTests = (): void => {
  retiredSessionIds.clear();
  retiredMessageIdsBySession.clear();
  retiredTurnIdsBySession.clear();
  retiredDelegationIdsBySession.clear();
  activatedSessionIdsAfterGlobalClear.clear();
  globalClearActive = false;
};
