import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ChevronDown, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

type LLMProviderModelKind = 'chat' | 'embedding' | 'image';

interface LLMProviderModelToolbarProps {
  providerId: string;
  isCustomProvider: boolean;
  isSettingsSurface: boolean;
  modelDraft: string;
  modelDraftKind: LLMProviderModelKind;
  discoveryLoading: boolean;
  onModelDraftChange: (value: string) => void;
  onModelDraftKindChange: (kind: LLMProviderModelKind) => void;
  onAddProviderModel: (providerId: string, model: string, kind: LLMProviderModelKind) => void;
  onDiscoverProviderModels: (providerId: string) => void;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export function LLMProviderModelToolbar({
  providerId,
  isCustomProvider,
  isSettingsSurface,
  modelDraft,
  modelDraftKind,
  discoveryLoading,
  onModelDraftChange,
  onModelDraftKindChange,
  onAddProviderModel,
  onDiscoverProviderModels,
}: LLMProviderModelToolbarProps) {
  const { t } = useTranslation('onboarding');
  const [kindMenuOpen, setKindMenuOpen] = useState(false);
  const kindMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setKindMenuOpen(false);
  }, [providerId]);

  useEffect(() => {
    if (!kindMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!kindMenuRef.current?.contains(event.target as Node)) {
        setKindMenuOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setKindMenuOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [kindMenuOpen]);

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div className="space-y-2 sm:w-fit">
        <span className="text-sm font-medium">{t('llm.fields.modelKind')}</span>
        <div className="relative" ref={kindMenuRef}>
          <button
            type="button"
            aria-haspopup="listbox"
            aria-expanded={kindMenuOpen}
            onClick={() => setKindMenuOpen((current) => !current)}
            className={cn(
              'inline-flex h-11 min-w-[160px] items-center justify-between gap-2 whitespace-nowrap rounded-md bg-[hsl(var(--settings-shell-elevated)/0.58)] px-3.5 text-sm font-medium text-foreground transition hover:bg-[hsl(var(--settings-shell-elevated)/0.82)]',
              isSettingsSurface && 'border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
            )}
          >
            <span>{t(`llm.modelKinds.${modelDraftKind}`)}</span>
            <ChevronDown className={cn('h-4 w-4 opacity-65 transition', kindMenuOpen && 'rotate-180')} />
          </button>

          {kindMenuOpen ? (
            <div
              role="listbox"
              className="absolute left-0 top-full z-20 mt-2 w-[min(220px,calc(100vw-2rem))] overflow-hidden rounded-[16px] border border-border/70 bg-background py-1.5 shadow-[0_18px_42px_rgba(15,23,42,0.16)]"
            >
              {(['chat', 'embedding', 'image'] as const).map((kindValue) => {
                const isSelected = modelDraftKind === kindValue;
                return (
                  <button
                    key={kindValue}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      onModelDraftKindChange(kindValue);
                      setKindMenuOpen(false);
                    }}
                    className={cn(
                      'flex w-full items-center justify-between px-3 py-2.5 text-left text-sm text-foreground transition',
                      isSelected ? 'bg-muted/80' : 'hover:bg-muted/50'
                    )}
                  >
                    <span>{t(`llm.modelKinds.${kindValue}`)}</span>
                    {isSelected ? <CheckCircle2 className="h-4 w-4 text-primary" /> : null}
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>

      <label className="flex-1 space-y-2">
        <span className="text-sm font-medium">
          {modelDraftKind === 'embedding'
            ? t('llm.fields.modelManualEntryEmbedding')
            : modelDraftKind === 'image'
              ? t('llm.fields.modelManualEntryImage')
              : t('llm.fields.modelManualEntryChat')}
        </span>
        <input
          aria-label={t('llm.fields.modelManualEntry')}
          className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
          placeholder={
            modelDraftKind === 'embedding'
              ? t('llm.fields.modelManualEntryEmbeddingPlaceholder')
              : modelDraftKind === 'image'
                ? t('llm.imageGenerationModelPlaceholder')
                : t('llm.fields.modelManualEntryPlaceholder')
          }
          value={modelDraft}
          onChange={(event) => onModelDraftChange(event.target.value)}
        />
      </label>

      <button
        type="button"
        onClick={() => {
          onAddProviderModel(providerId, modelDraft, modelDraftKind);
          onModelDraftChange('');
        }}
        className={cn(
          'inline-flex h-11 min-w-fit items-center justify-center whitespace-nowrap rounded-lg bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent',
          isSettingsSurface && 'rounded-md border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
        )}
      >
        {t('llm.actions.addModel')}
      </button>

      {isCustomProvider && modelDraftKind !== 'image' ? (
        <button
          type="button"
          onClick={() => onDiscoverProviderModels(providerId)}
          disabled={discoveryLoading}
          className={cn(
            'inline-flex h-11 min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60',
            isSettingsSurface && 'rounded-md border border-[hsl(var(--settings-subnav-border)/0.8)] bg-transparent hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
          )}
        >
          {discoveryLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          <span>{t('llm.actions.fetchModels')}</span>
        </button>
      ) : null}
    </div>
  );
}

export type { LLMProviderModelKind };