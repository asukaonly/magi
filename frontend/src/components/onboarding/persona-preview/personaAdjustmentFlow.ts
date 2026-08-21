import { streamChatPreview } from "../../../api/modules/chatPreview";
import type { LLMConfig } from "../../../api/modules/config";
import { personasApi } from "../../../api/modules/personas";
import {
  buildPreviewHistory,
  createStableId,
  type CustomPersonaDraft,
  type TranscriptMap,
} from "./personaPreviewModel";
import type { PersonaDraftRegistry } from "./usePersonaDraftRegistry";

interface RunPersonaAdjustmentOptions {
  instruction: string;
  customDraft: CustomPersonaDraft;
  seedSlug: string;
  llmConfig?: LLMConfig;
  locale?: string;
  targetLanguage: "Chinese" | "English";
  registry: PersonaDraftRegistry;
  getTranscripts: () => TranscriptMap;
  updateTranscripts: (
    update: (current: TranscriptMap) => TranscriptMap,
  ) => void;
  updateStreamContent: (
    seedSlug: string,
    streamGroupId: string,
    content: string,
  ) => void;
  onInstructionConsumed: () => void;
  isActive: () => boolean;
}

export async function runPersonaAdjustment({
  instruction,
  customDraft,
  seedSlug,
  llmConfig,
  locale,
  targetLanguage,
  registry,
  getTranscripts,
  updateTranscripts,
  updateStreamContent,
  onInstructionConsumed,
  isActive,
}: RunPersonaAdjustmentOptions): Promise<void> {
  const response = await personasApi.adjust({
    current_config: customDraft.config,
    instruction,
    scope: "auto",
    target_language: targetLanguage,
    intent: customDraft.intent,
    llm_override: llmConfig,
  });
  if (!isActive()) return;
  if (!response.data) {
    throw new Error("Persona adjustment returned no config");
  }
  registry.upsert({
    ...customDraft,
    name: response.data.name || customDraft.name,
    description: response.data.description || customDraft.description,
    config: response.data,
    revision: (customDraft.revision || 1) + 1,
  });
  onInstructionConsumed();

  const currentTurns = getTranscripts()[seedSlug] ?? [];
  let lastUserIndex = currentTurns.length - 1;
  while (
    lastUserIndex >= 0 &&
    currentTurns[lastUserIndex].role !== "user"
  ) {
    lastUserIndex -= 1;
  }
  if (lastUserIndex < 0) return;

  const lastUser = currentTurns[lastUserIndex];
  const history = buildPreviewHistory(
    currentTurns.slice(0, lastUserIndex),
  );
  const streamGroupId = createStableId();
  updateTranscripts((current) => {
    const list = current[seedSlug] ?? [];
    return {
      ...current,
      [seedSlug]: [
        ...list.map((turn, index) =>
          index > lastUserIndex && turn.role === "assistant"
            ? { ...turn, superseded: true }
            : turn,
        ),
        {
          id: createStableId(),
          kind: "revision-divider",
          role: "assistant",
          content: "",
        },
        {
          id: createStableId(),
          role: "assistant",
          content: "",
          streamGroupId,
        },
      ],
    };
  });

  let responseText = "";
  try {
    for await (const chunk of streamChatPreview({
      persona_override: response.data,
      history,
      message: { role: "user", content: lastUser.content },
      llm_override: llmConfig,
      locale,
    })) {
      if (!isActive()) return;
      responseText += chunk;
      updateStreamContent(seedSlug, streamGroupId, responseText);
    }
  } catch (error) {
    if (isActive()) {
      const prefix = responseText ? `${responseText}\n` : "";
      updateStreamContent(
        seedSlug,
        streamGroupId,
        `${prefix}[error: ${(error as Error).message}]`,
      );
    }
  }
}
