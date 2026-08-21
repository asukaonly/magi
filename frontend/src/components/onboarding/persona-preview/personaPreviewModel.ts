import type { PreviewTurn } from "../../../api/modules/chatPreview";
import type {
  PersonaFidelityLevel,
  PersonaGenerationIntent,
  PersonaIntentResolution,
  PersonaReferenceDossier,
  PersonaReferenceKind,
  PersonaReferenceSource,
  PersonaResearchPreference,
  PersonalityConfig,
  SeedPreview,
} from "../../../api/modules/personas";
import {
  candidateToEditableReference,
  defaultFidelityLevel,
  type EditablePersonaReference,
} from "../PersonaReferenceEditor";

export const PREVIEW_GUIDANCE_USER_TURN_COUNT = 5;
export const PREVIEW_HISTORY_TURN_LIMIT = 20;
export const PREVIEW_SEGMENT_SENTINEL = "‖";
export const FAKE_IP_COMPATIBILITY_REQUIRED = "FAKE_IP_COMPATIBILITY_REQUIRED";

export interface CustomPersonaDraft {
  personaId: string;
  slug: string;
  name: string;
  description: string;
  config: PersonalityConfig;
  originalDescription?: string;
  intent?: PersonaGenerationIntent;
  referenceDossier?: PersonaReferenceDossier;
  revision?: number;
}

export interface PersonaCreationDraft {
  draftId: string;
  personaId: string;
  phase:
    | "editing"
    | "resolving"
    | "reviewing"
    | "verifying"
    | "generating"
    | "failed";
  description: string;
  resolution?: PersonaIntentResolution;
  reference: EditablePersonaReference;
  referenceConfirmed: boolean;
  fidelityLevel: PersonaFidelityLevel;
  researchPreference: PersonaResearchPreference;
  referenceUrlsText: string;
  referenceModified: boolean;
  identityVerified: boolean;
  verificationFingerprint?: string;
  verificationSources: PersonaReferenceSource[];
  verificationWarning?: string;
  forceResearchRefresh: boolean;
  constraintsText: string;
  generationRequestId?: string;
  generationJobId?: string;
  editingPersonaSlug?: string;
  revision: number;
}

export interface PreviewDisplayTurn extends PreviewTurn {
  id?: string;
  kind?: "message" | "revision-divider";
  superseded?: boolean;
  streamGroupId?: string;
}

export type TranscriptMap = Record<string, PreviewDisplayTurn[]>;

export interface RailItem {
  slug: string;
  name: string;
  description: string;
  avatar?: string;
  isCustom: boolean;
  config?: PersonalityConfig;
  customDraft?: CustomPersonaDraft;
}

export interface PresetProfileState {
  status: "loading" | "success" | "error";
  config?: PersonalityConfig;
}

export type FakeIpCompatibilityRetry =
  | { kind: "verification"; draft: PersonaCreationDraft }
  | {
      kind: "generation";
      draft: PersonaCreationDraft;
      intent: PersonaGenerationIntent;
    };

export function errorCode(error: unknown): string | undefined {
  if (!error || typeof error !== "object" || !("code" in error)) {
    return undefined;
  }
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" ? code : undefined;
}

export function buildPreviewHistory(
  turns: PreviewDisplayTurn[],
): PreviewTurn[] {
  const history = turns.reduce<PreviewTurn[]>((collapsed, turn) => {
    if (turn.kind === "revision-divider" || turn.superseded) {
      return collapsed;
    }
    const previous = collapsed[collapsed.length - 1];
    if (turn.role === "assistant" && previous?.role === "assistant") {
      collapsed[collapsed.length - 1] = {
        role: "assistant",
        content: `${previous.content}\n${turn.content}`,
      };
      return collapsed;
    }
    collapsed.push({ role: turn.role, content: turn.content });
    return collapsed;
  }, []);
  return history.slice(-PREVIEW_HISTORY_TURN_LIMIT);
}

export function splitPreviewReply(content: string): string[] {
  return content
    .split(PREVIEW_SEGMENT_SENTINEL)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

export function createStableId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

export function createEmptyCreationDraft(): PersonaCreationDraft {
  return {
    draftId: createStableId(),
    personaId: createStableId(),
    phase: "editing",
    description: "",
    reference: {
      sourceKind: "original",
      name: "",
      workTitle: "",
      version: "",
      context: "",
    },
    referenceConfirmed: false,
    fidelityLevel: "natural",
    researchPreference: "disabled",
    referenceUrlsText: "",
    referenceModified: false,
    identityVerified: false,
    verificationSources: [],
    forceResearchRefresh: false,
    constraintsText: "",
    revision: 1,
  };
}

export function splitConstraints(value: string): string[] {
  return value
    .split(/\n|；|;/)
    .map((item) => item.trim())
    .filter(
      (item, index, items) => Boolean(item) && items.indexOf(item) === index,
    );
}

function expressionLevelForFidelity(
  fidelityLevel: PersonaFidelityLevel,
): PersonaGenerationIntent["expression_level"] {
  if (fidelityLevel === "traits") return "low";
  if (fidelityLevel === "faithful") return "high_contextual";
  return "balanced";
}

export function splitReferenceUrls(value: string): string[] {
  return value
    .split(/\n|,|，/)
    .map((item) => item.trim())
    .filter(
      (item, index, items) => Boolean(item) && items.indexOf(item) === index,
    );
}

export function referenceUrlsAreValid(value: string): boolean {
  const urls = splitReferenceUrls(value);
  if (urls.length > 4) return false;
  return urls.every((value) => {
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch {
      return false;
    }
  });
}

export function buildGenerationIntent(
  draft: PersonaCreationDraft,
): PersonaGenerationIntent {
  const explicitConstraints = splitConstraints(draft.constraintsText);
  if (draft.reference.sourceKind === "original") {
    return {
      source_kind: "original",
      reference: null,
      fidelity_level: "natural",
      expression_level: "balanced",
      research: {
        preference: "disabled",
        force_refresh: false,
        reference_urls: [],
        identity_confidence: 1,
        identity_ambiguous: false,
        identity_verified: false,
        reference_modified: false,
        verification_fingerprint: null,
      },
      explicit_constraints: explicitConstraints,
    };
  }
  return {
    source_kind: draft.reference.sourceKind,
    reference: {
      source_kind: draft.reference.sourceKind,
      name: draft.reference.name.trim(),
      work_title: draft.reference.workTitle.trim() || null,
      version: draft.reference.version.trim() || null,
      context: draft.reference.context.trim() || null,
      user_confirmed: true,
    },
    fidelity_level: draft.fidelityLevel,
    expression_level: expressionLevelForFidelity(draft.fidelityLevel),
    research: {
      preference:
        draft.reference.sourceKind === "private_person_reference"
          ? "disabled"
          : draft.researchPreference,
      force_refresh:
        draft.researchPreference === "disabled"
          ? false
          : draft.forceResearchRefresh,
      reference_urls:
        draft.reference.sourceKind === "private_person_reference" ||
        draft.researchPreference === "disabled"
          ? []
          : splitReferenceUrls(draft.referenceUrlsText),
      identity_confidence: draft.resolution?.confidence ?? 0,
      identity_ambiguous: draft.resolution?.status === "ambiguous",
      identity_verified: draft.identityVerified,
      reference_modified: draft.referenceModified,
      verification_fingerprint: draft.verificationFingerprint || null,
    },
    explicit_constraints: explicitConstraints,
  };
}

export function referenceSummary(intent?: PersonaGenerationIntent): string {
  const reference = intent?.reference;
  if (!reference) return "";
  return [
    reference.name,
    reference.work_title ? `《${reference.work_title}》` : "",
    reference.version || "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function applyIntentResolution(
  sourceDraft: PersonaCreationDraft,
  resolution: PersonaIntentResolution,
): PersonaCreationDraft {
  const selected =
    resolution.candidates.find(
      (candidate) =>
        candidate.candidate_id === resolution.selected_candidate_id,
    ) ?? resolution.candidates[0];
  const reference =
    resolution.status === "original"
      ? {
          sourceKind: "original" as const,
          name: "",
          workTitle: "",
          version: "",
          context: "",
        }
      : selected
        ? candidateToEditableReference(selected)
        : {
            sourceKind: "fictional_reference" as const,
            name: "",
            workTitle: "",
            version: "",
            context: "",
          };
  return {
    ...sourceDraft,
    phase: "reviewing",
    resolution,
    reference,
    referenceConfirmed:
      resolution.status === "resolved" ||
      resolution.status === "original" ||
      resolution.candidates.length <= 1,
    fidelityLevel: defaultFidelityLevel(reference.sourceKind),
    researchPreference:
      reference.sourceKind === "original" ||
      reference.sourceKind === "private_person_reference"
        ? "disabled"
        : "auto",
    referenceUrlsText: "",
    referenceModified: false,
    identityVerified: false,
    verificationFingerprint: undefined,
    verificationSources: [],
    verificationWarning: undefined,
    forceResearchRefresh: false,
    constraintsText: resolution.explicit_constraints.join("\n"),
  };
}

export function createReferenceEditDraft(
  customDraft: CustomPersonaDraft,
  forceResearchRefresh = false,
): PersonaCreationDraft {
  const intent = customDraft.intent;
  const reference = intent?.reference;
  const sourceKind = intent?.source_kind ?? "original";
  const editableReference: EditablePersonaReference =
    sourceKind === "original" || !reference
      ? {
          sourceKind: "original",
          name: "",
          workTitle: "",
          version: "",
          context: "",
        }
      : {
          sourceKind: sourceKind as PersonaReferenceKind,
          name: reference.name,
          workTitle: reference.work_title || "",
          version: reference.version || "",
          context: reference.context || "",
        };
  const candidates =
    editableReference.sourceKind === "original"
      ? []
      : [
          {
            candidate_id: "candidate-1",
            source_kind: editableReference.sourceKind,
            name: editableReference.name,
            work_title: editableReference.workTitle || null,
            version: editableReference.version || null,
            context: editableReference.context || null,
            confidence: 1,
          },
        ];
  return {
    draftId: createStableId(),
    personaId: customDraft.personaId,
    phase: "reviewing",
    description:
      customDraft.originalDescription || customDraft.description,
    resolution: {
      status:
        editableReference.sourceKind === "original"
          ? "original"
          : "resolved",
      candidates,
      selected_candidate_id: candidates[0]?.candidate_id || null,
      confidence: 1,
      requires_confirmation:
        editableReference.sourceKind !== "original",
      explicit_constraints: intent?.explicit_constraints || [],
    },
    reference: editableReference,
    referenceConfirmed: true,
    fidelityLevel:
      intent?.fidelity_level ||
      defaultFidelityLevel(editableReference.sourceKind),
    researchPreference:
      intent?.research.preference ||
      (editableReference.sourceKind === "original" ||
      editableReference.sourceKind === "private_person_reference"
        ? "disabled"
        : "auto"),
    referenceUrlsText: intent?.research.reference_urls.join("\n") || "",
    referenceModified: false,
    identityVerified: forceResearchRefresh
      ? false
      : intent?.research.identity_verified || false,
    verificationFingerprint: forceResearchRefresh
      ? undefined
      : intent?.research.verification_fingerprint || undefined,
    verificationSources: forceResearchRefresh
      ? []
      : customDraft.referenceDossier?.sources || [],
    verificationWarning: forceResearchRefresh
      ? undefined
      : customDraft.referenceDossier?.warning || undefined,
    forceResearchRefresh,
    constraintsText: (intent?.explicit_constraints || []).join("\n"),
    editingPersonaSlug: customDraft.slug,
    revision: (customDraft.revision || 1) + 1,
  };
}

export function updateCreationDescription(
  draft: PersonaCreationDraft,
  description: string,
): PersonaCreationDraft {
  return {
    ...draft,
    phase: "editing",
    description,
    resolution: undefined,
    referenceConfirmed: false,
    generationRequestId: undefined,
    generationJobId: undefined,
  };
}

export function buildRailItems(
  previews: SeedPreview[],
  customDrafts: CustomPersonaDraft[],
): RailItem[] {
  return [
    ...[...previews]
      .sort((left, right) => left.order - right.order)
      .map((preview) => ({
        slug: preview.seed_slug,
        name: preview.name,
        description: preview.description,
        avatar: preview.avatar,
        isCustom: false,
      })),
    ...customDrafts.map((draft) => ({
      slug: draft.slug,
      name: draft.name,
      description: draft.description,
      avatar: "",
      isCustom: true,
      config: draft.config,
      customDraft: draft,
    })),
  ];
}
