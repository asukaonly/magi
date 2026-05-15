import type { MouseEventHandler, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { motion } from 'framer-motion';
import { AssistantRuntimePanel } from './AssistantRuntimePanel';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import { normalizeAssistantMarkdownContent } from '@/domain/chat/markdown';
import { openExternalUrl } from '@/runtime/desktop';

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

const assistantMarkdownComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mb-4 mt-1 border-b border-border/60 pb-2 text-xl font-semibold tracking-[-0.03em] text-foreground">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-3 mt-6 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold leading-snug text-foreground">{children}</h3>,
  p: ({ children }) => <p className="mb-4 whitespace-pre-wrap text-sm leading-7 text-foreground last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-4 list-disc space-y-2 pl-5 text-sm leading-7 text-foreground marker:text-muted-foreground">{children}</ul>,
  ol: ({ children, start }) => <ol start={start} className="mb-4 list-decimal space-y-2 pl-5 text-sm leading-7 text-foreground marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="mb-4 rounded-r-2xl border-l-4 border-primary/35 bg-primary/5 px-4 py-3 text-sm leading-7 text-foreground/85 shadow-sm">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) => {
    const content = String(children ?? '').replace(/\n$/, '');
    const isBlockCode = Boolean(className) || content.includes('\n');
    if (isBlockCode) {
      return <code className="font-mono text-[13px] leading-7 text-inherit">{children}</code>;
    }
    return (
      <code className="rounded-md border border-border/60 bg-background/90 px-1.5 py-0.5 font-mono text-[0.84em] text-foreground shadow-sm">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="mb-4 overflow-x-auto rounded-2xl border border-foreground/10 bg-foreground px-4 py-4 text-[13px] leading-7 text-background shadow-sm">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="mb-4 overflow-x-auto rounded-2xl border border-border/60 bg-background/80 shadow-sm">
      <table className="min-w-full border-collapse text-sm leading-6 text-foreground">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/60 text-left text-xs uppercase tracking-[0.16em] text-muted-foreground">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-border/50">{children}</tbody>,
  tr: ({ children }) => <tr className="align-top">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 font-semibold">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2.5 text-sm text-foreground/90">{children}</td>,
  hr: () => <hr className="my-5 border-border/60" />,
  a: ({ href, children }) => (
    <a
      href={href}
      className="font-medium text-primary underline decoration-primary/45 underline-offset-4 transition-colors hover:text-primary/80"
      target="_blank"
      rel="noreferrer"
      onClick={(event) => {
        if (!href) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        void openExternalUrl(href);
      }}
    >
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
};

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
  const showStreamingCaret = Boolean(message.streaming && !String(renderedContent || '').trim());
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
                {normalizeAssistantMarkdownContent(renderedContent)}
              </ReactMarkdown>
              {showStreamingCaret && (
                <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-current opacity-70" />
              )}
              {bubbleFooter}
            </div>
          ) : renderedContent ? (
            <>
              <p className="m-0 whitespace-pre-wrap text-sm">{renderedContent}</p>
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