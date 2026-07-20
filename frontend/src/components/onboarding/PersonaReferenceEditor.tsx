import { useMemo, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type {
  PersonaAdaptationMode,
  PersonaIntentResolution,
  PersonaReferenceCandidate,
  PersonaReferenceKind,
} from '../../api/modules/personas';

export interface EditablePersonaReference {
  sourceKind: 'original' | PersonaReferenceKind;
  name: string;
  workTitle: string;
  version: string;
  context: string;
}

interface PersonaReferenceEditorProps {
  resolution: PersonaIntentResolution;
  value: EditablePersonaReference;
  adaptationMode: PersonaAdaptationMode;
  constraintsText: string;
  disabled: boolean;
  onChange: (value: EditablePersonaReference) => void;
  onAdaptationModeChange: (mode: PersonaAdaptationMode) => void;
  onConstraintsTextChange: (value: string) => void;
}

interface ModeOption {
  value: PersonaAdaptationMode;
  titleKey: string;
  descriptionKey: string;
  recommended?: boolean;
}

const MODE_OPTIONS: Record<PersonaReferenceKind, ModeOption[]> = {
  fictional_reference: [
    {
      value: 'fictional_inspired',
      titleKey: 'personaPreview.reference.modes.fictionalInspired.title',
      descriptionKey: 'personaPreview.reference.modes.fictionalInspired.description',
    },
    {
      value: 'fictional_natural',
      titleKey: 'personaPreview.reference.modes.fictionalNatural.title',
      descriptionKey: 'personaPreview.reference.modes.fictionalNatural.description',
      recommended: true,
    },
    {
      value: 'fictional_immersive',
      titleKey: 'personaPreview.reference.modes.fictionalImmersive.title',
      descriptionKey: 'personaPreview.reference.modes.fictionalImmersive.description',
    },
  ],
  public_person_reference: [
    {
      value: 'public_traits',
      titleKey: 'personaPreview.reference.modes.publicTraits.title',
      descriptionKey: 'personaPreview.reference.modes.publicTraits.description',
    },
    {
      value: 'public_expression',
      titleKey: 'personaPreview.reference.modes.publicExpression.title',
      descriptionKey: 'personaPreview.reference.modes.publicExpression.description',
      recommended: true,
    },
    {
      value: 'public_image',
      titleKey: 'personaPreview.reference.modes.publicImage.title',
      descriptionKey: 'personaPreview.reference.modes.publicImage.description',
    },
  ],
  private_person_reference: [
    {
      value: 'private_traits',
      titleKey: 'personaPreview.reference.modes.privateTraits.title',
      descriptionKey: 'personaPreview.reference.modes.privateTraits.description',
      recommended: true,
    },
  ],
};

function candidateLabel(candidate: PersonaReferenceCandidate): string {
  return [
    candidate.name,
    candidate.work_title ? `《${candidate.work_title}》` : '',
    candidate.version || '',
  ].filter(Boolean).join(' · ');
}

export function defaultAdaptationMode(
  sourceKind: EditablePersonaReference['sourceKind'],
): PersonaAdaptationMode {
  if (sourceKind === 'fictional_reference') return 'fictional_natural';
  if (sourceKind === 'public_person_reference') return 'public_expression';
  if (sourceKind === 'private_person_reference') return 'private_traits';
  return 'original';
}

export function candidateToEditableReference(
  candidate: PersonaReferenceCandidate,
): EditablePersonaReference {
  return {
    sourceKind: candidate.source_kind,
    name: candidate.name,
    workTitle: candidate.work_title || '',
    version: candidate.version || '',
    context: candidate.context || '',
  };
}

export function PersonaReferenceEditor({
  resolution,
  value,
  adaptationMode,
  constraintsText,
  disabled,
  onChange,
  onAdaptationModeChange,
  onConstraintsTextChange,
}: PersonaReferenceEditorProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const options = useMemo(
    () => value.sourceKind === 'original' ? [] : MODE_OPTIONS[value.sourceKind],
    [value.sourceKind],
  );
  const hasSelectedCandidate = resolution.candidates.some(
    (candidate) =>
      value.sourceKind === candidate.source_kind &&
      value.name === candidate.name &&
      value.workTitle === (candidate.work_title || '') &&
      value.version === (candidate.version || ''),
  );
  const otherSelected = resolution.candidates.length > 1 && !hasSelectedCandidate;

  return (
    <div
      data-testid="persona-reference-editor"
      className="mt-6 space-y-7"
    >
      <div className="max-w-2xl">
        <h4 className="text-base font-semibold tracking-[-0.01em] text-foreground">
          {resolution.status === 'ambiguous'
            ? t('personaPreview.reference.ambiguousTitle')
            : resolution.status === 'unknown'
              ? t('personaPreview.reference.unknownTitle')
              : t('personaPreview.reference.reviewTitle')}
        </h4>
        <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
          {t('personaPreview.reference.reviewHint')}
        </p>
      </div>

      {resolution.candidates.length > 1 && (
        <div
          className="grid gap-1 sm:grid-cols-2"
          role="radiogroup"
          aria-label={t('personaPreview.reference.candidatesLabel')}
        >
          {resolution.candidates.map((candidate) => {
            const selected =
              value.sourceKind === candidate.source_kind &&
              value.name === candidate.name &&
              value.workTitle === (candidate.work_title || '') &&
              value.version === (candidate.version || '');
            return (
              <button
                key={candidate.candidate_id}
                type="button"
                data-testid={`persona-reference-candidate-${candidate.candidate_id}`}
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => {
                  const next = candidateToEditableReference(candidate);
                  onChange(next);
                }}
                className={cn(
                  'group flex min-w-0 items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm transition-[background-color,color] duration-200',
                  selected
                    ? 'bg-muted/70 text-foreground'
                    : 'text-muted-foreground hover:bg-muted/35 hover:text-foreground',
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    'flex h-4 w-4 shrink-0 items-center justify-center rounded-full ring-1 transition-colors',
                    selected
                      ? 'ring-primary/55'
                      : 'ring-border group-hover:ring-foreground/25',
                  )}
                >
                  <span
                    className={cn(
                      'h-1.5 w-1.5 rounded-full bg-primary transition-opacity',
                      selected ? 'opacity-100' : 'opacity-0',
                    )}
                  />
                </span>
                <span className="min-w-0 truncate font-medium">
                  {candidateLabel(candidate)}
                </span>
              </button>
            );
          })}
          <button
            type="button"
            data-testid="persona-reference-other"
            role="radio"
            aria-checked={otherSelected}
            disabled={disabled}
            onClick={() => {
              onChange({
                sourceKind: 'fictional_reference',
                name: '',
                workTitle: '',
                version: '',
                context: '',
              });
            }}
            className={cn(
              'group flex items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm transition-[background-color,color] duration-200',
              otherSelected
                ? 'bg-muted/70 text-foreground'
                : 'text-muted-foreground hover:bg-muted/35 hover:text-foreground',
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                'flex h-4 w-4 shrink-0 items-center justify-center rounded-full ring-1 transition-colors',
                otherSelected
                  ? 'ring-primary/55'
                  : 'ring-border group-hover:ring-foreground/25',
              )}
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full bg-primary transition-opacity',
                  otherSelected ? 'opacity-100' : 'opacity-0',
                )}
              />
            </span>
            <span className="font-medium">{t('personaPreview.reference.other')}</span>
          </button>
        </div>
      )}

      <section className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="text-xs font-medium text-muted-foreground">
            <span>{t('personaPreview.reference.sourceKind')}</span>
            <Select
              value={value.sourceKind}
              disabled={disabled}
              onValueChange={(nextValue) => {
                const sourceKind = nextValue as EditablePersonaReference['sourceKind'];
                const keepsFictionalFields =
                  sourceKind === 'fictional_reference' &&
                  value.sourceKind === 'fictional_reference';
                onChange({
                  ...value,
                  sourceKind,
                  name: sourceKind === 'original' ? '' : value.name,
                  workTitle: keepsFictionalFields ? value.workTitle : '',
                  version: keepsFictionalFields ? value.version : '',
                });
              }}
            >
              <SelectTrigger
                data-testid="persona-reference-source-kind"
                aria-label={t('personaPreview.reference.sourceKind')}
                className="mt-1.5"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="original">
                  {t('personaPreview.reference.sourceKinds.original')}
                </SelectItem>
                <SelectItem value="fictional_reference">
                  {t('personaPreview.reference.sourceKinds.fictional')}
                </SelectItem>
                <SelectItem value="public_person_reference">
                  {t('personaPreview.reference.sourceKinds.publicPerson')}
                </SelectItem>
                <SelectItem value="private_person_reference">
                  {t('personaPreview.reference.sourceKinds.privatePerson')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {value.sourceKind !== 'original' && (
            <label className="text-xs font-medium text-muted-foreground">
              {t('personaPreview.reference.name')}
              <input
                data-testid="persona-reference-name"
                value={value.name}
                disabled={disabled}
                onChange={(event) => onChange({ ...value, name: event.target.value })}
                className="mt-1.5 h-10 w-full rounded-md bg-muted/35 px-3 text-sm text-foreground outline-none transition-[background-color,box-shadow] duration-200 hover:bg-muted/55 focus:bg-background focus:ring-2 focus:ring-primary/15"
              />
            </label>
          )}

          {value.sourceKind === 'fictional_reference' && (
            <label className="text-xs font-medium text-muted-foreground">
              {t('personaPreview.reference.workTitle')}
              <input
                data-testid="persona-reference-work"
                value={value.workTitle}
                disabled={disabled}
                onChange={(event) => onChange({ ...value, workTitle: event.target.value })}
                className="mt-1.5 h-10 w-full rounded-md bg-muted/35 px-3 text-sm text-foreground outline-none transition-[background-color,box-shadow] duration-200 hover:bg-muted/55 focus:bg-background focus:ring-2 focus:ring-primary/15"
              />
            </label>
          )}

          {value.sourceKind === 'private_person_reference' && (
            <label className="block text-xs font-medium text-muted-foreground sm:col-span-2">
              {t('personaPreview.reference.privateDetails')}
              <textarea
                data-testid="persona-reference-context"
                value={value.context}
                disabled={disabled}
                rows={2}
                onChange={(event) => onChange({ ...value, context: event.target.value })}
                placeholder={t('personaPreview.reference.privateDetailsPlaceholder')}
                className="mt-1.5 w-full resize-none rounded-md bg-muted/35 px-3 py-2 text-sm leading-6 text-foreground outline-none transition-[background-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 hover:bg-muted/55 focus:bg-background focus:ring-2 focus:ring-primary/15"
              />
            </label>
          )}
        </div>
      </section>

      {value.sourceKind !== 'original' && options.length > 0 && (
        <fieldset>
          <legend className="text-sm font-semibold text-foreground">
            {t('personaPreview.reference.modeTitle')}
          </legend>
          <div className="mt-2 space-y-1" role="radiogroup">
            {options.map((option) => {
              const selected = adaptationMode === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  data-testid={`persona-reference-mode-${option.value}`}
                  aria-checked={selected}
                  disabled={disabled}
                  onClick={() => onAdaptationModeChange(option.value)}
                  className={cn(
                    'group flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition-[background-color,color] duration-200',
                    selected ? 'bg-muted/70' : 'hover:bg-muted/35',
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ring-1 transition-colors',
                      selected
                        ? 'ring-primary/55'
                        : 'ring-border group-hover:ring-foreground/25',
                    )}
                  >
                    <span
                      className={cn(
                        'h-1.5 w-1.5 rounded-full bg-primary transition-opacity',
                        selected ? 'opacity-100' : 'opacity-0',
                      )}
                    />
                  </span>
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-foreground">
                      {t(option.titleKey)}
                      {option.recommended && (
                        <span className="text-[11px] font-normal text-primary/80">
                          · {t('personaPreview.reference.recommended')}
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                      {t(option.descriptionKey)}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>
      )}

      <div>
        <button
          type="button"
          data-testid="persona-reference-advanced-toggle"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
          className="group flex items-center gap-2 rounded-md py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15"
        >
          {t('personaPreview.reference.moreSettings')}
          <ChevronDown
            aria-hidden="true"
            className={cn(
              'h-4 w-4 transition-transform duration-200 motion-reduce:transition-none',
              advancedOpen && 'rotate-180',
            )}
          />
        </button>
        <div
          aria-hidden={!advancedOpen}
          className={cn(
            'grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none',
            advancedOpen
              ? 'grid-rows-[1fr] opacity-100'
              : 'pointer-events-none grid-rows-[0fr] opacity-0',
          )}
        >
          <div className="min-h-0 overflow-hidden">
            <div className="grid gap-3 pt-3 sm:grid-cols-2">
              {value.sourceKind === 'fictional_reference' && (
                <label className="text-xs font-medium text-muted-foreground">
                  {t('personaPreview.reference.version')}
                  <input
                    data-testid="persona-reference-version"
                    value={value.version}
                    disabled={disabled || !advancedOpen}
                    onChange={(event) => onChange({ ...value, version: event.target.value })}
                    placeholder={t('personaPreview.reference.versionPlaceholder')}
                    className="mt-1.5 h-10 w-full rounded-md bg-muted/35 px-3 text-sm text-foreground outline-none transition-[background-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 hover:bg-muted/55 focus:bg-background focus:ring-2 focus:ring-primary/15"
                  />
                </label>
              )}

              {value.sourceKind !== 'original' &&
                value.sourceKind !== 'private_person_reference' && (
                  <label
                    className={cn(
                      'block text-xs font-medium text-muted-foreground',
                      value.sourceKind !== 'fictional_reference' && 'sm:col-span-2',
                    )}
                  >
                    {t('personaPreview.reference.context')}
                    <textarea
                      data-testid="persona-reference-context"
                      value={value.context}
                      disabled={disabled || !advancedOpen}
                      rows={2}
                      onChange={(event) => onChange({ ...value, context: event.target.value })}
                      placeholder={t('personaPreview.reference.contextPlaceholder')}
                      className="mt-1.5 w-full resize-none rounded-md bg-muted/35 px-3 py-2 text-sm leading-6 text-foreground outline-none transition-[background-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 hover:bg-muted/55 focus:bg-background focus:ring-2 focus:ring-primary/15"
                    />
                  </label>
                )}

              <label className="block text-xs font-medium text-muted-foreground sm:col-span-2">
                {t('personaPreview.reference.constraints')}
                <textarea
                  data-testid="persona-reference-constraints"
                  value={constraintsText}
                  disabled={disabled || !advancedOpen}
                  rows={2}
                  onChange={(event) => onConstraintsTextChange(event.target.value)}
                  placeholder={t('personaPreview.reference.constraintsPlaceholder')}
                  className="mt-1.5 w-full resize-none rounded-md bg-muted/35 px-3 py-2 text-sm leading-6 text-foreground outline-none transition-[background-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 hover:bg-muted/55 focus:bg-background focus:ring-2 focus:ring-primary/15"
                />
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
