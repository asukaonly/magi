import type { LLMConfig } from "../../../api/modules/config";
import {
  personasApi,
  type PersonaGenerationIntent,
  type PersonaGenerationStage,
} from "../../../api/modules/personas";
import {
  createStableId,
  errorCode,
  FAKE_IP_COMPATIBILITY_REQUIRED,
  type CustomPersonaDraft,
  type FakeIpCompatibilityRetry,
  type PersonaCreationDraft,
} from "./personaPreviewModel";
import type { PersonaDraftRegistry } from "./usePersonaDraftRegistry";

interface PersonaGenerationMessages {
  compatibilityRequired: string;
  timedOut: string;
  unknownFailure: string;
}

function generationFailureMetadata(error: unknown): {
  terminal: boolean;
  jobId?: string;
} {
  if (!error || typeof error !== "object") {
    return { terminal: false };
  }
  const terminal =
    "terminal" in error && (error as { terminal?: unknown }).terminal === true;
  const jobId =
    "generationJobId" in error
      ? (error as { generationJobId?: unknown }).generationJobId
      : undefined;
  return {
    terminal,
    jobId: typeof jobId === "string" ? jobId : undefined,
  };
}

export interface RunPersonaGenerationJobOptions {
  sourceDraft: PersonaCreationDraft;
  intent: PersonaGenerationIntent;
  existingJobId?: string;
  disabled: boolean;
  llmConfig?: LLMConfig;
  targetLanguage: "Chinese" | "English";
  isActive: () => boolean;
  publishDraft: (draft: PersonaCreationDraft | null) => void;
  setStages: (stages: PersonaGenerationStage[]) => void;
  setError: (error: string | null) => void;
  setCompatibilityRetry: (
    retry: FakeIpCompatibilityRetry | null,
  ) => void;
  clearTranscript: (seedSlug: string) => void;
  registry: PersonaDraftRegistry;
  onActiveSeedChange: (seedSlug: string) => void;
  onGenerated: () => void;
  messages: PersonaGenerationMessages;
}

export async function runPersonaGenerationJob({
  sourceDraft,
  intent,
  existingJobId,
  disabled,
  llmConfig,
  targetLanguage,
  isActive,
  publishDraft,
  setStages,
  setError,
  setCompatibilityRetry,
  clearTranscript,
  registry,
  onActiveSeedChange,
  onGenerated,
  messages,
}: RunPersonaGenerationJobOptions): Promise<void> {
  const description = sourceDraft.description.trim();
  if (disabled || !description || !isActive()) return;

  let workingDraft: PersonaCreationDraft = {
    ...sourceDraft,
    phase: "generating",
    generationRequestId: existingJobId
      ? sourceDraft.generationRequestId
      : sourceDraft.generationRequestId || createStableId(),
    generationJobId: existingJobId || sourceDraft.generationJobId,
  };
  publishDraft(workingDraft);
  setError(null);
  setCompatibilityRetry(null);
  setStages([]);

  try {
    const response = await personasApi.generateWithProgress(
      {
        description,
        target_language: targetLanguage,
        llm_override: llmConfig,
        draft_id: workingDraft.draftId,
        request_id: workingDraft.generationRequestId,
        intent,
      },
      (snapshot) => {
        if (!isActive()) return;
        setStages(snapshot.stages ?? []);
        if (
          snapshot.job_id &&
          workingDraft.generationJobId !== snapshot.job_id
        ) {
          workingDraft = {
            ...workingDraft,
            generationJobId: snapshot.job_id,
          };
          publishDraft(workingDraft);
        }
      },
      existingJobId,
    );
    if (!isActive()) return;
    const config = response.data;
    if (!config) {
      throw new Error("generation returned no config");
    }
    const slug =
      workingDraft.editingPersonaSlug ||
      `onboarding-custom-${workingDraft.personaId}`;
    const generatedDraft: CustomPersonaDraft = {
      personaId: workingDraft.personaId,
      slug,
      name: config.name || description,
      description: config.description || description,
      config,
      originalDescription: description,
      intent,
      referenceDossier: response.reference_dossier,
      revision: workingDraft.revision,
    };
    if (workingDraft.editingPersonaSlug) {
      clearTranscript(slug);
    }
    registry.upsert(generatedDraft);
    onActiveSeedChange(slug);
    publishDraft(null);
    onGenerated();
  } catch (error) {
    if (!isActive()) return;
    const message = (error as Error).message;
    const failure = generationFailureMetadata(error);
    const failedDraft: PersonaCreationDraft = {
      ...workingDraft,
      phase: "failed",
      generationRequestId: failure.terminal
        ? undefined
        : workingDraft.generationRequestId,
      generationJobId: failure.terminal
        ? undefined
        : failure.jobId || workingDraft.generationJobId,
    };
    if (errorCode(error) === FAKE_IP_COMPATIBILITY_REQUIRED) {
      setError(messages.compatibilityRequired);
      setCompatibilityRetry({
        kind: "generation",
        draft: failedDraft,
        intent,
      });
    } else {
      setError(
        message === "Personality generation timed out"
          ? messages.timedOut
          : message || messages.unknownFailure,
      );
    }
    publishDraft(failedDraft);
  }
}
