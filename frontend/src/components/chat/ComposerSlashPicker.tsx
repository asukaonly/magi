import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2, Slash, Sparkles, SquareSplitVertical, Wrench } from 'lucide-react';
import type { SlashCommandItem } from '@/hooks/useChatComposerCommands';

type ComposerSlashPickerProps = {
  open: boolean;
  query: string;
  items: SlashCommandItem[];
  activeIndex: number;
  loading: boolean;
  error: string | null;
  onSelect: (item: SlashCommandItem) => void;
  onActiveIndexChange: (index: number) => void;
};

const itemId = (index: number) => `slash-option-${index}`;

export const ComposerSlashPicker = ({
  open,
  query,
  items,
  activeIndex,
  loading,
  error,
  onSelect,
  onActiveIndexChange,
}: ComposerSlashPickerProps) => {
  const { t } = useTranslation();
  const activeRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    if (!open) return;
    activeRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [activeIndex, open]);

  if (!open) return null;

  const activeId = items.length > 0 && activeIndex >= 0 ? itemId(activeIndex) : undefined;

  return (
    <div
      data-slash-picker
      role="listbox"
      aria-label={t('chat.commands.label')}
      aria-activedescendant={activeId}
      aria-busy={loading}
      className="absolute bottom-full left-0 z-30 mb-2 w-[min(100%,420px)] overflow-hidden rounded-xl border border-border/60 bg-background shadow-lg"
    >
      <div className="border-b border-border/40 bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        {t('chat.commands.heading')}
        {query ? <span className="ml-1 font-mono text-foreground/80">/{query}</span> : null}
      </div>

      {loading && items.length === 0 ? (
        <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('chat.commands.loading')}
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="px-3 py-3 text-sm text-destructive">{error}</div>
      ) : null}

      {!loading && items.length === 0 && !error ? (
        <div className="px-3 py-3 text-sm text-muted-foreground">
          {t('chat.commands.empty')}
        </div>
      ) : null}

      <ul className="max-h-72 overflow-y-auto py-1">
        {items.map((item, index) => {
          const active = index === activeIndex;
          const Icon =
            item.source === 'internal'
              ? Slash
              : item.source === 'skill'
                ? Sparkles
                : Wrench;
          const kindLabel =
            item.source === 'internal'
              ? t('chat.commands.kindInternal')
              : item.source === 'skill'
                ? t('chat.commands.kindSkill', { defaultValue: 'skill' })
                : t('chat.commands.kindTool');
          return (
            <li
              key={`${item.source}|${item.name}`}
              id={itemId(index)}
              ref={active ? activeRef : undefined}
              role="option"
              aria-selected={active}
              className={`flex cursor-pointer items-center gap-3 px-3 py-2 text-sm ${
                active ? 'bg-accent/50' : 'hover:bg-accent/30'
              }`}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(item);
              }}
              onMouseEnter={() => onActiveIndexChange(index)}
            >
              <Icon className="h-4 w-4 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 truncate font-medium text-foreground">
                  /{item.name}
                  {item.source !== 'skill' && item.dangerous ? (
                    <AlertTriangle
                      className="h-3 w-3 text-amber-500"
                      aria-label={t('chat.commands.dangerous')}
                    />
                  ) : null}
                  {item.source === 'skill' && item.argumentHint ? (
                    <span className="text-xs font-normal text-muted-foreground">
                      {item.argumentHint}
                    </span>
                  ) : null}
                  {item.source === 'skill' && item.contextMode === 'fork' ? (
                    <span
                      className="inline-flex items-center gap-0.5 rounded-sm bg-muted/60 px-1 py-0.5 text-[10px] font-normal uppercase tracking-wide text-muted-foreground"
                      aria-label={t('chat.commands.forkBadge', { defaultValue: 'Runs as background task' })}
                    >
                      <SquareSplitVertical className="h-2.5 w-2.5" />
                      {t('chat.commands.forkLabel', { defaultValue: 'fork' })}
                    </span>
                  ) : null}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {item.description}
                </div>
              </div>
              <span className="text-xs text-muted-foreground/70">{kindLabel}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
