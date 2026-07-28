import { useCallback, type MutableRefObject } from "react";
import type {
  PersonaFidelityLevel,
  PersonaResearchPreference,
} from "../../../api/modules/personas";
import {
  defaultFidelityLevel,
  type EditablePersonaReference,
} from "../PersonaReferenceEditor";
import {
  createEmptyCreationDraft,
  createReferenceEditDraft,
  updateCreationDescription,
  type CustomPersonaDraft,
  type PersonaCreationDraft,
} from "./personaPreviewModel";

interface UsePersonaCreationDraftEditorOptions {
  creationDraftRef: MutableRefObject<PersonaCreationDraft | null>;
  supersedeOperation: () => number;
  publishDraft: (draft: PersonaCreationDraft | null) => void;
  resetFeedback: (descriptionExpanded?: boolean) => void;
  onEditRequested: () => void;
}

export function usePersonaCreationDraftEditor({
  creationDraftRef,
  supersedeOperation,
  publishDraft,
  resetFeedback,
  onEditRequested,
}: UsePersonaCreationDraftEditorOptions) {
  const updateDraft = useCallback(
    (draft: PersonaCreationDraft) => {
      supersedeOperation();
      publishDraft(draft);
    },
    [publishDraft, supersedeOperation],
  );

  const editCustomReference = useCallback(
    (customDraft: CustomPersonaDraft, forceResearchRefresh = false) => {
      supersedeOperation();
      publishDraft(
        createReferenceEditDraft(customDraft, forceResearchRefresh),
      );
      resetFeedback(false);
      onEditRequested();
    },
    [
      onEditRequested,
      publishDraft,
      resetFeedback,
      supersedeOperation,
    ],
  );

  const startNewCreation = useCallback(() => {
    supersedeOperation();
    if (!creationDraftRef.current) {
      publishDraft(createEmptyCreationDraft());
    }
    resetFeedback(true);
    onEditRequested();
  }, [
    creationDraftRef,
    onEditRequested,
    publishDraft,
    resetFeedback,
    supersedeOperation,
  ]);

  const cancelCreation = useCallback(() => {
    supersedeOperation();
    publishDraft(null);
    resetFeedback();
  }, [publishDraft, resetFeedback, supersedeOperation]);

  const editDescription = useCallback(
    (description: string) => {
      supersedeOperation();
      const currentDraft =
        creationDraftRef.current ?? createEmptyCreationDraft();
      publishDraft(updateCreationDescription(currentDraft, description));
      resetFeedback(true);
    },
    [
      creationDraftRef,
      publishDraft,
      resetFeedback,
      supersedeOperation,
    ],
  );

  const updateReference = useCallback(
    (reference: EditablePersonaReference) => {
      const current = creationDraftRef.current;
      if (!current) return;
      updateDraft({
        ...current,
        reference,
        referenceConfirmed: true,
        referenceModified: true,
        identityVerified: false,
        verificationFingerprint: undefined,
        verificationSources: [],
        verificationWarning: undefined,
        fidelityLevel:
          reference.sourceKind === current.reference.sourceKind
            ? current.fidelityLevel
            : defaultFidelityLevel(reference.sourceKind),
        researchPreference:
          reference.sourceKind === "original" ||
          reference.sourceKind === "private_person_reference"
            ? "disabled"
            : current.researchPreference === "disabled"
              ? "auto"
              : current.researchPreference,
        referenceUrlsText:
          reference.sourceKind === "original" ||
          reference.sourceKind === "private_person_reference"
            ? ""
            : current.referenceUrlsText,
      });
    },
    [creationDraftRef, updateDraft],
  );

  const updateFidelityLevel = useCallback(
    (fidelityLevel: PersonaFidelityLevel) => {
      const current = creationDraftRef.current;
      if (!current) return;
      updateDraft({
        ...current,
        fidelityLevel,
        referenceConfirmed: true,
      });
    },
    [creationDraftRef, updateDraft],
  );

  const updateConstraintsText = useCallback(
    (constraintsText: string) => {
      const current = creationDraftRef.current;
      if (!current) return;
      updateDraft({ ...current, constraintsText });
    },
    [creationDraftRef, updateDraft],
  );

  const updateResearchPreference = useCallback(
    (researchPreference: PersonaResearchPreference) => {
      const current = creationDraftRef.current;
      if (!current) return;
      updateDraft({
        ...current,
        researchPreference,
        identityVerified: false,
        verificationFingerprint: undefined,
        verificationSources: [],
        verificationWarning: undefined,
      });
    },
    [creationDraftRef, updateDraft],
  );

  const updateReferenceUrlsText = useCallback(
    (referenceUrlsText: string) => {
      const current = creationDraftRef.current;
      if (!current) return;
      updateDraft({
        ...current,
        referenceUrlsText,
        identityVerified: false,
        verificationFingerprint: undefined,
        verificationSources: [],
        verificationWarning: undefined,
      });
    },
    [creationDraftRef, updateDraft],
  );

  return {
    updateDraft,
    editCustomReference,
    startNewCreation,
    cancelCreation,
    editDescription,
    updateReference,
    updateFidelityLevel,
    updateConstraintsText,
    updateResearchPreference,
    updateReferenceUrlsText,
  };
}
