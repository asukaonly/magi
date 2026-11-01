import { messagesApi } from '@/api';
import type { UserMessageRequest } from '@/api';
import { toApiClientError, type ApiClientError } from '@/api/client';
const SEND_CONFIRMATION_TIMEOUT_MS = 1_200;

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

export const confirmChatSend = async (
  confirmation: ChatSendConfirmation,
): Promise<ConfirmationCheck> => {
  const request = confirmation.kind === 'turn'
    ? { kind: 'turn' as const, session_id: confirmation.sessionId, turn_id: confirmation.turnId }
    : { kind: 'ask_response' as const, session_id: confirmation.sessionId, request_id: confirmation.requestId, answer: confirmation.answer };
  const result = await withConfirmationTimeout(messagesApi.confirmSend(request));
  return result.available
    ? { status: result.value.status, safeToRetry: result.value.safe_to_retry }
    : { status: 'unavailable', safeToRetry: false };
};

export const isChatTurnConfirmedTerminal = async (
  sessionId: string,
  turnId: string,
): Promise<boolean> => {
  const result = await withConfirmationTimeout(messagesApi.getTurnSnapshot(sessionId, turnId));
  return result.available && result.value.terminal;
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
      !preflightCheck.safeToRetry
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
