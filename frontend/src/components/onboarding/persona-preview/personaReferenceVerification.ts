import type { LLMConfig } from "../../../api/modules/config";
import { personasApi } from "../../../api/modules/personas";
import type { EditablePersonaReference } from "../PersonaReferenceEditor";
import {
  errorCode,
  FAKE_IP_COMPATIBILITY_REQUIRED,
  splitConstraints,
  splitReferenceUrls,
  type FakeIpCompatibilityRetry,
  type PersonaCreationDraft,
} from "./personaPreviewModel";

interface PersonaVerificationMessages {
  compatibilityRequired: string;
  needsReview: string;
  unavailable: string;
  faithfulRequired: string;
}

export interface VerifyPersonaReferenceOptions {
  sourceDraft: PersonaCreationDraft;
  llmConfig?: LLMConfig;
  targetLanguage: "Chinese" | "English";
  isActive: () => boolean;
  publishDraft: (draft: PersonaCreationDraft) => void;
  setError: (error: string | null) => void;
  setCompatibilityRetry: (
    retry: FakeIpCompatibilityRetry | null,
  ) => void;
  messages: PersonaVerificationMessages;
}

export async function verifyPersonaReference({
  sourceDraft,
  llmConfig,
  targetLanguage,
  isActive,
  publishDraft,
  setError,
  setCompatibilityRetry,
  messages,
}: VerifyPersonaReferenceOptions): Promise<PersonaCreationDraft | null> {
  if (
    sourceDraft.reference.sourceKind === "original" ||
    sourceDraft.reference.sourceKind === "private_person_reference" ||
    sourceDraft.researchPreference === "disabled" ||
    sourceDraft.identityVerified
  ) {
    return sourceDraft;
  }
  const verifyingDraft: PersonaCreationDraft = {
    ...sourceDraft,
    phase: "verifying",
  };
  publishDraft(verifyingDraft);
  setCompatibilityRetry(null);

  try {
    const response = await personasApi.verifyReferenceIdentity({
      description: sourceDraft.description,
      reference: {
        source_kind: sourceDraft.reference.sourceKind,
        name: sourceDraft.reference.name.trim(),
        work_title: sourceDraft.reference.workTitle.trim() || null,
        version: sourceDraft.reference.version.trim() || null,
        context: sourceDraft.reference.context.trim() || null,
        user_confirmed: true,
      },
      target_language: targetLanguage,
      reference_urls: splitReferenceUrls(sourceDraft.referenceUrlsText),
      llm_override: llmConfig,
    });
    if (!isActive()) return null;
    const verification = response.data;
    if (!verification) {
      throw new Error("Reference verification returned no result");
    }
    const canonical = verification.canonical_identity;
    const reference: EditablePersonaReference = canonical
      ? {
          sourceKind: canonical.source_kind,
          name: canonical.name,
          workTitle: canonical.work_title || "",
          version: canonical.version || "",
          context: canonical.context || "",
        }
      : sourceDraft.reference;
    if (
      verification.requires_confirmation ||
      verification.status === "ambiguous"
    ) {
      const identities = [
        ...(canonical ? [canonical] : []),
        ...verification.alternatives,
      ];
      const candidates = identities.map((identity, index) => ({
        candidate_id: `verified-candidate-${index + 1}`,
        source_kind: identity.source_kind,
        name: identity.name,
        work_title: identity.work_title || null,
        version: identity.version || null,
        context: identity.context || null,
        confidence: verification.confidence,
      }));
      publishDraft({
        ...sourceDraft,
        phase: "reviewing",
        reference,
        referenceConfirmed: false,
        resolution: {
          status: candidates.length > 1 ? "ambiguous" : "resolved",
          candidates,
          selected_candidate_id: candidates[0]?.candidate_id || null,
          confidence: verification.confidence,
          requires_confirmation: true,
          explicit_constraints: splitConstraints(
            sourceDraft.constraintsText,
          ),
        },
        identityVerified: verification.status === "verified",
        verificationFingerprint:
          verification.reference_fingerprint || undefined,
        verificationSources: verification.sources,
        verificationWarning: verification.warning || undefined,
      });
      setError(verification.warning || messages.needsReview);
      return null;
    }
    const verifiedDraft: PersonaCreationDraft = {
      ...sourceDraft,
      phase: "reviewing",
      reference,
      identityVerified: verification.status === "verified",
      verificationFingerprint:
        verification.reference_fingerprint || undefined,
      verificationSources: verification.sources,
      verificationWarning: verification.warning || undefined,
    };
    publishDraft(verifiedDraft);
    return verifiedDraft;
  } catch (error) {
    if (!isActive()) return null;
    if (errorCode(error) === FAKE_IP_COMPATIBILITY_REQUIRED) {
      const failedDraft: PersonaCreationDraft = {
        ...sourceDraft,
        phase: "failed",
        generationRequestId: undefined,
        generationJobId: undefined,
      };
      publishDraft(failedDraft);
      setError(messages.compatibilityRequired);
      setCompatibilityRetry({
        kind: "verification",
        draft: failedDraft,
      });
      return null;
    }
    const warning = (error as Error).message || messages.unavailable;
    const fallbackDraft: PersonaCreationDraft = {
      ...sourceDraft,
      phase:
        sourceDraft.fidelityLevel === "faithful"
          ? "failed"
          : "reviewing",
      identityVerified: false,
      verificationWarning: warning,
    };
    publishDraft(fallbackDraft);
    if (sourceDraft.fidelityLevel === "faithful") {
      setError(messages.faithfulRequired);
      return null;
    }
    return fallbackDraft;
  }
}
