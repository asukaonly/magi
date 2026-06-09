import type { MouseEventHandler, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { motion } from 'framer-motion';
import { AssistantRuntimePanel } from './AssistantRuntimePanel';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import { normalizeAssistantMarkdownContent } from '@/domain/chat/markdown';
import { createMarkdownComponents } from '@/components/ui/markdown-components';
import { useStreamingText } from '@/hooks/useStreamingText';

type TranscriptTimelineMessageProps = {
  message: ChatTimelineMessage;
  content?: string;
  assistantName: string;
  userNameLabel: string;
  timestampLabel: string;
  shouldReduceMotion: boolean;
  avatar: ReactNode;
  headerExtras?: ReactNode;
  bubbleTop?: ReactNode;
  bubbleFooter?: ReactNode;
  belowBubble?: ReactNode;
  onContextMenu?: MouseEventHandler<HTMLDivElement>;
};

// Main chat transcript renders assistant markdown at the ``comfortable`` density
// (larger type / airier spacing tuned for Chinese prose). The component map is
// shared with secondary surfaces via createMarkdownComponents — see
// components/ui/markdown-components.tsx.
const assistantMarkdownComponents = createMarkdownComponents('comfortable');

export const TranscriptTimelineMessage = ({
  message,
  content,
  assistantName,
  userNameLabel,
  timestampLabel,
  shouldReduceMotion,
  avatar,
  headerExtras,
  bubbleTop,
  bubbleFooter,
  belowBubble,
  onContextMenu,
}: TranscriptTimelineMessageProps) => {
  const renderedContent = typeof content === 'string' ? content : message.content;
  // Drip-animate streaming assistant content so the chunk-burst arrival
  // pattern (~500ms IPC poll batches) reveals as a continuous typewriter
  // rather than stepping in chunks. Disabled when prefers-reduced-motion is
  // on (passed via shouldReduceMotion) or when the message isn't streaming
  // (in which case the hook is a pure pass-through).
  const isAssistantStreaming = message.role === 'assistant' && Boolean(message.streaming);
  const drippedContent = useStreamingText(
    String(renderedContent || ''),
    isAssistantStreaming,
    { disabled: shouldReduceMotion },
  );
  const displayContent = message.role === 'assistant' ? drippedContent : renderedContent;
  const showStreamingCaret = Boolean(message.streaming && !String(displayContent || '').trim());
  const isUserMessage = message.role === 'user';
  const displayName = isUserMessage ? userNameLabel : assistantName;
  const headerActions = headerExtras ? (
    <span className="pointer-events-none inline-flex items-center gap-2 opacity-0 transition-opacity duration-150 group-hover/message:pointer-events-auto group-hover/message:opacity-100 group-focus-within/message:pointer-events-auto group-focus-within/message:opacity-100">
      {headerExtras}
    </span>
  ) : null;
  const headerTime = <span className="text-[11px] text-muted-foreground">{timestampLabel}</span>;
  const headerName = (
    <span className="text-xs font-medium text-muted-foreground">
      {displayName}
    </span>
  );

  return (
  <motion.div
    key={message.id}
    initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
    className={isUserMessage ? 'group/message mb-5 flex justify-end' : 'group/message mb-5 flex justify-start'}
  >
    <div className={isUserMessage ? 'flex max-w-[75%] flex-row-reverse gap-3' : 'flex max-w-[75%] gap-3'}>
      {avatar}
      <div className={isUserMessage ? 'flex flex-col items-end' : 'flex flex-col items-start'}>
        <div className="mb-1 flex items-center gap-2">
          {isUserMessage ? (
            <>
              {headerActions}
              {headerTime}
              {headerName}
            </>
          ) : (
            <>
              {headerName}
              {headerTime}
              {headerActions}
            </>
          )}
        </div>
        <div
          onContextMenu={onContextMenu}
          className={isUserMessage
            ? 'w-fit max-w-full rounded-xl rounded-tr-sm border border-border/55 bg-card px-4 py-2.5 text-foreground shadow-sm'
            : 'w-fit max-w-full rounded-xl rounded-tl-sm border border-border/55 bg-card px-4 py-2.5 shadow-sm'}
        >
          {bubbleTop}
          {message.role === 'assistant' ? (
            <div className="max-w-none text-current">
              <AssistantRuntimePanel runtimeStatuses={message.runtimeStatuses} reasoning={message.reasoning} toolCalls={message.toolCalls} streaming={message.streaming} />
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={assistantMarkdownComponents}>
                {normalizeAssistantMarkdownContent(displayContent)}
              </ReactMarkdown>
              {showStreamingCaret && (
                <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-current opacity-70" />
              )}
              {bubbleFooter}
            </div>
          ) : displayContent ? (
            <>
              <p className="m-0 whitespace-pre-wrap text-sm">{displayContent}</p>
              {bubbleFooter}
            </>
          ) : null}
        </div>
        {belowBubble}
      </div>
    </div>
  </motion.div>
  );
};