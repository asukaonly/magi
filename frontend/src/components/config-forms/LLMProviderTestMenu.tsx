import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Loader2, PlugZap, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { ProviderWorkbenchModelItem } from '@/components/config-forms/llm-provider-workbench-models';
import { cn } from '@/lib/utils';

interface LLMProviderTestMenuProps {
  providerId: string;
  isTesting: boolean;
  testableModels: ProviderWorkbenchModelItem[];
  selectedModelId: string;
  onSelectedModelChange: (providerId: string, modelId: string) => void;
  onTestProviderConnection: (providerId: string, model: string) => void;
}

export function LLMProviderTestMenu({
  providerId,
  isTesting,
  testableModels,
  selectedModelId,
  onSelectedModelChange,
  onTestProviderConnection,
}: LLMProviderTestMenuProps) {
  const { t } = useTranslation('onboarding');
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState('');
  const menuRef = useRef<HTMLDivElement | null>(null);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredModels = useMemo(
    () =>
      normalizedQuery
        ? testableModels.filter((model) => {
            const label = model.label.toLowerCase();
            const value = model.id.toLowerCase();
            return label.includes(normalizedQuery) || value.includes(normalizedQuery);
          })
        : testableModels,
    [normalizedQuery, testableModels]
  );

  useEffect(() => {
    setMenuOpen(false);
    setQuery('');
  }, [providerId]);

  useEffect(() => {
    if (!menuOpen && query) {
      setQuery('');
    }
  }, [menuOpen, query]);

  useEffect(() => {
    if (!menuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [menuOpen]);

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={menuOpen}
        aria-controls={menuOpen ? `provider-test-menu-${providerId}` : undefined}
        onClick={() => {
          if (isTesting || !testableModels.length) {
            return;
          }
          setMenuOpen((current) => !current);
        }}
        disabled={isTesting || !testableModels.length}
        className="inline-flex min-w-fit items-center justify-center gap-2 whitespace-nowrap rounded-md bg-[hsl(var(--settings-shell-elevated)/0.58)] px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-[hsl(var(--settings-shell-elevated)/0.82)] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
        <span>{isTesting ? t('llm.actions.testingConnection') : t('llm.actions.testConnection')}</span>
        {!isTesting ? <ChevronDown className="h-4 w-4 opacity-65" /> : null}
      </button>

      {menuOpen ? (
        <div
          id={`provider-test-menu-${providerId}`}
          data-testid="llm-provider-test-model-menu"
          className="absolute right-0 top-full z-20 mt-2 w-[min(320px,calc(100vw-2rem))] overflow-hidden rounded-[20px] border border-border/70 bg-background shadow-[0_18px_42px_rgba(15,23,42,0.16)]"
        >
          <div className="border-b border-border/60 px-3 py-3">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                aria-label={t('llm.providerConfiguration.testModelLabel')}
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('llm.providerConfiguration.testModelSearchPlaceholder')}
                className="h-11 w-full rounded-xl bg-background px-10 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
              />
            </label>
          </div>

          <div className="max-h-80 overflow-y-auto px-2 py-2">
            {filteredModels.length ? (
              filteredModels.map((model) => {
                const isSelected = model.id === selectedModelId;
                return (
                  <button
                    key={model.id}
                    type="button"
                    onClick={() => {
                      onSelectedModelChange(providerId, model.id);
                      setMenuOpen(false);
                      setQuery('');
                      onTestProviderConnection(providerId, model.id);
                    }}
                    className={cn(
                      'flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left text-base text-foreground transition',
                      isSelected
                        ? 'bg-muted/80 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.18)]'
                        : 'hover:bg-muted/50'
                    )}
                  >
                    <span className="truncate">{model.label}</span>
                    <span className="ml-3 shrink-0 text-xs text-muted-foreground">{model.id}</span>
                  </button>
                );
              })
            ) : (
              <div className="px-3 py-4 text-sm text-muted-foreground">
                {t('llm.fields.noSearchResults')}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}