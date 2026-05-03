import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Network } from 'lucide-react';
import type { MentionItem } from '@/hooks/useChatComposerMentions';

type ComposerMentionPickerProps = {
  open: boolean;
  query: string;
  items: MentionItem[];
  activeIndex: number;
  loading: boolean;
  error: string | null;
  onSelect: (item: MentionItem) => void;
  onActiveIndexChange: (index: number) => void;
};

const itemId = (index: number) => `mention-option-${index}`;

export const ComposerMentionPicker = ({
  open,
  query,
  items,
  activeIndex,
  loading,
  error,
  onSelect,
  onActiveIndexChange,
}: ComposerMentionPickerProps) => {
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
      data-mention-picker
      role="listbox"
      aria-label={t('chat.mentions.label')}
      aria-activedescendant={activeId}
      aria-busy={loading}
      className="absolute bottom-full left-0 z-30 mb-2 w-[min(100%,420px)] overflow-hidden rounded-xl border border-border/60 bg-background shadow-lg"
    >
      <div className="border-b border-border/40 bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        {t('chat.mentions.heading')}
        {query ? <span className="ml-1 font-mono text-foreground/80">·{' '}{query}</span> : null}
      </div>

      {loading && items.length === 0 ? (
        <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('chat.mentions.loading')}
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="px-3 py-3 text-sm text-destructive">{error}</div>
      ) : null}

      {!loading && items.length === 0 && !error ? (
        <div className="px-3 py-3 text-sm text-muted-foreground">
          {t('chat.mentions.empty')}
        </div>
      ) : null}

      <ul className="max-h-64 overflow-y-auto py-1">
        {items.map((item, index) => {
          const active = index === activeIndex;
          return (
            <li
              key={`${item.serverId}|${item.uri}`}
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
              <Network className="h-4 w-4 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-foreground">{item.name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {item.serverId} · {item.uri}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
