import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from "react";
import { useTranslation } from "react-i18next";
import type { LLMConfig } from "../../../api/modules/config";
import {
  personasApi,
  type PersonaGenerationIntent,
  type PersonaIntentResolution,
} from "../../../api/modules/personas";
import {
  applyIntentResolution,
  buildGenerationIntent,
  createStableId,
  type PersonaCreationDraft,
} from "./personaPreviewModel";
import {
  createPersonaGenerationState,
  personaGenerationReducer,
} from "./personaGenerationState";
import { runPersonaGenerationJob } from "./personaGenerationJob";
import { retryPersonaAfterEnablingCompatibility } from "./personaCompatibilityRetry";
import { verifyPersonaReference } from "./personaReferenceVerification";
import { usePersonaCreationDraftEditor } from "./usePersonaCreationDraftEditor";
import type { PersonaDraftRegistry } from "./usePersonaDraftRegistry";

interface UsePersonaGenerationControllerOptions {
  disabled: boolean;
  llmConfig?: LLMConfig;
  initialCreationDraft?: PersonaCreationDraft | null;
  onCreationDraftChange?: (draft: PersonaCreationDraft | null) => void;
  onActiveSeedChange: (seedSlug: string | null) => void;
  onGenerated: () => void;
  onEditRequested: () => void;
  clearTranscript: (seedSlug: string) => void;
  registry: PersonaDraftRegistry;
}

function targetLanguage(language: string): "Chinese" | "English" {
  return language.startsWith("zh") ? "Chinese" : "English";
}

export function usePersonaGenerationController({
  disabled,
  llmConfig,
  initialCreationDraft,
  onCreationDraftChange,
  onActiveSeedChange,
  onGenerated,
  onEditRequested,
  clearTranscript,
  registry,
}: UsePersonaGenerationControllerOptions) {
  const { t, i18n } = useTranslation("onboarding");
  const [state, dispatch] = useReducer(
    personaGenerationReducer,
    createPersonaGenerationState(initialCreationDraft),
  );
  const creationDraftRef = useRef<PersonaCreationDraft | null>(
    initialCreationDraft ?? null,
  );
  const mountedRef = useRef(true);
  const activeOperationRef = useRef(0);
  const submissionOwnerRef = useRef<number | null>(null);
  const restoredCreationDraftHandledRef = useRef(false);
  const restoredGenerationAttemptRef = useRef<{
    key: string;
    operationId: number;
  } | null>(null);
  const restoredGenerationDraftRef = useRef<PersonaCreationDraft | null>(
    initialCreationDraft?.phase === "generating"
      ? initialCreationDraft
      : null,
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeOperationRef.current += 1;
      submissionOwnerRef.current = null;
    };
  }, []);

  const isActiveOperation = useCallback(
    (operationId: number) =>
      mountedRef.current && activeOperationRef.current === operationId,
    [],
  );

  const beginOperation = useCallback(() => {
    activeOperationRef.current += 1;
    return activeOperationRef.current;
  }, []);

  const supersedeOperation = useCallback(() => {
    const operationId = beginOperation();
    submissionOwnerRef.current = null;
    return operationId;
  }, [beginOperation]);

  const publishCreationDraft = useCallback(
    (next: PersonaCreationDraft | null, operationId?: number) => {
      if (
        !mountedRef.current ||
        (operationId !== undefined && !isActiveOperation(operationId))
      ) {
        return;
      }
      creationDraftRef.current = next;
      dispatch({ type: "publishDraft", draft: next });
      onCreationDraftChange?.(next);
    },
    [isActiveOperation, onCreationDraftChange],
  );
  const resetFeedback = useCallback(
    (descriptionExpanded?: boolean) =>
      dispatch({
        type: "resetFeedback",
        descriptionExpanded,
      }),
    [],
  );
  const editor = usePersonaCreationDraftEditor({
    creationDraftRef,
    supersedeOperation,
    publishDraft: publishCreationDraft,
    resetFeedback,
    onEditRequested,
  });

  useEffect(() => {
    if (restoredCreationDraftHandledRef.current) return;
    restoredCreationDraftHandledRef.current = true;
    const restored = creationDraftRef.current;
    if (!restored) return;
    if (restored.phase === "resolving" || restored.phase === "verifying") {
      publishCreationDraft({ ...restored, phase: "editing" });
      return;
    }
    if (
      restored.phase === "generating" &&
      !restored.generationJobId &&
      !restored.generationRequestId
    ) {
      publishCreationDraft({
        ...restored,
        phase: "failed",
      });
    }
  }, [publishCreationDraft]);

  const runGeneration = useCallback(
    async (
      sourceDraft: PersonaCreationDraft,
      intent: PersonaGenerationIntent,
      operationId: number,
      existingJobId?: string,
    ) => {
      await runPersonaGenerationJob({
        sourceDraft,
        intent,
        existingJobId,
        disabled,
        llmConfig,
        targetLanguage: targetLanguage(i18n.language || ""),
        isActive: () => isActiveOperation(operationId),
        publishDraft: (draft) =>
          publishCreationDraft(draft, operationId),
        setStages: (stages) =>
          dispatch({ type: "setStages", stages }),
        setError: (error) =>
          dispatch({ type: "setError", error }),
        setCompatibilityRetry: (retry) =>
          dispatch({ type: "setCompatibilityRetry", retry }),
        clearTranscript,
        registry,
        onActiveSeedChange,
        onGenerated,
        messages: {
          compatibilityRequired: t(
            "settings.fakeIpCompatibilityPromptDesc",
            { ns: "app" },
          ),
          timedOut: t("personaPreview.generationTimedOut"),
          unknownFailure: t(
            "personaPreview.generationFailedUnknown",
          ),
        },
      });
    },
    [
      clearTranscript,
      disabled,
      i18n.language,
      isActiveOperation,
      llmConfig,
      onActiveSeedChange,
      onGenerated,
      publishCreationDraft,
      registry,
      t,
    ],
  );

  const verifyDraftReference = useCallback(
    async (
      sourceDraft: PersonaCreationDraft,
      operationId: number,
    ): Promise<PersonaCreationDraft | null> =>
      verifyPersonaReference({
        sourceDraft,
        llmConfig,
        targetLanguage: targetLanguage(i18n.language || ""),
        isActive: () => isActiveOperation(operationId),
        publishDraft: (draft) =>
          publishCreationDraft(draft, operationId),
        setError: (error) =>
          dispatch({ type: "setError", error }),
        setCompatibilityRetry: (retry) =>
          dispatch({ type: "setCompatibilityRetry", retry }),
        messages: {
          compatibilityRequired: t(
            "settings.fakeIpCompatibilityPromptDesc",
            { ns: "app" },
          ),
          needsReview: t(
            "personaPreview.reference.verificationNeedsReview",
          ),
          unavailable: t(
            "personaPreview.reference.verificationUnavailable",
          ),
          faithfulRequired: t(
            "personaPreview.reference.faithfulVerificationRequired",
          ),
        },
      }),
    [
      i18n.language,
      isActiveOperation,
      llmConfig,
      publishCreationDraft,
      t,
    ],
  );
  const handleResolveOrGenerate = useCallback(async () => {
    const sourceDraft = creationDraftRef.current;
    const description = sourceDraft?.description.trim() || "";
    const isGenerating =
      sourceDraft?.phase === "resolving" ||
      sourceDraft?.phase === "verifying" ||
      sourceDraft?.phase === "generating";
    if (
      !sourceDraft ||
      disabled ||
      !description ||
      isGenerating ||
      submissionOwnerRef.current !== null
    ) {
      return;
    }

    const operationId = beginOperation();
    submissionOwnerRef.current = operationId;
    try {
      if (
        sourceDraft.phase === "reviewing" ||
        sourceDraft.phase === "failed"
      ) {
        if (!sourceDraft.referenceConfirmed) return;
        if (
          sourceDraft.reference.sourceKind !== "original" &&
          !sourceDraft.reference.name.trim()
        ) {
          return;
        }
        const retryDraft: PersonaCreationDraft = {
          ...sourceDraft,
          generationRequestId:
            sourceDraft.generationRequestId || createStableId(),
          generationJobId: sourceDraft.generationJobId,
        };
        const verifiedDraft = await verifyDraftReference(
          retryDraft,
          operationId,
        );
        if (!verifiedDraft) return;
        await runGeneration(
          verifiedDraft,
          buildGenerationIntent(verifiedDraft),
          operationId,
          retryDraft.generationJobId,
        );
        return;
      }

      const resolvingDraft: PersonaCreationDraft = {
        ...sourceDraft,
        phase: "resolving",
      };
      publishCreationDraft(resolvingDraft, operationId);
      dispatch({ type: "setError", error: null });
      try {
        const response = await personasApi.resolveGenerationIntent({
          description,
          target_language: targetLanguage(i18n.language || ""),
          llm_override: llmConfig,
        });
        if (!isActiveOperation(operationId)) return;
        if (!response.data) {
          throw new Error("Persona intent resolution returned no result");
        }
        const reviewedDraft = applyIntentResolution(
          resolvingDraft,
          response.data,
        );
        if (response.data.status === "original") {
          await runGeneration(
            reviewedDraft,
            buildGenerationIntent(reviewedDraft),
            operationId,
          );
          return;
        }
        dispatch({ type: "setDescriptionExpanded", value: false });
        publishCreationDraft(reviewedDraft, operationId);
      } catch {
        if (!isActiveOperation(operationId)) return;
        const fallbackResolution: PersonaIntentResolution = {
          status: "unknown",
          candidates: [],
          selected_candidate_id: null,
          confidence: 0,
          requires_confirmation: true,
          explicit_constraints: [],
        };
        dispatch({ type: "setDescriptionExpanded", value: false });
        publishCreationDraft(
          applyIntentResolution(resolvingDraft, fallbackResolution),
          operationId,
        );
        dispatch({
          type: "setError",
          error: t("personaPreview.reference.resolveFailed"),
        });
      }
    } finally {
      if (submissionOwnerRef.current === operationId) {
        submissionOwnerRef.current = null;
      }
    }
  }, [
    beginOperation,
    disabled,
    i18n.language,
    isActiveOperation,
    llmConfig,
    publishCreationDraft,
    runGeneration,
    t,
    verifyDraftReference,
  ]);

  const enableCompatibilityAndRetry = useCallback(async () => {
    const pendingRetry = state.compatibilityRetry;
    if (!pendingRetry || state.enablingCompatibility) return;
    const operationId = beginOperation();
    dispatch({ type: "setEnablingCompatibility", value: true });
    dispatch({ type: "setError", error: null });
    try {
      await retryPersonaAfterEnablingCompatibility({
        pendingRetry,
        isActive: () => isActiveOperation(operationId),
        verifyDraft: (draft) =>
          verifyDraftReference(draft, operationId),
        runGeneration: (draft, intent) =>
          runGeneration(draft, intent, operationId),
        clearRetry: () =>
          dispatch({ type: "setCompatibilityRetry", retry: null }),
      });
    } catch (error) {
      if (isActiveOperation(operationId)) {
        const message =
          error instanceof Error ? error.message : String(error);
        dispatch({
          type: "setError",
          error: t("settings.fakeIpCompatibilityEnableFailed", {
            ns: "app",
            message,
          }),
        });
      }
    } finally {
      if (isActiveOperation(operationId)) {
        dispatch({ type: "setEnablingCompatibility", value: false });
      }
    }
  }, [
    beginOperation,
    isActiveOperation,
    runGeneration,
    state.compatibilityRetry,
    state.enablingCompatibility,
    t,
    verifyDraftReference,
  ]);
  const runGenerationRef = useRef(runGeneration);
  runGenerationRef.current = runGeneration;

  useEffect(() => {
    const restored = restoredGenerationDraftRef.current;
    const jobId = restored?.generationJobId;
    const requestId = restored?.generationRequestId;
    const resumeKey = jobId || (requestId ? `request:${requestId}` : null);
    if (
      !restored ||
      restored.phase !== "generating" ||
      !resumeKey
    ) {
      return;
    }
    const previousAttempt = restoredGenerationAttemptRef.current;
    if (
      previousAttempt?.key === resumeKey &&
      isActiveOperation(previousAttempt.operationId)
    ) {
      return;
    }
    const operationId = beginOperation();
    restoredGenerationAttemptRef.current = { key: resumeKey, operationId };
    void Promise.resolve().then(() => {
      if (!isActiveOperation(operationId)) return;
      return runGenerationRef.current(
        restored,
        buildGenerationIntent(restored),
        operationId,
        jobId,
      );
    });
  }, [beginOperation, isActiveOperation]);

  const creationDraft = state.creationDraft;
  const generating =
    creationDraft?.phase === "resolving" ||
    creationDraft?.phase === "verifying" ||
    creationDraft?.phase === "generating";
  const creationNeedsConfirmation =
    creationDraft?.phase === "reviewing" ||
    creationDraft?.phase === "failed";

  return {
    creationDraft,
    creationDraftRef,
    descriptionExpanded: state.descriptionExpanded,
    stages: state.stages,
    error: state.error,
    compatibilityRetry: state.compatibilityRetry,
    enablingCompatibility: state.enablingCompatibility,
    generating,
    creationNeedsConfirmation,
    publishCreationDraft: editor.updateDraft,
    setDescriptionExpanded: (value: boolean) =>
      dispatch({ type: "setDescriptionExpanded", value }),
    startNewCreation: editor.startNewCreation,
    cancelCreation: editor.cancelCreation,
    editDescription: editor.editDescription,
    updateReference: editor.updateReference,
    updateFidelityLevel: editor.updateFidelityLevel,
    updateConstraintsText: editor.updateConstraintsText,
    updateResearchPreference: editor.updateResearchPreference,
    updateReferenceUrlsText: editor.updateReferenceUrlsText,
    handleResolveOrGenerate,
    enableCompatibilityAndRetry,
    editCustomReference: editor.editCustomReference,
  };
}

export type PersonaGenerationController = ReturnType<
  typeof usePersonaGenerationController
>;
