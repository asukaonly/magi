import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
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
  const options = useMemo(
    () => value.sourceKind === 'original' ? [] : MODE_OPTIONS[value.sourceKind],
    [value.sourceKind],
  );

  return (
    <div
      data-testid="persona-reference-editor"
      className="mt-4 space-y-4 rounded-lg border border-border/55 bg-background/75 p-4"
    >
      <div>
        <h4 className="text-sm font-semibold text-foreground">
          {resolution.status === 'ambiguous'
            ? t('personaPreview.reference.ambiguousTitle')
            : resolution.status === 'unknown'
              ? t('personaPreview.reference.unknownTitle')
              : t('personaPreview.reference.reviewTitle')}
        </h4>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {t('personaPreview.reference.reviewHint')}
        </p>
      </div>

      {resolution.candidates.length > 1 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('personaPreview.reference.candidatesLabel')}>
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
                aria-pressed={selected}
                disabled={disabled}
                onClick={() => {
                  const next = candidateToEditableReference(candidate);
                  onChange(next);
                }}
                className={cn(
                  'rounded-full border px-3 py-1.5 text-sm transition-colors',
                  selected
                    ? 'border-primary/50 bg-primary/10 text-foreground'
                    : 'border-border text-muted-foreground hover:bg-muted',
                )}
              >
                {candidateLabel(candidate)}
              </button>
            );
          })}
          <button
            type="button"
            data-testid="persona-reference-other"
            aria-pressed={false}
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
            className="rounded-full border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted"
          >
            {t('personaPreview.reference.other')}
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-muted-foreground">
          {t('personaPreview.reference.sourceKind')}
          <select
            data-testid="persona-reference-source-kind"
            value={value.sourceKind}
            disabled={disabled}
            onChange={(event) => {
              const sourceKind = event.target.value as EditablePersonaReference['sourceKind'];
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
            className="mt-1.5 w-full rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="original">{t('personaPreview.reference.sourceKinds.original')}</option>
            <option value="fictional_reference">{t('personaPreview.reference.sourceKinds.fictional')}</option>
            <option value="public_person_reference">{t('personaPreview.reference.sourceKinds.publicPerson')}</option>
            <option value="private_person_reference">{t('personaPreview.reference.sourceKinds.privatePerson')}</option>
          </select>
        </label>

        {value.sourceKind !== 'original' && (
          <label className="text-xs font-medium text-muted-foreground">
            {t('personaPreview.reference.name')}
            <input
              data-testid="persona-reference-name"
              value={value.name}
              disabled={disabled}
              onChange={(event) => onChange({ ...value, name: event.target.value })}
              className="mt-1.5 w-full rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground"
            />
          </label>
        )}

        {value.sourceKind === 'fictional_reference' && (
          <>
            <label className="text-xs font-medium text-muted-foreground">
              {t('personaPreview.reference.workTitle')}
              <input
                data-testid="persona-reference-work"
                value={value.workTitle}
                disabled={disabled}
                onChange={(event) => onChange({ ...value, workTitle: event.target.value })}
                className="mt-1.5 w-full rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground"
              />
            </label>
            <label className="text-xs font-medium text-muted-foreground">
              {t('personaPreview.reference.version')}
              <input
                data-testid="persona-reference-version"
                value={value.version}
                disabled={disabled}
                onChange={(event) => onChange({ ...value, version: event.target.value })}
                placeholder={t('personaPreview.reference.versionPlaceholder')}
                className="mt-1.5 w-full rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60"
              />
            </label>
          </>
        )}
      </div>

      {value.sourceKind !== 'original' && (
        <>
          <label className="block text-xs font-medium text-muted-foreground">
            {value.sourceKind === 'private_person_reference'
              ? t('personaPreview.reference.privateDetails')
              : t('personaPreview.reference.context')}
            <textarea
              data-testid="persona-reference-context"
              value={value.context}
              disabled={disabled}
              rows={2}
              onChange={(event) => onChange({ ...value, context: event.target.value })}
              placeholder={
                value.sourceKind === 'private_person_reference'
                  ? t('personaPreview.reference.privateDetailsPlaceholder')
                  : t('personaPreview.reference.contextPlaceholder')
              }
              className="mt-1.5 w-full rounded-md border border-border/55 bg-background px-3 py-2 text-sm leading-6 text-foreground placeholder:text-muted-foreground/60"
            />
          </label>

          <fieldset>
            <legend className="text-xs font-medium text-muted-foreground">
              {t('personaPreview.reference.modeTitle')}
            </legend>
            <div className="mt-2 grid gap-2 lg:grid-cols-3">
              {options.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  data-testid={`persona-reference-mode-${option.value}`}
                  aria-pressed={adaptationMode === option.value}
                  disabled={disabled}
                  onClick={() => onAdaptationModeChange(option.value)}
                  className={cn(
                    'rounded-lg border p-3 text-left transition-colors',
                    adaptationMode === option.value
                      ? 'border-primary/50 bg-primary/10'
                      : 'border-border/55 bg-background hover:bg-muted/50',
                  )}
                >
                  <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                    {t(option.titleKey)}
                    {option.recommended && (
                      <span className="text-[10px] font-normal text-primary">
                        {t('personaPreview.reference.recommended')}
                      </span>
                    )}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {t(option.descriptionKey)}
                  </span>
                </button>
              ))}
            </div>
          </fieldset>
        </>
      )}

      <label className="block text-xs font-medium text-muted-foreground">
        {t('personaPreview.reference.constraints')}
        <textarea
          data-testid="persona-reference-constraints"
          value={constraintsText}
          disabled={disabled}
          rows={2}
          onChange={(event) => onConstraintsTextChange(event.target.value)}
          placeholder={t('personaPreview.reference.constraintsPlaceholder')}
          className="mt-1.5 w-full rounded-md border border-border/55 bg-background px-3 py-2 text-sm leading-6 text-foreground placeholder:text-muted-foreground/60"
        />
      </label>
    </div>
  );
}
