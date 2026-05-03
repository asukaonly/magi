import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2, Slash, Wrench } from 'lucide-react';
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

  if (!open) return null;

  return (
    <div
      data-slash-picker
      role="listbox"
      aria-label={t('chat.commands.label', { defaultValue: 'Run command' })}
      className="absolute bottom-full left-0 z-30 mb-2 w-[min(100%,420px)] overflow-hidden rounded-xl border border-border/60 bg-background shadow-lg"
    >
      <div className="border-b border-border/40 bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        {t('chat.commands.heading', { defaultValue: 'Commands' })}
        {query ? <span className="ml-1 font-mono text-foreground/80">/{query}</span> : null}
      </div>

      {loading && items.length === 0 ? (
        <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('chat.commands.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : null}

      {error ? (
        <div className="px-3 py-3 text-sm text-destructive">{error}</div>
      ) : null}

      {!loading && items.length === 0 && !error ? (
        <div className="px-3 py-3 text-sm text-muted-foreground">
          {t('chat.commands.empty', {
            defaultValue: 'No matching commands.',
          })}
        </div>
      ) : null}

      <ul className="max-h-72 overflow-y-auto py-1">
        {items.map((item, index) => {
          const active = index === activeIndex;
          const Icon = item.source === 'internal' ? Slash : Wrench;
          return (
            <li
              key={`${item.source}|${item.name}`}
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
                  {item.source === 'tool' && item.dangerous ? (
                    <AlertTriangle
                      className="h-3 w-3 text-amber-500"
                      aria-label={t('chat.commands.dangerous', { defaultValue: 'Dangerous tool — will request confirmation' })}
                    />
                  ) : null}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {item.description}
                </div>
              </div>
              <span className="text-xs text-muted-foreground/70">
                {item.source === 'internal'
                  ? t('chat.commands.kindInternal', { defaultValue: 'built-in' })
                  : t('chat.commands.kindTool', { defaultValue: 'tool' })}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
