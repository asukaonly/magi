import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Brain, ChevronDown, ChevronRight, Hammer, MessageSquare } from 'lucide-react';
import type { ReasoningTrace, RuntimeStatusTrace, ToolCallTrace } from '@/domain/chat/state';
import { ChatProgressDots } from './ChatProgressDots';

type AssistantRuntimePanelProps = {
  runtimeStatuses?: RuntimeStatusTrace[];
  reasoning?: ReasoningTrace[];
  toolCalls?: ToolCallTrace[];
  streaming?: boolean;
  showProgress?: boolean;
  progressText?: string;
  shouldReduceMotion?: boolean;
  actions?: ReactNode;
  children?: ReactNode;
};

const formatToolArguments = (toolCall: ToolCallTrace): string => {
  if (toolCall.toolArguments && Object.keys(toolCall.toolArguments).length > 0) {
    return JSON.stringify(toolCall.toolArguments, null, 2);
  }
  return String(toolCall.toolArgsText || '').trim();
};

export function AssistantRuntimePanel({
  runtimeStatuses, reasoning, toolCalls, streaming, showProgress = streaming,
  progressText, shouldReduceMotion, actions, children,
}: AssistantRuntimePanelProps) {
  const { t } = useTranslation('app');
  const visibleStatuses = useMemo(
    () => (runtimeStatuses || []).filter((item) => Boolean(String(item.content || '').trim())),
    [runtimeStatuses],
  );
  const visibleReasoning = useMemo(
    () => (reasoning || []).filter((item) => Boolean(String(item.content || '').trim())),
    [reasoning],
  );
  const visibleToolCalls = useMemo(
    () => (toolCalls || []).filter((item) => Boolean(String(item.toolName || '').trim())),
    [toolCalls],
  );
  const hasStatuses = visibleStatuses.length > 0;
  const hasReasoning = visibleReasoning.length > 0;
  const hasToolCalls = visibleToolCalls.length > 0;
  const hasRuntimeActivity = hasStatuses || hasReasoning || hasToolCalls || Boolean(children);
  const [expanded, setExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setExpanded(false);
  }, [streaming, showProgress]);

  useEffect(() => {
    if (!streaming || !expanded || !scrollRef.current) {
      return;
    }
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [streaming, expanded, visibleStatuses, visibleReasoning, visibleToolCalls]);

  if (!hasRuntimeActivity && !showProgress && !actions) {
    return null;
  }

  const reasoningText = visibleReasoning.map((item) => item.content.trim()).join('\n\n');
  const latestNarration = visibleStatuses.filter((item) => item.source === 'assistant_tool_call' || item.source === 'assistant_interim').at(-1)?.content.trim();
  const narration = latestNarration || progressText?.trim();

  return (
    <div className="space-y-2 text-muted-foreground" data-testid="chat-assistant-runtime-panel">
      {showProgress && !expanded && (
        narration ? (
          <p role="status" className="m-0 whitespace-pre-wrap text-sm leading-6">{narration}</p>
        ) : <ChatProgressDots shouldReduceMotion={shouldReduceMotion} />
      )}
      <div className="flex flex-wrap items-center gap-2">
        {hasRuntimeActivity && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
            aria-label={expanded ? t('chat.runtime.collapse') : t('chat.runtime.expand')}
            className="inline-flex items-center gap-1 rounded py-1 text-xs text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-ring"
          >
            <span>{t('chat.runtime.label')}</span>
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            )}
          </button>
        )}
        {actions}
      </div>
      {expanded && (
        <div ref={scrollRef} className="max-h-80 space-y-3 overflow-y-auto overscroll-contain border-t border-border/30 px-3 py-2 pr-2">
          {hasStatuses ? (
            <section className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{t('chat.runtime.status')}</span>
              </div>
              <div className="space-y-1.5">
                {visibleStatuses.map((item, index) => (
                  <div
                    key={`${item.source}-${item.stepLabel || 'status'}-${index}`}
                    className="rounded-md border border-border/35 bg-background/60 px-3 py-2 text-xs leading-relaxed text-muted-foreground"
                  >
                    {item.content.trim()}
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {hasReasoning ? (
            <section className="space-y-1">
              <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Brain className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{t('chat.trace.thinkingContent')}</span>
              </div>
              <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap wrap-break-word rounded-md border border-border/40 bg-background/60 px-3 py-2 text-xs text-muted-foreground">
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
                        <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap wrap-break-word text-[11px] text-muted-foreground">
                          {argumentsText}
                        </pre>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </section>
          ) : null}
          {children}
        </div>
      )}
    </div>
  );
}
