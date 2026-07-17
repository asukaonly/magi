import type {
  MemoryCorrectionContextOption,
  MemoryCorrectionKind,
  MemoryCorrectionRecord,
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

const PROJECT_CONTEXT_ID_PATTERN = /^ctx_project_[a-f0-9]{64}$/;

export interface MemoryCorrectionDraft {
  requestId: string;
  correctionKind: MemoryCorrectionKind;
  recordErrorAction: MemoryCorrectionRecordErrorAction;
  value: string;
  effectiveAt: string;
  scopeContextId: string;
  reason: string;
  relationObjectId: string;
}

export const MEMORY_CORRECTION_VALIDATION_ERROR_CODES = {
  REPLACEMENT_REQUIRED: 'replacement_required',
  REPLACEMENT_UNCHANGED: 'replacement_unchanged',
  EFFECTIVE_AT_REQUIRED: 'effective_at_required',
  EFFECTIVE_AT_INVALID: 'effective_at_invalid',
  SCOPE_REQUIRED: 'scope_required',
  SCOPE_UNAVAILABLE: 'scope_unavailable',
  RELATION_OBJECT_REQUIRED: 'relation_object_required',
  RELATION_OBJECT_UNCHANGED: 'relation_object_unchanged',
  RELATION_OBJECT_UNAVAILABLE: 'relation_object_unavailable',
} as const;

export type MemoryCorrectionValidationErrorCode =
  (typeof MEMORY_CORRECTION_VALIDATION_ERROR_CODES)[keyof typeof MEMORY_CORRECTION_VALIDATION_ERROR_CODES];

export type MemoryCorrectionValidationField =
  | 'value'
  | 'effectiveAt'
  | 'scopeContextId'
  | 'relationObjectId';

export type MemoryCorrectionValidationErrors = Partial<
  Record<MemoryCorrectionValidationField, MemoryCorrectionValidationErrorCode>
>;

export function memoryCorrectionErrorCode(details: unknown): string | null {
  if (!details || typeof details !== 'object' || Array.isArray(details)) return null;
  const code = (details as Record<string, unknown>).code;
  return typeof code === 'string' ? code : null;
}

export function isMemoryCorrectionScopeOccupied(code: string | null): boolean {
  return code === 'assertion_scope_occupied' || code === 'relationship_scope_occupied';
}

export type MemoryCorrectionLifecycleStatus = 'active' | 'scheduled' | 'cancelled' | 'reverted';

export type MemoryCorrectionHistoryStatus =
  | MemoryCorrectionLifecycleStatus
  | 'content_deleted';

export function memoryCorrectionLifecycleStatus(
  correction: MemoryCorrectionRecord,
  nowSeconds = Date.now() / 1000
): MemoryCorrectionLifecycleStatus {
  if (
    correction.transition_cancelled_at != null
    && correction.transition_applied_at == null
  ) return 'cancelled';
  if (correction.state !== 'active') return 'reverted';
  if (correction.correction_kind !== 'situation_changed') return 'active';

  if (correction.transition_applied_at !== undefined) {
    return correction.transition_applied_at === null ? 'scheduled' : 'active';
  }
  return correction.effective_at != null && correction.effective_at > nowSeconds
    ? 'scheduled'
    : 'active';
}

export function memoryCorrectionHistoryStatus(
  correction: MemoryCorrectionRecord,
  nowSeconds = Date.now() / 1000
): MemoryCorrectionHistoryStatus {
  const lifecycleStatus = memoryCorrectionLifecycleStatus(correction, nowSeconds);
  return (
    lifecycleStatus === 'active' || lifecycleStatus === 'scheduled'
  ) && correction.content_redacted === true
    ? 'content_deleted'
    : lifecycleStatus;
}

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
  scopeContextId: '',
  reason: '',
  relationObjectId: target.kind === 'edge' ? target.relationship.objectId : '',
});

export const validateMemoryCorrectionDraft = (
  target: MemoryCorrectionUiTarget,
  draft: MemoryCorrectionDraft,
  contextOptions: readonly MemoryCorrectionContextOption[] = []
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
    if (!draft.scopeContextId.trim()) {
      errors.scopeContextId = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.SCOPE_REQUIRED;
    } else if (!findSelectableProjectContextOption(contextOptions, draft.scopeContextId)) {
      errors.scopeContextId = MEMORY_CORRECTION_VALIDATION_ERROR_CODES.SCOPE_UNAVAILABLE;
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
  requestId: string = draft.requestId,
  contextOptions: readonly MemoryCorrectionContextOption[] = []
): MemoryCorrectionRequest | null => {
  if (!validateMemoryCorrectionDraft(target, draft, contextOptions).valid) {
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
    const selectedContext = findSelectableProjectContextOption(
      contextOptions,
      draft.scopeContextId
    );
    if (!selectedContext) return null;
    request.replacement = target.kind === 'assertion'
      ? { value: target.currentValue.trim() }
      : {};
    request.scope = {
      all_of: [{
        dimension: 'project',
        context_id: selectedContext.context_id,
      }],
    };
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

export const isSelectableProjectContextOption = (
  option: unknown
): option is MemoryCorrectionContextOption => {
  if (!option || typeof option !== 'object' || Array.isArray(option)) return false;
  const candidate = option as Record<string, unknown>;
  return candidate.dimension === 'project'
    && typeof candidate.context_id === 'string'
    && PROJECT_CONTEXT_ID_PATTERN.test(candidate.context_id)
    && typeof candidate.label === 'string'
    && Boolean(candidate.label.trim());
};

export const selectableProjectContextOptions = (
  options: readonly unknown[]
): MemoryCorrectionContextOption[] => {
  const uniqueOptions = new Map<string, MemoryCorrectionContextOption>();
  for (const option of options) {
    if (!isSelectableProjectContextOption(option)) continue;
    if (!uniqueOptions.has(option.context_id)) {
      uniqueOptions.set(option.context_id, option);
    }
  }
  return [...uniqueOptions.values()];
};

export const findSelectableProjectContextOption = (
  options: readonly MemoryCorrectionContextOption[],
  contextId: string
): MemoryCorrectionContextOption | undefined => {
  const normalizedContextId = contextId.trim();
  if (!normalizedContextId) return undefined;
  return options.find(
    (option) => isSelectableProjectContextOption(option)
      && option.context_id === normalizedContextId
  );
};

export const canRevertMemoryCorrection = (
  correction: MemoryCorrectionRecord
): boolean => {
  return correction.can_revert === true
    && correction.state === 'active'
    && correction.transition_cancelled_at == null;
};

export const shouldExplainUnavailableMemoryCorrectionRevert = (
  correction: MemoryCorrectionRecord,
  nowSeconds = Date.now() / 1000
): boolean => {
  const lifecycleStatus = memoryCorrectionLifecycleStatus(correction, nowSeconds);
  return !canRevertMemoryCorrection(correction)
    && !correction.forget_affected
    && !correction.content_redacted
    && (lifecycleStatus === 'active' || lifecycleStatus === 'scheduled');
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
