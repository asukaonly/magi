import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Hammer } from 'lucide-react';
import type { ToolCallTrace } from '@/domain/chat/state';

type ToolCallPanelProps = {
  toolCalls?: ToolCallTrace[];
  streaming?: boolean;
};

const formatToolArguments = (toolCall: ToolCallTrace): string => {
  if (toolCall.toolArguments && Object.keys(toolCall.toolArguments).length > 0) {
    return JSON.stringify(toolCall.toolArguments, null, 2);
  }
  return String(toolCall.toolArgsText || '').trim();
};

export function ToolCallPanel({ toolCalls, streaming }: ToolCallPanelProps) {
  const { t } = useTranslation('app');
  const visibleToolCalls = useMemo(
    () => (toolCalls || []).filter((item) => Boolean(String(item.toolName || '').trim())),
    [toolCalls],
  );
  const hasToolCalls = visibleToolCalls.length > 0;
  const [expanded, setExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (streaming && visibleToolCalls.some((item) => item.status === 'running')) {
      setExpanded(true);
    }
  }, [streaming, visibleToolCalls]);

  useEffect(() => {
    if (!streaming || !expanded || !scrollRef.current) {
      return;
    }
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [streaming, expanded, visibleToolCalls]);

  if (!hasToolCalls) {
    return null;
  }

  return (
    <div className="mb-2 rounded-lg border border-border/40 bg-muted/30" data-testid="chat-tool-call-panel">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        aria-label={expanded ? t('chat.toolCalls.collapse') : t('chat.toolCalls.expand')}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Hammer className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="font-medium">{t('chat.toolCalls.label', { count: visibleToolCalls.length })}</span>
        {streaming && visibleToolCalls.some((item) => item.status === 'running') && (
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
        <div ref={scrollRef} className="max-h-80 space-y-2 overflow-y-auto overscroll-contain border-t border-border/30 px-3 py-2 pr-2">
          {visibleToolCalls.map((toolCall) => {
            const statusKey = toolCall.status === 'completed'
              ? 'chat.toolCalls.completed'
              : 'chat.toolCalls.running';
            const argumentsText = formatToolArguments(toolCall);
            return (
              <div
                key={toolCall.toolCallId || `${toolCall.toolName}-${toolCall.status}`}
                className="rounded-md border border-border/40 bg-background/70 px-3 py-2"
              >
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{toolCall.toolName}</span>
                  <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium">
                    {t(statusKey)}
                  </span>
                </div>
                {argumentsText ? (
                  <div className="mt-2 space-y-1">
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {t('chat.toolCalls.arguments')}
                    </div>
                    <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap break-words text-[11px] text-muted-foreground">
                      {argumentsText}
                    </pre>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}