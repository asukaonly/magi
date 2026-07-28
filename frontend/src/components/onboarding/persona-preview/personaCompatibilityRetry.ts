import { configApi } from "../../../api/modules/config";
import type {
  FakeIpCompatibilityRetry,
  PersonaCreationDraft,
} from "./personaPreviewModel";
import { buildGenerationIntent } from "./personaPreviewModel";

interface RetryPersonaCompatibilityOptions {
  pendingRetry: FakeIpCompatibilityRetry;
  isActive: () => boolean;
  unknownFailureMessage: string;
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
  unknownFailureMessage,
  verifyDraft,
  runGeneration,
  clearRetry,
}: RetryPersonaCompatibilityOptions): Promise<void> {
  const response = await configApi.get();
  if (!isActive()) return;
  if (!response.data) {
    throw new Error(unknownFailureMessage);
  }
  const nextConfig = structuredClone(response.data);
  nextConfig.tools.builtIn.webFetch.allowRfc2544BenchmarkRange = true;
  await configApi.update(nextConfig);
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
