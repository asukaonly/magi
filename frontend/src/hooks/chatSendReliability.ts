import { messagesApi } from '@/api';
import type { UserMessageRequest } from '@/api';
import { toApiClientError, type ApiClientError } from '@/api/client';
import { getAskState } from '@/api/modules/control';
import { DEFAULT_USER_ID } from '@/constants';
import { normalizeHistoryMessages } from '@/domain/chat/state';
import { isTurnDurablyTerminal } from '@/domain/chat/turn-completion';

const USER_ID = DEFAULT_USER_ID;
const SEND_CONFIRMATION_TIMEOUT_MS = 1_200;
const ASK_CONFIRMATION_DELAYS_MS = [0, 75, 200] as const;

export type ChatSendConfirmation =
  | {
    kind: 'turn';
    sessionId: string;
    turnId: string;
  }
  | {
    kind: 'ask_response';
    sessionId: string;
    requestId: string;
    answer: string;
  };

export type ReliableChatSendOutcome =
  | {
    kind: 'accepted';
    responseSessionId?: unknown;
  }
  | {
    kind: 'concluded';
  }
  | {
    kind: 'rejected';
    message: string;
  }
  | {
    kind: 'unconfirmed';
  };

type SendAttemptOutcome =
  | {
    kind: 'accepted';
    responseSessionId?: unknown;
  }
  | {
    kind: 'reported_rejection';
    message: string;
  }
  | {
    kind: 'rejected';
    message: string;
  }
  | {
    kind: 'uncertain';
  };

type ConfirmationCheck = {
  status: 'confirmed' | 'absent' | 'concluded' | 'unavailable';
  safeToRetry: boolean;
};

type TimedRequestResult<T> =
  | {
    available: true;
    value: T;
  }
  | {
    available: false;
  };

const wait = async (delayMs: number): Promise<void> => {
  if (delayMs <= 0) {
    return;
  }
  await new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
};

const withConfirmationTimeout = async <T>(
  request: Promise<T>,
): Promise<TimedRequestResult<T>> => {
  let timeoutId: number | null = null;
  try {
    const value = await Promise.race([
      request.then((result) => ({ available: true as const, value: result })),
      new Promise<{ available: false }>((resolve) => {
        timeoutId = window.setTimeout(
          () => resolve({ available: false }),
          SEND_CONFIRMATION_TIMEOUT_MS,
        );
      }),
    ]);
    return value;
  } catch {
    return { available: false };
  } finally {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  }
};

const attemptChatSend = async (
  request: UserMessageRequest,
  fallbackMessage: string,
): Promise<SendAttemptOutcome> => {
  try {
    const result = await messagesApi.sendMessage(request);
    if (result.success === false) {
      return {
        kind: 'reported_rejection',
        message: result.message || fallbackMessage,
      };
    }
    return {
      kind: 'accepted',
      responseSessionId: result.data?.session_id,
    };
  } catch (error) {
    const hasExplicitKind = Boolean(
      error
      && typeof error === 'object'
      && typeof (error as { kind?: unknown }).kind === 'string',
    );
    const normalized = hasExplicitKind
      ? error as ApiClientError
      : toApiClientError(error);
    if (
      normalized.kind === 'http'
      && typeof normalized.status === 'number'
      && normalized.status >= 400
      && normalized.status < 500
    ) {
      return {
        kind: 'rejected',
        message: normalized.message || fallbackMessage,
      };
    }
    if (hasExplicitKind && normalized.kind === 'request') {
      return {
        kind: 'rejected',
        message: normalized.message || fallbackMessage,
      };
    }
    return { kind: 'uncertain' };
  }
};

const readConfirmationHistory = async (
  confirmation: ChatSendConfirmation,
): Promise<ConfirmationCheck> => {
  const result = await withConfirmationTimeout(
    messagesApi.getHistory(USER_ID, confirmation.sessionId),
  );
  if (!result.available) {
    return {
      status: 'unavailable',
      safeToRetry: confirmation.kind === 'turn',
    };
  }
  const history = result.value;
  const messages = normalizeHistoryMessages(
    Array.isArray(history.messages) ? history.messages : [],
  );
  const confirmed = confirmation.kind === 'turn'
    ? messages.some((message) => (
      message.role === 'user'
      && String(message.turnId || '').trim() === confirmation.turnId
    ))
    : messages.some((message) => (
      message.role === 'user'
      && message.messageKind === 'ask_response'
      && String(message.payload?.ask_request_id || '').trim() === confirmation.requestId
      && String(message.content || '').trim() === confirmation.answer.trim()
    ));
  return {
    status: confirmed ? 'confirmed' : 'absent',
    safeToRetry: confirmation.kind === 'turn',
  };
};

const readAskStateConfirmation = async (
  confirmation: Extract<ChatSendConfirmation, { kind: 'ask_response' }>,
): Promise<ConfirmationCheck> => {
  const result = await withConfirmationTimeout(getAskState(confirmation.sessionId));
  if (!result.available) {
    return { status: 'unavailable', safeToRetry: false };
  }
  const ask = result.value;
  if (!ask || ask.request_id !== confirmation.requestId) {
    return { status: 'concluded', safeToRetry: false };
  }
  if (ask.status === 'answered') {
    const confirmed = (
      String(ask.answer || '').trim() === confirmation.answer.trim()
    );
    return confirmed
      ? { status: 'confirmed', safeToRetry: false }
      : { status: 'concluded', safeToRetry: false };
  }
  if (ask.status !== 'pending') {
    return { status: 'concluded', safeToRetry: false };
  }
  return {
    status: 'absent',
    safeToRetry: true,
  };
};

export const confirmChatSend = async (
  confirmation: ChatSendConfirmation,
): Promise<ConfirmationCheck> => {
  if (confirmation.kind === 'turn') {
    return readConfirmationHistory(confirmation);
  }
  for (
    let index = 0;
    index < ASK_CONFIRMATION_DELAYS_MS.length;
    index += 1
  ) {
    const delayMs = ASK_CONFIRMATION_DELAYS_MS[index];
    await wait(delayMs);
    const [historyCheck, stateCheck] = await Promise.all([
      readConfirmationHistory(confirmation),
      readAskStateConfirmation(confirmation),
    ]);
    if (
      historyCheck.status === 'confirmed'
      || stateCheck.status === 'confirmed'
    ) {
      return { status: 'confirmed', safeToRetry: false };
    }
    if (stateCheck.status === 'concluded') {
      return stateCheck;
    }
    const isLastCheck = index === ASK_CONFIRMATION_DELAYS_MS.length - 1;
    if (stateCheck.status === 'absent' && isLastCheck) {
      return stateCheck;
    }
    if (isLastCheck) {
      return { status: 'unavailable', safeToRetry: false };
    }
  }
  return { status: 'unavailable', safeToRetry: false };
};

export const isChatTurnConfirmedTerminal = async (
  sessionId: string,
  turnId: string,
): Promise<boolean> => {
  const result = await withConfirmationTimeout(
    messagesApi.getHistory(USER_ID, sessionId),
  );
  if (!result.available) {
    return false;
  }
  const messages = normalizeHistoryMessages(
    Array.isArray(result.value.messages) ? result.value.messages : [],
  );
  return isTurnDurablyTerminal(messages, turnId);
};

export const sendChatMessageReliably = async ({
  request,
  confirmation,
  fallbackMessage,
  preflight = false,
}: {
  request: UserMessageRequest;
  confirmation: ChatSendConfirmation;
  fallbackMessage: string;
  preflight?: boolean;
}): Promise<ReliableChatSendOutcome> => {
  if (preflight) {
    const preflightCheck = await confirmChatSend(confirmation);
    if (preflightCheck.status === 'confirmed') {
      return {
        kind: 'accepted',
        responseSessionId: confirmation.sessionId,
      };
    }
    if (preflightCheck.status === 'concluded') {
      return { kind: 'concluded' };
    }
    if (
      confirmation.kind === 'ask_response'
      && !preflightCheck.safeToRetry
    ) {
      return { kind: 'unconfirmed' };
    }
  }

  let outcome = await attemptChatSend(request, fallbackMessage);
  if (preflight && outcome.kind === 'rejected') {
    const rejectionCheck = await confirmChatSend(confirmation);
    if (rejectionCheck.status === 'confirmed') {
      return {
        kind: 'accepted',
        responseSessionId: confirmation.sessionId,
      };
    }
    return rejectionCheck.status === 'concluded'
      ? { kind: 'concluded' }
      : { kind: 'unconfirmed' };
  }
  if (outcome.kind === 'reported_rejection') {
    const rejectionCheck = await confirmChatSend(confirmation);
    if (rejectionCheck.status === 'confirmed') {
      return {
        kind: 'accepted',
        responseSessionId: confirmation.sessionId,
      };
    }
    if (rejectionCheck.status === 'concluded') {
      return { kind: 'concluded' };
    }
    return rejectionCheck.status === 'absent'
      ? { kind: 'rejected', message: outcome.message }
      : { kind: 'unconfirmed' };
  }
  if (outcome.kind === 'uncertain') {
    const firstCheck = await confirmChatSend(confirmation);
    if (firstCheck.status === 'confirmed') {
      return {
        kind: 'accepted',
        responseSessionId: confirmation.sessionId,
      };
    }
    if (firstCheck.status === 'concluded') {
      return { kind: 'concluded' };
    }
    if (!firstCheck.safeToRetry) {
      return { kind: 'unconfirmed' };
    }
    outcome = await attemptChatSend(request, fallbackMessage);
    if (preflight && outcome.kind === 'rejected') {
      const rejectionCheck = await confirmChatSend(confirmation);
      if (rejectionCheck.status === 'confirmed') {
        return {
          kind: 'accepted',
          responseSessionId: confirmation.sessionId,
        };
      }
      return rejectionCheck.status === 'concluded'
        ? { kind: 'concluded' }
        : { kind: 'unconfirmed' };
    }
    if (outcome.kind === 'reported_rejection') {
      const rejectionCheck = await confirmChatSend(confirmation);
      if (rejectionCheck.status === 'confirmed') {
        return {
          kind: 'accepted',
          responseSessionId: confirmation.sessionId,
        };
      }
      if (rejectionCheck.status === 'concluded') {
        return { kind: 'concluded' };
      }
      return rejectionCheck.status === 'absent'
        ? { kind: 'rejected', message: outcome.message }
        : { kind: 'unconfirmed' };
    }
    if (outcome.kind === 'uncertain') {
      const finalCheck = await confirmChatSend(confirmation);
      if (finalCheck.status === 'confirmed') {
        return {
          kind: 'accepted',
          responseSessionId: confirmation.sessionId,
        };
      }
      if (finalCheck.status === 'concluded') {
        return { kind: 'concluded' };
      }
    }
  }
  return outcome.kind === 'uncertain'
    ? { kind: 'unconfirmed' }
    : outcome;
};
