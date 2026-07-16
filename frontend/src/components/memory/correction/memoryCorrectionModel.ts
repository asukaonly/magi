import type {
  MemoryCorrectionKind,
  MemoryCorrectionRequest,
} from '@/api/modules/memory';

export interface MemoryCorrectionEntityOption {
  id: string;
  name: string;
  type: string;
}

export interface MemoryCorrectionRelationship {
  subjectId: string;
  subjectType: string;
  subjectName: string;
  predicate: string;
  predicateLabel: string;
  objectId: string;
  objectType: string;
  objectName: string;
}

export interface MemoryCorrectionAssertionTarget {
  kind: 'assertion';
  id: string;
  statement: string;
  currentValue: string;
  displayValue?: string;
  expectedUpdatedAt?: number;
}

export interface MemoryCorrectionEdgeTarget {
  kind: 'edge';
  id: string;
  statement: string;
  expectedUpdatedAt?: number;
  relationship: MemoryCorrectionRelationship;
  entityOptions: MemoryCorrectionEntityOption[];
}

export type MemoryCorrectionUiTarget =
  | MemoryCorrectionAssertionTarget
  | MemoryCorrectionEdgeTarget;

export type MemoryCorrectionRecordErrorAction = 'replace' | 'remove';
export type MemoryCorrectionScopeType = 'project' | 'activity' | 'place' | 'person';

export interface MemoryCorrectionDraft {
  requestId: string;
  correctionKind: MemoryCorrectionKind;
  recordErrorAction: MemoryCorrectionRecordErrorAction;
  value: string;
  effectiveAt: string;
  scopeType: MemoryCorrectionScopeType;
  scopeValue: string;
  reason: string;
  relationObjectId: string;
}

export const MEMORY_CORRECTION_VALIDATION_ERROR_CODES = {
  REPLACEMENT_REQUIRED: 'replacement_required',
  REPLACEMENT_UNCHANGED: 'replacement_unchanged',
  EFFECTIVE_AT_REQUIRED: 'effective_at_required',
  EFFECTIVE_AT_INVALID: 'effective_at_invalid',
  SCOPE_REQUIRED: 'scope_required',
  RELATION_OBJECT_REQUIRED: 'relation_object_required',
  RELATION_OBJECT_UNCHANGED: 'relation_object_unchanged',
  RELATION_OBJECT_UNAVAILABLE: 'relation_object_unavailable',
} as const;

export type MemoryCorrectionValidationErrorCode =
  (typeof MEMORY_CORRECTION_VALIDATION_ERROR_CODES)[keyof typeof MEMORY_CORRECTION_VALIDATION_ERROR_CODES];

export type MemoryCorrectionValidationField =
  | 'value'
  | 'effectiveAt'
  | 'scopeValue'
  | 'relationObjectId';

export type MemoryCorrectionValidationErrors = Partial<
  Record<MemoryCorrectionValidationField, MemoryCorrectionValidationErrorCode>
>;

export interface MemoryCorrectionValidationResult {
  valid: boolean;
  errors: MemoryCorrectionValidationErrors;
}

export const createMemoryCorrectionRequestId = (): string => {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2);
  return `memory-correction-${timestamp}-${random}`;
};

export const createInitialMemoryCorrectionDraft = (
  target: MemoryCorrectionUiTarget
): MemoryCorrectionDraft => ({
  requestId: createMemoryCorrectionRequestId(),
  correctionKind: 'record_error',
  recordErrorAction: 'replace',
  value: target.kind === 'assertion' ? assertionDisplayValue(target) : '',
  effectiveAt: '',
  scopeType: 'project',
  scopeValue: '',
  reason: '',
  relationObjectId: target.kind === 'edge' ? target.relationship.objectId : '',
});

export const validateMemoryCorrectionDraft = (
  target: MemoryCorrectionUiTarget,
  draft: MemoryCorrectionDraft
): MemoryCorrectionValidationResult => {
  const errors: MemoryCorrectionValidationErrors = {};

  if (draft.correctionKind === 'record_error' && draft.recordErrorAction === 'replace') {
    validateChangedReplacement(target, draft, errors);
  }

  if (draft.correctionKind === 'situation_changed') {
    validateChangedReplacement(target, draft, errors);
    validateEffectiveAt(draft.effectiveAt, errors);
  }

  if (draft.correctionKind === 'scope_refinement') {
    if (target.kind === 'assertion' && !draft.value.trim()) {
      errors.value = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.REPLACEMENT_REQUIRED;
    }
    if (!draft.scopeValue.trim()) {
      errors.scopeValue = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.SCOPE_REQUIRED;
    }
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
};

export const buildMemoryCorrectionRequest = (
  target: MemoryCorrectionUiTarget,
  draft: MemoryCorrectionDraft,
  requestId: string = draft.requestId
): MemoryCorrectionRequest | null => {
  if (!validateMemoryCorrectionDraft(target, draft).valid) {
    return null;
  }

  const request: MemoryCorrectionRequest = {
    request_id: requestId,
    target: { kind: target.kind, id: target.id },
    correction_kind: draft.correctionKind,
  };
  const reason = draft.reason.trim();
  if (reason) {
    request.reason = reason;
  }
  if (target.expectedUpdatedAt !== undefined) {
    request.expected_updated_at = target.expectedUpdatedAt;
  }

  if (draft.correctionKind === 'scope_refinement') {
    request.replacement = target.kind === 'assertion'
      ? {
          value: draft.value.trim() === assertionDisplayValue(target).trim()
            ? target.currentValue.trim()
            : draft.value.trim(),
        }
      : {};
    request.scope = { [draft.scopeType]: draft.scopeValue.trim() };
    return request;
  }

  if (draft.correctionKind === 'record_error' && draft.recordErrorAction === 'remove') {
    return request;
  }

  if (target.kind === 'assertion') {
    request.replacement = { value: draft.value.trim() };
  } else {
    const selectedObject = target.entityOptions.find(
      (option) => option.id === draft.relationObjectId.trim()
    );
    if (!selectedObject) {
      return null;
    }
    request.replacement = {
      object_id: selectedObject.id,
      object_type: selectedObject.type,
    };
  }

  if (draft.correctionKind === 'situation_changed') {
    request.effective_at = toLocalEpochSeconds(draft.effectiveAt);
  }

  return request;
};

const validateChangedReplacement = (
  target: MemoryCorrectionUiTarget,
  draft: MemoryCorrectionDraft,
  errors: MemoryCorrectionValidationErrors
): void => {
  if (target.kind === 'assertion') {
    const value = draft.value.trim();
    if (!value) {
      errors.value = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.REPLACEMENT_REQUIRED;
    } else if (value === assertionDisplayValue(target).trim()) {
      errors.value = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.REPLACEMENT_UNCHANGED;
    }
    return;
  }

  const objectId = draft.relationObjectId.trim();
  if (!objectId) {
    errors.relationObjectId =
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.RELATION_OBJECT_REQUIRED;
  } else if (objectId === target.relationship.objectId) {
    errors.relationObjectId =
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.RELATION_OBJECT_UNCHANGED;
  } else if (!target.entityOptions.some((option) => option.id === objectId)) {
    errors.relationObjectId =
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.RELATION_OBJECT_UNAVAILABLE;
  }
};

const assertionDisplayValue = (
  target: MemoryCorrectionAssertionTarget
): string => target.displayValue ?? formatMemoryCorrectionValue(target.currentValue, target.currentValue);

export const formatMemoryCorrectionValue = (
  value: unknown,
  fallback = ''
): string => {
  if (value === null || value === undefined) return fallback;
  let parsed: unknown = value;
  if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return fallback;
    if ('[{"'.includes(text[0])) {
      try {
        parsed = JSON.parse(text);
      } catch {
        return text;
      }
    } else {
      return text;
    }
  }
  if (Array.isArray(parsed)) {
    const items = parsed
      .map((item) => formatMemoryCorrectionValue(item))
      .filter(Boolean);
    return items.join('、') || fallback;
  }
  if (typeof parsed === 'object') {
    const record = parsed as Record<string, unknown>;
    return 'value' in record
      ? formatMemoryCorrectionValue(record.value, fallback)
      : fallback;
  }
  const text = String(parsed).trim();
  return text || fallback;
};

const validateEffectiveAt = (
  effectiveAt: string,
  errors: MemoryCorrectionValidationErrors
): void => {
  const value = effectiveAt.trim();
  if (!value) {
    errors.effectiveAt = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.EFFECTIVE_AT_REQUIRED;
    return;
  }
  if (!Number.isFinite(new Date(value).getTime())) {
    errors.effectiveAt = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.EFFECTIVE_AT_INVALID;
  }
};

const toLocalEpochSeconds = (dateTimeLocal: string): number =>
  Math.floor(new Date(dateTimeLocal.trim()).getTime() / 1000);
