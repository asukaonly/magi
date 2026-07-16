import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Loader2, RefreshCw, Search, SlidersHorizontal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toApiClientError } from '@/api/client';
import { memoryApi, type MemoryCorrectionCommandResponse, type MemoryCorrectionKind } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import {
  buildMemoryCorrectionRequest,
  createInitialMemoryCorrectionDraft,
  createMemoryCorrectionRequestId,
  formatMemoryCorrectionValue,
  validateMemoryCorrectionDraft,
  type MemoryCorrectionDraft,
  type MemoryCorrectionEntityOption,
  type MemoryCorrectionUiTarget,
  type MemoryCorrectionValidationErrors,
  type MemoryCorrectionValidationField,
} from './memoryCorrectionModel';
import {
  correctionLocale,
  formatCorrectionEntityType,
  formatCorrectionScope,
  formatCorrectionTime,
} from './memoryCorrectionPresentation';

interface MemoryCorrectionDialogProps {
  open: boolean;
  target: MemoryCorrectionUiTarget | null;
  onOpenChange: (open: boolean) => void;
  onSaved?: (result: MemoryCorrectionCommandResponse) => void | Promise<void>;
  onConflict?: () => void | Promise<void>;
  initialCorrectionKind?: MemoryCorrectionKind;
  initialRecordErrorAction?: MemoryCorrectionDraft['recordErrorAction'];
}

const KIND_ICONS = {
  record_error: AlertCircle,
  situation_changed: RefreshCw,
  scope_refinement: SlidersHorizontal,
} satisfies Record<MemoryCorrectionKind, typeof AlertCircle>;

const CORRECTION_KINDS: MemoryCorrectionKind[] = [
  'record_error',
  'situation_changed',
  'scope_refinement',
];

const SCOPE_TYPES: MemoryCorrectionDraft['scopeType'][] = [
  'project',
  'activity',
  'place',
  'person',
];

const CORRECTION_FIELD_IDS: Record<MemoryCorrectionValidationField, string> = {
  value: 'memory-correction-value',
  effectiveAt: 'memory-correction-effective-at',
  scopeValue: 'memory-correction-scope-value',
  relationObjectId: 'memory-correction-object',
};

export function MemoryCorrectionDialog({
  open,
  target,
  onOpenChange,
  onSaved,
  onConflict,
  initialCorrectionKind = 'record_error',
  initialRecordErrorAction = 'replace',
}: MemoryCorrectionDialogProps) {
  const { t } = useTranslation('app');
  const [draft, setDraft] = useState<MemoryCorrectionDraft | null>(null);
  const [requestId, setRequestId] = useState(createMemoryCorrectionRequestId);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [result, setResult] = useState<MemoryCorrectionCommandResponse | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [entitySearch, setEntitySearch] = useState('');
  const [entityOptions, setEntityOptions] = useState<MemoryCorrectionEntityOption[]>([]);
  const [entitySearchLoading, setEntitySearchLoading] = useState(false);
  const [entitySearchError, setEntitySearchError] = useState(false);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const previousTargetRef = useRef<string | null>(null);
  const initialDraftRef = useRef<MemoryCorrectionDraft | null>(null);
  const submittingRef = useRef(false);

  useEffect(() => {
    const targetKey = target ? `${target.kind}:${target.id}` : null;
    if (!open || !target || (targetKey === previousTargetRef.current && draft)) return;
    previousTargetRef.current = targetKey;
    const initialDraft = {
      ...createInitialMemoryCorrectionDraft(target),
      correctionKind: initialCorrectionKind,
      recordErrorAction: initialRecordErrorAction,
    };
    initialDraftRef.current = initialDraft;
    setDraft(initialDraft);
    setRequestId(createMemoryCorrectionRequestId());
    submittingRef.current = false;
    setSubmitting(false);
    setError(null);
    setSubmitted(false);
    setResult(null);
    setConflicted(false);
    setEntitySearch('');
    setEntityOptions(target.kind === 'edge' ? target.entityOptions : []);
    setEntitySearchLoading(false);
    setEntitySearchError(false);
    setDiscardConfirmOpen(false);
  }, [draft, initialCorrectionKind, initialRecordErrorAction, open, target]);

  useEffect(() => {
    if (!open) setDiscardConfirmOpen(false);
  }, [open]);

  useEffect(() => {
    if (!open || target?.kind !== 'edge') return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setEntitySearchLoading(true);
      setEntitySearchError(false);
      try {
        const response = await memoryApi.getL2Entities({
          limit: entitySearch.trim() ? 50 : 100,
          ...(entitySearch.trim() ? { query: entitySearch.trim() } : {}),
        });
        if (cancelled) return;
        const loadedOptions = (response.items || []).map((entity) => ({
          id: entity.entity_id,
          name: entity.canonical_name,
          type: entity.entity_type,
        }));
        setEntityOptions((current) => mergeEntityOptions(
          target.entityOptions,
          current,
          loadedOptions,
        ));
      } catch {
        if (!cancelled) setEntitySearchError(true);
      } finally {
        if (!cancelled) setEntitySearchLoading(false);
      }
    }, entitySearch.trim() ? 250 : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [entitySearch, open, target]);

  const effectiveTarget = useMemo<MemoryCorrectionUiTarget | null>(() => {
    if (!target || target.kind === 'assertion') return target;
    return { ...target, entityOptions: mergeEntityOptions(target.entityOptions, entityOptions) };
  }, [entityOptions, target]);

  const validation = useMemo(
    () => (effectiveTarget && draft ? validateMemoryCorrectionDraft(effectiveTarget, draft) : null),
    [draft, effectiveTarget]
  );
  const hasUnsavedChanges = useMemo(
    () => Boolean(
      draft
      && initialDraftRef.current
      && correctionDraftFingerprint(draft) !== correctionDraftFingerprint(initialDraftRef.current)
    ),
    [draft]
  );

  const updateDraft = (patch: Partial<MemoryCorrectionDraft>) => {
    if (submittingRef.current) return;
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setRequestId(createMemoryCorrectionRequestId());
    setError(null);
    setSubmitted(false);
  };

  const validationMessage = useMemo(() => {
    if (!submitted || !validation || validation.valid) return null;
    return t('memory.correction.validation.form', { defaultValue: '请检查填写内容后再保存。' });
  }, [submitted, t, validation]);

  const validationError = (field: MemoryCorrectionValidationField): string | null => {
    const code = submitted ? validation?.errors[field] : undefined;
    return code
      ? t(`memory.correction.validation.${code}`, {
          defaultValue: correctionValidationFallback(code),
        })
      : null;
  };

  const handleSubmit = async () => {
    if (submittingRef.current || !effectiveTarget || !draft) return;
    setSubmitted(true);
    if (!validation?.valid) {
      focusFirstInvalidCorrectionField(validation?.errors ?? {});
      return;
    }
    const payload = buildMemoryCorrectionRequest(effectiveTarget, draft, requestId);
    if (!payload) return;

    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const response = await memoryApi.applyCorrection(payload);
      setResult(response);
      void runCallback(
        () => onSaved?.(response),
        'Failed to refresh memory after correction'
      );
    } catch (caught) {
      const clientError = toApiClientError(caught);
      if (clientError.status === 409 || clientError.status === 404) {
        setConflicted(true);
        setError(t('memory.correction.errors.targetChanged', {
          defaultValue: '这条记忆已经发生变化或不再存在，当前内容不会被覆盖。请查看最新内容后重新打开。',
        }));
        void runCallback(
          onConflict,
          'Failed to refresh memory after correction conflict'
        );
      } else if (
        clientError.status === 422
        && correctionValidationCode(clientError.details) === 'effective_at_before_target'
      ) {
        setError(t('memory.correction.errors.effectiveAtBeforeTarget', {
          defaultValue: '变化时间不能早于这条记忆开始生效的时间，请重新选择。',
        }));
        focusCorrectionField('effectiveAt');
      } else {
        setError(t('memory.correction.errors.saveFailed', {
          defaultValue: '暂时没能保存。你填写的内容还在，可以稍后重试。',
        }));
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (submittingRef.current) return;
    if (!nextOpen && !result && !conflicted && hasUnsavedChanges) {
      setDiscardConfirmOpen(true);
      return;
    }
    if (!nextOpen) {
      previousTargetRef.current = null;
      setDiscardConfirmOpen(false);
    }
    onOpenChange(nextOpen);
  };

  const discardAndClose = () => {
    previousTargetRef.current = null;
    setDiscardConfirmOpen(false);
    onOpenChange(false);
  };

  if (!effectiveTarget || !draft) return null;

  const isAssertion = effectiveTarget.kind === 'assertion';
  const isRecordError = draft.correctionKind === 'record_error';
  const isSituationChanged = draft.correctionKind === 'situation_changed';
  const isScopeRefinement = draft.correctionKind === 'scope_refinement';
  const showReplacement = isAssertion
    ? !isRecordError || draft.recordErrorAction === 'replace'
    : isSituationChanged || (isRecordError && draft.recordErrorAction === 'replace');

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent
          closeLabel={t('memory.correction.close', { defaultValue: '关闭' })}
          className="max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-2xl overflow-y-auto rounded-xl p-0 sm:max-h-[min(88dvh,760px)] sm:rounded-2xl"
        >
        {result ? (
          <CorrectionSuccess
            target={effectiveTarget}
            result={result}
            onDone={() => handleOpenChange(false)}
          />
        ) : (
          <>
            <DialogHeader className="pr-12">
              <DialogTitle>{t('memory.correction.title', { defaultValue: '修正这条记忆' })}</DialogTitle>
              <DialogDescription className="leading-6">
                {t('memory.correction.description', {
                  defaultValue: '告诉 Magi 哪里不对。原始来源会保留，之后的回答会使用修正后的理解。',
                })}
              </DialogDescription>
            </DialogHeader>

            <fieldset
              disabled={submitting}
              aria-busy={submitting}
              className="m-0 min-w-0 space-y-6 border-0 px-5 pb-6 sm:px-6"
            >
              <section aria-labelledby="memory-correction-current">
                <h3 id="memory-correction-current" className="text-xs font-semibold text-muted-foreground">
                  {t('memory.correction.currentLabel', { defaultValue: '当前记住的是' })}
                </h3>
                <p className="mt-2 rounded-xl bg-muted/55 px-4 py-3 text-sm font-medium leading-6 text-foreground">
                  {effectiveTarget.statement}
                </p>
              </section>

              <fieldset>
                <legend className="text-sm font-semibold text-foreground">
                  {t('memory.correction.kindLabel', { defaultValue: '哪里需要修正？' })}
                </legend>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  {CORRECTION_KINDS.map((kind) => {
                    const Icon = KIND_ICONS[kind];
                    const active = draft.correctionKind === kind;
                    return (
                      <button
                        key={kind}
                        type="button"
                        aria-pressed={active}
                        onClick={() => updateDraft({ correctionKind: kind })}
                        className={cn(
                          'min-h-20 rounded-xl border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          active
                            ? 'border-primary/45 bg-primary/8 text-foreground'
                            : 'border-border/70 bg-background text-muted-foreground hover:bg-muted/45 hover:text-foreground'
                        )}
                      >
                        <span className="flex items-center gap-2 text-sm font-semibold">
                          <Icon className="h-4 w-4" aria-hidden="true" />
                          {t(`memory.correction.kinds.${kind}.title`, {
                            defaultValue: kind === 'record_error'
                              ? '这条记忆本来就不对'
                              : kind === 'situation_changed'
                                ? '以前是这样，现在变了'
                                : '只在某些情况下是这样',
                          })}
                        </span>
                        <span className="mt-1.5 block text-xs leading-5">
                          {t(`memory.correction.kinds.${kind}.description`, {
                            defaultValue: kind === 'record_error'
                              ? '纠正错误内容，或让 Magi 不再使用它。'
                              : kind === 'situation_changed'
                                ? '保留过去的情况，从你选择的时间开始使用新内容。'
                                : '只有在指定的项目、活动、地点或人物下才使用。',
                          })}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              {isRecordError ? (
                <fieldset>
                  <legend className="text-sm font-semibold text-foreground">
                    {t('memory.correction.recordErrorActionLabel', { defaultValue: '希望怎么处理？' })}
                  </legend>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <ChoiceButton
                      selected={draft.recordErrorAction === 'replace'}
                      onClick={() => updateDraft({ recordErrorAction: 'replace' })}
                      title={isAssertion
                        ? t('memory.correction.actions.replaceAssertion', { defaultValue: '改成正确内容' })
                        : t('memory.correction.actions.replaceRelation', { defaultValue: '关系对象写错了' })}
                      description={isAssertion
                        ? t('memory.correction.actions.replaceAssertionHint', { defaultValue: '以后使用你填写的正确内容。' })
                        : t('memory.correction.actions.replaceRelationHint', { defaultValue: '关系含义不变，改成正确的对象。' })}
                    />
                    <ChoiceButton
                      selected={draft.recordErrorAction === 'remove'}
                      onClick={() => updateDraft({ recordErrorAction: 'remove' })}
                      title={isAssertion
                        ? t('memory.correction.actions.removeAssertion', { defaultValue: '这条记忆不存在' })
                        : t('memory.correction.actions.removeRelation', { defaultValue: '这段关系不存在' })}
                      description={t('memory.correction.actions.removeHint', { defaultValue: '以后不再把它当作你的信息。' })}
                    />
                  </div>
                </fieldset>
              ) : null}

              {showReplacement ? (
                isAssertion ? (
                  <FormField
                    label={t('memory.correction.correctValue', { defaultValue: '正确内容' })}
                    htmlFor="memory-correction-value"
                    hint={isScopeRefinement
                      ? t('memory.correction.scopeValueHint', { defaultValue: '如果内容本身没错，可以保持原样。' })
                      : undefined}
                    error={validationError('value')}
                  >
                    <Input
                      id="memory-correction-value"
                      value={draft.value}
                      onChange={(event) => updateDraft({ value: event.target.value })}
                      maxLength={2000}
                      aria-invalid={Boolean(submitted && validation?.errors.value)}
                      aria-errormessage={validationError('value') ? 'memory-correction-value-error' : undefined}
                      className="h-11"
                    />
                  </FormField>
                ) : (
                  <FormField
                    label={t('memory.correction.correctRelationObject', { defaultValue: '正确的关系对象' })}
                    htmlFor="memory-correction-object"
                    hint={t('memory.correction.correctRelationObjectHint', {
                      defaultValue: '主体和关系含义保持不变，只选择正确的对象。',
                    })}
                    error={validationError('relationObjectId')}
                  >
                    <div className="space-y-2">
                      <div className="relative">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                        <Input
                          value={entitySearch}
                          onChange={(event) => setEntitySearch(event.target.value)}
                          maxLength={200}
                          aria-label={t('memory.correction.entitySearch', { defaultValue: '搜索关系对象' })}
                          placeholder={t('memory.correction.entitySearchPlaceholder', { defaultValue: '输入名称搜索全部对象' })}
                          className="h-11 pl-9"
                        />
                      </div>
                      <select
                        id="memory-correction-object"
                        value={draft.relationObjectId}
                        onChange={(event) => updateDraft({ relationObjectId: event.target.value })}
                        aria-invalid={Boolean(submitted && validation?.errors.relationObjectId)}
                        aria-errormessage={validationError('relationObjectId') ? 'memory-correction-object-error' : undefined}
                        className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      >
                        {effectiveTarget.kind === 'edge' ? effectiveTarget.entityOptions.map((entity) => (
                          <option key={entity.id} value={entity.id}>
                            {t('memory.correction.entityOption', {
                              defaultValue: '{{name}} · {{type}}',
                              name: entity.name,
                              type: formatCorrectionEntityType(entity.type, t),
                            })}
                          </option>
                        )) : null}
                      </select>
                      {entitySearchLoading ? (
                        <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                          {t('memory.correction.entitySearching', { defaultValue: '正在搜索…' })}
                        </p>
                      ) : entitySearchError ? (
                        <p className="text-xs text-amber-700 dark:text-amber-300">
                          {t('memory.correction.entitySearchFailed', { defaultValue: '暂时无法搜索更多对象，已保留当前选项。' })}
                        </p>
                      ) : null}
                    </div>
                  </FormField>
                )
              ) : null}

              {isSituationChanged ? (
                <FormField
                  label={t('memory.correction.effectiveAt', { defaultValue: '从什么时候开始变化？' })}
                  htmlFor="memory-correction-effective-at"
                  error={validationError('effectiveAt')}
                >
                  <Input
                    id="memory-correction-effective-at"
                    type="datetime-local"
                    value={draft.effectiveAt}
                    onChange={(event) => updateDraft({ effectiveAt: event.target.value })}
                    aria-invalid={Boolean(submitted && validation?.errors.effectiveAt)}
                    aria-errormessage={validationError('effectiveAt') ? 'memory-correction-effective-at-error' : undefined}
                    className="h-11"
                  />
                </FormField>
              ) : null}

              {isScopeRefinement ? (
                <fieldset>
                  <legend className="text-sm font-semibold text-foreground">
                    {t('memory.correction.scopeLabel', { defaultValue: '在什么情况下成立？' })}
                  </legend>
                  <div className="mt-3 grid gap-3 sm:grid-cols-[160px_1fr]">
                    <select
                      aria-label={t('memory.correction.scopeType', { defaultValue: '情况类型' })}
                      value={draft.scopeType}
                      onChange={(event) => updateDraft({ scopeType: event.target.value as MemoryCorrectionDraft['scopeType'] })}
                      className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    >
                      {SCOPE_TYPES.map((scopeType) => (
                        <option key={scopeType} value={scopeType}>
                          {t(`memory.correction.scopes.${scopeType}`, {
                            defaultValue: scopeType === 'project'
                              ? '某个项目'
                              : scopeType === 'activity'
                                ? '某种活动'
                                : scopeType === 'place'
                                  ? '某个地点'
                                  : '和某个人有关',
                          })}
                        </option>
                      ))}
                    </select>
                    <Input
                      id="memory-correction-scope-value"
                      aria-label={t('memory.correction.scopeValue', { defaultValue: '具体情况' })}
                      value={draft.scopeValue}
                      onChange={(event) => updateDraft({ scopeValue: event.target.value })}
                      maxLength={200}
                      placeholder={t(`memory.correction.scopePlaceholders.${draft.scopeType}`, {
                        defaultValue: draft.scopeType === 'project'
                          ? '例如：Magi'
                          : draft.scopeType === 'activity'
                            ? '例如：写代码时'
                            : draft.scopeType === 'place'
                              ? '例如：公司'
                              : '例如：和小王聊天时',
                      })}
                      aria-invalid={Boolean(submitted && validation?.errors.scopeValue)}
                      aria-errormessage={validationError('scopeValue') ? 'memory-correction-scope-value-error' : undefined}
                      className="h-11"
                    />
                  </div>
                  {validationError('scopeValue') ? (
                    <p id="memory-correction-scope-value-error" className="mt-2 text-xs leading-5 text-destructive">
                      {validationError('scopeValue')}
                    </p>
                  ) : null}
                </fieldset>
              ) : null}

              <FormField
                label={t('memory.correction.reason', { defaultValue: '补充说明（可选）' })}
                htmlFor="memory-correction-reason"
                hint={t('memory.correction.reasonHint', { defaultValue: '帮助你以后看懂这次修改为什么发生。' })}
              >
                <Textarea
                  id="memory-correction-reason"
                  value={draft.reason}
                  onChange={(event) => updateDraft({ reason: event.target.value })}
                  maxLength={2000}
                  className="min-h-20 resize-y"
                />
              </FormField>

              <div className="rounded-xl border border-blue-200/70 bg-blue-50/70 px-4 py-3 text-xs leading-5 text-blue-900 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-200">
                {isRecordError
                  ? t('memory.correction.impact.recordError', {
                      defaultValue: '保存后，之后相关的回答会使用这次修正；原始来源和修改记录仍会保留。',
                    })
                  : isSituationChanged
                    ? t('memory.correction.impact.situationChanged', {
                        defaultValue: '保存后，变化时间之前仍保留旧情况，之后使用新情况。相关内容会随后重新整理。',
                      })
                    : t('memory.correction.impact.scopeRefinement', {
                        defaultValue: '保存后，这条记忆只会在你填写的情况下使用，其他情况下不会带入回答。',
                      })}
              </div>

              {validationMessage || error ? (
                <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm leading-5 text-red-700 dark:bg-red-950/30 dark:text-red-300">
                  {error || validationMessage}
                </p>
              ) : null}
            </fieldset>

            <DialogFooter className="sticky bottom-0 bg-card/95 px-5 backdrop-blur sm:px-6">
              <Button type="button" variant="ghost" className="min-h-11" onClick={() => handleOpenChange(false)} disabled={submitting}>
                {t('memory.correction.cancel', { defaultValue: '取消' })}
              </Button>
              <Button
                type="button"
                className="min-h-11"
                onClick={() => conflicted ? handleOpenChange(false) : void handleSubmit()}
                disabled={submitting}
              >
                {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                {conflicted
                  ? t('memory.correction.viewLatest', { defaultValue: '查看最新内容' })
                  : isRecordError && draft.recordErrorAction === 'remove'
                  ? t('memory.correction.removeSubmit', { defaultValue: '确认不再使用' })
                  : t('memory.correction.save', { defaultValue: '保存修正' })}
              </Button>
            </DialogFooter>
          </>
        )}
        </DialogContent>
      </Dialog>

      <Dialog open={discardConfirmOpen} onOpenChange={setDiscardConfirmOpen}>
        <DialogContent
          hideClose
          overlayClassName="bg-foreground/25 backdrop-blur-[3px]"
          className="max-w-[420px] overflow-hidden rounded-xl p-0"
        >
          <DialogHeader className="px-6 pb-3 pt-6">
            <div className="flex items-start gap-4">
              <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <DialogTitle className="text-lg leading-7">
                  {t('memory.correction.discard.title', { defaultValue: '放弃未保存的修改？' })}
                </DialogTitle>
                <DialogDescription className="mt-1 leading-6">
                  {t('memory.correction.discard.description', {
                    defaultValue: '你刚才填写的内容还没有保存，关闭后会丢失。',
                  })}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>
          <DialogFooter className="px-6 pb-6 pt-2">
            <Button type="button" variant="ghost" onClick={() => setDiscardConfirmOpen(false)}>
              {t('memory.correction.discard.keepEditing', { defaultValue: '继续修改' })}
            </Button>
            <Button type="button" variant="destructive" onClick={discardAndClose}>
              {t('memory.correction.discard.confirm', { defaultValue: '放弃修改' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ChoiceButton({
  selected,
  onClick,
  title,
  description,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  description: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        'min-h-16 rounded-xl border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected ? 'border-primary/45 bg-primary/8' : 'border-border/70 hover:bg-muted/45'
      )}
    >
      <span className="block text-sm font-semibold text-foreground">{title}</span>
      <span className="mt-1 block text-xs leading-5 text-muted-foreground">{description}</span>
    </button>
  );
}

function FormField({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="text-sm font-semibold text-foreground">{label}</label>
      {hint ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{hint}</p> : null}
      <div className="mt-2">{children}</div>
      {error ? (
        <p id={`${htmlFor}-error`} className="mt-2 text-xs leading-5 text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function CorrectionSuccess({
  target,
  result,
  onDone,
}: {
  target: MemoryCorrectionUiTarget;
  result: MemoryCorrectionCommandResponse;
  onDone: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const hasReplacement = Boolean(result.correction.replacement_target_id);
  const currentValue = hasReplacement ? getReadableCurrentClaim(target, result.current_claim) : null;
  const locale = correctionLocale(i18n.resolvedLanguage || i18n.language);
  const effectiveAt = result.correction.effective_at
    ? formatCorrectionTime(result.correction.effective_at, locale)
    : null;
  const scope = formatCorrectionScope(result.correction.scope, t);
  const isFutureChange = Boolean(
    result.correction.effective_at
      && result.correction.effective_at > Date.now() / 1000 + 1
  );
  const wasPendingReview = isPendingReviewClaim(result.correction.before);

  return (
    <div className="px-6 py-8 sm:px-8 sm:py-10" role="status" aria-live="polite">
      <div className="mx-auto max-w-lg text-center">
        <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-600" aria-hidden="true" />
        <DialogTitle className="mt-4 text-xl">
          {t('memory.correction.success.title', { defaultValue: '已经按你的意思修正' })}
        </DialogTitle>
        <DialogDescription className="mt-2 leading-6">
          {hasReplacement
            ? isFutureChange
              ? t('memory.correction.success.replacedInFuture', { defaultValue: '到设定时间后，相关回答会使用下面这条理解。' })
              : t('memory.correction.success.replaced', { defaultValue: '之后相关的回答会使用下面这条当前理解。' })
            : wasPendingReview
              ? t('memory.correction.success.removedPending', {
                  defaultValue: '已经把这条待确认内容标为不准确，之后不会用它来了解你。',
                })
              : t('memory.correction.success.removed', { defaultValue: '之后不会再把原来的内容当作你的信息。' })}
        </DialogDescription>
        {currentValue ? (
          <div className="mt-5 rounded-xl bg-muted/55 px-4 py-4 text-left">
            <div className="text-xs font-semibold text-muted-foreground">
              {isFutureChange
                ? t('memory.correction.success.futureLabel', { defaultValue: '从设定时间起会这样理解' })
                : t('memory.correction.success.currentLabel', { defaultValue: '现在会这样理解' })}
            </div>
            <p className="mt-2 text-sm font-medium leading-6 text-foreground">{currentValue}</p>
          </div>
        ) : null}
        {effectiveAt || scope ? (
          <dl className="mt-4 space-y-2 rounded-xl border border-border/65 px-4 py-3 text-left text-xs leading-5">
            {effectiveAt ? (
              <div className="flex gap-2">
                <dt className="shrink-0 text-muted-foreground">
                  {t('memory.correction.success.effectiveAt', { defaultValue: '从什么时候起' })}
                </dt>
                <dd className="font-medium text-foreground">{effectiveAt}</dd>
              </div>
            ) : null}
            {scope ? (
              <div className="flex gap-2">
                <dt className="shrink-0 text-muted-foreground">
                  {t('memory.correction.success.scope', { defaultValue: '在什么情况下' })}
                </dt>
                <dd className="font-medium text-foreground">{scope}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
        {isFutureChange ? (
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            {t('memory.correction.success.scheduledUpdate', { defaultValue: '到设定时间后，相关总结会自动更新。' })}
          </p>
        ) : result.derivation_state === 'failed' ? (
          <p className="mt-4 text-xs leading-5 text-amber-700 dark:text-amber-300">
            {t('memory.correction.success.backgroundUpdateFailed', {
              defaultValue: '这次修正已经生效，但相关总结暂时没能更新；你可以稍后再查看。',
            })}
          </p>
        ) : result.derivation_state !== 'completed' ? (
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            {t('memory.correction.success.backgroundUpdate', { defaultValue: '相关总结会在后台继续更新，不影响这次修正生效。' })}
          </p>
        ) : null}
        <Button type="button" className="mt-7 min-h-11 min-w-28" onClick={onDone}>
          {t('memory.correction.success.done', { defaultValue: '完成' })}
        </Button>
      </div>
    </div>
  );
}

async function runCallback(
  callback: (() => void | Promise<void>) | undefined,
  failureMessage: string
): Promise<void> {
  if (!callback) return;
  try {
    await callback();
  } catch (error) {
    console.error(failureMessage, error);
  }
}

function correctionValidationCode(details: unknown): string | null {
  if (!details || typeof details !== 'object' || Array.isArray(details)) return null;
  const code = (details as Record<string, unknown>).code;
  return typeof code === 'string' ? code : null;
}

function correctionValidationFallback(code: string): string {
  const messages: Record<string, string> = {
    replacement_required: '请填写正确内容。',
    replacement_unchanged: '新内容和当前内容相同，请填写实际变化后的内容。',
    effective_at_required: '请选择变化开始的时间。',
    effective_at_invalid: '变化时间无效，请重新选择。',
    scope_required: '请填写具体适用的情况。',
    relation_object_required: '请选择正确的关系对象。',
    relation_object_unchanged: '请选择一个与当前不同的对象。',
    relation_object_unavailable: '这个对象目前不可用，请重新选择。',
  };
  return messages[code] ?? '请检查填写内容后再保存。';
}

function correctionDraftFingerprint(draft: MemoryCorrectionDraft): string {
  return JSON.stringify({
    correctionKind: draft.correctionKind,
    recordErrorAction: draft.recordErrorAction,
    value: draft.value,
    effectiveAt: draft.effectiveAt,
    scopeType: draft.scopeType,
    scopeValue: draft.scopeValue,
    reason: draft.reason,
    relationObjectId: draft.relationObjectId,
  });
}

function focusFirstInvalidCorrectionField(errors: MemoryCorrectionValidationErrors): void {
  const firstInvalidField = (Object.keys(CORRECTION_FIELD_IDS) as MemoryCorrectionValidationField[])
    .find((field) => Boolean(errors[field]));
  if (firstInvalidField) focusCorrectionField(firstInvalidField);
}

function focusCorrectionField(field: MemoryCorrectionValidationField): void {
  const focus = () => document.getElementById(CORRECTION_FIELD_IDS[field])?.focus();
  if (typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(focus);
  } else {
    window.setTimeout(focus, 0);
  }
}

function isPendingReviewClaim(claim: Record<string, unknown>): boolean {
  const lifecycle = String(claim.status ?? claim.validation_state ?? '').trim().toLowerCase();
  return lifecycle === 'shadow' || lifecycle === 'pending';
}

function mergeEntityOptions(
  ...groups: MemoryCorrectionEntityOption[][]
): MemoryCorrectionEntityOption[] {
  const merged = new Map<string, MemoryCorrectionEntityOption>();
  for (const group of groups) {
    for (const option of group) {
      if (!option?.id) continue;
      merged.set(option.id, option);
    }
  }
  return [...merged.values()].sort((left, right) => left.name.localeCompare(right.name));
}

function getReadableCurrentClaim(
  target: MemoryCorrectionUiTarget,
  claim: Record<string, unknown> | null | undefined
): string | null {
  if (!claim) return null;
  if (target.kind === 'assertion') {
    const value = formatMemoryCorrectionValue(claim.trait_value ?? claim.value);
    return value || null;
  }

  const objectId = String(claim.object_id ?? '').trim();
  const objectName = target.entityOptions.find((entity) => entity.id === objectId)?.name;
  if (!objectName) return target.statement;
  return `${target.relationship.subjectName} ${target.relationship.predicateLabel} ${objectName}`;
}

export default MemoryCorrectionDialog;
