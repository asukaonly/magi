import { apiClient } from "@/api/client";
import { messagesApi } from "@/api/modules/messages";
import { DEFAULT_USER_ID } from "@/constants/app";
import type { FirstContextQuestionId } from "@/domain/chat/first-context";
import { createClientTurnId } from "@/domain/chat/state";
import { activateRealtimeChatSession } from "@/realtime/chat-projection-retirement";
import { useConversationStore } from "@/stores/conversation-store";

import type { FirstContextProgress } from "./onboardingProgress";

const RUNTIME_READY_WAIT_INTERVAL_MS = 500;
const RUNTIME_READY_WAIT_TIMEOUT_MS = 12_000;

interface RuntimeReadyResponse {
  success: boolean;
  data?: {
    ready: boolean;
    status: string;
    runtime_ready: boolean;
    runtime_status: string;
    startup_state?: string;
    deferred_reason?: string | null;
  };
}

export type RuntimeReadySnapshot = NonNullable<RuntimeReadyResponse["data"]>;

export interface FirstContextCompletionOptions {
  destination: "/chat";
  sessionId: string | null;
  onError: (message: string) => void;
}

export type FirstContextProgressUpdate =
  | Partial<FirstContextProgress>
  | ((currentProgress: FirstContextProgress) => FirstContextProgress);

export interface FirstContextSubmissionDependencies {
  readProgress: () => FirstContextProgress;
  updateProgress: (
    update: FirstContextProgressUpdate,
  ) => FirstContextProgress;
  finishOnboarding: (
    options: FirstContextCompletionOptions,
  ) => Promise<boolean>;
  waitForRuntimeReady: () => Promise<RuntimeReadySnapshot | null>;
  translate: (key: string) => string;
  isOwner: () => boolean;
  setError: (message: string) => void;
}

function waitFor(durationMs: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, durationMs);
  });
}

export async function waitForRuntimeReadyAfterOnboarding(): Promise<
  RuntimeReadySnapshot | null
> {
  const deadline = Date.now() + RUNTIME_READY_WAIT_TIMEOUT_MS;
  let lastSnapshot: RuntimeReadySnapshot | null = null;

  while (Date.now() <= deadline) {
    try {
      const response = await apiClient.get<RuntimeReadyResponse>("/ready");
      const snapshot = response.data?.data;
      lastSnapshot = snapshot || null;
      if (snapshot?.runtime_ready) {
        return snapshot;
      }
    } catch {
      // Runtime startup can temporarily make the readiness endpoint unavailable.
    }
    await waitFor(RUNTIME_READY_WAIT_INTERVAL_MS);
  }

  return lastSnapshot;
}

function createFirstContextSessionCreationKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `first_context_${crypto.randomUUID()}`;
  }
  return `first_context_${Date.now().toString(36)}_${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

function normalizeIdentity(value: unknown): string {
  return String(value || "").trim();
}

function showFirstContextMessageInChat(
  sessionId: string,
  turnId: string,
  message: string,
  questionId: FirstContextQuestionId,
  questionText: string,
  messageId?: string | null,
): void {
  const normalizedMessageId = normalizeIdentity(messageId);
  useConversationStore.getState().upsertMessage(sessionId, {
    id: normalizedMessageId || `${turnId}-user`,
    messageId: normalizedMessageId || undefined,
    messageKind: "user_text",
    role: "user",
    kind: "user",
    content: message,
    timestamp: Date.now(),
    turnId,
    traceAvailable: false,
    payload: {
      interaction_kind: "first_context_story",
      first_context: {
        question_id: questionId,
        question_text: questionText,
      },
    },
  });
}

function reportSessionError(
  dependencies: FirstContextSubmissionDependencies,
): void {
  dependencies.setError(
    dependencies.translate("firstContext.story.errors.sessionFailed"),
  );
}

export async function submitFirstContextStory(
  message: string,
  dependencies: FirstContextSubmissionDependencies,
): Promise<void> {
  let progress = dependencies.readProgress();

  if (!progress.submitted) {
    const runtimeSnapshot = await dependencies.waitForRuntimeReady();
    if (!dependencies.isOwner()) return;
    if (!runtimeSnapshot?.runtime_ready) {
      dependencies.setError(
        dependencies.translate("firstContext.story.errors.runtimeNotReady"),
      );
      return;
    }
  }

  let sessionId = normalizeIdentity(progress.sessionId);
  if (!sessionId) {
    let sessionCreationKey = normalizeIdentity(progress.sessionCreationKey);
    if (!sessionCreationKey) {
      sessionCreationKey = createFirstContextSessionCreationKey();
      dependencies.updateProgress({ sessionCreationKey });
    }

    let created: Awaited<ReturnType<typeof messagesApi.createNewSession>>;
    try {
      created = await messagesApi.createNewSession(
        DEFAULT_USER_ID,
        sessionCreationKey,
      );
    } catch {
      if (dependencies.isOwner()) reportSessionError(dependencies);
      return;
    }
    if (!dependencies.isOwner()) return;

    const createdSessionId = normalizeIdentity(created.session_id);
    if (!created.success || !createdSessionId) {
      reportSessionError(dependencies);
      return;
    }
    sessionId = createdSessionId;
    progress = dependencies.updateProgress({ sessionId });
    activateRealtimeChatSession(sessionId);
  }

  let turnId = normalizeIdentity(progress.turnId);
  if (!turnId) {
    turnId = createClientTurnId();
    progress = dependencies.updateProgress({ turnId });
  }

  if (!progress.submitted) {
    progress = dependencies.updateProgress({ sendUncertain: true });
    const questionText = dependencies.translate(
      `firstContext.story.questions.${progress.questionId}`,
    );
    let sendErrorMessage = dependencies.translate(
      "firstContext.story.errors.sendFailed",
    );
    let sendAccepted = false;
    let acceptedMessageId: string | null = null;

    try {
      const response = await messagesApi.sendMessage({
        user_id: DEFAULT_USER_ID,
        session_id: sessionId,
        message,
        client_turn_id: turnId,
        interaction_kind: "first_context_story",
        first_context: {
          question_id: progress.questionId,
          question_text: questionText,
        },
      });
      if (!dependencies.isOwner()) return;

      acceptedMessageId =
        normalizeIdentity(response.data?.message_id) || null;
      sendAccepted = response.success === true && acceptedMessageId !== null;
      if (response.success === true && !acceptedMessageId) {
        sendErrorMessage = dependencies.translate(
          "firstContext.story.errors.confirmationUnavailable",
        );
      } else if (!sendAccepted && !acceptedMessageId) {
        progress = dependencies.updateProgress({ sendUncertain: false });
      } else if (!sendAccepted) {
        sendErrorMessage = dependencies.translate(
          "firstContext.story.errors.confirmationUnavailable",
        );
        progress = dependencies.updateProgress({
          messageId: acceptedMessageId,
        });
      }
    } catch {
      if (!dependencies.isOwner()) return;
      sendErrorMessage = dependencies.translate(
        "firstContext.story.errors.confirmationUnavailable",
      );
    }

    if (!sendAccepted) {
      dependencies.setError(sendErrorMessage);
      return;
    }
    progress = dependencies.updateProgress({
      messageId: acceptedMessageId,
      submitted: true,
      sendUncertain: false,
    });
  }

  if (!dependencies.isOwner()) return;
  showFirstContextMessageInChat(
    sessionId,
    turnId,
    message,
    progress.questionId,
    dependencies.translate(
      `firstContext.story.questions.${progress.questionId}`,
    ),
    progress.messageId,
  );
  await dependencies.finishOnboarding({
    destination: "/chat",
    sessionId,
    onError: dependencies.setError,
  });
}

export async function continueFirstContextWithoutConfirmation(
  progress: FirstContextProgress,
  dependencies: FirstContextSubmissionDependencies,
): Promise<void> {
  const sessionId = normalizeIdentity(progress.sessionId);
  const turnId = normalizeIdentity(progress.turnId);
  const message = progress.draft.trim();
  if (sessionId && turnId && progress.messageId && message) {
    showFirstContextMessageInChat(
      sessionId,
      turnId,
      message,
      progress.questionId,
      dependencies.translate(
        `firstContext.story.questions.${progress.questionId}`,
      ),
      progress.messageId,
    );
  }
  await dependencies.finishOnboarding({
    destination: "/chat",
    sessionId: sessionId || null,
    onError: dependencies.setError,
  });
}
