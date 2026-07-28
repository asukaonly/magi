import type { PersonaGenerationStage } from "../../../api/modules/personas";
import type {
  FakeIpCompatibilityRetry,
  PersonaCreationDraft,
} from "./personaPreviewModel";

export interface PersonaGenerationState {
  creationDraft: PersonaCreationDraft | null;
  descriptionExpanded: boolean;
  stages: PersonaGenerationStage[];
  error: string | null;
  compatibilityRetry: FakeIpCompatibilityRetry | null;
  enablingCompatibility: boolean;
}

export type PersonaGenerationAction =
  | { type: "publishDraft"; draft: PersonaCreationDraft | null }
  | { type: "setDescriptionExpanded"; value: boolean }
  | { type: "setStages"; stages: PersonaGenerationStage[] }
  | { type: "setError"; error: string | null }
  | {
      type: "setCompatibilityRetry";
      retry: FakeIpCompatibilityRetry | null;
    }
  | { type: "setEnablingCompatibility"; value: boolean }
  | {
      type: "resetFeedback";
      descriptionExpanded?: boolean;
    };

export function createPersonaGenerationState(
  initialCreationDraft?: PersonaCreationDraft | null,
): PersonaGenerationState {
  return {
    creationDraft: initialCreationDraft ?? null,
    descriptionExpanded:
      !initialCreationDraft ||
      (initialCreationDraft.phase !== "reviewing" &&
        initialCreationDraft.phase !== "failed"),
    stages: [],
    error: null,
    compatibilityRetry: null,
    enablingCompatibility: false,
  };
}

export function personaGenerationReducer(
  state: PersonaGenerationState,
  action: PersonaGenerationAction,
): PersonaGenerationState {
  switch (action.type) {
    case "publishDraft":
      return { ...state, creationDraft: action.draft };
    case "setDescriptionExpanded":
      return { ...state, descriptionExpanded: action.value };
    case "setStages":
      return { ...state, stages: action.stages };
    case "setError":
      return { ...state, error: action.error };
    case "setCompatibilityRetry":
      return { ...state, compatibilityRetry: action.retry };
    case "setEnablingCompatibility":
      return { ...state, enablingCompatibility: action.value };
    case "resetFeedback":
      return {
        ...state,
        stages: [],
        error: null,
        compatibilityRetry: null,
        ...(action.descriptionExpanded === undefined
          ? {}
          : { descriptionExpanded: action.descriptionExpanded }),
      };
  }
}
