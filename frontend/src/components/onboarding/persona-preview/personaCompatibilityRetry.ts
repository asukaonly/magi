import { toolsApi } from "../../../api/modules/tools";
import type {
  FakeIpCompatibilityRetry,
  PersonaCreationDraft,
} from "./personaPreviewModel";
import { buildGenerationIntent } from "./personaPreviewModel";

interface RetryPersonaCompatibilityOptions {
  pendingRetry: FakeIpCompatibilityRetry;
  isActive: () => boolean;
  verifyDraft: (
    draft: PersonaCreationDraft,
  ) => Promise<PersonaCreationDraft | null>;
  runGeneration: (
    draft: PersonaCreationDraft,
    intent: Extract<
      FakeIpCompatibilityRetry,
      { kind: "generation" }
    >["intent"],
  ) => Promise<void>;
  clearRetry: () => void;
}

export async function retryPersonaAfterEnablingCompatibility({
  pendingRetry,
  isActive,
  verifyDraft,
  runGeneration,
  clearRetry,
}: RetryPersonaCompatibilityOptions): Promise<void> {
  if (!isActive()) return;
  await toolsApi.updateToolConfig("web-fetch", {
    updates: { allow_rfc2544_benchmark_range: true },
  });
  if (!isActive()) return;
  clearRetry();

  if (pendingRetry.kind === "verification") {
    const verifiedDraft = await verifyDraft(pendingRetry.draft);
    if (verifiedDraft) {
      await runGeneration(
        verifiedDraft,
        buildGenerationIntent(verifiedDraft),
      );
    }
    return;
  }
  await runGeneration(pendingRetry.draft, pendingRetry.intent);
}
