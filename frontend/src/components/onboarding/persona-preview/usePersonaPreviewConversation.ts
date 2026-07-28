import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  streamChatPreview,
  type PreviewTurn,
} from "../../../api/modules/chatPreview";
import type { LLMConfig } from "../../../api/modules/config";
import {
  collapsePreviewHistory,
  MAX_USER_TURNS_PER_PERSONA,
  splitPreviewReply,
  type PreviewDisplayTurn,
  type RailItem,
  type TranscriptMap,
} from "./personaPreviewModel";
import { runPersonaAdjustment } from "./personaAdjustmentFlow";
import type { PersonaDraftRegistry } from "./usePersonaDraftRegistry";

interface ConversationState {
  transcripts: TranscriptMap;
  draft: string;
  busy: boolean;
  adjustmentDraft: string;
  adjusting: boolean;
  adjustmentError: string | null;
}

type ConversationAction =
  | { type: "setDraft"; value: string }
  | { type: "setBusy"; value: boolean }
  | { type: "setAdjustmentDraft"; value: string }
  | { type: "setAdjusting"; value: boolean }
  | { type: "setAdjustmentError"; value: string | null }
  | {
      type: "updateTranscripts";
      update: (current: TranscriptMap) => TranscriptMap;
    };

const INITIAL_STATE: ConversationState = {
  transcripts: {},
  draft: "",
  busy: false,
  adjustmentDraft: "",
  adjusting: false,
  adjustmentError: null,
};

function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  switch (action.type) {
    case "setDraft":
      return { ...state, draft: action.value };
    case "setBusy":
      return { ...state, busy: action.value };
    case "setAdjustmentDraft":
      return { ...state, adjustmentDraft: action.value };
    case "setAdjusting":
      return { ...state, adjusting: action.value };
    case "setAdjustmentError":
      return { ...state, adjustmentError: action.value };
    case "updateTranscripts":
      return {
        ...state,
        transcripts: action.update(state.transcripts),
      };
  }
}

interface UsePersonaPreviewConversationOptions {
  activeSeed: string | null;
  activeItem?: RailItem;
  disabled: boolean;
  locale?: string;
  llmConfig?: LLMConfig;
  registry: PersonaDraftRegistry;
}

export function usePersonaPreviewConversation({
  activeSeed,
  activeItem,
  disabled,
  locale,
  llmConfig,
  registry,
}: UsePersonaPreviewConversationOptions) {
  const { t, i18n } = useTranslation("onboarding");
  const [state, dispatch] = useReducer(conversationReducer, INITIAL_STATE);
  const stateRef = useRef(state);
  stateRef.current = state;
  const mountedRef = useRef(true);
  const sendInFlightRef = useRef(false);
  const adjustmentInFlightRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const updateTranscripts = useCallback(
    (update: (current: TranscriptMap) => TranscriptMap) => {
      if (!mountedRef.current) return;
      dispatch({ type: "updateTranscripts", update });
    },
    [],
  );

  const appendTurn = useCallback(
    (seedSlug: string, turn: PreviewDisplayTurn) => {
      updateTranscripts((current) => {
        const list = current[seedSlug] ?? [];
        return { ...current, [seedSlug]: [...list, turn] };
      });
    },
    [updateTranscripts],
  );

  const updateAssistantStreamContent = useCallback(
    (seedSlug: string, content: string) => {
      updateTranscripts((current) => {
        const list = current[seedSlug] ?? [];
        let currentUserIndex = list.length - 1;
        while (
          currentUserIndex >= 0 &&
          list[currentUserIndex].role !== "user"
        ) {
          currentUserIndex -= 1;
        }
        if (
          currentUserIndex < 0 ||
          currentUserIndex === list.length - 1
        ) {
          return current;
        }
        const segments = splitPreviewReply(content);
        const assistantTurns = (
          segments.length > 0 ? segments : [content]
        ).map<PreviewTurn>((segment) => ({
          role: "assistant",
          content: segment,
        }));
        return {
          ...current,
          [seedSlug]: [
            ...list.slice(0, currentUserIndex + 1),
            ...assistantTurns,
          ],
        };
      });
    },
    [updateTranscripts],
  );

  const updateAdjustmentStreamContent = useCallback(
    (seedSlug: string, streamGroupId: string, content: string) => {
      updateTranscripts((current) => {
        const list = current[seedSlug] ?? [];
        const firstIndex = list.findIndex(
          (turn) => turn.streamGroupId === streamGroupId,
        );
        if (firstIndex < 0) return current;
        const withoutGroup = list.filter(
          (turn) => turn.streamGroupId !== streamGroupId,
        );
        const segments = splitPreviewReply(content);
        const assistantTurns = (
          segments.length > 0 ? segments : [content]
        ).map<PreviewDisplayTurn>((segment) => ({
          role: "assistant",
          content: segment,
          streamGroupId,
        }));
        return {
          ...current,
          [seedSlug]: [
            ...withoutGroup.slice(0, firstIndex),
            ...assistantTurns,
            ...withoutGroup.slice(firstIndex),
          ],
        };
      });
    },
    [updateTranscripts],
  );

  const activeTranscript = useMemo(
    () => (activeSeed ? state.transcripts[activeSeed] ?? [] : []),
    [activeSeed, state.transcripts],
  );
  const userTurnCount = activeTranscript.filter(
    (turn) => turn.role === "user",
  ).length;
  const capReached = userTurnCount >= MAX_USER_TURNS_PER_PERSONA;

  const send = useCallback(async () => {
    const currentState = stateRef.current;
    const message = currentState.draft.trim();
    if (
      disabled ||
      !activeSeed ||
      !message ||
      sendInFlightRef.current ||
      adjustmentInFlightRef.current ||
      capReached
    ) {
      return;
    }

    sendInFlightRef.current = true;
    const userTurn: PreviewTurn = { role: "user", content: message };
    const seed = activeSeed;
    const snapshotHistory = collapsePreviewHistory(
      currentState.transcripts[seed] ?? [],
    );
    const personaOverride =
      activeItem?.isCustom && activeItem.config
        ? activeItem.config
        : undefined;
    appendTurn(seed, userTurn);
    appendTurn(seed, { role: "assistant", content: "" });
    dispatch({ type: "setDraft", value: "" });
    dispatch({ type: "setBusy", value: true });

    let responseText = "";
    try {
      for await (const chunk of streamChatPreview({
        seed_slug: personaOverride ? undefined : seed,
        locale,
        persona_override: personaOverride,
        history: snapshotHistory,
        message: userTurn,
        llm_override: llmConfig,
      })) {
        if (!mountedRef.current) return;
        responseText += chunk;
        updateAssistantStreamContent(seed, responseText);
      }
    } catch (error) {
      if (mountedRef.current) {
        const prefix = responseText ? `${responseText}\n` : "";
        updateAssistantStreamContent(
          seed,
          `${prefix}[error: ${(error as Error).message}]`,
        );
      }
    } finally {
      sendInFlightRef.current = false;
      if (mountedRef.current) {
        dispatch({ type: "setBusy", value: false });
      }
    }
  }, [
    activeItem,
    activeSeed,
    appendTurn,
    capReached,
    disabled,
    llmConfig,
    locale,
    updateAssistantStreamContent,
  ]);

  const adjustActivePersona = useCallback(async () => {
    const currentState = stateRef.current;
    const instruction = currentState.adjustmentDraft.trim();
    const customDraft = activeItem?.customDraft;
    const seed = activeSeed;
    if (
      !instruction ||
      !customDraft ||
      !seed ||
      disabled ||
      sendInFlightRef.current ||
      adjustmentInFlightRef.current
    ) {
      return;
    }

    adjustmentInFlightRef.current = true;
    dispatch({ type: "setAdjusting", value: true });
    dispatch({ type: "setAdjustmentError", value: null });
    try {
      await runPersonaAdjustment({
        instruction,
        customDraft,
        seedSlug: seed,
        llmConfig,
        locale,
        targetLanguage: (i18n.language || "").startsWith("zh")
          ? "Chinese"
          : "English",
        registry,
        getTranscripts: () => stateRef.current.transcripts,
        updateTranscripts,
        updateStreamContent: updateAdjustmentStreamContent,
        onInstructionConsumed: () =>
          dispatch({ type: "setAdjustmentDraft", value: "" }),
        isActive: () => mountedRef.current,
      });
    } catch (error) {
      if (mountedRef.current) {
        dispatch({
          type: "setAdjustmentError",
          value:
            (error as Error).message ||
            t("personaPreview.adjustment.failed"),
        });
      }
    } finally {
      adjustmentInFlightRef.current = false;
      if (mountedRef.current) {
        dispatch({ type: "setAdjusting", value: false });
      }
    }
  }, [
    activeItem,
    activeSeed,
    disabled,
    i18n.language,
    llmConfig,
    locale,
    registry,
    t,
    updateAdjustmentStreamContent,
    updateTranscripts,
  ]);
  const clearTranscript = useCallback(
    (seedSlug: string) => {
      updateTranscripts((current) => {
        if (!(seedSlug in current)) return current;
        const next = { ...current };
        delete next[seedSlug];
        return next;
      });
    },
    [updateTranscripts],
  );

  return {
    transcripts: state.transcripts,
    activeTranscript,
    draft: state.draft,
    busy: state.busy,
    adjustmentDraft: state.adjustmentDraft,
    adjusting: state.adjusting,
    adjustmentError: state.adjustmentError,
    capReached,
    setDraft: (value: string) => dispatch({ type: "setDraft", value }),
    setAdjustmentDraft: (value: string) =>
      dispatch({ type: "setAdjustmentDraft", value }),
    send,
    adjustActivePersona,
    clearTranscript,
  };
}

export type PersonaPreviewConversationController = ReturnType<
  typeof usePersonaPreviewConversation
>;
