import { useCallback, useReducer, useRef } from "react";
import type { CustomPersonaDraft } from "./personaPreviewModel";

type DraftRegistryAction =
  | { type: "replace"; drafts: CustomPersonaDraft[] }
  | { type: "upsert"; draft: CustomPersonaDraft };

function draftRegistryReducer(
  state: CustomPersonaDraft[],
  action: DraftRegistryAction,
): CustomPersonaDraft[] {
  if (action.type === "replace") {
    return action.drafts;
  }
  const existingIndex = state.findIndex(
    (draft) =>
      draft.slug === action.draft.slug ||
      draft.personaId === action.draft.personaId,
  );
  if (existingIndex < 0) {
    return [...state, action.draft];
  }
  return state.map((draft, index) =>
    index === existingIndex ? action.draft : draft,
  );
}

interface UsePersonaDraftRegistryOptions {
  initialDrafts: CustomPersonaDraft[];
  onChange?: (drafts: CustomPersonaDraft[]) => void;
}

export function usePersonaDraftRegistry({
  initialDrafts,
  onChange,
}: UsePersonaDraftRegistryOptions) {
  const [drafts, dispatch] = useReducer(draftRegistryReducer, initialDrafts);
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;

  const publish = useCallback(
    (action: DraftRegistryAction): CustomPersonaDraft[] => {
      const nextDrafts = draftRegistryReducer(draftsRef.current, action);
      draftsRef.current = nextDrafts;
      dispatch(action);
      onChange?.(nextDrafts);
      return nextDrafts;
    },
    [onChange],
  );

  const replace = useCallback(
    (nextDrafts: CustomPersonaDraft[]) =>
      publish({ type: "replace", drafts: nextDrafts }),
    [publish],
  );

  const upsert = useCallback(
    (draft: CustomPersonaDraft) => publish({ type: "upsert", draft }),
    [publish],
  );

  return {
    drafts,
    draftsRef,
    replace,
    upsert,
  };
}

export type PersonaDraftRegistry = ReturnType<
  typeof usePersonaDraftRegistry
>;
