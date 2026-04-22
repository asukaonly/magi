import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Brain } from 'lucide-react';
import type { ReasoningTrace } from '@/domain/chat/state';

type ThinkingPanelProps = {
  reasoning?: ReasoningTrace[];
  streaming?: boolean;
};

export function ThinkingPanel({ reasoning, streaming }: ThinkingPanelProps) {
  const { t } = useTranslation('app');
  const hasReasoning = Array.isArray(reasoning) && reasoning.some((r) => r.content && r.content.trim());
  const [expanded, setExpanded] = useState(false);

  // Auto-expand while actively streaming reasoning before the main body starts.
  useEffect(() => {
    if (streaming && hasReasoning) {
      setExpanded(true);
    }
  }, [streaming, hasReasoning]);

  if (!hasReasoning) {
    return null;
  }

  const combined = (reasoning ?? [])
    .filter((r) => r.content && r.content.trim())
    .map((r) => r.content.trim())
    .join('\n\n');

  return (
    <div className="mb-2 rounded-lg border border-border/40 bg-muted/30">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        aria-label={expanded ? t('chat.thinking.collapse') : t('chat.thinking.expand')}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Brain className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="font-medium">{t('chat.thinking.label')}</span>
        {streaming && (
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current opacity-70" />
        )}
        <span className="ml-auto">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </span>
      </button>
      {expanded && (
        <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap break-words border-t border-border/30 px-3 py-2 text-xs text-muted-foreground">
          {combined}
        </pre>
      )}
    </div>
  );
}
