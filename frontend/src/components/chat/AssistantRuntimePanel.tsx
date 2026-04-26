import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, Brain, ChevronDown, ChevronRight, Hammer } from 'lucide-react';
import type { ReasoningTrace, ToolCallTrace } from '@/domain/chat/state';

type AssistantRuntimePanelProps = {
  reasoning?: ReasoningTrace[];
  toolCalls?: ToolCallTrace[];
  streaming?: boolean;
};

const formatToolArguments = (toolCall: ToolCallTrace): string => {
  if (toolCall.toolArguments && Object.keys(toolCall.toolArguments).length > 0) {
    return JSON.stringify(toolCall.toolArguments, null, 2);
  }
  return String(toolCall.toolArgsText || '').trim();
};

export function AssistantRuntimePanel({ reasoning, toolCalls, streaming }: AssistantRuntimePanelProps) {
  const { t } = useTranslation('app');
  const visibleReasoning = useMemo(
    () => (reasoning || []).filter((item) => Boolean(String(item.content || '').trim())),
    [reasoning],
  );
  const visibleToolCalls = useMemo(
    () => (toolCalls || []).filter((item) => Boolean(String(item.toolName || '').trim())),
    [toolCalls],
  );
  const hasReasoning = visibleReasoning.length > 0;
  const hasToolCalls = visibleToolCalls.length > 0;
  const hasRuntimeActivity = hasReasoning || hasToolCalls;
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (streaming && (hasReasoning || visibleToolCalls.some((item) => item.status === 'running'))) {
      setExpanded(true);
    }
  }, [streaming, hasReasoning, visibleToolCalls]);

  if (!hasRuntimeActivity) {
    return null;
  }

  const reasoningText = visibleReasoning.map((item) => item.content.trim()).join('\n\n');

  return (
    <div className="mb-2 rounded-lg border border-border/40 bg-muted/30" data-testid="chat-assistant-runtime-panel">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        aria-label={expanded ? t('chat.runtime.collapse') : t('chat.runtime.expand')}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Activity className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="font-medium">{t('chat.runtime.label')}</span>
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
        <div className="space-y-3 border-t border-border/30 px-3 py-2">
          {hasReasoning ? (
            <section className="space-y-1">
              <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Brain className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{t('chat.thinking.label')}</span>
              </div>
              <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border/40 bg-background/60 px-3 py-2 text-xs text-muted-foreground">
                {reasoningText}
              </pre>
            </section>
          ) : null}
          {hasToolCalls ? (
            <section className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Hammer className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{t('chat.toolCalls.label', { count: visibleToolCalls.length })}</span>
              </div>
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
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}